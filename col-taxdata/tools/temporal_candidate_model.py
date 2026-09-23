from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import unicodedata

ROLE_PUBLICATION = "publication_date"
ROLE_ISSUED = "issued_date"
ROLE_COMMENCEMENT = "commencement_rule"
ROLES = (ROLE_PUBLICATION, ROLE_ISSUED, ROLE_COMMENCEMENT)

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
PUBLICATION_RE = re.compile(
    r"Diario\s+Oficial\s+No\.?\s*[\d.]+\s+de\s+"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)
ISSUED_RE = re.compile(
    r"Dad[oa]\s+en\s+.+?,\s*(?:a\s+)?"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)
EFFECTIVE_ON_PUBLICATION_RE = re.compile(
    r"rige\s+a\s+partir\s+de\s+la\s+fecha\s+de\s+su\s+"
    r"publicaci[oó]n"
    r"(?:\s+en\s+el\s+Diario\s+Oficial)?",
    re.IGNORECASE,
)
LEGAL_CITATION_RE = re.compile(
    r"\b(?:LEY|DECRETO|RESOLUCI[ÓO]N|CIRCULAR|SENTENCIA|CONCEPTO|OFICIO)"
    r"\s+(?:N[ÚU]MERO\s+)?[A-Z0-9._/-]+(?:\s+DE\s+\d{4})?\b",
    re.IGNORECASE,
)
EDITORIAL_MARKERS = (
    "NOTA DE VIGENCIA",
    "NOTAS DE VIGENCIA",
    "NOTA: VIGENCIA",
    "MODIFICADO POR",
    "MODIFICADA POR",
    "DEROGADO POR",
    "DEROGADA POR",
    "ADICIONADO POR",
    "ADICIONADA POR",
    "JURISPRUDENCIA",
    "CONCORDANCIA",
)
FRONT_MATTER_LIMIT = 30
NEAR_CLOSING_DISTANCE = 2


@dataclass(frozen=True)
class Segment:
    segment_id: str
    sequence_no: int
    segment_type: str
    section_path: str | None
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class TemporalCandidate:
    candidate_id: str
    role: str
    segment: Segment
    candidate_date: str | None
    context_type: str
    trusted_structure: bool
    char_start: int
    char_end: int
    exact_quote: str


@dataclass(frozen=True)
class RoleResolution:
    role: str
    status: str
    candidates: tuple[TemporalCandidate, ...]
    trusted_candidates: tuple[TemporalCandidate, ...]
    promoted: TemporalCandidate | None


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_key(value: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_ascii(value or "")).strip().upper()


def parse_date(match: re.Match[str]) -> str:
    month_key = normalize_ascii(match.group("month")).lower()
    if month_key not in MONTHS:
        raise RuntimeError(f"unsupported Spanish month: {match.group('month')!r}")
    return date(
        int(match.group("year")),
        MONTHS[month_key],
        int(match.group("day")),
    ).isoformat()


def structural_boundaries(segments: list[Segment]) -> tuple[int, set[int]]:
    first_article = next(
        (
            segment.sequence_no
            for segment in segments
            if segment.segment_type in {"article", "regulatory_article"}
        ),
        len(segments) + 1,
    )
    closing_sequences = {
        segment.sequence_no
        for segment in segments
        if segment.segment_type == "closing"
    }
    return first_article, closing_sequences


def is_editorial_context(segment: Segment) -> bool:
    combined = normalize_key(f"{segment.section_path or ''} {segment.text}")
    return any(marker in combined for marker in EDITORIAL_MARKERS)


