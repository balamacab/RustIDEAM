from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import unicodedata
import urllib.parse
import uuid


NORMATIVE_ACT = "NORMATIVE_ACT"
DIAN_CONCEPTO = "DIAN_CONCEPTO"
DIAN_OFICIO = "DIAN_OFICIO"
CORTE_CONSTITUCIONAL_SENTENCIA_C = "CORTE_CONSTITUCIONAL_SENTENCIA_C"
CONPES = "CONPES"
CONSTITUCION_POLITICA = "CONSTITUCION_POLITICA"
JURISPRUDENCIA = "JURISPRUDENCIA"
UNKNOWN = "UNKNOWN"

DOCUMENT_HEADING_RE = re.compile(
    r"^(?P<type>DECRETO|LEY|RESOLUCI[ÓO]N|CIRCULAR)"
    r"\s+(?:N[ÚU]MERO\s+)?(?P<number>\d+[A-Z]?)"
    r"\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
NORMATIVE_PREFIX_RE = re.compile(r"^(ley|decreto|resolucion|circular)_", re.I)
URL_NUMBER_YEAR_RE = re.compile(r"(?:_|-)(?P<number>0*\d+[a-z]?)[_](?P<year>\d{4})\.html?$", re.I)
C_DECISION_RE = re.compile(r"^c-(?P<number>\d+[a-z]?)_(?P<year>\d{4})\.html?$", re.I)
CONPES_RE = re.compile(r"^conpes_(?:[a-z0-9-]+_)*(?P<number>\d+)_(?P<year>\d{4})\.html?$", re.I)


@dataclass(frozen=True)
class IdentitySignal:
    family: str
    raw_value: str
    document_type: str | None = None
    number: str | None = None
    year: int | None = None

    @property
    def canonical_key(self) -> str | None:
        if self.document_type and self.number and self.year:
            return f"CO:{self.document_type}:{self.number}:{self.year}"
        return None


@dataclass(frozen=True)
class IdentityAssessment:
    status: str
    source: IdentitySignal
    content: IdentitySignal | None
    reason_code: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted" and self.content is not None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, material).hex}"


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_document_type(value: str) -> str:
    key = normalize_ascii(value).upper()
    return {
        "DECRETO": "DECRETO",
        "LEY": "LEY",
        "RESOLUCION": "RESOLUCION",
        "CIRCULAR": "CIRCULAR",
    }[key]


def normalize_document_number(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper()
    match = re.fullmatch(r"0*(\d+)([A-Z]?)", compact)
    if not match:
        return compact
    return str(int(match.group(1))) + match.group(2)


def classify_source_url(source_url: str) -> IdentitySignal:
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(source_url).path)).name.lower()

    prefix = NORMATIVE_PREFIX_RE.match(name)
    if prefix:
        doc_type = normalize_document_type(prefix.group(1))
        tail = URL_NUMBER_YEAR_RE.search(name)
        number = normalize_document_number(tail.group("number")) if tail else None
        year = int(tail.group("year")) if tail else None
        return IdentitySignal(NORMATIVE_ACT, source_url, doc_type, number, year)

    if name.startswith("oficio_dian_"):
        return IdentitySignal(DIAN_OFICIO, source_url)
    if name.startswith("concepto_") and ("_dian_" in name or name.startswith("concepto_dian_")):
        return IdentitySignal(DIAN_CONCEPTO, source_url)

    match = C_DECISION_RE.match(name)
    if match:
        return IdentitySignal(
            CORTE_CONSTITUCIONAL_SENTENCIA_C,
            source_url,
            "SENTENCIA_C",
            normalize_document_number(match.group("number")),
            int(match.group("year")),
        )

    match = CONPES_RE.match(name)
    if match:
        return IdentitySignal(
            CONPES,
            source_url,
            "CONPES",
            normalize_document_number(match.group("number")),
            int(match.group("year")),
        )

    if name.startswith("constitucion_politica_"):
        year_match = re.search(r"_(\d{4})\.html?$", name)
        return IdentitySignal(
            CONSTITUCION_POLITICA,
            source_url,
            "CONSTITUCION_POLITICA",
            None,
            int(year_match.group(1)) if year_match else None,
        )

    if name.startswith(("sentencia_", "auto_")) or re.match(r"^\d{5}-\d{2}-", name):
        return IdentitySignal(JURISPRUDENCIA, source_url)

    return IdentitySignal(UNKNOWN, source_url)


