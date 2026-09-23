#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path

from register_document_identity import register_document_identity


PARSER_NAME = "dian_doctrine_registry"
PARSER_VERSION = "2"

TITLE_RE = re.compile(
    r"^CONCEPTO\s+(?P<external>\d+)\s+int\s+(?P<internal>\d+)\s+DE\s+(?P<year>\d{4})$",
    re.IGNORECASE,
)

MONTH_DAY_RE = re.compile(
    r"^\(?(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(?P<day>\d{1,2})\)?$"
)

WEB_PUBLICATION_RE = re.compile(
    r"Publicado\s+en\s+la\s+p[aá]gina\s+web\s+de\s+la\s+DIAN:\s*"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)

POSITION_LABEL_RE = re.compile(
    r"(?P<kind>PROBLEMA\s+JUR[IÍ]DICO|TESIS\s+JUR[IÍ]DICA)"
    r"(?:\s*\|)?\s+(?:PROBLEMA\s+JUR[IÍ]DICO|TESIS\s+JUR[IÍ]DICA)?"
    r"\s*No\.\s*(?P<ordinal>\d+)\s*$",
    re.IGNORECASE,
)

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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def parse_spanish_date(day: str, month: str, year: str) -> str:
    key = normalize_ascii(month).lower()
    if key not in MONTHS:
        raise RuntimeError(f"unsupported Spanish month: {month!r}")
    return date(int(year), MONTHS[key], int(day)).isoformat()


def create_evidence(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    source_url: str,
    source_sha256: str,
    retrieved_at: str,
    segment_id: str,
    char_start: int,
    char_end: int,
    text: str,
    role: str,
) -> tuple[str, bool]:
    evidence_id = deterministic_id(
        "EVD",
        f"{segment_id}:{PARSER_NAME}:{PARSER_VERSION}:{role}",
    )
    cur = con.execute(
        """
        INSERT OR IGNORE INTO evidence(
            evidence_id,
            claim_id,
            manifestation_id,
            segment_id,
            page_number,
            char_start,
            char_end,
            exact_quote,
            source_url,
            source_sha256,
            retrieved_at,
            extraction_method,
            extractor_version,
            confidence,
            review_status,
            extracted_segment_id
        )
        VALUES (
            ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?,
            ?, ?, 1.0, 'machine_validated', ?
        )
        """,
        (
            evidence_id,
            manifestation_id,
            char_start,
            char_end,
            text,
            source_url,
            source_sha256,
            retrieved_at,
            f"{PARSER_NAME}:{PARSER_VERSION}:{role}",
            PARSER_VERSION,
            segment_id,
        ),
    )
    return evidence_id, bool(cur.rowcount)


def register_identifier(
    con: sqlite3.Connection,
    *,
    document_id: str,
    identifier_type: str,
    identifier_value: str,
    issuer: str,
    is_primary: int,
    evidence_id: str,
    evidence_role: str,
    now: str,
) -> tuple[str, bool, bool]:
    identifier_id = deterministic_id(
        "ID",
        f"{document_id}:{identifier_type}:{identifier_value}",
    )
    cur = con.execute(
        """
        INSERT OR IGNORE INTO document_identifiers(
            identifier_id,
            document_id,
            identifier_type,
            identifier_value,
            issuer,
            is_primary
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            identifier_id,
            document_id,
            identifier_type,
            identifier_value,
            issuer,
            is_primary,
        ),
    )

    ev = con.execute(
        """
        INSERT OR IGNORE INTO document_identifier_evidence(
            identifier_id,
            evidence_id,
            evidence_role,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            identifier_id,
            evidence_id,
            evidence_role,
            now,
        ),
    )
    return identifier_id, bool(cur.rowcount), bool(ev.rowcount)


