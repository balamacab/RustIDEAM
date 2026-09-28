from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_bundle_persistence_v4 import persist_legal_research_bundle
from case_rest_runtime import (
    REQUIRED_V4_MIGRATION,
    REQUIRED_V4_TABLES,
    STARTUP_FAILURE,
    main as runtime_main,
    prepare_case_runtime_database,
)
from init_db import migrate_database


EXAMPLE = (
    ROOT
    / "specs"
    / "application"
    / "examples"
    / "case-rest-v1"
    / "complete-response.json"
)


def _copy_pre016_schema(target: Path) -> None:
    target.mkdir(parents=True)
    for migration in sorted((ROOT / "schema").glob("*.sql")):
        if migration.name >= "016_":
            continue
        shutil.copy2(migration, target / migration.name)


def _manifestation_fingerprint(db_path: Path) -> tuple[int, str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT manifestation_id, sha256 "
            "FROM manifestations ORDER BY manifestation_id"
        ).fetchall()
    finally:
        con.close()
    encoded = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(rows), hashlib.sha256(encoded).hexdigest()


class Issue0255RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "state" / "taxdata.sqlite"
        self.schema15 = self.root / "schema15"
        _copy_pre016_schema(self.schema15)
        migrate_database(
            db_path=self.db,
            schema_dir=self.schema15,
            emit=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _insert_raw_fixture(self) -> str:
        raw_sha = hashlib.sha256(b"issue255 immutable raw fixture").hexdigest()
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                )
                VALUES (
                    'SRC-255',
                    'https://example.invalid/issue255',
                    'fixture',
                    'fixture',
                    NULL,
                    '2026-09-28T00:00:00+00:00',
                    '2026-09-28T00:00:00+00:00'
                )
                """
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                )
                VALUES (
                    'MAN-255',
                    NULL,
                    'SRC-255',
                    'text/plain',
                    ?,
                    30,
                    '2026-09-28T00:00:00+00:00',
                    'raw/issue255.txt',
                    'fixture'
                )
                """,
                (raw_sha,),
            )
            con.commit()
        finally:
            con.close()
        return raw_sha

    def test_pre016_copy_is_migrated_before_v4_persistence_without_raw_drift(self):
        raw_sha = self._insert_raw_fixture()
        before = _manifestation_fingerprint(self.db)
        bundle = json.loads(EXAMPLE.read_text(encoding="utf-8"))["bundle"]

        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                persist_legal_research_bundle(
                    con,
                    case_ref="case:issue255",
                    bundle=bundle,
                )
        finally:
            con.close()

        schema = prepare_case_runtime_database(
            db_path=self.db,
            schema_dir=ROOT / "schema",
        )

        self.assertIn(REQUIRED_V4_MIGRATION, schema["applied"])
        self.assertEqual(
            set(schema["required_tables"]),
            set(REQUIRED_V4_TABLES),
        )

        con = sqlite3.connect(self.db)
        try:
            recorded = con.execute(
                """
                SELECT schema_sha256
                FROM schema_metadata
                WHERE schema_name = ?
                """,
                (REQUIRED_V4_MIGRATION,),
            ).fetchone()
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            result = persist_legal_research_bundle(
                con,
                case_ref="case:issue255",
                bundle=bundle,
            )
            observed_raw_sha = con.execute(
                """
                SELECT sha256
                FROM manifestations
                WHERE manifestation_id = 'MAN-255'
                """
            ).fetchone()[0]
        finally:
            con.close()

        self.assertIsNotNone(recorded)
        self.assertEqual(len(recorded[0]), 64)
        self.assertTrue(REQUIRED_V4_TABLES.issubset(tables))
        self.assertEqual(result["action"], "insert")
        self.assertEqual(observed_raw_sha, raw_sha)
        self.assertEqual(_manifestation_fingerprint(self.db), before)

    def test_repository_migration_hash_drift_fails_closed(self):
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO schema_metadata(schema_name, schema_sha256)
                VALUES (?, ?)
                """,
                (REQUIRED_V4_MIGRATION, "0" * 64),
            )
            con.commit()
        finally:
            con.close()

        with self.assertRaisesRegex(
            RuntimeError,
            "Applied migration changed on disk: "
            + REQUIRED_V4_MIGRATION,
        ):
            prepare_case_runtime_database(
                db_path=self.db,
                schema_dir=ROOT / "schema",
            )

        con = sqlite3.connect(self.db)
        try:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()
        self.assertTrue(REQUIRED_V4_TABLES.isdisjoint(tables))

    def test_startup_schema_failure_happens_before_rest_bind(self):
        argv = [
            "case_rest_runtime.py",
            "--db",
            str(self.db),
            "--schema-dir",
            str(ROOT / "schema"),
            "--port",
            "0",
        ]
        stderr = io.StringIO()
        with (
            mock.patch("case_rest_runtime.sys.argv", argv),
            mock.patch(
                "case_rest_runtime.build_runtime_application",
                return_value=(object(), "fixture-provider", "fixture-model"),
            ),
            mock.patch(
                "case_rest_runtime.prepare_case_runtime_database",
                side_effect=RuntimeError("fixture migration failure"),
            ),
            mock.patch("case_rest_runtime.CaseRESTServer") as server,
            redirect_stderr(stderr),
        ):
            code = runtime_main()

        self.assertEqual(code, 2)
        server.assert_not_called()
        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(diagnostic["error"], STARTUP_FAILURE)
        self.assertEqual(diagnostic["stage"], "schema_migration")
        self.assertEqual(diagnostic["status"], "FAIL")

    def test_successful_startup_migrates_before_binding_rest_server(self):
        events: list[str] = []

        class FakeServer:
            server_address = ("127.0.0.1", 8765)

            def serve_forever(self) -> None:
                events.append("serve")

            def server_close(self) -> None:
                events.append("close")

        def build(**_kwargs):
            events.append("configure")
            return object(), "fixture-provider", "fixture-model"

        def migrate(**_kwargs):
            events.append("migrate")
            return {
                "applied": [REQUIRED_V4_MIGRATION],
                "already_applied": [],
                "required_migration": REQUIRED_V4_MIGRATION,
                "required_tables": sorted(REQUIRED_V4_TABLES),
            }

        def bind(*_args, **_kwargs):
            events.append("bind")
            return FakeServer()

        argv = [
            "case_rest_runtime.py",
            "--db",
            str(self.db),
            "--schema-dir",
            str(ROOT / "schema"),
            "--port",
            "0",
        ]
        with (
            mock.patch("case_rest_runtime.sys.argv", argv),
            mock.patch(
                "case_rest_runtime.build_runtime_application",
                side_effect=build,
            ),
            mock.patch(
                "case_rest_runtime.prepare_case_runtime_database",
                side_effect=migrate,
            ),
            mock.patch(
                "case_rest_runtime.CaseRESTServer",
                side_effect=bind,
            ),
            redirect_stdout(io.StringIO()),
        ):
            code = runtime_main()

        self.assertEqual(code, 0)
        self.assertEqual(
            events,
            ["configure", "migrate", "bind", "serve", "close"],
        )


if __name__ == "__main__":
    unittest.main()
