from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_bundle_persistence_v4 import (
    BundleIntegrityError,
    load_legal_research_bundle,
    materialization_path,
    persist_and_materialize_legal_research_bundle,
    persist_legal_research_bundle,
)
from case_contract_validation import CaseContractError
from case_contract_validation_v4 import validate_legal_research_bundle
from materialize_case_report import render_report


NOW = "2026-09-27T12:00:00+00:00"
CASE_REF = "case:issue140"
EXAMPLES = ROOT / "specs" / "application" / "examples" / "case-rest-v1"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))["bundle"]


def apply_migrations(
    con: sqlite3.Connection,
    *,
    include_v4_persistence: bool = True,
) -> None:
    for migration in sorted((ROOT / "schema").glob("*.sql")):
        if not include_v4_persistence and migration.name >= "016_":
            continue
        con.executescript(migration.read_text(encoding="utf-8"))
    con.commit()


def bundle_with_deterministic_artifacts() -> dict:
    bundle = deepcopy(load_example("complete-response.json"))
    rule_ref = "rule:article-1"
    calculation_ref = "calculation:article-1"
    evaluation_ref = "evaluation:article-1"

    bundle["rule_fragments"] = [
        {
            "kind": "rule_fragment",
            "contract_version": "4.0.0",
            "rule_ref": rule_ref,
            "rule_type": "canonical_source_statement",
            "rule_schema_version": "1",
            "structured_data": {
                "statement_scope": "canonical_provision",
                "document_ref": "document:law",
                "authority_ref": "authority:law",
                "evidence_refs": ["evidence:article-1"],
                "provision_ref": "provision:article-1",
                "provision_type": "article",
                "designation": "Artículo 1",
            },
            "derivation": {
                "method": "extractive_normalization",
                "version": "1",
            },
            "authority_refs": ["authority:law"],
            "evidence_refs": ["evidence:article-1"],
            "as_of_date": "2026-09-27",
        }
    ]
    bundle["calculation_traces"] = [
        {
            "kind": "calculation_trace",
            "contract_version": "4.0.0",
            "calculation_ref": calculation_ref,
            "calculator_id": "issue140-fixture-calculator",
            "calculator_version": "1",
            "inputs": [
                {
                    "name": "fixture_value",
                    "decimal_value": "1",
                    "unit": "unit",
                    "source_fact_ref": "fact:dates",
                }
            ],
            "formula": "fixture_value",
            "formula_language": "decimal-expression-v1",
            "steps": [
                {
                    "label": "identity",
                    "expression": "fixture_value",
                    "result_decimal": "1",
                    "unit": "unit",
                }
            ],
            "result": {
                "decimal_value": "1",
                "unit": "unit",
            },
            "rounding": {
                "mode": "NONE",
                "scale": 0,
            },
            "rule_refs": [rule_ref],
            "evidence_refs": ["evidence:article-1"],
            "generated_at": NOW,
        }
    ]
    bundle["deterministic_evaluations"] = [
        {
            "kind": "deterministic_evaluation",
            "contract_version": "4.0.0",
            "evaluation_ref": evaluation_ref,
            "evaluator_id": "issue140-fixture-evaluator",
            "evaluator_version": "1",
            "status": "determined",
            "question_refs": ["question:date-effect"],
            "fact_refs": ["fact:dates"],
            "rule_refs": [rule_ref],
            "evidence_refs": ["evidence:article-1"],
            "calculation_trace_refs": [calculation_ref],
            "unresolved_refs": [],
            "as_of_date": "2026-09-27",
            "result": {
                "code": "fixture_determined",
                "value": True,
            },
            "generated_at": NOW,
        }
    ]
    validate_legal_research_bundle(bundle)
    return bundle


