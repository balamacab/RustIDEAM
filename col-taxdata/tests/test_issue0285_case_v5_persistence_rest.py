from __future__ import annotations

from copy import deepcopy
import hashlib
from http import HTTPStatus
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlrequest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_application import (
    CaseAnalysisIntegrityError,
    publish_v5_legal_research_bundle,
)
from case_bundle_persistence import (
    UNSUPPORTED_BUNDLE_PERSISTENCE_VERSION,
    load_versioned_bundle,
    persist_and_materialize_versioned_bundle,
)
from case_bundle_persistence_v4 import (
    BundlePersistenceError,
    persist_legal_research_bundle as persist_v4_bundle,
)
from case_bundle_persistence_v5 import materialization_path as v5_materialization_path
from case_contract_validation_v5 import validate_legal_research_bundle
from case_rest_api import API_VERSION as V1_API_VERSION, DEFAULT_ENDPOINT as V1_ENDPOINT
from case_rest_api_v2 import (
    API_VERSION,
    CASE_API_INTEGRITY_FAILURE,
    CaseRESTApplication,
    CaseRESTServer,
    DEFAULT_ENDPOINT,
    prepare_case_request,
    validate_error_payload,
    validate_success_payload,
)
from init_db import migrate_database


SPEC_ROOT = ROOT / "specs" / "application"
V2_EXAMPLES = SPEC_ROOT / "examples" / "case-rest-v2"
V1_EXAMPLES = SPEC_ROOT / "examples" / "case-rest-v1"
V2_OPENAPI = SPEC_ROOT / "openapi" / "case-rest-api-v2.openapi.json"
V2_SCHEMA = SPEC_ROOT / "schemas" / "case-rest-api-v2.schema.json"
NOW = "2026-09-29T18:30:00Z"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_all_migrations(db_path: Path) -> None:
    migrate_database(db_path=db_path, schema_dir=ROOT / "schema", emit=None)


