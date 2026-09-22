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


PROCESSOR_NAME = "document_temporality_regex"
PROCESSOR_VERSION = "1"

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
    r"Dado\s+en\s+.+?,\s*(?:a\s+)?"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)

EFFECTIVE_ON_PUBLICATION_RE = re.compile(
    r"rige\s+a\s+partir\s+de\s+la\s+fecha\s+de\s+su\s+"
    r"publicaci[oó]n\s+en\s+el\s+Diario\s+Oficial",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def parse_date(match: re.Match[str]) -> str:
    month_key = normalize_ascii(match.group("month")).lower()
    if month_key not in MONTHS:
        raise RuntimeError(f"unsupported Spanish month: {match.group('month')!r}")
    parsed = date(
        int(match.group("year")),
        MONTHS[month_key],
        int(match.group("day")),
    )
    return parsed.isoformat()


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
        f"{segment_id}:{PROCESSOR_NAME}:{PROCESSOR_VERSION}:{role}",
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
            f"{PROCESSOR_NAME}:{PROCESSOR_VERSION}:{role}",
            PROCESSOR_VERSION,
            segment_id,
        ),
    )
    return evidence_id, bool(cur.rowcount)


def create_event(
    con: sqlite3.Connection,
    *,
    document_id: str,
    event_type: str,
    event_date: str,
    effective_from: str | None,
    primary_evidence_id: str,
    scope: str,
    evidence_roles: list[tuple[str, str]],
    now: str,
) -> tuple[str, bool, int]:
    event_id = deterministic_id(
        "TEV",
        (
            f"{document_id}:{event_type}:{event_date}:"
            f"{effective_from or ''}:{PROCESSOR_VERSION}"
        ),
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
            ?, 'document', ?, ?, ?, ?, NULL,
            NULL, NULL, ?, 'validated', ?, 1.0, 0
        )
        ON CONFLICT(temporal_event_id) DO UPDATE SET
            event_date = excluded.event_date,
            effective_from = excluded.effective_from,
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
            effective_from,
            scope,
            primary_evidence_id,
        ),
    )

    evidence_links_inserted = 0
    for evidence_id, role in evidence_roles:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO temporal_event_evidence(
                temporal_event_id,
                evidence_id,
                evidence_role,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (event_id, evidence_id, role, now),
        )
        evidence_links_inserted += int(bool(cur.rowcount))

    return event_id, existing is None, evidence_links_inserted


