from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re
import sqlite3
from typing import Any
import unicodedata


_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
# Batch size affects query round-trips only; each stage keeps scanning until its
# requested number of unique exact-text groups is filled or FTS is exhausted.
_FTS_SCAN_BATCH_SIZE = 64

_MAX_QUERY_TERMS = 18
_MAX_QUERY_TOKENS = 64
_MAX_CONCEPT_WINDOWS = 12
_MAX_CONCEPT_GAP_TOKENS = 3
_STAGE_POOL_MULTIPLIER = 2

# These are syntax/filler words, not legal concepts. They are excluded only
# from thematic relevance construction; exact canonical lookup is unaffected.
_GENERIC_QUERY_TERMS = frozenset(
    {
        "a", "al", "ante", "aplica", "aplicable", "aplicacion", "and",
        "como", "con", "contra", "cual", "cuales", "cuando", "de", "del",
        "desde", "donde", "efecto", "el", "ella", "en", "entre", "es",
        "esta", "este", "hay", "la", "las", "lo", "los", "near", "no",
        "not", "o", "or", "para", "por", "puede", "que", "se", "segun",
        "si", "sin", "sobre", "su", "sus", "tener", "tiene", "un", "una",
        "y",
    }
)

# Small deterministic equivalence families improve recall without allowing a
# model to invent query semantics. Accent folding and conservative
# singular/plural variants are added separately.
_LEXICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "extemporanea": ("extemporaneidad", "tardia", "tardio"),
    "extemporaneidad": ("extemporanea", "tardia", "tardio"),
    "tardia": ("extemporanea", "extemporaneidad"),
    "tardio": ("extemporanea", "extemporaneidad"),
    "canon": ("regalia",),
    "canones": ("regalia", "regalias"),
    "regalia": ("canon",),
    "regalias": ("canon", "canones"),
}


class RetrievalIntegrityError(RuntimeError):
    """Canonical evidence cannot be trusted for a retrieved segment."""


@dataclass(frozen=True)
class RetrievalHit:
    extracted_segment_id: str
    extraction_id: str
    sequence_no: int
    text: str
    text_sha256: str
    manifestation_id: str
    manifestation_sha256: str
    retrieved_at: str
    source_id: str
    source_url: str
    authority: str
    source_kind: str
    document_id: str | None
    document_type: str | None
    document_title: str | None
    document_number: str | None
    document_issuer: str | None
    document_year: int | None
    rank: float
    # Cardinality includes the representative itself. Alternate IDs preserve
    # every equivalent evidence row without allowing them to consume top-N.
    duplicate_count: int = 1
    alternate_segment_ids: tuple[str, ...] = ()
    retrieval_strategy: str | None = None
    retrieval_reason: str | None = None


@dataclass(frozen=True)
class CanonicalTargetLookup:
    """Result of a read-only lookup for one already-resolved canonical target."""

    target_document_id: str
    target_provision_id: str | None
    strategy: str
    status: str
    hits: tuple[RetrievalHit, ...] = ()


@dataclass(frozen=True)
class CitableContextGap:
    """One explicit reason verified context could not be completed safely."""

    reason: str
    source_segment_id: str
    reference_mention_id: str | None = None
    target_document_id: str | None = None
    target_provision_id: str | None = None


@dataclass(frozen=True)
class CitableContextHit:
    """One independently citable segment admitted as bounded context."""

    hit: RetrievalHit
    provision_id: str
    bases: tuple[str, ...]
    source_segment_ids: tuple[str, ...]
    reference_mention_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CitableContextResult:
    """Read-only context expansion outcome for one exact source segment."""

    anchor_segment_id: str
    document_id: str | None
    provision_id: str | None
    context_status: str
    hits: tuple[CitableContextHit, ...] = ()
    gaps: tuple[CitableContextGap, ...] = ()
    budget_exhausted: bool = False
    verified_candidate_count: int = 0


@dataclass(frozen=True)
class ThematicQueryStage:
    """One generated, injection-safe thematic FTS stage."""

    strategy: str
    fts_query: str
    match_terms: tuple[str, ...]


@dataclass(frozen=True)
class ThematicStageExecution:
    """Observable internal execution metadata for one thematic retrieval stage."""

    strategy: str
    reason: str
    fts_query: str
    candidate_count: int
    newly_admitted_count: int


@dataclass(frozen=True)
class ThematicSearchResult:
    """Bounded thematic hits plus the deterministic stages actually executed."""

    hits: tuple[RetrievalHit, ...]
    stages: tuple[ThematicStageExecution, ...]


@dataclass(frozen=True)
class _ThematicQueryPlan:
    stages: tuple[ThematicQueryStage, ...]
    terms: tuple[str, ...]
    concepts: tuple[tuple[str, str], ...]
    numeric_terms: tuple[str, ...]


def thematic_retrieval_config() -> dict[str, Any]:
    """Return stable JSON-compatible inputs to the retrieval fingerprint."""
    return {
        "strategy": "phrase_then_controlled_variants_then_broad_fallback",
        "max_query_terms": _MAX_QUERY_TERMS,
        "max_query_tokens": _MAX_QUERY_TOKENS,
        "max_concept_windows": _MAX_CONCEPT_WINDOWS,
        "max_concept_gap_tokens": _MAX_CONCEPT_GAP_TOKENS,
        "stage_pool_multiplier": _STAGE_POOL_MULTIPLIER,
        "generic_query_terms": sorted(_GENERIC_QUERY_TERMS),
        "lexical_aliases": {
            key: list(values)
            for key, values in sorted(_LEXICAL_ALIASES.items())
        },
        "diversity": "distinct-document-first-then-ranked-backfill",
        "tie_break": "concepts,terms,numerics,stage,bm25,provenance",
    }


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def exact_unambiguous_substring_offset(
    source_text: str,
    exact_text: str,
) -> int | None:
    """Return the sole exact offset for citable text, otherwise None.

    Empty/blank text and zero-or-multiple matches are non-citable. Callers
    must preserve the containing verified segment as evidence instead of
    inventing an anchor.
    """
    if not exact_text or not exact_text.strip():
        return None
    first = source_text.find(exact_text)
    if first < 0:
        return None
    if source_text.find(exact_text, first + 1) >= 0:
        return None
    return first


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _query_tokens(value: str, *, maximum: int = _MAX_QUERY_TOKENS) -> list[str]:
    tokens: list[str] = []
    for match in _WORD_RE.finditer(_fold_text(value)):
        token = match.group(0)
        if not token:
            continue
        tokens.append(token)
        if len(tokens) >= maximum:
            break
    return tokens


