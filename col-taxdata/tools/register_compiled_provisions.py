#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path

PARSER_NAME = "canonical_normative_registry"
PARSER_VERSION = "1"

DOCUMENT_HEADING_RE = re.compile(
    r"^(?P<type>DECRETO|LEY|RESOLUCI[ÓO]N|CIRCULAR)"
    r"\s+(?:N[ÚU]MERO\s+)?(?P<number>\d+[A-Z]?)"
    r"\s+DE\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

REG_ARTICLE_RE = re.compile(
    r"^ART[IÍ]CULO\s+(?P<designation>\d+(?:\.\d+){2,})\s*\.?"
    r"\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

EDITORIAL_NOTE_RE = re.compile(
    r"<(?P<note>(?:Art[ií]culo|Par[áa]grafo|Inciso)[ ]+[^>]+)>",
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


def normalize_designation(value: str) -> str:
    return value.strip().strip(".").upper()


def parse_article(text: str) -> tuple[str, str | None, str, str | None]:
    match = REG_ARTICLE_RE.match(text.strip())
    if not match:
        raise RuntimeError(f"not a regulatory article: {text[:120]!r}")

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
        r"^(?P<title>[A-ZÁÉÍÓÚÜÑ0-9 ,;:/()\-]+?)[.][ ]+(?P<body>.+)$",
        rest,
    )
    if title_match and len(title_match.group("title")) <= 220:
        title = title_match.group("title").strip()
        normative_text = title_match.group("body").strip()

    return designation, title, normative_text, editorial_note


def ensure_document(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    extraction_id: str,
) -> tuple[str, str]:
    row = con.execute(
        """
        SELECT es.text, m.document_id
        FROM extracted_segments es
        JOIN text_extractions te ON te.extraction_id = es.extraction_id
        JOIN manifestations m ON m.manifestation_id = te.manifestation_id
        WHERE es.extraction_id = ?
          AND es.segment_type = 'document_heading'
        ORDER BY es.sequence_no
        LIMIT 1
        """,
        (extraction_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError("document heading not found")

    heading, existing_document_id = row
    match = DOCUMENT_HEADING_RE.match(normalize_ascii(heading).upper())
    if not match:
        raise RuntimeError(f"unsupported document heading: {heading!r}")

    doc_type = normalize_document_type(match.group("type"))
    number = match.group("number").upper()
    year = int(match.group("year"))
    canonical_key = f"CO:{doc_type}:{number}:{year}"
    document_id = deterministic_id("DOC", canonical_key)
    now = utc_now()

    if existing_document_id is not None and existing_document_id != document_id:
        raise RuntimeError(
            f"manifestation already linked to another document: {existing_document_id}"
        )

    con.execute(
        """
        INSERT INTO documents(
            document_id, jurisdiction, entity, document_type,
            title, issued_date, publication_date, created_at, updated_at
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
            identifier_id, document_id, identifier_type,
            identifier_value, issuer, is_primary
        )
        VALUES (?, ?, 'canonical_key', ?, NULL, 1)
        ON CONFLICT(document_id, identifier_type, identifier_value)
        DO NOTHING
        """,
        (identifier_id, document_id, canonical_key),
    )

    con.execute(
        """
        UPDATE manifestations
        SET document_id = ?
        WHERE manifestation_id = ?
        """,
        (document_id, manifestation_id),
    )

    return document_id, canonical_key


def register_compiled_provisions(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        extraction = con.execute(
            """
            SELECT manifestation_id
            FROM text_extractions
            WHERE extraction_id = ?
            """,
            (extraction_id,),
        ).fetchone()
        if extraction is None:
            raise RuntimeError(f"extraction not found: {extraction_id}")

        manifestation_id = extraction[0]

        rows = con.execute(
            """
            SELECT extracted_segment_id, sequence_no, text, text_sha256
            FROM extracted_segments
            WHERE extraction_id = ?
              AND segment_type = 'regulatory_article'
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        if not rows:
            raise RuntimeError("no regulatory_article segments found")

        created = 0
        observed = 0
        editorial_notes = 0

        with con:
            document_id, canonical_key = ensure_document(
                con,
                manifestation_id=manifestation_id,
                extraction_id=extraction_id,
            )

            for segment_id, sequence_no, text, observed_hash in rows:
                designation, title, normative_text, editorial_note = parse_article(text)
                provision_id = deterministic_id(
                    "PROV",
                    f"{document_id}:ARTICLE:{designation}",
                )
                now = utc_now()

                existed = con.execute(
                    "SELECT 1 FROM provisions WHERE provision_id = ?",
                    (provision_id,),
                ).fetchone()

                con.execute(
                    """
                    INSERT INTO provisions(
                        provision_id, document_id, provision_type,
                        designation, normalized_designation,
                        title, created_at, updated_at
                    )
                    VALUES (?, ?, 'article', ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, normalized_designation)
                    DO UPDATE SET
                        title = COALESCE(excluded.title, provisions.title),
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
                if existed is None:
                    created += 1

                observation_id = deterministic_id(
                    "POBS",
                    f"{provision_id}:{extraction_id}:{segment_id}:{PARSER_VERSION}",
                )
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO provision_observations(
                        provision_observation_id, provision_id,
                        extraction_id, extracted_segment_id,
                        observed_text, normative_text, editorial_note,
                        observed_text_sha256, normative_text_sha256,
                        observed_at, parser_name, parser_version
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
                if cur.rowcount:
                    observed += 1
                if editorial_note:
                    editorial_notes += 1

        return {
            "document_id": document_id,
            "canonical_key": canonical_key,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "regulatory_article_segments": len(rows),
            "provisions_created": created,
            "observations_created": observed,
            "editorial_notes_detected": editorial_notes,
        }

    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register a compiled normative document and its regulatory "
            "articles as canonical provisions."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_compiled_provisions(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
