#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid


PARSER_NAME = "estatuto_tributario_registry"
PARSER_VERSION = "1"

PRIMARY_CANONICAL_KEY = "CO:DECRETO:624:1989"
ALIAS_CANONICAL_KEY = "CO:ESTATUTO_TRIBUTARIO"
EXPECTED_HEADING = "DECRETO 624 DE 1989"

NUMERIC_ARTICLE_RE = re.compile(
    r"^ART[IÍ]CULO\s+"
    r"(?P<designation>\d+(?:-\d+)?[A-Z]?)"
    r"\s*\.?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

EDITORIAL_NOTE_RE = re.compile(
    r"<(?P<note>(?:Art[ií]culo|Par[áa]grafo|Inciso)[^>]+)>",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_designation(value: str) -> str:
    return value.strip().strip(".").upper()


def parse_article(
    text: str,
) -> tuple[str, str | None, str, str | None]:
    match = NUMERIC_ARTICLE_RE.match(text.strip())
    if not match:
        raise RuntimeError(f"not a numeric Estatuto article: {text[:120]!r}")

    designation = normalize_designation(match.group("designation"))
    rest = match.group("rest").strip()

    editorial_note = None
    note_match = EDITORIAL_NOTE_RE.search(rest)
    if note_match:
        editorial_note = note_match.group("note").strip()
        rest = (
            rest[:note_match.start()] + " " + rest[note_match.end():]
        ).strip()
        rest = " ".join(rest.split())

    title = None
    normative_text = rest
    title_match = re.match(
        r"^(?P<title>[A-ZÁÉÍÓÚÜÑ0-9 ,;:/()\-]+?)[.]"
        r"(?:\s+(?P<body>.*))?$",
        rest,
    )
    if title_match and len(title_match.group("title")) <= 220:
        title = title_match.group("title").strip()
        normative_text = (title_match.group("body") or "").strip()

    return designation, title, normative_text, editorial_note


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


def register_estatuto(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
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
            existing_document_id,
            source_sha256,
            retrieved_at,
            source_url,
        ) = base

        heading = con.execute(
            """
            SELECT
                extracted_segment_id,
                char_start,
                char_end,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
              AND segment_type = 'document_heading'
            ORDER BY sequence_no
            LIMIT 1
            """,
            (extraction_id,),
        ).fetchone()

        if heading is None:
            raise RuntimeError("document heading not found")

        heading_key = normalize_ascii(heading[3]).upper().strip()
        if heading_key != EXPECTED_HEADING:
            raise RuntimeError(
                f"unexpected document heading: {heading[3]!r}"
            )

        alias_segment = con.execute(
            """
            SELECT
                extracted_segment_id,
                char_start,
                char_end,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
              AND UPPER(text) LIKE 'ARTICULO PRIMERO.%ESTATUTO TRIBUTARIO%'
            ORDER BY sequence_no
            LIMIT 1
            """,
            (extraction_id,),
        ).fetchone()

        if alias_segment is None:
            alias_segment = con.execute(
                """
                SELECT
                    extracted_segment_id,
                    char_start,
                    char_end,
                    text
                FROM extracted_segments
                WHERE extraction_id = ?
                  AND text LIKE '%Estatuto Tributario%'
                ORDER BY sequence_no
                LIMIT 1
                """,
                (extraction_id,),
            ).fetchone()

        if alias_segment is None:
            raise RuntimeError(
                "could not find source evidence for Estatuto Tributario alias"
            )

        article_rows = con.execute(
            """
            SELECT
                extracted_segment_id,
                sequence_no,
                char_start,
                char_end,
                text,
                text_sha256
            FROM extracted_segments
            WHERE extraction_id = ?
              AND segment_type = 'article'
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        numeric_rows = []
        skipped_rows = []

        for row in article_rows:
            if NUMERIC_ARTICLE_RE.match(row[4].strip()):
                numeric_rows.append(row)
            else:
                skipped_rows.append(row)

        if not numeric_rows:
            raise RuntimeError("no numeric Estatuto articles found")

        document_id = deterministic_id("DOC", PRIMARY_CANONICAL_KEY)

        if (
            existing_document_id is not None
            and existing_document_id != document_id
        ):
            raise RuntimeError(
                "manifestation already linked to another document: "
                f"{existing_document_id}"
            )

        now = utc_now()

        provisions_created = 0
        observations_created = 0
        editorial_notes_detected = 0
        evidence_inserted = 0
        identifiers_inserted = 0
        identifier_evidence_inserted = 0
        reviews_inserted = 0
        designation_counts: Counter[str] = Counter()

        with con:
            heading_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=heading[0],
                char_start=heading[1],
                char_end=heading[2],
                text=heading[3],
                role="decree_identity",
            )
            evidence_inserted += int(inserted)

            alias_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=alias_segment[0],
                char_start=alias_segment[1],
                char_end=alias_segment[2],
                text=alias_segment[3],
                role="estatuto_alias",
            )
            evidence_inserted += int(inserted)

            con.execute(
                """
                INSERT INTO documents(
                    document_id,
                    jurisdiction,
                    entity,
                    document_type,
                    title,
                    issued_date,
                    publication_date,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, 'CO', 'UNKNOWN', 'DECRETO',
                    ?, NULL, NULL, ?, ?
                )
                ON CONFLICT(document_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    "DECRETO 624 DE 1989 - Estatuto Tributario",
                    now,
                    now,
                ),
            )

            identifiers = [
                (
                    PRIMARY_CANONICAL_KEY,
                    1,
                    heading_evidence,
                    "document_heading",
                ),
                (
                    ALIAS_CANONICAL_KEY,
                    0,
                    alias_evidence,
                    "estatuto_designation",
                ),
            ]

            for key, is_primary, evidence_id, evidence_role in identifiers:
                identifier_id = deterministic_id(
                    "ID",
                    f"{document_id}:canonical:{key}",
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
                    VALUES (
                        ?, ?, 'canonical_key', ?, NULL, ?
                    )
                    """,
                    (
                        identifier_id,
                        document_id,
                        key,
                        is_primary,
                    ),
                )
                identifiers_inserted += int(bool(cur.rowcount))

                cur = con.execute(
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
                identifier_evidence_inserted += int(bool(cur.rowcount))

            con.execute(
                """
                UPDATE manifestations
                SET document_id = ?
                WHERE manifestation_id = ?
                """,
                (document_id, manifestation_id),
            )

            for (
                segment_id,
                sequence_no,
                char_start,
                char_end,
                text,
                observed_hash,
            ) in numeric_rows:
                (
                    designation,
                    title,
                    normative_text,
                    editorial_note,
                ) = parse_article(text)

                designation_counts[designation] += 1

                provision_id = deterministic_id(
                    "PROV",
                    f"{document_id}:ARTICLE:{designation}",
                )

                existed = con.execute(
                    """
                    SELECT 1
                    FROM provisions
                    WHERE provision_id = ?
                    """,
                    (provision_id,),
                ).fetchone()

                con.execute(
                    """
                    INSERT INTO provisions(
                        provision_id,
                        document_id,
                        provision_type,
                        designation,
                        normalized_designation,
                        title,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, ?, 'article', ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(document_id, normalized_designation)
                    DO UPDATE SET
                        title = COALESCE(
                            provisions.title,
                            excluded.title
                        ),
                        updated_at = excluded.updated_at
                    """,
                    (
                        provision_id,
                        document_id,
                        designation,
                        designation,
                        title,
                        now,
                        now,
                    ),
                )
                provisions_created += int(existed is None)

                observation_id = deterministic_id(
                    "POBS",
                    (
                        f"{provision_id}:{extraction_id}:"
                        f"{segment_id}:{PARSER_VERSION}"
                    ),
                )

                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO provision_observations(
                        provision_observation_id,
                        provision_id,
                        extraction_id,
                        extracted_segment_id,
                        observed_text,
                        normative_text,
                        editorial_note,
                        observed_text_sha256,
                        normative_text_sha256,
                        observed_at,
                        parser_name,
                        parser_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        provision_id,
                        extraction_id,
                        segment_id,
                        text,
                        normative_text,
                        editorial_note,
                        observed_hash or sha256_text(text),
                        sha256_text(normative_text),
                        now,
                        PARSER_NAME,
                        PARSER_VERSION,
                    ),
                )
                observations_created += int(bool(cur.rowcount))
                editorial_notes_detected += int(editorial_note is not None)

            for row in skipped_rows:
                text_key = normalize_ascii(row[4]).upper()
                if text_key.startswith("ARTICULO ADICIONAL"):
                    review_id = deterministic_id(
                        "REV",
                        (
                            f"{row[0]}:{PARSER_NAME}:{PARSER_VERSION}:"
                            "UNNUMBERED_PROVISION_IN_SOURCE"
                        ),
                    )
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO review_queue(
                            review_id,
                            entity_type,
                            entity_id,
                            reason_code,
                            severity,
                            created_at
                        )
                        VALUES (
                            ?,
                            'extracted_segment',
                            ?,
                            'UNNUMBERED_PROVISION_IN_SOURCE',
                            'medium',
                            ?
                        )
                        """,
                        (review_id, row[0], now),
                    )
                    reviews_inserted += int(bool(cur.rowcount))

        duplicates = {
            designation: count
            for designation, count in sorted(designation_counts.items())
            if count > 1
        }

        return {
            "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            "document_id": document_id,
            "primary_canonical_key": PRIMARY_CANONICAL_KEY,
            "alias_canonical_key": ALIAS_CANONICAL_KEY,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "article_segments_total": len(article_rows),
            "numeric_article_segments": len(numeric_rows),
            "skipped_non_numeric_articles": len(skipped_rows),
            "unique_numeric_designations": len(designation_counts),
            "duplicate_designations": duplicates,
            "provisions_created": provisions_created,
            "observations_created": observations_created,
            "editorial_notes_detected": editorial_notes_detected,
            "identifiers_inserted": identifiers_inserted,
            "identifier_evidence_inserted": identifier_evidence_inserted,
            "evidence_inserted": evidence_inserted,
            "review_items_inserted": reviews_inserted,
            "reused": existing_document_id == document_id,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register the DIAN compilation of the Estatuto Tributario "
            "as Decreto 624 de 1989 with an Estatuto canonical alias."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_estatuto(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