def _query_terms(value: str, *, maximum: int = _MAX_QUERY_TERMS) -> list[str]:
    """Return unique safe terms, preserving short numeric identifiers."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in _query_tokens(value, maximum=max(maximum * 4, _MAX_QUERY_TOKENS)):
        if not token.isdigit() and len(token) < 3:
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= maximum:
            break
    return terms


def _is_significant_query_term(term: str) -> bool:
    if term.isdigit():
        return True
    return len(term) >= 3 and term not in _GENERIC_QUERY_TERMS


def _quote_fts_phrase(tokens: tuple[str, ...] | list[str]) -> str:
    # Tokens come exclusively from _WORD_RE, but quote defensively so caller
    # text can never inject FTS operators or syntax.
    phrase = " ".join(token.replace('"', '""') for token in tokens)
    return f'"{phrase}"'


def _lexical_variants(term: str) -> tuple[str, ...]:
    """Return conservative deterministic variants for one significant term."""
    if term.isdigit():
        return (term,)

    variants: set[str] = {term}
    pending = [term]
    while pending:
        current = pending.pop()
        for alias in _LEXICAL_ALIASES.get(current, ()):
            if alias not in variants:
                variants.add(alias)
                pending.append(alias)

    for current in tuple(variants):
        if len(current) < 4:
            continue
        if current.endswith("es") and len(current) > 4:
            variants.add(current[:-2])
        elif current.endswith("s") and len(current) > 4:
            variants.add(current[:-1])
        elif current[-1] in "aeiou":
            variants.add(current + "s")
        else:
            variants.add(current + "es")

    return tuple([term, *sorted(variants - {term})])


def _variant_group(term: str) -> str:
    variants = _lexical_variants(term)
    clauses = [_quote_fts_phrase((variant,)) for variant in variants]
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " OR ".join(clauses) + ")"


def _concept_windows(tokens: list[str]) -> list[tuple[tuple[str, ...], tuple[str, str]]]:
    """Preserve bounded adjacent concepts, allowing only filler between them."""
    significant_positions = [
        index for index, token in enumerate(tokens)
        if _is_significant_query_term(token)
    ]
    windows: list[tuple[tuple[str, ...], tuple[str, str]]] = []
    seen: set[tuple[str, ...]] = set()

    for left_pos, right_pos in zip(significant_positions, significant_positions[1:]):
        gap = right_pos - left_pos - 1
        if gap > _MAX_CONCEPT_GAP_TOKENS:
            continue
        raw = tuple(tokens[left_pos : right_pos + 1])
        if raw in seen:
            continue
        seen.add(raw)
        windows.append((raw, (tokens[left_pos], tokens[right_pos])))
        if len(windows) >= _MAX_CONCEPT_WINDOWS:
            break
    return windows


def build_thematic_query_plan(value: str) -> _ThematicQueryPlan:
    """Build deterministic phrase/variant/broad stages from plain query text."""
    tokens = _query_tokens(value)
    terms: list[str] = []
    seen_terms: set[str] = set()
    for token in tokens:
        if not _is_significant_query_term(token) or token in seen_terms:
            continue
        seen_terms.add(token)
        terms.append(token)
        if len(terms) >= _MAX_QUERY_TERMS:
            break

    windows = _concept_windows(tokens)
    stages: list[ThematicQueryStage] = []

    if windows:
        phrase_clauses = [_quote_fts_phrase(raw) for raw, _ in windows]
        phrase_terms = tuple(
            dict.fromkeys(
                token
                for raw, _ in windows
                for token in raw
                if _is_significant_query_term(token)
            )
        )
        stages.append(
            ThematicQueryStage(
                strategy="concept_phrase",
                fts_query=" OR ".join(phrase_clauses),
                match_terms=phrase_terms,
            )
        )

        lexical_clauses: list[str] = []
        lexical_match_terms: list[str] = []
        for _, (left, right) in windows:
            lexical_clauses.append(
                f"({_variant_group(left)} AND {_variant_group(right)})"
            )
            lexical_match_terms.extend(_lexical_variants(left))
            lexical_match_terms.extend(_lexical_variants(right))
        stages.append(
            ThematicQueryStage(
                strategy="controlled_lexical_variants",
                fts_query=" OR ".join(dict.fromkeys(lexical_clauses)),
                match_terms=tuple(dict.fromkeys(lexical_match_terms)),
            )
        )

    if terms:
        broad_clauses: list[str] = []
        broad_match_terms: list[str] = []
        for term in terms:
            variants = _lexical_variants(term)
            broad_clauses.extend(_quote_fts_phrase((variant,)) for variant in variants)
            broad_match_terms.extend(variants)
        stages.append(
            ThematicQueryStage(
                strategy="broad_lexical_fallback",
                fts_query=" OR ".join(dict.fromkeys(broad_clauses)),
                match_terms=tuple(dict.fromkeys(broad_match_terms)),
            )
        )

    # Avoid executing semantically identical generated queries twice.
    unique_stages: list[ThematicQueryStage] = []
    seen_queries: set[str] = set()
    for stage in stages:
        if not stage.fts_query or stage.fts_query in seen_queries:
            continue
        seen_queries.add(stage.fts_query)
        unique_stages.append(stage)

    concepts = tuple(pair for _, pair in windows)
    numeric_terms = tuple(term for term in terms if term.isdigit())
    return _ThematicQueryPlan(
        stages=tuple(unique_stages),
        terms=tuple(terms),
        concepts=concepts,
        numeric_terms=numeric_terms,
    )


def _fts_query(value: str) -> tuple[str, list[str]]:
    """Compatibility helper for the broad sanitized lexical expression."""
    terms = _query_terms(value)
    if not terms:
        return "", []
    return " OR ".join(_quote_fts_phrase((term,)) for term in terms), terms


class CorpusRetrievalService:
    """Read-only FTS retrieval over canonical extracted-segment provenance.

    The FTS table is contentless and was populated in lockstep with
    extracted_segments. Its rowid is therefore used only to obtain a candidate
    row. Every candidate is re-read from extracted_segments and its persisted
    text fingerprint is verified before it can be used as evidence.
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def _ranked_rows(
        self,
        fts_query: str,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[int, float]]:
        """Return one deterministic page of raw FTS candidates."""
        rows = self.con.execute(
            """
            SELECT rowid, bm25(extracted_segments_fts) AS rank
            FROM extracted_segments_fts
            WHERE extracted_segments_fts MATCH ?
            ORDER BY rank, rowid
            LIMIT ? OFFSET ?
            """,
            (fts_query, limit, offset),
        ).fetchall()
        return [(int(row[0]), float(row[1])) for row in rows]

    def _candidate_row(self, rowid: int) -> Any | None:
        """Resolve one FTS locator back to authoritative segment provenance."""
        return self.con.execute(
            """
            SELECT
                es.extracted_segment_id,
                es.extraction_id,
                es.sequence_no,
                es.text,
                es.text_sha256,
                m.manifestation_id,
                m.sha256,
                m.retrieved_at,
                s.source_id,
                s.source_url,
                s.authority,
                s.source_kind,
                d.document_id,
                d.document_type,
                d.title,
                (
                    SELECT di.identifier_value
                    FROM document_identifiers di
                    WHERE di.document_id = d.document_id
                      AND di.is_primary = 1
                    ORDER BY di.identifier_id
                    LIMIT 1
                ) AS document_number,
                (
                    SELECT di.issuer
                    FROM document_identifiers di
                    WHERE di.document_id = d.document_id
                      AND di.is_primary = 1
                    ORDER BY di.identifier_id
                    LIMIT 1
                ) AS document_issuer,
                CASE
                    WHEN d.issued_date GLOB '[0-9][0-9][0-9][0-9]-*'
                    THEN CAST(substr(d.issued_date, 1, 4) AS INTEGER)
                    ELSE NULL
                END AS document_year
            FROM extracted_segments es
            JOIN text_extractions te
              ON te.extraction_id = es.extraction_id
             AND te.status = 'success'
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            JOIN sources s
              ON s.source_id = m.source_id
            LEFT JOIN documents d
              ON d.document_id = m.document_id
            WHERE es.rowid = ?
            """,
            (rowid,),
        ).fetchone()

    @staticmethod
    def _verify_segment_fingerprint(
        extracted_segment_id: str,
        text: str,
        expected_hash: str,
    ) -> None:
        actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise RetrievalIntegrityError(
                "extracted segment text fingerprint mismatch: "
                f"{extracted_segment_id} expected={expected_hash} actual={actual_hash}"
            )

    def _duplicate_provenance(
        self,
        *,
        extraction_id: str,
        text_sha256: str,
        representative_id: str,
        representative_text: str,
    ) -> tuple[int, tuple[str, ...]]:
        """Return verified deterministic provenance for one exact-text group.

        Equivalence is deliberately scoped to one extraction. Identical wording
        from another extraction/document remains an independent retrieval hit.
        """
        rows = self.con.execute(
            """
            SELECT extracted_segment_id, sequence_no, text, text_sha256
            FROM extracted_segments
            WHERE extraction_id = ?
              AND text_sha256 = ?
            ORDER BY sequence_no, extracted_segment_id
            """,
            (extraction_id, text_sha256),
        ).fetchall()

        alternates: list[str] = []
        representative_found = False
        for row in rows:
            segment_id = str(row[0])
            segment_text = str(row[2])
            persisted_hash = str(row[3])
            self._verify_segment_fingerprint(segment_id, segment_text, persisted_hash)
            if segment_text != representative_text:
                raise RetrievalIntegrityError(
                    "same extraction/text_sha256 group contains non-equivalent text: "
                    f"{representative_id} vs {segment_id}"
                )
            if segment_id == representative_id:
                representative_found = True
            else:
                alternates.append(segment_id)

        if not representative_found:
            raise RetrievalIntegrityError(
                "retrieval representative missing from its exact-text provenance group: "
                f"{representative_id}"
            )
        return len(rows), tuple(alternates)

    def _materialize_hit(self, row: Any, *, rank: float) -> RetrievalHit:
        """Build one verified hit from an authoritative extracted-segment row."""
        self._verify_segment_fingerprint(row[0], row[3], row[4])
        duplicate_count, alternate_segment_ids = self._duplicate_provenance(
            extraction_id=str(row[1]),
            text_sha256=str(row[4]),
            representative_id=str(row[0]),
            representative_text=str(row[3]),
        )
        return RetrievalHit(
            extracted_segment_id=row[0],
            extraction_id=row[1],
            sequence_no=int(row[2]),
            text=row[3],
            text_sha256=row[4],
            manifestation_id=row[5],
            manifestation_sha256=row[6],
            retrieved_at=row[7],
            source_id=row[8],
            source_url=row[9],
            authority=row[10],
            source_kind=row[11],
            document_id=row[12],
            document_type=row[13],
            document_title=row[14],
            document_number=row[15],
            document_issuer=row[16],
            document_year=row[17],
            rank=rank,
            duplicate_count=duplicate_count,
            alternate_segment_ids=alternate_segment_ids,
        )

    def _search_generated_stage(
        self,
        stage: ThematicQueryStage,
        *,
        limit: int,
    ) -> list[RetrievalHit]:
        """Execute one generated FTS stage with exact-text diversification."""
        if not stage.fts_query or limit <= 0:
            return []

        hits: list[RetrievalHit] = []
        seen_equivalents: set[tuple[str, str]] = set()
        offset = 0
        batch_size = max(limit, _FTS_SCAN_BATCH_SIZE)

        while len(hits) < limit:
            ranked_rows = self._ranked_rows(
                stage.fts_query,
                limit=batch_size,
                offset=offset,
            )
            if not ranked_rows:
                break

            for rowid, rank in ranked_rows:
                row = self._candidate_row(rowid)
                if row is None:
                    continue

                # A contentless FTS rowid is only a candidate locator. Generated
                # query terms must still be observable in the authoritative row.
                row_tokens = set(_query_tokens(str(row[3]), maximum=512))
                if stage.match_terms and not any(
                    term in row_tokens for term in stage.match_terms
                ):
                    continue

                equivalence_key = (str(row[1]), str(row[4]))
                if equivalence_key in seen_equivalents:
                    continue

                hit = self._materialize_hit(row, rank=rank)
                seen_equivalents.add(equivalence_key)
                hits.append(hit)
                if len(hits) >= limit:
                    break

            if len(hits) >= limit or len(ranked_rows) < batch_size:
                break
            offset += len(ranked_rows)

        return hits

    @staticmethod
    def _thematic_relevance_key(
        hit: RetrievalHit,
        *,
        plan: _ThematicQueryPlan,
        stage_index: int,
    ) -> tuple[Any, ...]:
        text_sequence = _query_tokens(hit.text, maximum=512)
        text_tokens = set(text_sequence)
        significant_sequence = [
            token for token in text_sequence
            if _is_significant_query_term(token)
        ]

        def term_matches(term: str) -> bool:
            return any(variant in text_tokens for variant in _lexical_variants(term))

        def ordered_concept_matches(left: str, right: str) -> bool:
            left_variants = set(_lexical_variants(left))
            right_variants = set(_lexical_variants(right))
            return any(
                current in left_variants and following in right_variants
                for current, following in zip(
                    significant_sequence,
                    significant_sequence[1:],
                )
            )

        concept_matches = sum(
            1
            for left, right in plan.concepts
            if ordered_concept_matches(left, right)
        )
        term_matches_count = sum(1 for term in plan.terms if term_matches(term))
        numeric_matches = sum(1 for term in plan.numeric_terms if term in text_tokens)
        return (
            -concept_matches,
            -term_matches_count,
            -numeric_matches,
            stage_index,
            hit.rank,
            hit.document_id or "",
            hit.extraction_id,
            hit.sequence_no,
            hit.extracted_segment_id,
        )

    @staticmethod
    def _diversify_ranked_hits(
        ranked: list[RetrievalHit],
        *,
        limit: int,
    ) -> list[RetrievalHit]:
        """Prefer distinct documents once, then backfill in relevance order."""
        if limit <= 0:
            return []

        selected: list[RetrievalHit] = []
        seen_segments: set[str] = set()
        seen_documents: set[str] = set()

        for hit in ranked:
            document_key = hit.document_id or f"extraction:{hit.extraction_id}"
            if document_key in seen_documents:
                continue
            selected.append(hit)
            seen_segments.add(hit.extracted_segment_id)
            seen_documents.add(document_key)
            if len(selected) >= limit:
                return selected

        for hit in ranked:
            if hit.extracted_segment_id in seen_segments:
                continue
            selected.append(hit)
            seen_segments.add(hit.extracted_segment_id)
            if len(selected) >= limit:
                break
        return selected

    def search_detailed(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> ThematicSearchResult:
        """Run deterministic staged thematic retrieval.

        Phrase-aware concepts are attempted first, controlled lexical variants
        backfill paraphrased wording, and the broad OR stage is used only when
        focused stages cannot fill the bounded result window. All FTS syntax is
        generated from sanitized tokens.
        """
        if limit <= 0:
            return ThematicSearchResult((), ())

        plan = build_thematic_query_plan(query)
        if not plan.stages:
            return ThematicSearchResult((), ())

        pool_limit = max(limit * _STAGE_POOL_MULTIPLIER, limit)
        collected: dict[tuple[str, str], tuple[RetrievalHit, int]] = {}
        executions: list[ThematicStageExecution] = []

        for stage_index, stage in enumerate(plan.stages):
            current_ranked = [
                item[0]
                for item in sorted(
                    collected.values(),
                    key=lambda pair: self._thematic_relevance_key(
                        pair[0],
                        plan=plan,
                        stage_index=pair[1],
                    ),
                )
            ]
            current_full = (
                len(self._diversify_ranked_hits(current_ranked, limit=limit))
                >= limit
            )
            # Phrase and controlled-variant stages jointly define focused
            # retrieval. A full exact-phrase window must not suppress unseen
            # paraphrased evidence. Only the broad OR stage is a true fallback.
            if stage.strategy == "broad_lexical_fallback" and current_full:
                break

            if stage.strategy == "concept_phrase":
                reason = "focused_multiword_concepts"
            elif stage.strategy == "controlled_lexical_variants":
                reason = "controlled_variant_recall"
            else:
                reason = (
                    "focused_stages_underfilled"
                    if executions
                    else "no_multiword_concepts"
                )

            stage_hits = self._search_generated_stage(stage, limit=pool_limit)
            admitted = 0
            for hit in stage_hits:
                key = (hit.extraction_id, hit.text_sha256)
                if key in collected:
                    continue
                collected[key] = (
                    replace(
                        hit,
                        retrieval_strategy=stage.strategy,
                        retrieval_reason=reason,
                    ),
                    stage_index,
                )
                admitted += 1

            executions.append(
                ThematicStageExecution(
                    strategy=stage.strategy,
                    reason=reason,
                    fts_query=stage.fts_query,
                    candidate_count=len(stage_hits),
                    newly_admitted_count=admitted,
                )
            )

        ordered_pairs = sorted(
            collected.values(),
            key=lambda pair: self._thematic_relevance_key(
                pair[0],
                plan=plan,
                stage_index=pair[1],
            ),
        )
        ordered = [pair[0] for pair in ordered_pairs]
        selected = self._diversify_ranked_hits(ordered, limit=limit)
        return ThematicSearchResult(tuple(selected), tuple(executions))

    def search(self, query: str, *, limit: int = 20) -> list[RetrievalHit]:
        """Return bounded, diversified thematic hits without mutating evidence."""
        return list(self.search_detailed(query, limit=limit).hits)

    def search_candidate(
        self,
        candidate: dict[str, Any],
        *,
        limit: int = 24,
    ) -> list[RetrievalHit]:
        query_parts = [candidate["text"]]
        query_parts.extend(candidate.get("target_hints", []))
        return self.search(" ".join(query_parts), limit=limit)

    def exact_canonical_support(
        self,
        candidate: dict[str, Any],
        hits: list[RetrievalHit],
    ) -> list[RetrievalHit]:
        """Return only conservative exact-text support with canonical identity.

        FTS similarity alone is never enough to validate a claim. The baseline
        issue-16 promoter requires a substantive candidate sentence to occur
        verbatim (modulo whitespace/case folding) in a verified extracted
        segment that is already bound to a canonical Document.
        """
        claim = normalize_text(candidate["text"])
        if len(claim) < 40 or len(_query_terms(claim, maximum=100)) < 6:
            return []

        result: list[RetrievalHit] = []
        seen_segments: set[str] = set()
        for hit in hits:
            if hit.document_id is None:
                continue
            if claim not in normalize_text(hit.text):
                continue
            if hit.extracted_segment_id in seen_segments:
                continue
            seen_segments.add(hit.extracted_segment_id)
            result.append(hit)
        return result

    def lookup_canonical_target(
        self,
        target_document_id: str,
        *,
        target_provision_id: str | None = None,
        limit: int = 20,
    ) -> CanonicalTargetLookup:
        """Retrieve evidence only from one validated canonical target.

        This path never falls back to thematic FTS. A provision target is valid
        only inside its owning document. Missing/stale/inconsistent targets are
        returned as explicit lookup states so the research layer can preserve
        uncertainty rather than broadening the query silently.
        """
        strategy = (
            "canonical_provision_target"
            if target_provision_id is not None
            else "canonical_document_target"
        )
        if limit <= 0:
            return CanonicalTargetLookup(
                target_document_id,
                target_provision_id,
                strategy,
                "no_evidence",
            )

        document = self.con.execute(
            "SELECT 1 FROM documents WHERE document_id = ?",
            (target_document_id,),
        ).fetchone()
        if document is None:
            return CanonicalTargetLookup(
                target_document_id,
                target_provision_id,
                strategy,
                "missing_document",
            )

        if target_provision_id is not None:
            provision = self.con.execute(
                "SELECT document_id FROM provisions WHERE provision_id = ?",
                (target_provision_id,),
            ).fetchone()
            if provision is None:
                return CanonicalTargetLookup(
                    target_document_id,
                    target_provision_id,
                    strategy,
                    "missing_provision",
                )
            if str(provision[0]) != target_document_id:
                return CanonicalTargetLookup(
                    target_document_id,
                    target_provision_id,
                    strategy,
                    "inconsistent_provision",
                )

        hits: list[RetrievalHit] = []
        seen_equivalents: set[tuple[str, str]] = set()
        offset = 0
        batch_size = max(limit, _FTS_SCAN_BATCH_SIZE)

        while len(hits) < limit:
            if target_provision_id is None:
                rows = self.con.execute(
                    """
                    SELECT es.rowid
                    FROM extracted_segments es
                    JOIN text_extractions te
                      ON te.extraction_id = es.extraction_id
                     AND te.status = 'success'
                    JOIN manifestations m
                      ON m.manifestation_id = te.manifestation_id
                    WHERE m.document_id = ?
                    ORDER BY es.extraction_id, es.sequence_no, es.extracted_segment_id
                    LIMIT ? OFFSET ?
                    """,
                    (target_document_id, batch_size, offset),
                ).fetchall()
            else:
                rows = self.con.execute(
                    """
                    SELECT DISTINCT es.rowid
                    FROM provision_observations po
                    JOIN provisions p
                      ON p.provision_id = po.provision_id
                    JOIN extracted_segments es
                      ON es.extracted_segment_id = po.extracted_segment_id
                    JOIN text_extractions te
                      ON te.extraction_id = es.extraction_id
                     AND te.status = 'success'
                    JOIN manifestations m
                      ON m.manifestation_id = te.manifestation_id
                    WHERE p.provision_id = ?
                      AND p.document_id = ?
                      AND m.document_id = ?
                    ORDER BY es.extraction_id, es.sequence_no, es.extracted_segment_id
                    LIMIT ? OFFSET ?
                    """,
                    (
                        target_provision_id,
                        target_document_id,
                        target_document_id,
                        batch_size,
                        offset,
                    ),
                ).fetchall()

            if not rows:
                break
            for (rowid,) in rows:
                row = self._candidate_row(int(rowid))
                if row is None:
                    continue
                if str(row[12]) != target_document_id:
                    raise RetrievalIntegrityError(
                        "canonical target lookup escaped owning document: "
                        f"expected={target_document_id} actual={row[12]}"
                    )
                equivalence_key = (str(row[1]), str(row[4]))
                if equivalence_key in seen_equivalents:
                    continue
                hits.append(self._materialize_hit(row, rank=0.0))
                seen_equivalents.add(equivalence_key)
                if len(hits) >= limit:
                    break

            if len(hits) >= limit or len(rows) < batch_size:
                break
            offset += len(rows)

        return CanonicalTargetLookup(
            target_document_id,
            target_provision_id,
            strategy,
            "resolved" if hits else "no_evidence",
            tuple(hits),
        )

    def provision_for_segment(
        self,
        extracted_segment_id: str,
    ) -> dict[str, Any] | None:
        """Return one provision only when its observation is exactly citable.

        Provision identity and citable provision text are separate facts. A
        heading-only/empty observation, a quote absent from the segment, or a
        quote with multiple exact anchors may still be useful canonical
        structure, but it must not be promoted to provision-level CASE
        evidence or rule semantics.
        """
        rows = self.con.execute(
            """
            SELECT
                p.provision_id,
                p.document_id,
                p.provision_type,
                p.designation,
                p.title,
                po.normative_text,
                po.normative_text_sha256,
                es.text,
                es.text_sha256
            FROM provision_observations po
            JOIN provisions p
              ON p.provision_id = po.provision_id
            JOIN extracted_segments es
              ON es.extracted_segment_id = po.extracted_segment_id
            WHERE po.extracted_segment_id = ?
            ORDER BY p.provision_id
            """,
            (extracted_segment_id,),
        ).fetchall()
        if len(rows) != 1:
            return None

        row = rows[0]
        normative_text = row[5]
        normative_sha = hashlib.sha256(normative_text.encode("utf-8")).hexdigest()
        if normative_sha != row[6]:
            raise RetrievalIntegrityError(
                "provision normative-text fingerprint mismatch: "
                f"{row[0]} expected={row[6]} actual={normative_sha}"
            )

        segment_text = row[7]
        segment_sha = hashlib.sha256(segment_text.encode("utf-8")).hexdigest()
        if segment_sha != row[8]:
            raise RetrievalIntegrityError(
                "extracted segment text fingerprint mismatch: "
                f"{extracted_segment_id} expected={row[8]} actual={segment_sha}"
            )

        if exact_unambiguous_substring_offset(
            segment_text,
            normative_text,
        ) is None:
            return None

        return {
            "provision_id": row[0],
            "document_id": row[1],
            "provision_type": row[2],
            "designation": row[3],
            "title": row[4],
        }


    def reference_resolution_states_for_segment(
        self,
        extracted_segment_id: str,
    ) -> list[dict[str, Any]]:
        """Return one conservative resolution state for each reference mention."""
        rows = self.con.execute(
            """
            SELECT
                rm.reference_mention_id,
                rm.normalized_reference,
                rm.requires_human_review,
                rr.reference_resolution_id,
                rr.status,
                rr.requires_human_review,
                rr.target_document_id,
                rr.target_provision_id
            FROM reference_mentions rm
            LEFT JOIN reference_resolutions rr
              ON rr.reference_mention_id = rm.reference_mention_id
            WHERE rm.extracted_segment_id = ?
            ORDER BY
                rm.reference_mention_id,
                rr.reference_resolution_id
            """,
            (extracted_segment_id,),
        ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            mention_id = str(row[0])
            item = grouped.setdefault(
                mention_id,
                {
                    "reference_mention_id": mention_id,
                    "query_text": str(row[1]),
                    "mention_requires_human_review": bool(row[2]),
                    "resolutions": [],
                },
            )
            if row[3] is not None:
                item["resolutions"].append(
                    {
                        "reference_resolution_id": str(row[3]),
                        "status": str(row[4]),
                        "requires_human_review": bool(row[5]),
                        "target_document_id": row[6],
                        "target_provision_id": row[7],
                    }
                )

        result: list[dict[str, Any]] = []
        for mention_id in sorted(grouped):
            item = grouped[mention_id]
            resolutions = item.pop("resolutions")
            state = "missing_resolution"
            target_document_id: str | None = None
            target_provision_id: str | None = None

            if item["mention_requires_human_review"] or any(
                row["requires_human_review"] for row in resolutions
            ):
                state = "requires_review"
            elif not resolutions:
                state = "missing_resolution"
            elif any(row["status"] == "ambiguous" for row in resolutions):
                state = "ambiguous"
            elif any(row["status"] == "unresolved" for row in resolutions):
                state = "unresolved"
            elif all(row["status"] == "resolved" for row in resolutions):
                targets = {
                    (row["target_document_id"], row["target_provision_id"])
                    for row in resolutions
                }
                if len(targets) != 1:
                    state = "ambiguous"
                else:
                    target_document_id, target_provision_id = next(iter(targets))
                    state = (
                        "resolved"
                        if target_document_id is not None
                        else "inconsistent_target"
                    )
            else:
                state = "unresolved"

            query_text = item["query_text"]
            if state == "resolved" and target_provision_id is not None:
                provision = self.con.execute(
                    """
                    SELECT designation
                    FROM provisions
                    WHERE provision_id = ?
                      AND document_id = ?
                    """,
                    (target_provision_id, target_document_id),
                ).fetchone()
                if provision is not None and provision[0]:
                    query_text = f"{query_text} {provision[0]}"

            result.append(
                {
                    "reference_mention_id": mention_id,
                    "query_text": query_text,
                    "resolution_state": state,
                    "target_document_id": target_document_id,
                    "target_provision_id": target_provision_id,
                }
            )
        return result

    def resolved_references_for_segment(
        self,
        extracted_segment_id: str,
    ) -> list[dict[str, Any]]:
        """Return only references eligible for exact canonical expansion."""
        return [
            {
                "query_text": item["query_text"],
                "target_document_id": item["target_document_id"],
                "target_provision_id": item["target_provision_id"],
            }
            for item in self.reference_resolution_states_for_segment(
                extracted_segment_id
            )
            if item["resolution_state"] == "resolved"
        ]

    def _hit_for_segment(
        self,
        extracted_segment_id: str,
    ) -> RetrievalHit | None:
        """Materialize one verified segment without using thematic retrieval."""
        rows = self.con.execute(
            """
            SELECT es.rowid
            FROM extracted_segments es
            JOIN text_extractions te
              ON te.extraction_id = es.extraction_id
             AND te.status = 'success'
            WHERE es.extracted_segment_id = ?
            """,
            (extracted_segment_id,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RetrievalIntegrityError(
                "extracted segment identity is not unique: "
                f"{extracted_segment_id}"
            )
        row = self._candidate_row(int(rows[0][0]))
        if row is None:
            return None
        return self._materialize_hit(row, rank=0.0)

    def _sequence_neighbor(
        self,
        *,
        extraction_id: str,
        sequence_no: int,
    ) -> tuple[str, RetrievalHit | None]:
        """Resolve one sequence position without guessing across ambiguity."""
        rows = self.con.execute(
            """
            SELECT es.rowid
            FROM extracted_segments es
            WHERE es.extraction_id = ?
              AND es.sequence_no = ?
            ORDER BY es.extracted_segment_id
            """,
            (extraction_id, sequence_no),
        ).fetchall()
        if not rows:
            return "missing", None
        if len(rows) != 1:
            return "ambiguous", None
        row = self._candidate_row(int(rows[0][0]))
        if row is None:
            return "missing", None
        return "resolved", self._materialize_hit(row, rank=0.0)

    def _citable_provision_target_hits(
        self,
        *,
        target_document_id: str,
        target_provision_id: str,
        limit: int,
    ) -> list[RetrievalHit]:
        """Return bounded target hits that retain an exact provision anchor."""
        if limit <= 0:
            return []

        hits: list[RetrievalHit] = []
        seen_equivalents: set[tuple[str, str]] = set()
        offset = 0
        batch_size = max(limit, _FTS_SCAN_BATCH_SIZE)

        while len(hits) < limit:
            rows = self.con.execute(
                """
                SELECT DISTINCT es.rowid
                FROM provision_observations po
                JOIN provisions p
                  ON p.provision_id = po.provision_id
                JOIN extracted_segments es
                  ON es.extracted_segment_id = po.extracted_segment_id
                JOIN text_extractions te
                  ON te.extraction_id = es.extraction_id
                 AND te.status = 'success'
                JOIN manifestations m
                  ON m.manifestation_id = te.manifestation_id
                WHERE p.provision_id = ?
                  AND p.document_id = ?
                  AND m.document_id = ?
                ORDER BY es.extraction_id, es.sequence_no, es.extracted_segment_id
                LIMIT ? OFFSET ?
                """,
                (
                    target_provision_id,
                    target_document_id,
                    target_document_id,
                    batch_size,
                    offset,
                ),
            ).fetchall()
            if not rows:
                break

            for (rowid,) in rows:
                row = self._candidate_row(int(rowid))
                if row is None:
                    continue
                if str(row[12]) != target_document_id:
                    raise RetrievalIntegrityError(
                        "context target lookup escaped owning document: "
                        f"expected={target_document_id} actual={row[12]}"
                    )
                provision = self.provision_for_segment(str(row[0]))
                if (
                    provision is None
                    or str(provision["provision_id"]) != target_provision_id
                ):
                    continue
                equivalence_key = (str(row[1]), str(row[4]))
                if equivalence_key in seen_equivalents:
                    continue
                hits.append(self._materialize_hit(row, rank=0.0))
                seen_equivalents.add(equivalence_key)
                if len(hits) >= limit:
                    break

            if len(hits) >= limit or len(rows) < batch_size:
                break
            offset += len(rows)

        return hits

    def retrieve_citable_context(
        self,
        extracted_segment_id: str,
        *,
        provision_id: str | None = None,
        max_context_hits: int = 4,
        include_resolved_references: bool = True,
    ) -> CitableContextResult:
        """Retrieve only structurally verified context for one citable segment.

        Context is intentionally opt-in. Same-provision expansion walks only
        contiguous positions in the same extraction/document and stops at a
        verified different provision or any unverified boundary. Explicit
        references expand only to uniquely resolved provision targets. Each
        returned hit remains an independent exact source segment; materializers
        must preserve separate EvidenceSpan anchors rather than concatenate text.
        """
        if max_context_hits < 0:
            raise ValueError("max_context_hits must be non-negative")

        anchor = self._hit_for_segment(extracted_segment_id)
        if anchor is None:
            gap = CitableContextGap(
                reason="anchor_missing",
                source_segment_id=extracted_segment_id,
            )
            return CitableContextResult(
                anchor_segment_id=extracted_segment_id,
                document_id=None,
                provision_id=provision_id,
                context_status="incomplete",
                gaps=(gap,),
            )

        if anchor.document_id is None:
            gap = CitableContextGap(
                reason="anchor_document_unresolved",
                source_segment_id=extracted_segment_id,
            )
            return CitableContextResult(
                anchor_segment_id=extracted_segment_id,
                document_id=None,
                provision_id=provision_id,
                context_status="incomplete",
                gaps=(gap,),
            )

        anchor_provision = self.provision_for_segment(extracted_segment_id)
        if anchor_provision is None:
            gap = CitableContextGap(
                reason="anchor_provision_not_citable",
                source_segment_id=extracted_segment_id,
            )
            return CitableContextResult(
                anchor_segment_id=extracted_segment_id,
                document_id=anchor.document_id,
                provision_id=provision_id,
                context_status="incomplete",
                gaps=(gap,),
            )

        resolved_provision_id = str(anchor_provision["provision_id"])
        if provision_id is not None and provision_id != resolved_provision_id:
            gap = CitableContextGap(
                reason="anchor_provision_mismatch",
                source_segment_id=extracted_segment_id,
                target_document_id=anchor.document_id,
                target_provision_id=provision_id,
            )
            return CitableContextResult(
                anchor_segment_id=extracted_segment_id,
                document_id=anchor.document_id,
                provision_id=provision_id,
                context_status="incomplete",
                gaps=(gap,),
            )

        provision_id = resolved_provision_id
        sentinel_limit = max_context_hits + 1
        ordered_keys: list[tuple[str, str]] = []
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        gaps: list[CitableContextGap] = []
        seen_gaps: set[tuple[object, ...]] = set()
        budget_exhausted = False

        def add_gap(
            reason: str,
            *,
            source_segment_id: str,
            reference_mention_id: str | None = None,
            target_document_id: str | None = None,
            target_provision_id: str | None = None,
        ) -> None:
            key = (
                reason,
                source_segment_id,
                reference_mention_id,
                target_document_id,
                target_provision_id,
            )
            if key in seen_gaps:
                return
            seen_gaps.add(key)
            gaps.append(
                CitableContextGap(
                    reason=reason,
                    source_segment_id=source_segment_id,
                    reference_mention_id=reference_mention_id,
                    target_document_id=target_document_id,
                    target_provision_id=target_provision_id,
                )
            )

        def add_candidate(
            hit: RetrievalHit,
            *,
            candidate_provision_id: str,
            basis: str,
            source_segment_id: str,
            reference_mention_id: str | None = None,
        ) -> bool:
            nonlocal budget_exhausted
            if hit.extracted_segment_id == extracted_segment_id:
                return True
            key = (hit.extracted_segment_id, candidate_provision_id)
            existing = candidates.get(key)
            if existing is None:
                if len(candidates) >= sentinel_limit:
                    budget_exhausted = True
                    return False
                existing = {
                    "hit": hit,
                    "provision_id": candidate_provision_id,
                    "bases": set(),
                    "source_segment_ids": set(),
                    "reference_mention_ids": set(),
                }
                candidates[key] = existing
                ordered_keys.append(key)
            existing["bases"].add(basis)
            existing["source_segment_ids"].add(source_segment_id)
            if reference_mention_id is not None:
                existing["reference_mention_ids"].add(reference_mention_id)
            if len(candidates) > max_context_hits:
                budget_exhausted = True
            return not budget_exhausted

        # Verified contiguous parts are collected forward first because headings
        # and amendment introductions conventionally depend on following text.
        # Preceding parts are considered second, but never by skipping a gap.
        contiguous_source_ids: list[str] = [extracted_segment_id]
        for direction in (1, -1):
            next_sequence = anchor.sequence_no + direction
            while next_sequence > 0 and not budget_exhausted:
                state, neighbor = self._sequence_neighbor(
                    extraction_id=anchor.extraction_id,
                    sequence_no=next_sequence,
                )
                if state == "missing":
                    break
                if state == "ambiguous":
                    add_gap(
                        "ambiguous_contiguous_sequence",
                        source_segment_id=extracted_segment_id,
                    )
                    break
                assert neighbor is not None
                if neighbor.document_id != anchor.document_id:
                    add_gap(
                        "document_boundary_mismatch",
                        source_segment_id=neighbor.extracted_segment_id,
                        target_document_id=neighbor.document_id,
                    )
                    break

                neighbor_provision = self.provision_for_segment(
                    neighbor.extracted_segment_id
                )
                if neighbor_provision is None:
                    add_gap(
                        "unverified_contiguous_boundary",
                        source_segment_id=neighbor.extracted_segment_id,
                    )
                    break
                neighbor_provision_id = str(
                    neighbor_provision["provision_id"]
                )
                if neighbor_provision_id != provision_id:
                    # A different exact provision is a verified hard boundary,
                    # not itself a context failure.
                    break

                contiguous_source_ids.append(neighbor.extracted_segment_id)
                if not add_candidate(
                    neighbor,
                    candidate_provision_id=provision_id,
                    basis="contiguous_provision",
                    source_segment_id=extracted_segment_id,
                ):
                    break
                next_sequence += direction

        if include_resolved_references and not budget_exhausted:
            for source_segment_id in contiguous_source_ids:
                states = self.reference_resolution_states_for_segment(
                    source_segment_id
                )
                for reference in states:
                    if budget_exhausted:
                        break
                    reference_mention_id = str(
                        reference["reference_mention_id"]
                    )
                    target_document_id = reference["target_document_id"]
                    target_provision_id = reference["target_provision_id"]
                    if reference["resolution_state"] != "resolved":
                        add_gap(
                            "reference_resolution_incomplete",
                            source_segment_id=source_segment_id,
                            reference_mention_id=reference_mention_id,
                            target_document_id=target_document_id,
                            target_provision_id=target_provision_id,
                        )
                        continue
                    if (
                        target_document_id is None
                        or target_provision_id is None
                    ):
                        add_gap(
                            "reference_without_provision_target",
                            source_segment_id=source_segment_id,
                            reference_mention_id=reference_mention_id,
                            target_document_id=target_document_id,
                            target_provision_id=target_provision_id,
                        )
                        continue

                    remaining = max(
                        1,
                        sentinel_limit - len(candidates),
                    )
                    target_hits = self._citable_provision_target_hits(
                        target_document_id=str(target_document_id),
                        target_provision_id=str(target_provision_id),
                        limit=remaining,
                    )
                    if not target_hits:
                        add_gap(
                            "reference_target_context_unavailable",
                            source_segment_id=source_segment_id,
                            reference_mention_id=reference_mention_id,
                            target_document_id=str(target_document_id),
                            target_provision_id=str(target_provision_id),
                        )
                        continue
                    for target_hit in target_hits:
                        if not add_candidate(
                            target_hit,
                            candidate_provision_id=str(target_provision_id),
                            basis="explicit_cross_reference",
                            source_segment_id=source_segment_id,
                            reference_mention_id=reference_mention_id,
                        ):
                            break

        if budget_exhausted:
            add_gap(
                "budget_exhausted",
                source_segment_id=extracted_segment_id,
            )

        admitted_keys = ordered_keys[:max_context_hits]
        hits = tuple(
            CitableContextHit(
                hit=candidates[key]["hit"],
                provision_id=candidates[key]["provision_id"],
                bases=tuple(sorted(candidates[key]["bases"])),
                source_segment_ids=tuple(
                    sorted(candidates[key]["source_segment_ids"])
                ),
                reference_mention_ids=tuple(
                    sorted(candidates[key]["reference_mention_ids"])
                ),
            )
            for key in admitted_keys
        )

        if not hits and not gaps:
            add_gap(
                "no_verified_context",
                source_segment_id=extracted_segment_id,
            )

        context_status = (
            "expanded_verified"
            if hits and not gaps and not budget_exhausted
            else "incomplete"
        )
        return CitableContextResult(
            anchor_segment_id=extracted_segment_id,
            document_id=anchor.document_id,
            provision_id=provision_id,
            context_status=context_status,
            hits=hits,
            gaps=tuple(gaps),
            budget_exhausted=budget_exhausted,
            verified_candidate_count=len(candidates),
        )

    def query_for_document(self, document_id: str) -> str | None:
        """Return human-readable canonical vocabulary for reference expansion.

        The document ID is used only as an internal lookup key. It is never
        emitted into the FTS query, which prevents canonical identity from
        becoming a magic search token.
        """
        row = self.con.execute(
            """
            SELECT
                d.document_type,
                d.title,
                (
                    SELECT di.identifier_value
                    FROM document_identifiers di
                    WHERE di.document_id = d.document_id
                      AND di.is_primary = 1
                    ORDER BY di.identifier_id
                    LIMIT 1
                )
            FROM documents d
            WHERE d.document_id = ?
            """,
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        parts = [value for value in (row[0], row[2], row[1]) if value]
        return " ".join(str(value) for value in parts) or None