def extract_temporality(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        row = con.execute(
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

        if row is None:
            raise RuntimeError(f"extraction not found: {extraction_id}")

        (
            manifestation_id,
            document_id,
            source_sha256,
            retrieved_at,
            source_url,
        ) = row

        if document_id is None:
            raise RuntimeError(
                "manifestation has no canonical document identity"
            )

        segments = con.execute(
            """
            SELECT
                extracted_segment_id,
                sequence_no,
                char_start,
                char_end,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        publication_matches = []
        issued_matches = []
        effective_matches = []

        for segment_id, sequence_no, char_start, char_end, text in segments:
            pm = PUBLICATION_RE.search(text)
            if pm:
                publication_matches.append(
                    (
                        segment_id,
                        sequence_no,
                        char_start,
                        char_end,
                        text,
                        parse_date(pm),
                    )
                )

            im = ISSUED_RE.search(text)
            if im:
                issued_matches.append(
                    (
                        segment_id,
                        sequence_no,
                        char_start,
                        char_end,
                        text,
                        parse_date(im),
                    )
                )

            if EFFECTIVE_ON_PUBLICATION_RE.search(text):
                effective_matches.append(
                    (
                        segment_id,
                        sequence_no,
                        char_start,
                        char_end,
                        text,
                    )
                )

        if len(publication_matches) != 1:
            raise RuntimeError(
                "expected exactly one publication date; "
                f"found {len(publication_matches)}"
            )

        if len(issued_matches) != 1:
            raise RuntimeError(
                "expected exactly one issued date; "
                f"found {len(issued_matches)}"
            )

        if len(effective_matches) != 1:
            raise RuntimeError(
                "expected exactly one effective-on-publication rule; "
                f"found {len(effective_matches)}"
            )

        publication = publication_matches[0]
        issued = issued_matches[0]
        effective = effective_matches[0]

        publication_date = publication[5]
        issued_date = issued[5]
        effective_date = publication_date

        now = utc_now()
        evidence_inserted = 0
        events_inserted = 0
        evidence_links_inserted = 0
        temporal_basis_inserted = 0

        with con:
            publication_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=publication[0],
                char_start=publication[2],
                char_end=publication[3],
                text=publication[4],
                role="publication_date",
            )
            evidence_inserted += int(inserted)

            issued_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=issued[0],
                char_start=issued[2],
                char_end=issued[3],
                text=issued[4],
                role="issued_date",
            )
            evidence_inserted += int(inserted)

            effective_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=effective[0],
                char_start=effective[2],
                char_end=effective[3],
                text=effective[4],
                role="effective_on_publication",
            )
            evidence_inserted += int(inserted)

            con.execute(
                """
                UPDATE documents
                SET issued_date = ?,
                    publication_date = ?,
                    updated_at = ?
                WHERE document_id = ?
                """,
                (
                    issued_date,
                    publication_date,
                    now,
                    document_id,
                ),
            )

            issued_event_id, inserted, links = create_event(
                con,
                document_id=document_id,
                event_type="issued",
                event_date=issued_date,
                effective_from=None,
                primary_evidence_id=issued_evidence,
                scope="document",
                evidence_roles=[
                    (issued_evidence, "issued_date_source"),
                ],
                now=now,
            )
            events_inserted += int(inserted)
            evidence_links_inserted += links

            publication_event_id, inserted, links = create_event(
                con,
                document_id=document_id,
                event_type="published",
                event_date=publication_date,
                effective_from=None,
                primary_evidence_id=publication_evidence,
                scope="document",
                evidence_roles=[
                    (publication_evidence, "publication_date_source"),
                ],
                now=now,
            )
            events_inserted += int(inserted)
            evidence_links_inserted += links

            effective_event_id, inserted, links = create_event(
                con,
                document_id=document_id,
                event_type="enters_into_force",
                event_date=effective_date,
                effective_from=effective_date,
                primary_evidence_id=effective_evidence,
                scope="document",
                evidence_roles=[
                    (effective_evidence, "commencement_rule"),
                    (publication_evidence, "publication_date_basis"),
                ],
                now=now,
            )
            events_inserted += int(inserted)
            evidence_links_inserted += links

            relationships = con.execute(
                """
                SELECT relationship_id
                FROM relationships
                WHERE source_type = 'document'
                  AND source_id = ?
                  AND status = 'validated'
                  AND relation_type IN (
                      'substitutes',
                      'modifies',
                      'adds',
                      'repeals',
                      'partially_repeals'
                  )
                ORDER BY relationship_id
                """,
                (document_id,),
            ).fetchall()

            for (relationship_id,) in relationships:
                con.execute(
                    """
                    UPDATE relationships
                    SET asserted_date = ?,
                        effective_date = ?
                    WHERE relationship_id = ?
                    """,
                    (
                        issued_date,
                        effective_date,
                        relationship_id,
                    ),
                )

                for event_id, basis_role in (
                    (issued_event_id, "asserted_date"),
                    (effective_event_id, "effective_date"),
                ):
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO relationship_temporal_basis(
                            relationship_id,
                            temporal_event_id,
                            basis_role,
                            created_at
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            relationship_id,
                            event_id,
                            basis_role,
                            now,
                        ),
                    )
                    temporal_basis_inserted += int(bool(cur.rowcount))

        return {
            "processor_name": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION,
            "document_id": document_id,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "issued_date": issued_date,
            "publication_date": publication_date,
            "effective_date": effective_date,
            "issued_segment_sequence": issued[1],
            "publication_segment_sequence": publication[1],
            "effective_rule_segment_sequence": effective[1],
            "evidence_inserted": evidence_inserted,
            "events_inserted": events_inserted,
            "event_evidence_links_inserted": evidence_links_inserted,
            "relationships_updated": len(relationships),
            "relationship_temporal_basis_inserted":
                temporal_basis_inserted,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract explicit document issuance/publication/commencement "
            "temporality and bind canonical relationships to its evidence."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = extract_temporality(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
