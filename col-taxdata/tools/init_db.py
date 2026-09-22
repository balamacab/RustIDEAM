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
        description="Initialize or migrate the col-taxdata SQLite database."
    )
    parser.add_argument(
        "--db",
        default="data/state/taxdata.sqlite",
        help="SQLite database path.",
    )
    parser.add_argument(
        "--schema-dir",
        default="schema",
        help="Directory containing ordered *.sql migrations.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    schema_dir = Path(args.schema_dir)

    migrations = sorted(schema_dir.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"No SQL migrations found in: {schema_dir}")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                schema_name TEXT PRIMARY KEY,
                schema_sha256 TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for migration in migrations:
            schema_hash = sha256_file(migration)
            existing = con.execute(
                """
                SELECT schema_sha256
                FROM schema_metadata
                WHERE schema_name = ?
                """,
                (migration.name,),
            ).fetchone()

            if existing is not None:
                if existing[0] != schema_hash:
                    raise RuntimeError(
                        f"Applied migration changed on disk: {migration.name}"
                    )
                print(f"already applied: {migration.name}")
                continue

            con.executescript(migration.read_text(encoding="utf-8"))
            con.execute(
                """
                INSERT INTO schema_metadata(
                    schema_name,
                    schema_sha256
                )
                VALUES (?, ?)
                """,
                (migration.name, schema_hash),
            )
            con.commit()
            print(f"applied: {migration.name}")

    finally:
        con.close()

    print(f"database ready: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
