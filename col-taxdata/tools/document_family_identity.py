from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from source_identity import (
    CONPES,
    CONSTITUCION_POLITICA,
    CORTE_CONSTITUCIONAL_SENTENCIA_C,
    DIAN_CONCEPTO,
    DIAN_OFICIO,
    IdentityAssessment,
    IdentitySignal,
    classify_source_url,
    normalize_ascii,
    normalize_document_number,
)


SUPPORTED_FAMILIES = frozenset(
    {
        DIAN_CONCEPTO,
        DIAN_OFICIO,
        CORTE_CONSTITUCIONAL_SENTENCIA_C,
        CONPES,
        CONSTITUCION_POLITICA,
    }
)

# Family-specific headings are deliberately narrower than generic normative-act
# headings. A quoted Ley/Decreto/Resolución therefore cannot become the identity
# of one of these source families.
DIAN_CONCEPTO_HEADING_RE = re.compile(
    r"^CONCEPTO(?:\s+(?:TRIBUTARIO|ADUANERO|CAMBIARIO))?"
    r"\s+(?:NUMERO\s+)?(?P<number>\d+[A-Z]?)"
    r"(?:\s+INT(?:ERNO)?\.?\s+(?P<internal>\d+))?"
    r"\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
DIAN_CONCEPTO_BRACKET_HEADING_RE = re.compile(
    r"^CONCEPTO\s+(?:\d+-)?(?P<number>\d+[A-Z]?)"
    r"\s+\[\d+\]\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
DIAN_OFICIO_HEADING_RE = re.compile(
    r"^OFICIO(?:\s+(?:TRIBUTARIO|ADUANERO|CAMBIARIO))?"
    r"\s+(?:(?:NO|NRO|NUMERO)\.?\s*)?"
    r"(?P<number>\d+[A-Z]?)\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
SENTENCIA_C_HEADING_RE = re.compile(
    r"^SENTENCIA\s+C[-\s]?(?P<number>\d+[A-Z]?)"
    r"\s+(?:DE|DEL)\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
CONPES_HEADING_RE = re.compile(
    r"^(?:DOCUMENTO\s+)?CONPES\s+(?P<number>\d+)"
    r"(?:\s+DE\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
CONSTITUCION_HEADING_RE = re.compile(
    r"^CONSTITUCION\s+POLITICA(?:\s+DE\s+COLOMBIA)?"
    r"(?:\s+DE)?\s*(?P<year>\d{4})?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SegmentIdentityInput:
    """Minimal extracted-segment view used for family identity assessment."""

    sequence_no: int
    segment_type: str
    text: str


@dataclass(frozen=True)
class FamilyIdentityResult:
    """Resolved family identity plus the evidence that justified it."""

    assessment: IdentityAssessment
    identity: IdentitySignal | None
    title: str | None
    metadata: dict[str, str]

    @property
    def accepted(self) -> bool:
        return self.assessment.accepted and self.identity is not None


@dataclass(frozen=True)
class _HeadingCandidate:
    signal: IdentitySignal
    title: str
    metadata: dict[str, str]


def _normalized_heading(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_ascii(text).upper()).strip()


def _candidate_from_match(
    *,
    family: str,
    title: str,
    document_type: str,
    issuer_key: str,
    match: re.Match[str],
    fallback_year: int | None = None,
) -> _HeadingCandidate:
    year_text = match.groupdict().get("year")
    metadata: dict[str, str] = {}
    internal = match.groupdict().get("internal")
    if internal:
        metadata["internal_number"] = internal
    return _HeadingCandidate(
        IdentitySignal(
            family,
            title,
            document_type,
            normalize_document_number(match.group("number")),
            int(year_text) if year_text else fallback_year,
            issuer_key,
        ),
        title,
        metadata,
    )


def _heading_candidates(
    source: IdentitySignal,
    segments: Iterable[SegmentIdentityInput],
) -> list[_HeadingCandidate]:
    """Return only identity-shaped headings near the document front matter.

    The extraction pipeline can classify quoted norms as document headings.
    Restricting this parser to family-specific patterns and early/front-matter
    segments prevents a generic cited norm from participating in identity.
    """

    candidates: list[_HeadingCandidate] = []
    for segment in segments:
        if segment.sequence_no > 12:
            continue
        title = segment.text.strip()
        if not title:
            continue
        normalized = _normalized_heading(title)

        if source.family in {DIAN_CONCEPTO, DIAN_OFICIO}:
            for concept_pattern in (
                DIAN_CONCEPTO_HEADING_RE,
                DIAN_CONCEPTO_BRACKET_HEADING_RE,
            ):
                concept = concept_pattern.match(normalized)
                if concept:
                    candidates.append(
                        _candidate_from_match(
                            family=source.family,
                            title=title,
                            document_type="CONCEPTO",
                            issuer_key="DIAN",
                            match=concept,
                        )
                    )
                    break
            if source.family == DIAN_OFICIO:
                oficio = DIAN_OFICIO_HEADING_RE.match(normalized)
                if oficio:
                    candidates.append(
                        _candidate_from_match(
                            family=source.family,
                            title=title,
                            document_type="OFICIO",
                            issuer_key="DIAN",
                            match=oficio,
                        )
                    )
        elif source.family == CORTE_CONSTITUCIONAL_SENTENCIA_C:
            match = SENTENCIA_C_HEADING_RE.match(normalized)
            if match:
                candidates.append(
                    _candidate_from_match(
                        family=source.family,
                        title=title,
                        document_type="SENTENCIA_C",
                        issuer_key="CORTE_CONSTITUCIONAL",
                        match=match,
                    )
                )
        elif source.family == CONPES:
            match = CONPES_HEADING_RE.match(normalized)
            if match:
                candidates.append(
                    _candidate_from_match(
                        family=source.family,
                        title=title,
                        document_type="CONPES",
                        issuer_key="CONPES",
                        match=match,
                        fallback_year=source.year,
                    )
                )
        elif source.family == CONSTITUCION_POLITICA:
            match = CONSTITUCION_HEADING_RE.match(normalized)
            if match:
                year_text = match.groupdict().get("year")
                year = int(year_text) if year_text else source.year
                if year is not None:
                    candidates.append(
                        _HeadingCandidate(
                            IdentitySignal(
                                source.family,
                                title,
                                "CONSTITUCION_POLITICA",
                                str(year),
                                year,
                                "ASAMBLEA_CONSTITUYENTE",
                            ),
                            title,
                            {},
                        )
                    )

    unique: dict[tuple[str | None, str | None, int | None, str | None], _HeadingCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.signal.document_type,
            candidate.signal.number,
            candidate.signal.year,
            candidate.signal.issuer_key,
        )
        unique.setdefault(key, candidate)
    return list(unique.values())


def _source_is_complete(source: IdentitySignal) -> bool:
    return bool(
        source.document_type
        and source.number
        and source.year
        and source.issuer_key
        and source.canonical_key
    )


def _candidate_conflicts_with_source(
    source: IdentitySignal,
    candidate: IdentitySignal,
) -> bool:
    # oficio_dian_* is a source-page family. Modern pages may carry an explicit
    # CONCEPTO title; that title is accepted only when the encoded number/year
    # agree with the source URL. Older pages default to OFICIO from the URL.
    allowed_types = (
        {"OFICIO", "CONCEPTO"}
        if source.family == DIAN_OFICIO
        else {source.document_type}
    )
    if candidate.document_type not in allowed_types:
        return True
    if source.number is not None and candidate.number != source.number:
        return True
    if source.year is not None and candidate.year != source.year:
        return True
    if source.issuer_key is not None and candidate.issuer_key != source.issuer_key:
        return True
    return False


def assess_supported_family_identity(
    source_url: str,
    segments: Iterable[SegmentIdentityInput],
) -> FamilyIdentityResult | None:
    """Assess one DEF-0003 family without generic normative fall-through.

    Trusted URL constraints are evaluated first. Family-specific content can
    confirm/refine the identity, but contradictory or incomplete evidence is
    left unresolved rather than guessed.
    """

    source = classify_source_url(source_url)
    if source.family not in SUPPORTED_FAMILIES:
        return None

    candidates = _heading_candidates(source, segments)
    compatible = [
        candidate
        for candidate in candidates
        if not _candidate_conflicts_with_source(source, candidate.signal)
    ]
    if len(compatible) > 1:
        return FamilyIdentityResult(
            IdentityAssessment(
                "unresolved",
                source,
                compatible[0].signal,
                "FAMILY_IDENTITY_AMBIGUOUS",
            ),
            None,
            compatible[0].title,
            {},
        )

    if compatible:
        # A candidate that exactly confirms the trusted URL identity wins over
        # other early family-shaped text. DIAN pages often expose both a
        # radication/display number and the source-family number in front matter.
        candidate = compatible[0]
        if candidate.signal.canonical_key is None:
            return FamilyIdentityResult(
                IdentityAssessment(
                    "unresolved",
                    source,
                    candidate.signal,
                    "SOURCE_IDENTITY_UNRESOLVED",
                ),
                None,
                candidate.title,
                candidate.metadata,
            )
        return FamilyIdentityResult(
            IdentityAssessment("accepted", source, candidate.signal),
            candidate.signal,
            candidate.title,
            candidate.metadata,
        )

    conflicting = [
        candidate
        for candidate in candidates
        if _candidate_conflicts_with_source(source, candidate.signal)
    ]
    if conflicting:
        return FamilyIdentityResult(
            IdentityAssessment(
                "unresolved",
                source,
                conflicting[0].signal,
                "SOURCE_IDENTITY_CONFLICT",
            ),
            None,
            conflicting[0].title,
            conflicting[0].metadata,
        )

    if not _source_is_complete(source):
        return FamilyIdentityResult(
            IdentityAssessment(
                "unresolved",
                source,
                None,
                "SOURCE_IDENTITY_UNRESOLVED",
            ),
            None,
            None,
            {},
        )

    return FamilyIdentityResult(
        IdentityAssessment("accepted", source, None),
        source,
        None,
        {},
    )


def default_family_title(signal: IdentitySignal) -> str:
    """Build a deterministic display title when source evidence has no heading."""

    labels = {
        "CONCEPTO": "CONCEPTO",
        "OFICIO": "OFICIO",
        "SENTENCIA_C": "SENTENCIA C",
        "CONPES": "CONPES",
        "CONSTITUCION_POLITICA": "CONSTITUCIÓN POLÍTICA",
    }
    label = labels.get(signal.document_type or "", signal.document_type or signal.family)
    if signal.document_type == "SENTENCIA_C":
        return f"{label}-{signal.number} DE {signal.year}"
    if signal.document_type == "CONSTITUCION_POLITICA":
        return f"{label} DE COLOMBIA {signal.year}"
    return f"{label} {signal.number} DE {signal.year}"
