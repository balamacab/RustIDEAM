#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the col-taxdata SQLite state database."
    )
    parser.add_argument(
        "--db",
        default="data/state/taxdata.sqlite",
        help="SQLite database path.",
    )
    parser.add_argument(
        "--schema",
        default="schema/001_initial.sql",
        help="SQL schema path.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    schema_path = Path(args.schema)

    if not schema_path.is_file():
        raise SystemExit(f"Schema not found: {schema_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = schema_path.read_text(encoding="utf-8")
    schema_hash = sha256_file(schema_path)

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.executescript(schema_sql)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                schema_name TEXT PRIMARY KEY,
                schema_sha256 TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        con.execute(
            """
            INSERT INTO schema_metadata(schema_name, schema_sha256)
            VALUES (?, ?)
            ON CONFLICT(schema_name) DO UPDATE SET
                schema_sha256 = excluded.schema_sha256,
                applied_at = CURRENT_TIMESTAMP
            """,
            (schema_path.name, schema_hash),
        )
        con.commit()
    finally:
        con.close()

    print(f"initialized: {db_path}")
    print(f"schema: {schema_path}")
    print(f"schema_sha256: {schema_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
