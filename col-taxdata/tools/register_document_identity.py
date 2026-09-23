#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path

from source_identity import (
    assess_generic_normative_identity,
    canonical_identifier_values,
    equivalent_existing_canonical_key,
    persist_assessment,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def register_document_identity(
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
                es.text,
                m.document_id,
                s.source_url
            FROM text_extractions te
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            JOIN sources s
              ON s.source_id = m.source_id
            JOIN extracted_segments es
              ON es.extraction_id = te.extraction_id
            WHERE te.extraction_id = ?
              AND es.segment_type = 'document_heading'
            ORDER BY es.sequence_no
            LIMIT 1
            """,
            (extraction_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError("document heading not found")

        manifestation_id, heading, existing_document_id, source_url = row
        assessment = assess_generic_normative_identity(source_url, heading)

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
                        "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                return {
                    "status": "unresolved",
                    "reason_code": assessment.reason_code,
                    "review_id": review_id,
                    "source_family": assessment.source.family,
                    "source_url": source_url,
                    "heading": heading,
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
            now = utc_now()

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
                    review_id = persist_assessment(
                        con,
                        manifestation_id=manifestation_id,
                        extraction_id=extraction_id,
                        assessment=assessment.__class__(
                            "unresolved",
                            assessment.source,
                            assessment.content,
                            "SOURCE_IDENTITY_CONFLICT",
                        ),
                    )
                    con.execute(
                        "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                    return {
                        "status": "unresolved",
                        "reason_code": "SOURCE_IDENTITY_CONFLICT",
                        "review_id": review_id,
                        "source_family": assessment.source.family,
                        "source_url": source_url,
                        "heading": heading,
                        "manifestation_id": manifestation_id,
                        "extraction_id": extraction_id,
                        "document_id": None,
                    }

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
                    heading,
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
                    ON CONFLICT(
                        document_id,
                        identifier_type,
                        identifier_value
                    )
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

            con.execute(
                """
                UPDATE manifestations
                SET document_id = ?
                WHERE manifestation_id = ?
                """,
                (document_id, manifestation_id),
            )

        return {
            "status": "registered",
            "document_id": document_id,
            "canonical_key": canonical_key,
            "issuer_key": issuer_key,
            "document_type": doc_type,
            "number": number,
            "year": year,
            "heading": heading,
            "source_family": assessment.source.family,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "reused": existing_document_id == document_id,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register only the canonical identity of a legal document "
            "without creating provisions from its embedded text."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_document_identity(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())