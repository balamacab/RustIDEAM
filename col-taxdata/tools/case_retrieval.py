from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import sqlite3
from typing import Any


_WORD_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)
# Batch size affects query round-trips only; search keeps scanning until the
# requested number of unique exact-text groups is filled or FTS is exhausted.
_FTS_SCAN_BATCH_SIZE = 64


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


def _query_terms(value: str, *, maximum: int = 18) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.finditer(value.casefold()):
        term = match.group(0)
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= maximum:
            break
    return terms


def _fts_query(value: str) -> tuple[str, list[str]]:
    terms = _query_terms(value)
    if not terms:
        return "", []
    escaped = [term.replace('"', '""') for term in terms]
    return " OR ".join(f'"{term}"' for term in escaped), terms


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

    def search(self, query: str, *, limit: int = 20) -> list[RetrievalHit]:
        """Return top-N exact-text-diversified hits without deleting evidence.

        Raw FTS ranking remains authoritative. Once one valid representative of
        an (extraction_id, text_sha256) group occupies a normal result slot,
        later equivalents are skipped and cannot exhaust the requested window.
        """
        fts_query, terms = _fts_query(query)
        if not fts_query or limit <= 0:
            return []

        hits: list[RetrievalHit] = []
        seen_equivalents: set[tuple[str, str]] = set()
        offset = 0
        batch_size = max(limit, _FTS_SCAN_BATCH_SIZE)

        while len(hits) < limit:
            ranked_rows = self._ranked_rows(
                fts_query,
                limit=batch_size,
                offset=offset,
            )
            if not ranked_rows:
                break

            for rowid, rank in ranked_rows:
                row = self._candidate_row(rowid)
                if row is None:
                    continue

                # A contentless FTS rowid is only a candidate locator. If a
                # future replay causes rowid drift, never bind unrelated text.
                normalized = normalize_text(row[3])
                if not any(term in normalized for term in terms):
                    continue

                self._verify_segment_fingerprint(row[0], row[3], row[4])
                equivalence_key = (str(row[1]), str(row[4]))
                if equivalence_key in seen_equivalents:
                    continue

                duplicate_count, alternate_segment_ids = self._duplicate_provenance(
                    extraction_id=str(row[1]),
                    text_sha256=str(row[4]),
                    representative_id=str(row[0]),
                    representative_text=str(row[3]),
                )
                seen_equivalents.add(equivalence_key)

                hits.append(
                    RetrievalHit(
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
                )
                if len(hits) >= limit:
                    break

            if len(hits) >= limit or len(ranked_rows) < batch_size:
                break
            offset += len(ranked_rows)

        return hits

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


    def resolved_references_for_segment(
        self,
        extracted_segment_id: str,
    ) -> list[dict[str, Any]]:
        """Return only explicitly resolved canonical references from one hit.

        Candidate/ambiguous reference mentions are deliberately excluded: #137
        may expand through supported canonical resolution, never through a guess.
        """
        rows = self.con.execute(
            """
            SELECT DISTINCT
                rm.normalized_reference,
                rr.target_document_id,
                rr.target_provision_id
            FROM reference_mentions rm
            JOIN reference_resolutions rr
              ON rr.reference_mention_id = rm.reference_mention_id
             AND rr.status = 'resolved'
             AND rr.requires_human_review = 0
            WHERE rm.extracted_segment_id = ?
              AND rr.target_document_id IS NOT NULL
            ORDER BY
                rm.normalized_reference,
                rr.target_document_id,
                rr.target_provision_id
            """,
            (extracted_segment_id,),
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            query_text = row[0]
            if row[2] is not None:
                provision = self.con.execute(
                    """
                    SELECT designation
                    FROM provisions
                    WHERE provision_id = ?
                      AND document_id = ?
                    """,
                    (row[2], row[1]),
                ).fetchone()
                if provision is not None and provision[0]:
                    query_text = f"{query_text} {provision[0]}"
            result.append(
                {
                    "query_text": query_text,
                    "target_document_id": row[1],
                    "target_provision_id": row[2],
                }
            )
        return result

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
