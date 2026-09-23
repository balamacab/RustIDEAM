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

from source_identity import (
    assess_generic_normative_identity,
    canonical_identifier_values,
    equivalent_existing_canonical_key,
    persist_assessment,
)


PARSER_NAME = "simple_normative_act_registry"
PARSER_VERSION = "1"

DOCUMENT_HEADING_RE = re.compile(
    r"^(?P<type>DECRETO|LEY|RESOLUCI[ÓO]N|CIRCULAR)"
    r"\s+(?:N[ÚU]MERO\s+)?(?P<number>\d+[A-Z]?)"
    r"\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

ARTICLE_RE = re.compile(
    r"^ART[IÍ]CULO\s+"
    r"(?P<designation>\d+)"
    r"(?:[oOº°])?"
    r"\s*\.\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

EDITORIAL_NOTE_RE = re.compile(
    r"<(?P<note>(?:Art[ií]culo|Par[áa]grafo|Inciso|Numeral)[^>]+)>",
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


def parse_article(
    text: str,
) -> tuple[str, str | None, str, str | None]:
    match = ARTICLE_RE.match(text.strip())
    if not match:
        raise RuntimeError(f"not a simple article: {text[:120]!r}")

    designation = str(int(match.group("designation")))
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
        r"^(?P<title>[A-ZÁÉÍÓÚÜÑ0-9 ,;:/()\-]+?)"
        r"\.\s+(?P<body>.+)$",
        rest,
    )
    if title_match and len(title_match.group("title")) <= 1000:
        title = title_match.group("title").strip()
        normative_text = title_match.group("body").strip()

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


def register_simple_act(
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

        assessment = assess_generic_normative_identity(source_url, heading[3])
        with con:
            review_id = persist_assessment(
                con,
                manifestation_id=manifestation_id,
                extraction_id=extraction_id,
                assessment=assessment,
            )
            if not assessment.accepted:
                if existing_document_id is not None:
                    con.execute(
                        "UPDATE manifestations SET document_id = NULL "
                        "WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                return {
                    "parser_name": PARSER_NAME,
                    "parser_version": PARSER_VERSION,
                    "status": "unresolved",
                    "reason_code": assessment.reason_code,
                    "review_id": review_id,
                    "source_family": assessment.source.family,
                    "manifestation_id": manifestation_id,
                    "extraction_id": extraction_id,
                    "document_id": None,
                }

        assert assessment.content is not None
        doc_type = assessment.content.document_type
        number = assessment.content.number
        year = assessment.content.year
        issuer_key = assessment.content.issuer_key
        canonical_key = assessment.content.canonical_key
        assert doc_type and number and year and canonical_key
        document_id = deterministic_id("DOC", canonical_key)

        if (
            existing_document_id is not None
            and existing_document_id != document_id
        ):
            equivalent_key = equivalent_existing_canonical_key(
                con,
                document_id=existing_document_id,
                signal=assessment.content,
            )
            if equivalent_key is not None:
                document_id = existing_document_id
                canonical_key = equivalent_key
            else:
                conflict = assessment.__class__(
                    "unresolved",
                    assessment.source,
                    assessment.content,
                    "SOURCE_IDENTITY_CONFLICT",
                )
                with con:
                    review_id = persist_assessment(
                        con,
                        manifestation_id=manifestation_id,
                        extraction_id=extraction_id,
                        assessment=conflict,
                    )
                    con.execute(
                        "UPDATE manifestations SET document_id = NULL "
                        "WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                return {
                    "parser_name": PARSER_NAME,
                    "parser_version": PARSER_VERSION,
                    "status": "unresolved",
                    "reason_code": "SOURCE_IDENTITY_CONFLICT",
                    "review_id": review_id,
                    "source_family": assessment.source.family,
                    "manifestation_id": manifestation_id,
                    "extraction_id": extraction_id,
                    "document_id": None,
                }

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

        parsed_rows = []
        skipped_rows = []
        designation_counts: Counter[str] = Counter()

        for row in article_rows:
            if ARTICLE_RE.match(row[4].strip()):
                parsed = parse_article(row[4])
                parsed_rows.append((row, parsed))
                designation_counts[parsed[0]] += 1
            else:
                skipped_rows.append(row)

        if not parsed_rows:
            raise RuntimeError("no simple numeric articles found")

        now = utc_now()
        provisions_created = 0
        observations_created = 0
        editorial_notes_detected = 0
        identifiers_inserted = 0
        identifier_evidence_inserted = 0
        evidence_inserted = 0

        with con:
            heading_evidence_id, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=heading[0],
                char_start=heading[1],
                char_end=heading[2],
                text=heading[3],
                role="document_identity",
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
                VALUES (?, 'CO', ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    entity = excluded.entity,
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    issuer_key or "UNKNOWN",
                    doc_type,
                    heading[3],
                    now,
                    now,
                ),
            )

            for identifier_value, is_primary in canonical_identifier_values(
                assessment.content
            ):
                identifier_id = deterministic_id(
                    "ID",
                    f"{document_id}:canonical:{identifier_value}",
                )
                existed_identifier = con.execute(
                    """
                    SELECT 1
                    FROM document_identifiers
                    WHERE document_id = ?
                      AND identifier_type = 'canonical_key'
                      AND identifier_value = ?
                    """,
                    (document_id, identifier_value),
                ).fetchone()
                con.execute(
                    """
                    INSERT INTO document_identifiers(
                        identifier_id,
                        document_id,
                        identifier_type,
                        identifier_value,
                        issuer,
                        is_primary
                    )
                    VALUES (?, ?, 'canonical_key', ?, ?, ?)
                    ON CONFLICT(document_id, identifier_type, identifier_value)
                    DO UPDATE SET
                        issuer = excluded.issuer,
                        is_primary = excluded.is_primary
                    """,
                    (
                        identifier_id,
                        document_id,
                        identifier_value,
                        issuer_key,
                        is_primary,
                    ),
                )
                identifiers_inserted += int(existed_identifier is None)

                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO document_identifier_evidence(
                        identifier_id,
                        evidence_id,
                        evidence_role,
                        created_at
                    )
                    VALUES (?, ?, 'document_heading', ?)
                    """,
                    (
                        identifier_id,
                        heading_evidence_id,
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

            for row, parsed in parsed_rows:
                (
                    segment_id,
                    sequence_no,
                    char_start,
                    char_end,
                    text,
                    observed_hash,
                ) = row
                (
                    designation,
                    title,
                    normative_text,
                    editorial_note,
                ) = parsed

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
                    VALUES (?, ?, 'article', ?, ?, ?, ?, ?)
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

        duplicates = {
            designation: count
            for designation, count in sorted(designation_counts.items())
            if count > 1
        }

        return {
            "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            "document_id": document_id,
            "canonical_key": canonical_key,
            "issuer_key": issuer_key,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "article_segments_total": len(article_rows),
            "numeric_article_segments": len(parsed_rows),
            "skipped_non_numeric_articles": len(skipped_rows),
            "unique_numeric_designations": len(designation_counts),
            "duplicate_designations": duplicates,
            "provisions_created": provisions_created,
            "observations_created": observations_created,
            "editorial_notes_detected": editorial_notes_detected,
            "identifiers_inserted": identifiers_inserted,
            "identifier_evidence_inserted": identifier_evidence_inserted,
            "evidence_inserted": evidence_inserted,
            "reused": existing_document_id == document_id,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register a simple legal act and only its own simple-numbered "
            "articles, excluding embedded compiled regulatory provisions."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_simple_act(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())