def classify_candidate_context(
    *,
    role: str,
    segment: Segment,
    first_article_sequence: int,
    closing_sequences: set[int],
) -> tuple[str, bool]:
    """Classify candidates from deterministic extraction structure only.

    Conservative false negatives are preferable to promoting quoted or
    editorial material into canonical document-level temporal state.
    """
    if is_editorial_context(segment):
        return "editorial_history", False

    has_citation = LEGAL_CITATION_RE.search(segment.text) is not None
    if role == ROLE_PUBLICATION:
        if (
            segment.sequence_no < first_article_sequence
            and segment.sequence_no <= FRONT_MATTER_LIMIT
            and segment.segment_type
            in {"document_heading", "section_heading", "text", "table_row"}
            and not has_citation
        ):
            return "publication_metadata", True
    elif role == ROLE_ISSUED:
        near_closing = any(
            abs(segment.sequence_no - closing) <= NEAR_CLOSING_DISTANCE
            for closing in closing_sequences
        )
        if segment.segment_type == "closing" or (near_closing and not has_citation):
            return "primary_document_date", True
    elif role == ROLE_COMMENCEMENT:
        section_key = normalize_key(segment.section_path)
        if segment.segment_type in {"article", "regulatory_article"}:
            return "commencement_clause", True
        if section_key.startswith("ARTICULO") and (
            "VIGENCIA" in section_key or "RIGE" in normalize_key(segment.text)
        ):
            return "commencement_clause", True

    if has_citation:
        return "quoted_cited_norm", False
    return "unknown", False


def build_candidate(
    *,
    deterministic_id,
    extraction_id: str,
    role: str,
    segment: Segment,
    match: re.Match[str],
    candidate_date: str | None,
    first_article_sequence: int,
    closing_sequences: set[int],
    processor_name: str,
    processor_version: str,
) -> TemporalCandidate:
    context_type, trusted = classify_candidate_context(
        role=role,
        segment=segment,
        first_article_sequence=first_article_sequence,
        closing_sequences=closing_sequences,
    )
    char_start = segment.char_start + match.start()
    char_end = segment.char_start + match.end()
    candidate_id = deterministic_id(
        "TCA",
        (
            f"{extraction_id}:{role}:{segment.segment_id}:"
            f"{char_start}:{char_end}:{processor_name}:{processor_version}"
        ),
    )
    return TemporalCandidate(
        candidate_id=candidate_id,
        role=role,
        segment=segment,
        candidate_date=candidate_date,
        context_type=context_type,
        trusted_structure=trusted,
        char_start=char_start,
        char_end=char_end,
        exact_quote=match.group(0),
    )


def collect_candidates(
    *,
    deterministic_id,
    extraction_id: str,
    segments: list[Segment],
    processor_name: str,
    processor_version: str,
) -> dict[str, list[TemporalCandidate]]:
    first_article, closing_sequences = structural_boundaries(segments)
    result = {role: [] for role in ROLES}
    patterns = (
        (ROLE_PUBLICATION, PUBLICATION_RE, True),
        (ROLE_ISSUED, ISSUED_RE, True),
        (ROLE_COMMENCEMENT, EFFECTIVE_ON_PUBLICATION_RE, False),
    )
    for segment in segments:
        for role, pattern, has_date in patterns:
            for match in pattern.finditer(segment.text):
                result[role].append(
                    build_candidate(
                        deterministic_id=deterministic_id,
                        extraction_id=extraction_id,
                        role=role,
                        segment=segment,
                        match=match,
                        candidate_date=parse_date(match) if has_date else None,
                        first_article_sequence=first_article,
                        closing_sequences=closing_sequences,
                        processor_name=processor_name,
                        processor_version=processor_version,
                    )
                )
    return result


def resolve_role(role: str, candidates: list[TemporalCandidate]) -> RoleResolution:
    trusted = tuple(candidate for candidate in candidates if candidate.trusted_structure)
    promoted = trusted[0] if len(trusted) == 1 else None
    if promoted is not None:
        status = "resolved"
    elif len(trusted) > 1 or len(candidates) > 1:
        status = "ambiguous"
    else:
        status = "unresolved"
    return RoleResolution(
        role=role,
        status=status,
        candidates=tuple(candidates),
        trusted_candidates=trusted,
        promoted=promoted,
    )