class RunningV2Server:
    def __init__(self, researcher):
        self.server = CaseRESTServer(
            ("127.0.0.1", 0),
            CaseRESTApplication(researcher),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Issue0285CaseV5PersistenceRESTTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "state.sqlite"
        self.case_root = self.root / "cases"
        apply_all_migrations(self.db)
        self.example = load_json(V2_EXAMPLES / "complete-response.json")
        self.bundle = deepcopy(self.example["bundle"])
        validate_legal_research_bundle(self.bundle)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_published_contract_openapi_examples_and_versions_agree(self):
        openapi = load_json(V2_OPENAPI)
        schema = load_json(V2_SCHEMA)
        request_raw = (V2_EXAMPLES / "request.json").read_bytes()
        prepared = prepare_case_request(request_raw)

        self.assertEqual(API_VERSION, "2.0.0")
        self.assertEqual(DEFAULT_ENDPOINT, "/v2/cases")
        self.assertEqual(V1_API_VERSION, "1.0.0")
        self.assertEqual(V1_ENDPOINT, "/v1/cases")
        self.assertEqual(openapi["info"]["version"], API_VERSION)
        self.assertIn(DEFAULT_ENDPOINT, openapi["paths"])
        self.assertEqual(
            schema["$defs"]["CaseResearchResponse"]["properties"]["api_version"]["const"],
            API_VERSION,
        )
        self.assertEqual(
            schema["$defs"]["CaseResearchResponse"]["properties"]["bundle"]["$ref"],
            "case-contracts-v5.schema.json#/$defs/LegalResearchBundle",
        )
        self.assertEqual(prepared.case_input, self.bundle["case_input"])
        validate_success_payload(self.example)
        validate_error_payload(
            load_json(V2_EXAMPLES / "invalid-request-error.json")
        )
        validate_error_payload(
            load_json(V2_EXAMPLES / "service-unavailable-error.json")
        )

    def test_produce_persist_reload_validate_rest_preserves_v5_coverage_exactly(self):
        request_raw = (V2_EXAMPLES / "request.json").read_bytes()
        prepared = prepare_case_request(request_raw)
        canonical_before = json.dumps(
            self.bundle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        preview = publish_v5_legal_research_bundle(
            case_ref="case:issue285",
            bundle=self.bundle,
            db_path=self.db,
            case_root=self.case_root,
            dry_run=True,
        )
        path = v5_materialization_path(
            case_root=self.case_root,
            bundle_ref=self.bundle["bundle_ref"],
        )
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v5_bundles").fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v5_artifacts").fetchone()[0],
                0,
            )
        finally:
            con.close()
        self.assertFalse(path.exists())
        self.assertEqual(preview.persistence["action"], "insert")
        self.assertTrue(preview.persistence["would_insert_bundle"])

        written = publish_v5_legal_research_bundle(
            case_ref="case:issue285",
            bundle=self.bundle,
            db_path=self.db,
            case_root=self.case_root,
            dry_run=False,
        )
        con = sqlite3.connect(self.db)
        try:
            rebuilt = load_versioned_bundle(
                con,
                bundle_ref=self.bundle["bundle_ref"],
                contract_version="5.0.0",
            )
            persisted_context_hash = con.execute(
                """
                SELECT research_context_sha256
                FROM case_v5_bundles
                WHERE bundle_ref = ?
                """,
                (self.bundle["bundle_ref"],),
            ).fetchone()[0]
        finally:
            con.close()

        validate_legal_research_bundle(rebuilt)
        self.assertEqual(rebuilt, self.bundle)
        self.assertEqual(
            json.dumps(rebuilt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            canonical_before,
        )
        expected_context_hash = hashlib.sha256(
            json.dumps(
                self.bundle["research_result"]["research_context"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(persisted_context_hash, expected_context_hash)
        self.assertTrue(written.materialization["updated"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.bundle)

        def researcher(case_input: dict) -> dict:
            self.assertEqual(case_input, prepared.case_input)
            con = sqlite3.connect(self.db)
            try:
                return load_versioned_bundle(
                    con,
                    bundle_ref=self.bundle["bundle_ref"],
                    contract_version="5.0.0",
                )
            finally:
                con.close()

        with RunningV2Server(researcher) as running:
            req = urlrequest.Request(
                running.base_url + DEFAULT_ENDPOINT,
                data=request_raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_rest_api_v2.sys.stderr", io.StringIO()):
                response = urlrequest.urlopen(req, timeout=3)
                payload = json.loads(response.read())

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(
            response.headers["X-Col-Taxdata-API-Version"],
            API_VERSION,
        )
        validate_success_payload(payload)
        self.assertEqual(payload["bundle"], self.bundle)

        original_result = self.bundle["research_result"]
        returned_result = payload["bundle"]["research_result"]
        for field in (
            "trace",
            "evidence_selections",
            "aspect_coverage",
            "omitted_work",
            "unresolved_refs",
            "research_context",
        ):
            self.assertEqual(returned_result[field], original_result[field])
        self.assertEqual(
            payload["bundle"]["research_plan"]["aspects"],
            self.bundle["research_plan"]["aspects"],
        )
        self.assertEqual(
            payload["bundle"]["research_plan"]["tasks"],
            self.bundle["research_plan"]["tasks"],
        )
        self.assertEqual(
            returned_result["aspect_coverage"][0]["synthesis_status"],
            "requires_interpretive_synthesis",
        )

        second = publish_v5_legal_research_bundle(
            case_ref="case:issue285",
            bundle=self.bundle,
            db_path=self.db,
            case_root=self.case_root,
            dry_run=False,
        )
        self.assertEqual(second.persistence["action"], "reuse")
        self.assertFalse(second.materialization["updated"])

        equivalent_raw = json.dumps(
            json.loads(request_raw),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        equivalent = prepare_case_request(equivalent_raw)
        self.assertNotEqual(
            prepared.raw_request_sha256,
            equivalent.raw_request_sha256,
        )
        self.assertEqual(
            prepared.case_input_sha256,
            equivalent.case_input_sha256,
        )

    def test_v4_remains_interpretable_and_unsupported_versions_fail_explicitly(self):
        v4_bundle = load_json(V1_EXAMPLES / "complete-response.json")["bundle"]
        con = sqlite3.connect(self.db)
        try:
            persist_v4_bundle(
                con,
                case_ref="case:historical-v4",
                bundle=v4_bundle,
                persisted_at=NOW,
            )
            rebuilt_v4 = load_versioned_bundle(
                con,
                bundle_ref=v4_bundle["bundle_ref"],
                contract_version="4.0.0",
            )
            self.assertEqual(rebuilt_v4, v4_bundle)
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM case_v5_bundles WHERE bundle_ref = ?",
                    (v4_bundle["bundle_ref"],),
                ).fetchone()[0],
                0,
            )
        finally:
            con.close()

        invalid = deepcopy(self.bundle)
        invalid["contract_version"] = "6.0.0"
        with self.assertRaisesRegex(
            BundlePersistenceError,
            UNSUPPORTED_BUNDLE_PERSISTENCE_VERSION,
        ):
            persist_and_materialize_versioned_bundle(
                db_path=self.db,
                case_root=self.case_root,
                case_ref="case:unsupported",
                bundle=invalid,
                dry_run=True,
            )

    def test_migration_017_upgrades_016_without_rewriting_v4_or_raw_state(self):
        upgrade_db = self.root / "upgrade.sqlite"
        pre017 = self.root / "schema-pre017"
        pre017.mkdir()
        for migration in sorted((ROOT / "schema").glob("*.sql")):
            if migration.name < "017_":
                shutil.copy2(migration, pre017 / migration.name)

        migrate_database(db_path=upgrade_db, schema_dir=pre017, emit=None)
        v4_bundle = load_json(V1_EXAMPLES / "complete-response.json")["bundle"]
        raw_sha = hashlib.sha256(b"issue285 immutable raw fixture").hexdigest()
        con = sqlite3.connect(upgrade_db)
        try:
            persist_v4_bundle(
                con,
                case_ref="case:upgrade-v4",
                bundle=v4_bundle,
                persisted_at=NOW,
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (
                    'SRC-285', 'https://example.invalid/issue285',
                    'fixture', 'fixture', NULL, ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (
                    'MAN-285', NULL, 'SRC-285', 'text/plain',
                    ?, 30, ?, 'raw/issue285.txt', 'fixture'
                )
                """,
                (raw_sha, NOW),
            )
            before_bundle_sha = con.execute(
                "SELECT bundle_sha256 FROM case_v4_bundles WHERE bundle_ref = ?",
                (v4_bundle["bundle_ref"],),
            ).fetchone()[0]
            con.commit()
        finally:
            con.close()

        migration016 = ROOT / "schema" / "016_case_v4_bundle_persistence.sql"
        sha016_before = hashlib.sha256(migration016.read_bytes()).hexdigest()
        migrated = migrate_database(
            db_path=upgrade_db,
            schema_dir=ROOT / "schema",
            emit=None,
        )
        sha016_after = hashlib.sha256(migration016.read_bytes()).hexdigest()

        self.assertEqual(
            migrated["applied"],
            ("017_case_v5_bundle_persistence.sql",),
        )
        self.assertEqual(sha016_before, sha016_after)

        con = sqlite3.connect(upgrade_db)
        try:
            self.assertEqual(
                load_versioned_bundle(
                    con,
                    bundle_ref=v4_bundle["bundle_ref"],
                    contract_version="4.0.0",
                ),
                v4_bundle,
            )
            self.assertEqual(
                con.execute(
                    "SELECT bundle_sha256 FROM case_v4_bundles WHERE bundle_ref = ?",
                    (v4_bundle["bundle_ref"],),
                ).fetchone()[0],
                before_bundle_sha,
            )
            self.assertEqual(
                con.execute(
                    "SELECT sha256 FROM manifestations WHERE manifestation_id='MAN-285'"
                ).fetchone()[0],
                raw_sha,
            )
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("case_v5_bundles", tables)
            self.assertIn("case_v5_artifacts", tables)
        finally:
            con.close()

    def test_intake_model_text_stays_intake_only_and_consumer_inference_is_rejected(self):
        marker = "MODEL-INTAKE-ONLY-ISSUE285"
        bundle = deepcopy(self.bundle)
        bundle["intake_draft"]["model_metadata"]["model"] = marker
        validate_legal_research_bundle(bundle)

        publish_v5_legal_research_bundle(
            case_ref="case:model-boundary",
            bundle=bundle,
            db_path=self.db,
            case_root=self.case_root,
            dry_run=False,
        )
        con = sqlite3.connect(self.db)
        try:
            intake_payload = con.execute(
                """
                SELECT payload_json
                FROM case_v5_artifacts
                WHERE bundle_ref = ? AND authority_role = 'intake_only'
                """,
                (bundle["bundle_ref"],),
            ).fetchone()[0]
            canonical = [
                row[0]
                for row in con.execute(
                    """
                    SELECT payload_json
                    FROM case_v5_artifacts
                    WHERE bundle_ref = ?
                      AND authority_role IN (
                        'canonical_legal_support',
                        'deterministic_platform'
                      )
                    """,
                    (bundle["bundle_ref"],),
                )
            ]
        finally:
            con.close()
        self.assertIn(marker, intake_payload)
        self.assertTrue(canonical)
        self.assertTrue(all(marker not in payload for payload in canonical))

        rejected = deepcopy(self.bundle)
        rejected["bundle_ref"] = "bundle:consumer-inference-rejected"
        rejected["consumer_inference"] = {
            "answer": "consumer-owned legal conclusion"
        }
        with self.assertRaises(CaseAnalysisIntegrityError):
            publish_v5_legal_research_bundle(
                case_ref="case:consumer-inference",
                bundle=rejected,
                db_path=self.db,
                case_root=self.case_root,
                dry_run=True,
            )
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM case_v5_bundles WHERE bundle_ref = ?",
                    (rejected["bundle_ref"],),
                ).fetchone()[0],
                0,
            )
        finally:
            con.close()

    def test_v2_rejects_v4_bundle_as_integrity_failure(self):
        v4_bundle = load_json(V1_EXAMPLES / "complete-response.json")["bundle"]
        request_raw = (V2_EXAMPLES / "request.json").read_bytes()

        with RunningV2Server(lambda _case_input: deepcopy(v4_bundle)) as running:
            req = urlrequest.Request(
                running.base_url + DEFAULT_ENDPOINT,
                data=request_raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_rest_api_v2.sys.stderr", io.StringIO()):
                with self.assertRaises(urlerror.HTTPError) as raised:
                    urlrequest.urlopen(req, timeout=3)
            error = raised.exception
            payload = json.loads(error.read())

        self.assertEqual(error.code, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertEqual(
            payload["error"]["code"],
            CASE_API_INTEGRITY_FAILURE,
        )
        validate_error_payload(payload)


if __name__ == "__main__":
    unittest.main()