def create_temporal_event(
    con: sqlite3.Connection,
    *,
    document_id: str,
    event_type: str,
    event_date: str,
    scope: str,
    evidence_id: str,
    evidence_role: str,
    now: str,
) -> tuple[str, bool, bool]:
    event_id = deterministic_id(
        "TEV",
        f"{document_id}:{event_type}:{event_date}:{scope}:{PARSER_VERSION}",
    )
    existing = con.execute(
        "SELECT 1 FROM temporal_events WHERE temporal_event_id = ?",
        (event_id,),
    ).fetchone()

    con.execute(
        """
        INSERT INTO temporal_events(
            temporal_event_id,
            entity_type,
            entity_id,
            event_type,
            event_date,
            effective_from,
            effective_to,
            caused_by_type,
            caused_by_id,
            scope,
            status,
            evidence_id,
            confidence,
            requires_human_review
        )
        VALUES (
            ?, 'document', ?, ?, ?, NULL, NULL,
            NULL, NULL, ?, 'validated', ?, 1.0, 0
        )
        ON CONFLICT(temporal_event_id) DO UPDATE SET
            event_date = excluded.event_date,
            scope = excluded.scope,
            status = excluded.status,
            evidence_id = excluded.evidence_id,
            confidence = excluded.confidence,
            requires_human_review = excluded.requires_human_review
        """,
        (
            event_id,
            document_id,
            event_type,
            event_date,
            scope,
            evidence_id,
        ),
    )

    link = con.execute(
        """
        INSERT OR IGNORE INTO temporal_event_evidence(
            temporal_event_id,
            evidence_id,
            evidence_role,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (event_id, evidence_id, evidence_role, now),
    )
    return event_id, existing is None, bool(link.rowcount)


def register_doctrine(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    """Register DIAN identity first, then optional modern doctrine metadata.

    Canonical identity is intentionally independent from the modern Concepto
    layout. Historic Oficios and older Conceptos therefore remain first-class
    documents even when they do not contain the modern internal-number/date/
    problem-thesis structure.
    """

    identity = register_document_identity(
        extraction_id=extraction_id,
        db_path=db_path,
    )
    if identity["status"] != "registered":
        return {
            "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            "doctrine_metadata_status": "not_registered",
            **identity,
        }

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        base = con.execute(
            """
            SELECT
                te.manifestation_id,
                m.document_id,
                m.sha256,
                m.retrieved_at,
                s.source_url
            FROM text_extractions te
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            JOIN sources s
              ON s.source_id = m.source_id
            WHERE te.extraction_id = ?
            """,
            (extraction_id,),
        ).fetchone()
        if base is None:
            raise RuntimeError(f"extraction not found: {extraction_id}")

        (
            manifestation_id,
            document_id,
            source_sha256,
            retrieved_at,
            source_url,
        ) = base
        assert document_id == identity["document_id"]

        segments = con.execute(
            """
            SELECT
                extracted_segment_id,
                sequence_no,
                segment_type,
                char_start,
                char_end,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        title_matches = []
        for row in segments:
            match = TITLE_RE.fullmatch(row[5].strip())
            if match:
                title_matches.append((row, match))

        # Only the modern Concepto shape has the richer doctrine metadata
        # modeled by schema/009. Identity registration above is complete even
        # when this optional structure is absent.
        if identity["document_type"] != "CONCEPTO" or len(title_matches) != 1:
            return {
                "parser_name": PARSER_NAME,
                "parser_version": PARSER_VERSION,
                **identity,
                "doctrine_metadata_status": "not_applicable",
                "modern_title_matches": len(title_matches),
            }

        title_row, title_match = title_matches[0]
        external_number = title_match.group("external")
        normalized_external_number = str(int(external_number))
        internal_number = title_match.group("internal")
        year = int(title_match.group("year"))

        if (
            normalized_external_number != str(identity["number"])
            or year != int(identity["year"])
        ):
            # This should normally have been rejected by the family identity
            # parser. Keep the metadata layer conservative if a future parser
            # change broadens its heading acceptance.
            return {
                "parser_name": PARSER_NAME,
                "parser_version": PARSER_VERSION,
                **identity,
                "doctrine_metadata_status": "unresolved",
                "metadata_reason": "DOCTRINE_TITLE_IDENTITY_CONFLICT",
            }

        date_matches = []
        for row in segments:
            match = MONTH_DAY_RE.fullmatch(row[5].strip())
            if match:
                date_matches.append((row, match))

        web_matches = []
        for row in segments:
            match = WEB_PUBLICATION_RE.search(row[5])
            if match:
                web_matches.append((row, match))

        if len(date_matches) != 1 or len(web_matches) != 1:
            return {
                "parser_name": PARSER_NAME,
                "parser_version": PARSER_VERSION,
                **identity,
                "doctrine_metadata_status": "unresolved",
                "metadata_reason": "DOCTRINE_DATE_EVIDENCE_AMBIGUOUS",
                "doctrine_date_matches": len(date_matches),
                "web_publication_matches": len(web_matches),
            }

        date_row, date_match = date_matches[0]
        doctrine_date = parse_spanish_date(
            date_match.group("day"),
            date_match.group("month"),
            str(year),
        )
        web_row, web_match = web_matches[0]
        web_publication_date = parse_spanish_date(
            web_match.group("day"),
            web_match.group("month"),
            web_match.group("year"),
        )

        positions: dict[int, dict[str, tuple]] = {}
        incomplete_positions: list[int] = []
        for idx, row in enumerate(segments):
            if row[2] != "table_row":
                continue
            label = POSITION_LABEL_RE.search(row[5].strip())
            if not label:
                continue

            ordinal = int(label.group("ordinal"))
            kind_norm = normalize_ascii(label.group("kind")).upper()
            role = "problem" if kind_norm.startswith("PROBLEMA") else "thesis"
            if idx + 1 >= len(segments) or segments[idx + 1][2] != "table_row":
                incomplete_positions.append(ordinal)
                continue
            positions.setdefault(ordinal, {})[role] = segments[idx + 1]

        incomplete_positions.extend(
            ordinal
            for ordinal, parts in positions.items()
            if set(parts) != {"problem", "thesis"}
        )
        incomplete_positions = sorted(set(incomplete_positions))

        now = utc_now()
        evidence_inserted = 0
        identifiers_inserted = 0
        identifier_evidence_inserted = 0
        positions_inserted = 0
        position_evidence_inserted = 0
        events_inserted = 0
        event_evidence_links_inserted = 0

        with con:
            title_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=title_row[0],
                char_start=title_row[3],
                char_end=title_row[4],
                text=title_row[5],
                role="document_identity",
            )
            evidence_inserted += int(inserted)

            date_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=date_row[0],
                char_start=date_row[3],
                char_end=date_row[4],
                text=date_row[5],
                role="doctrine_date",
            )
            evidence_inserted += int(inserted)

            web_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=web_row[0],
                char_start=web_row[3],
                char_end=web_row[4],
                text=web_row[5],
                role="web_publication_date",
            )
            evidence_inserted += int(inserted)

            con.execute(
                """
                UPDATE documents
                SET entity = 'DIAN',
                    document_type = 'CONCEPTO',
                    title = ?,
                    issued_date = ?,
                    publication_date = ?,
                    updated_at = ?
                WHERE document_id = ?
                """,
                (
                    title_row[5].strip(),
                    doctrine_date,
                    web_publication_date,
                    now,
                    document_id,
                ),
            )

            for identifier_type, identifier_value, primary, role in (
                ("concept_number", external_number, 1, "external_number"),
                ("internal_number", internal_number, 0, "internal_number"),
            ):
                _, inserted_id, inserted_ev = register_identifier(
                    con,
                    document_id=document_id,
                    identifier_type=identifier_type,
                    identifier_value=identifier_value,
                    issuer="DIAN",
                    is_primary=primary,
                    evidence_id=title_evidence,
                    evidence_role=role,
                    now=now,
                )
                identifiers_inserted += int(inserted_id)
                identifier_evidence_inserted += int(inserted_ev)

            con.execute(
                """
                INSERT INTO dian_doctrine_metadata(
                    document_id,
                    external_number,
                    normalized_external_number,
                    internal_number,
                    document_year,
                    doctrine_date,
                    web_publication_date,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    external_number = excluded.external_number,
                    normalized_external_number =
                        excluded.normalized_external_number,
                    internal_number = excluded.internal_number,
                    document_year = excluded.document_year,
                    doctrine_date = excluded.doctrine_date,
                    web_publication_date =
                        excluded.web_publication_date,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    external_number,
                    normalized_external_number,
                    internal_number,
                    year,
                    doctrine_date,
                    web_publication_date,
                    now,
                    now,
                ),
            )

            _, inserted, linked = create_temporal_event(
                con,
                document_id=document_id,
                event_type="issued",
                event_date=doctrine_date,
                scope="doctrine_document",
                evidence_id=date_evidence,
                evidence_role="doctrine_date_source",
                now=now,
            )
            events_inserted += int(inserted)
            event_evidence_links_inserted += int(linked)

            _, inserted, linked = create_temporal_event(
                con,
                document_id=document_id,
                event_type="published",
                event_date=web_publication_date,
                scope="dian_web",
                evidence_id=web_evidence,
                evidence_role="web_publication_source",
                now=now,
            )
            events_inserted += int(inserted)
            event_evidence_links_inserted += int(linked)

            for ordinal in sorted(positions):
                parts = positions[ordinal]
                if set(parts) != {"problem", "thesis"}:
                    continue
                problem = parts["problem"]
                thesis = parts["thesis"]
                position_id = deterministic_id("DPOS", f"{document_id}:{ordinal}")
                existed = con.execute(
                    "SELECT 1 FROM doctrine_positions "
                    "WHERE doctrine_position_id = ?",
                    (position_id,),
                ).fetchone()

                con.execute(
                    """
                    INSERT INTO doctrine_positions(
                        doctrine_position_id,
                        document_id,
                        ordinal,
                        problem_segment_id,
                        thesis_segment_id,
                        problem_text,
                        thesis_text,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'validated', ?, ?)
                    ON CONFLICT(doctrine_position_id) DO UPDATE SET
                        problem_segment_id = excluded.problem_segment_id,
                        thesis_segment_id = excluded.thesis_segment_id,
                        problem_text = excluded.problem_text,
                        thesis_text = excluded.thesis_text,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        position_id,
                        document_id,
                        ordinal,
                        problem[0],
                        thesis[0],
                        problem[5],
                        thesis[5],
                        now,
                        now,
                    ),
                )
                positions_inserted += int(existed is None)

                problem_evidence, inserted = create_evidence(
                    con,
                    manifestation_id=manifestation_id,
                    source_url=source_url,
                    source_sha256=source_sha256,
                    retrieved_at=retrieved_at,
                    segment_id=problem[0],
                    char_start=problem[3],
                    char_end=problem[4],
                    text=problem[5],
                    role=f"problem_{ordinal}",
                )
                evidence_inserted += int(inserted)
                thesis_evidence, inserted = create_evidence(
                    con,
                    manifestation_id=manifestation_id,
                    source_url=source_url,
                    source_sha256=source_sha256,
                    retrieved_at=retrieved_at,
                    segment_id=thesis[0],
                    char_start=thesis[3],
                    char_end=thesis[4],
                    text=thesis[5],
                    role=f"thesis_{ordinal}",
                )
                evidence_inserted += int(inserted)

                for evidence_id, role in (
                    (problem_evidence, "problem"),
                    (thesis_evidence, "thesis"),
                ):
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO doctrine_position_evidence(
                            doctrine_position_id,
                            evidence_id,
                            evidence_role,
                            created_at
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (position_id, evidence_id, role, now),
                    )
                    position_evidence_inserted += int(bool(cur.rowcount))

        return {
            "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            **identity,
            "doctrine_metadata_status": (
                "partial" if incomplete_positions else "registered"
            ),
            "metadata_reason": (
                "INCOMPLETE_DOCTRINE_POSITIONS"
                if incomplete_positions
                else None
            ),
            "incomplete_positions": incomplete_positions,
            "external_number": external_number,
            "normalized_external_number": normalized_external_number,
            "internal_number": internal_number,
            "doctrine_date": doctrine_date,
            "web_publication_date": web_publication_date,
            "positions_found": len(positions),
            "positions_inserted": positions_inserted,
            "evidence_inserted": evidence_inserted,
            "identifiers_inserted": identifiers_inserted,
            "identifier_evidence_inserted": identifier_evidence_inserted,
            "events_inserted": events_inserted,
            "event_evidence_links_inserted": event_evidence_links_inserted,
            "position_evidence_inserted": position_evidence_inserted,
        }
    finally:
        con.close()

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register DIAN doctrine identity for historic/modern families and "
            "enrich modern Conceptos with optional structured metadata."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_doctrine(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
