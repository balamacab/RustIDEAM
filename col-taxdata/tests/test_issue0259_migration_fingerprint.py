"""Contract regressions for issue #259's ordered migration-state SHA-256."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from migration_fingerprint import (  # noqa: E402
    fingerprint_applied_migrations,
    fingerprint_schema_metadata,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
PAIRS = [("001_initial.sql", A), ("002_index.sql", B)]


def database(rows=PAIRS):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE schema_metadata ("
        "schema_name TEXT PRIMARY KEY, schema_sha256 TEXT NOT NULL, "
        "applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO schema_metadata(schema_name, schema_sha256) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    return conn


class MigrationFingerprintTests(unittest.TestCase):
    def test_deterministic_and_sha256_format(self):
        a = fingerprint_applied_migrations(PAIRS)
        b = fingerprint_applied_migrations(tuple(PAIRS))
        self.assertEqual(a, b)
        self.assertEqual(a.status, "available")
        self.assertEqual(a.count, 2)
        self.assertEqual(len(a.sha256), 64)
        int(a.sha256, 16)

    def test_order_is_part_of_identity_and_never_silently_sorted(self):
        a = fingerprint_applied_migrations(PAIRS)
        self.assertNotEqual(
            a.sha256, fingerprint_applied_migrations(list(reversed(PAIRS))).sha256
        )

    def test_changed_name_hash_addition_and_removal_change_identity(self):
        baseline = fingerprint_applied_migrations(PAIRS).sha256
        edits = [
            [("001_changed.sql", A), PAIRS[1]],
            [("001_initial.sql", C), PAIRS[1]],
            PAIRS + [("003_more.sql", C)],
            PAIRS[:1],
        ]
        for rows in edits:
            with self.subTest(rows=rows):
                self.assertNotEqual(
                    baseline, fingerprint_applied_migrations(rows).sha256
                )

    def test_empty_is_available_and_not_unknown(self):
        empty = fingerprint_applied_migrations([])
        unknown = fingerprint_applied_migrations(None)
        self.assertEqual((empty.status, empty.count), ("available", 0))
        self.assertEqual(unknown.status, "unavailable")
        self.assertIsNone(unknown.sha256)
        self.assertNotEqual(empty, unknown)
        self.assertEqual(empty.sha256, hashlib.sha256(
            b'{"kind":"col-taxdata-applied-migrations","ordered":[],"version":1}'
        ).hexdigest())

    def test_invalid_or_duplicate_records_are_inconsistent(self):
        invalid = [
            [("001.sql", "bad")],
            [("001.sql", A), ("001.sql", B)],
            [("../001.sql", A)],
            [("002.txt", A)],
            [("001.sql", A), ("002.sql", None)],
            [("001.sql", A, "extra")],
            ["001.sql"],
        ]
        for rowset in invalid:
            with self.subTest(rowset=rowset):
                result = fingerprint_applied_migrations(rowset)
                self.assertEqual(result.status, "inconsistent")
                self.assertIsNone(result.sha256)

    def test_implicit_unordered_iterators_are_rejected(self):
        result = fingerprint_applied_migrations(iter(PAIRS))
        self.assertEqual(result.status, "inconsistent")

    def test_db_fingerprint_requires_external_order(self):
        with database() as conn:
            self.assertEqual(
                fingerprint_schema_metadata(conn, applied_order=None).status,
                "unavailable",
            )
            self.assertEqual(
                fingerprint_schema_metadata(
                    conn, applied_order=["001_initial.sql", "002_index.sql"]
                ).status,
                "available",
            )

    def test_db_insertion_order_does_not_change_explicit_sequence(self):
        with database(PAIRS) as first, database(list(reversed(PAIRS))) as second:
            order = ["001_initial.sql", "002_index.sql"]
            self.assertEqual(
                fingerprint_schema_metadata(first, applied_order=order),
                fingerprint_schema_metadata(second, applied_order=order),
            )
            self.assertNotEqual(
                fingerprint_schema_metadata(first, applied_order=order).sha256,
                fingerprint_schema_metadata(
                    second, applied_order=list(reversed(order))
                ).sha256,
            )

    def test_db_extra_or_missing_rows_are_inconsistent(self):
        with database(PAIRS) as conn:
            self.assertEqual(
                fingerprint_schema_metadata(conn, applied_order=["001_initial.sql"]).reason,
                "applied_migration_set_mismatch",
            )
            self.assertEqual(
                fingerprint_schema_metadata(conn, applied_order=[
                    "001_initial.sql", "002_index.sql", "003_more.sql"
                ]).status,
                "inconsistent",
            )

    def test_db_changed_digest_changes_identity(self):
        with database(PAIRS) as conn:
            order = ["001_initial.sql", "002_index.sql"]
            before = fingerprint_schema_metadata(conn, applied_order=order)
            conn.execute(
                "UPDATE schema_metadata SET schema_sha256=? WHERE schema_name=?",
                (C, "002_index.sql"),
            )
            after = fingerprint_schema_metadata(conn, applied_order=order)
            self.assertNotEqual(before.sha256, after.sha256)

    def test_db_missing_table_is_unavailable(self):
        with sqlite3.connect(":memory:") as conn:
            result = fingerprint_schema_metadata(conn, applied_order=[])
            self.assertEqual(result.status, "unavailable")
            self.assertEqual(result.reason, "schema_metadata_unavailable")

    def test_db_empty_is_known_and_distinct(self):
        with database([]) as conn:
            result = fingerprint_schema_metadata(conn, applied_order=[])
            self.assertEqual((result.status, result.count), ("available", 0))
            self.assertEqual(result, fingerprint_applied_migrations([]))

    def test_db_explicit_order_is_validated(self):
        with database(PAIRS) as conn:
            self.assertEqual(
                fingerprint_schema_metadata(
                    conn, applied_order=["001_initial.sql", "001_initial.sql"]
                ).status,
                "inconsistent",
            )
            self.assertEqual(
                fingerprint_schema_metadata(
                    conn, applied_order=iter(["001_initial.sql", "002_index.sql"])
                ).status,
                "inconsistent",
            )

    def test_no_database_mutation(self):
        with database(PAIRS) as conn:
            before = conn.total_changes
            self.assertEqual(
                fingerprint_schema_metadata(
                    conn, applied_order=["001_initial.sql", "002_index.sql"]
                ).status,
                "available",
            )
            self.assertEqual(conn.total_changes, before)


if __name__ == "__main__":
    unittest.main()
