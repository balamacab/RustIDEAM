#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path
from typing import Callable


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate_database(
    *,
    db_path: Path,
    schema_dir: Path,
    emit: Callable[[str], None] | None = print,
) -> dict[str, tuple[str, ...]]:
    """Apply every repository migration in order with immutable hash checks.

    This is the single migration engine used by both the standalone initializer
    and writable CASE runtime bootstrap. Existing migration rows are accepted
    only when their recorded SHA-256 still matches the migration file on disk.
    """
    migrations = sorted(schema_dir.glob("*.sql"))
    if not migrations:
        raise RuntimeError(f"No SQL migrations found in: {schema_dir}")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    applied: list[str] = []
    already_applied: list[str] = []
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
                already_applied.append(migration.name)
                if emit is not None:
                    emit(f"already applied: {migration.name}")
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
            applied.append(migration.name)
            if emit is not None:
                emit(f"applied: {migration.name}")
    finally:
        con.close()

    return {
        "applied": tuple(applied),
        "already_applied": tuple(already_applied),
    }


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
    migrate_database(db_path=db_path, schema_dir=schema_dir)

    print(f"database ready: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