class Issue0140LegalResearchBundlePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "case140.sqlite"
        self.case_root = self.root / "cases"
        con = sqlite3.connect(self.db)
        try:
            apply_migrations(con)
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fresh_and_upgrade_migration_preserve_existing_raw_hash(self):
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
        self.assertIn("case_v4_bundles", tables)
        self.assertIn("case_v4_artifacts", tables)

        upgrade = self.root / "upgrade.sqlite"
        con = sqlite3.connect(upgrade)
        try:
            apply_migrations(con, include_v4_persistence=False)
            raw_sha = hashlib.sha256(b"immutable raw fixture").hexdigest()
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                )
                VALUES (
                    'SRC-140',
                    'https://example.invalid/issue140',
                    'fixture',
                    'fixture',
                    NULL,
                    ?,
                    ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                )
                VALUES (
                    'MAN-140',
                    NULL,
                    'SRC-140',
                    'text/plain',
                    ?,
                    21,
                    ?,
                    'raw/issue140.txt',
                    'fixture'
                )
                """,
                (raw_sha, NOW),
            )
            con.commit()

            migration = ROOT / "schema" / "016_case_v4_bundle_persistence.sql"
            con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()

            after = con.execute(
                "SELECT sha256 FROM manifestations WHERE manifestation_id='MAN-140'"
            ).fetchone()[0]
            self.assertEqual(after, raw_sha)
            upgraded_tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("case_v4_bundles", upgraded_tables)
            self.assertIn("case_v4_artifacts", upgraded_tables)
        finally:
            con.close()

    def test_canonical_artifacts_persist_with_ownership_and_provenance(self):
        bundle = bundle_with_deterministic_artifacts()
        con = sqlite3.connect(self.db)
        try:
            result = persist_legal_research_bundle(
                con,
                case_ref=CASE_REF,
                bundle=bundle,
                persisted_at=NOW,
            )
            rebuilt = load_legal_research_bundle(
                con,
                bundle_ref=bundle["bundle_ref"],
            )
            artifact_rows = con.execute(
                """
                SELECT artifact_kind, owner, authority_role
                FROM case_v4_artifacts
                WHERE bundle_ref = ?
                ORDER BY artifact_kind
                """,
                (bundle["bundle_ref"],),
            ).fetchall()
            legacy_claim_count = con.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
        finally:
            con.close()

        self.assertEqual(result["action"], "insert")
        self.assertEqual(rebuilt, bundle)
        self.assertEqual(legacy_claim_count, 0)

        ownership = {
            kind: (owner, role)
            for kind, owner, role in artifact_rows
        }
        self.assertEqual(
            ownership["intake_draft"],
            ("internal_intake_model", "intake_only"),
        )
        self.assertEqual(
            ownership["evidence_span"],
            ("platform", "canonical_legal_support"),
        )
        self.assertEqual(
            ownership["rule_fragment"],
            ("platform", "canonical_legal_support"),
        )
        self.assertEqual(
            ownership["deterministic_evaluation"],
            ("platform", "deterministic_platform"),
        )
        self.assertEqual(
            ownership["calculation_trace"],
            ("platform", "deterministic_platform"),
        )

        evidence = rebuilt["evidence_spans"][0]
        self.assertEqual(
            evidence["source_sha256"],
            "3" * 64,
        )
        self.assertEqual(
            evidence["text_sha256"],
            "4" * 64,
        )
        self.assertEqual(
            evidence["provenance_ref"],
            "provenance:article-1",
        )
        rule = rebuilt["rule_fragments"][0]
        self.assertEqual(
            rule["evidence_refs"],
            ["evidence:article-1"],
        )
        self.assertEqual(
            rule["derivation"],
            {"method": "extractive_normalization", "version": "1"},
        )
        evaluation = rebuilt["deterministic_evaluations"][0]
        self.assertEqual(
            evaluation["calculation_trace_refs"],
            ["calculation:article-1"],
        )
        self.assertEqual(
            rebuilt["calculation_traces"][0]["result"],
            {"decimal_value": "1", "unit": "unit"},
        )

    def test_model_prose_is_persisted_only_as_intake_not_legal_authority(self):
        bundle = deepcopy(load_example("complete-response.json"))
        marker = "MODELO DICE QUE DEBE DECLARAR"
        bundle["intake_draft"]["facts"][1]["label"] = marker
        validate_legal_research_bundle(bundle)

        con = sqlite3.connect(self.db)
        try:
            persist_legal_research_bundle(
                con,
                case_ref=CASE_REF,
                bundle=bundle,
                persisted_at=NOW,
            )
            intake_json = con.execute(
                """
                SELECT payload_json
                FROM case_v4_artifacts
                WHERE bundle_ref = ?
                  AND authority_role = 'intake_only'
                """,
                (bundle["bundle_ref"],),
            ).fetchone()[0]
            canonical_payloads = [
                row[0]
                for row in con.execute(
                    """
                    SELECT payload_json
                    FROM case_v4_artifacts
                    WHERE bundle_ref = ?
                      AND authority_role IN (
                          'canonical_legal_support',
                          'deterministic_platform'
                      )
                    """,
                    (bundle["bundle_ref"],),
                )
            ]
            legacy_claim_count = con.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
        finally:
            con.close()

        self.assertIn(marker, intake_json)
        self.assertTrue(canonical_payloads)
        self.assertTrue(
            all(marker not in payload for payload in canonical_payloads)
        )
        self.assertEqual(legacy_claim_count, 0)

    def test_requires_synthesis_unresolved_state_survives_round_trip(self):
        bundle = load_example("partial-response.json")
        con = sqlite3.connect(self.db)
        try:
            persist_legal_research_bundle(
                con,
                case_ref=CASE_REF,
                bundle=bundle,
                persisted_at=NOW,
            )
            rebuilt = load_legal_research_bundle(
                con,
                bundle_ref=bundle["bundle_ref"],
            )
        finally:
            con.close()

        self.assertEqual(rebuilt["status"], "partial")
        self.assertTrue(
            any(
                item["category"] == "requires_interpretive_synthesis"
                and item["next_action"] == "external_interpretive_synthesis"
                for item in rebuilt["unresolved"]
            )
        )

    def test_preview_write_regeneration_are_non_mutating_then_idempotent(self):
        bundle = bundle_with_deterministic_artifacts()

        preview_persistence, preview_materialization = (
            persist_and_materialize_legal_research_bundle(
                db_path=self.db,
                case_root=self.case_root,
                case_ref=CASE_REF,
                bundle=bundle,
                dry_run=True,
            )
        )
        path = materialization_path(
            case_root=self.case_root,
            bundle_ref=bundle["bundle_ref"],
        )
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v4_bundles").fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v4_artifacts").fetchone()[0],
                0,
            )
        finally:
            con.close()
        self.assertFalse(path.exists())
        self.assertTrue(preview_persistence["would_insert_bundle"])
        self.assertGreater(
            preview_persistence["would_insert_artifacts"],
            0,
        )
        self.assertEqual(
            preview_materialization["before"]["status"],
            "missing",
        )

        first_persistence, first_materialization = (
            persist_and_materialize_legal_research_bundle(
                db_path=self.db,
                case_root=self.case_root,
                case_ref=CASE_REF,
                bundle=bundle,
                dry_run=False,
            )
        )
        self.assertEqual(
            preview_persistence["would_insert_artifacts"],
            first_persistence["artifacts_inserted"],
        )
        self.assertTrue(first_materialization["updated"])
        self.assertTrue(path.exists())

        con = sqlite3.connect(self.db)
        try:
            before_counts = (
                con.execute("SELECT COUNT(*) FROM case_v4_bundles").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM case_v4_artifacts").fetchone()[0],
            )
        finally:
            con.close()

        second_persistence, second_materialization = (
            persist_and_materialize_legal_research_bundle(
                db_path=self.db,
                case_root=self.case_root,
                case_ref=CASE_REF,
                bundle=bundle,
                dry_run=False,
            )
        )
        con = sqlite3.connect(self.db)
        try:
            after_counts = (
                con.execute("SELECT COUNT(*) FROM case_v4_bundles").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM case_v4_artifacts").fetchone()[0],
            )
        finally:
            con.close()

        self.assertEqual(second_persistence["action"], "reuse")
        self.assertEqual(before_counts, after_counts)
        self.assertFalse(second_materialization["updated"])
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            bundle,
        )
        validate_legal_research_bundle(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def test_legacy_candidate_report_is_explicitly_v3_and_noncanonical(self):
        case_id = "CASE-LEGACY-140"
        claim_id = "CLM-LEGACY-140"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO cases(
                    case_id, title, query_text, as_of_date, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'open', ?, ?)
                """,
                (
                    case_id,
                    "Legacy compatibility fixture",
                    "Legacy candidate must remain visibly non-canonical.",
                    "2026-09-27",
                    NOW,
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO claims(
                    claim_id, subject_type, subject_id, predicate,
                    object_type, object_id, object_literal, claim_type,
                    status, extraction_method, confidence_extraction,
                    requires_human_review, created_at
                )
                VALUES (
                    ?, 'case', ?, 'legal_conclusion',
                    'literal', NULL, ?,
                    'case_legal_conclusion', 'candidate',
                    'legacy_model_fixture', 0.5, 1, ?
                )
                """,
                (
                    claim_id,
                    case_id,
                    "MODELO LEGACY: conclusión jurídica no soportada.",
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO case_items(
                    case_id, item_type, item_id, relevance, added_at
                )
                VALUES (?, 'claim', ?, 'legacy-fixture', ?)
                """,
                (case_id, claim_id, NOW),
            )
            con.commit()

            report = render_report(
                con=con,
                case_id=case_id,
                case_dir=self.case_root / case_id,
            )
        finally:
            con.close()

        self.assertIn(
            "# CASE-LEGACY-140 — Informe histórico v3 (compatibilidad)",
            report,
        )
        self.assertIn(
            "## Claims jurídicos históricos v3 (compatibilidad)",
            report,
        )
        self.assertIn(
            "Propiedad: `historical_v3_claim_state` · Estado: **candidate**",
            report,
        )
        self.assertIn(
            "un claim `candidate` o no soportado no constituye autoridad jurídica canónica",
            report,
        )
        self.assertNotIn("## Conclusiones jurídicas registradas", report)

    def test_external_consumer_inference_cannot_enter_canonical_persistence(self):
        bundle = deepcopy(load_example("complete-response.json"))
        bundle["consumer_inference"] = {
            "answer": "Consumer-owned legal conclusion"
        }

        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(CaseContractError):
                persist_legal_research_bundle(
                    con,
                    case_ref=CASE_REF,
                    bundle=bundle,
                    persisted_at=NOW,
                )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v4_bundles").fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM case_v4_artifacts").fetchone()[0],
                0,
            )
        finally:
            con.close()

    def test_same_bundle_ref_with_changed_content_fails_closed(self):
        bundle = deepcopy(load_example("complete-response.json"))
        con = sqlite3.connect(self.db)
        try:
            persist_legal_research_bundle(
                con,
                case_ref=CASE_REF,
                bundle=bundle,
                persisted_at=NOW,
            )
            changed = deepcopy(bundle)
            changed["case_input"]["caller_metadata"]["attempt"] = 2
            changed["intake_draft"]["caller_metadata"]["attempt"] = 2
            validate_legal_research_bundle(changed)
            with self.assertRaises(BundleIntegrityError):
                persist_legal_research_bundle(
                    con,
                    case_ref=CASE_REF,
                    bundle=changed,
                    persisted_at=NOW,
                )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
