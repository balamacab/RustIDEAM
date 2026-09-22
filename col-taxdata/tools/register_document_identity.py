#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path


DOCUMENT_HEADING_RE = re.compile(
    r"^(?P<type>DECRETO|LEY|RESOLUCI[ÓO]N|CIRCULAR)"
    r"\s+(?:N[ÚU]MERO\s+)?(?P<number>\d+[A-Z]?)"
    r"\s+DE\s+(?P<year>\d{4})\b",
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


def normalize_document_type(value: str) -> str:
    key = normalize_ascii(value).upper()
    return {
        "DECRETO": "DECRETO",
        "LEY": "LEY",
        "RESOLUCION": "RESOLUCION",
        "CIRCULAR": "CIRCULAR",
    }[key]


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
                m.document_id
            FROM text_extractions te
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
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

        manifestation_id, heading, existing_document_id = row

        match = DOCUMENT_HEADING_RE.match(
            normalize_ascii(heading).upper()
        )
        if not match:
            raise RuntimeError(
                f"unsupported document heading: {heading!r}"
            )

        doc_type = normalize_document_type(match.group("type"))
        number = match.group("number").upper()
        year = int(match.group("year"))
        canonical_key = f"CO:{doc_type}:{number}:{year}"
        document_id = deterministic_id("DOC", canonical_key)
        now = utc_now()

        if (
            existing_document_id is not None
            and existing_document_id != document_id
        ):
            raise RuntimeError(
                "manifestation already linked to another document: "
                f"{existing_document_id}"
            )

        with con:
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
                VALUES (?, 'CO', 'UNKNOWN', ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (document_id, doc_type, heading, now, now),
            )

            identifier_id = deterministic_id(
                "ID",
                f"{document_id}:canonical:{canonical_key}",
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
                VALUES (?, ?, 'canonical_key', ?, NULL, 1)
                ON CONFLICT(
                    document_id,
                    identifier_type,
                    identifier_value
                )
                DO NOTHING
                """,
                (
                    identifier_id,
                    document_id,
                    canonical_key,
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
            "document_id": document_id,
            "canonical_key": canonical_key,
            "document_type": doc_type,
            "number": number,
            "year": year,
            "heading": heading,
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