def parse_normative_heading(heading: str) -> IdentitySignal | None:
    match = DOCUMENT_HEADING_RE.match(normalize_ascii(heading).upper())
    if not match:
        return None
    return IdentitySignal(
        NORMATIVE_ACT,
        heading,
        normalize_document_type(match.group("type")),
        normalize_document_number(match.group("number")),
        int(match.group("year")),
    )


def assess_generic_normative_identity(source_url: str, heading: str) -> IdentityAssessment:
    source = classify_source_url(source_url)
    content = parse_normative_heading(heading)

    if source.family != NORMATIVE_ACT:
        reason = (
            "SOURCE_IDENTITY_UNRESOLVED"
            if source.family == UNKNOWN
            else (
                "SOURCE_IDENTITY_CONFLICT"
                if content is not None
                else "SOURCE_IDENTITY_UNRESOLVED"
            )
        )
        return IdentityAssessment("unresolved", source, content, reason)
    if content is None:
        return IdentityAssessment("unresolved", source, None, "SOURCE_IDENTITY_UNRESOLVED")

    conflict = (
        source.document_type != content.document_type
        or (source.number is not None and source.number != content.number)
        or (source.year is not None and source.year != content.year)
    )
    if conflict:
        return IdentityAssessment("unresolved", source, content, "SOURCE_IDENTITY_CONFLICT")
    return IdentityAssessment("accepted", source, content)


def equivalent_existing_canonical_key(
    con: sqlite3.Connection,
    *,
    document_id: str,
    signal: IdentitySignal,
) -> str | None:
    if not (signal.document_type and signal.number and signal.year):
        return None
    rows = con.execute(
        """
        SELECT identifier_value
        FROM document_identifiers
        WHERE document_id = ? AND identifier_type = 'canonical_key'
        ORDER BY is_primary DESC, identifier_id
        """,
        (document_id,),
    ).fetchall()
    for (value,) in rows:
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "CO":
            continue
        _, doc_type, number, year = parts
        try:
            year_int = int(year)
        except ValueError:
            continue
        if (
            doc_type == signal.document_type
            and normalize_document_number(number) == signal.number
            and year_int == signal.year
        ):
            return value
    return None


def record_identity_signals(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    extraction_id: str,
    assessment: IdentityAssessment,
) -> None:
    now = utc_now()
    for origin, signal in (("source_url", assessment.source), ("document_heading", assessment.content)):
        if signal is None:
            continue
        signal_id = deterministic_id(
            "IDSIG",
            f"{manifestation_id}:{extraction_id}:{origin}:{signal.raw_value}",
        )
        con.execute(
            """
            INSERT INTO document_identity_signals(
                identity_signal_id, manifestation_id, extraction_id,
                signal_origin, source_family, document_type,
                document_number, document_year, raw_value, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_signal_id) DO NOTHING
            """,
            (
                signal_id,
                manifestation_id,
                extraction_id,
                origin,
                signal.family,
                signal.document_type,
                signal.number,
                signal.year,
                signal.raw_value,
                now,
            ),
        )


def open_identity_review(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    reason_code: str,
) -> str:
    review_id = deterministic_id("REV", f"{manifestation_id}:{reason_code}")
    con.execute(
        """
        INSERT INTO review_queue(
            review_id, entity_type, entity_id, reason_code, severity, created_at
        )
        VALUES (?, 'manifestation', ?, ?, 'high', ?)
        ON CONFLICT(review_id) DO UPDATE SET
            resolved_at = NULL,
            resolution = NULL,
            reviewer = NULL
        """,
        (review_id, manifestation_id, reason_code, utc_now()),
    )
    return review_id


def persist_assessment(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    extraction_id: str,
    assessment: IdentityAssessment,
) -> str | None:
    record_identity_signals(
        con,
        manifestation_id=manifestation_id,
        extraction_id=extraction_id,
        assessment=assessment,
    )
    if assessment.accepted:
        return None
    assert assessment.reason_code is not None
    return open_identity_review(
        con,
        manifestation_id=manifestation_id,
        reason_code=assessment.reason_code,
    )