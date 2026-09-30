from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_issue0138_citable_evidence_graph as issue138
import test_issue0281_case_v5_planning as issue281

from case_application import publish_v5_legal_research_bundle
from case_contract_validation_v5 import validate_legal_research_bundle
from case_research_runtime_v5 import analyze_case_v5
from case_rest_api_v2 import CaseRESTApplication
from case_rest_runtime_v2 import prepare_case_v5_runtime_database
from llm_client import (
    CaseStructuringService,
    FakeLLMClient,
    LLMPlatformConfig,
    ModelRoute,
)


class Issue0306CaseV5RuntimeTests(unittest.TestCase):
    """Focused product-composition coverage for issue #306."""

    setUp = issue138.Issue0138CitableEvidenceGraphTests.setUp
    tearDown = issue138.Issue0138CitableEvidenceGraphTests.tearDown
    add_provision_document = (
        issue138.Issue0138CitableEvidenceGraphTests.add_provision_document
    )

    def _case_and_intake(self) -> tuple[dict, dict]:
        problem = "textoomega regla tributaria especial"
        case_input = issue281._case_input(problem)
        intake = issue281._intake(
            problem,
            [issue281._question("question:omega", problem)],
            intake_ref="intake:issue306",
        )
        return case_input, intake

    @staticmethod
    def _generated_payload(intake: dict) -> dict:
        payload = deepcopy(intake)
        payload.pop("problem_text")
        payload.pop("model_metadata")
        return payload

    @staticmethod
    def _config() -> LLMPlatformConfig:
        return LLMPlatformConfig(
            adapter="fake-llm",
            provider="test",
            base_url="https://example.invalid/v1",
            timeout_seconds=5,
            chars_per_token_estimate=4.0,
            primary=ModelRoute(
                name="fixture-model",
                routing_role="primary",
                context_tokens=32768,
                max_output_tokens=4096,
            ),
            auxiliary=None,
            review=None,
            primary_attempts=1,
            review_on_invalid_output=False,
            review_on_provider_error=False,
        )

    def _structurer(self, intake: dict) -> CaseStructuringService:
        return CaseStructuringService(
            self._config(),
            FakeLLMClient([self._generated_payload(intake)]),
        )

    def test_v5_intake_boundary_uses_the_existing_intake_only_semantics(self) -> None:
        case_input, intake = self._case_and_intake()
        outcome = self._structurer(intake).structure(case_input)

        self.assertEqual(outcome.draft["contract_version"], "5.0.0")
        self.assertEqual(outcome.draft["problem_text"], case_input["problem_text"])
        self.assertEqual(
            outcome.draft["model_metadata"]["prompt_template_id"],
            "case-intake-v5",
        )
        self.assertEqual(
            outcome.draft["model_metadata"]["structured_generation_mechanism"],
            "deterministic-test-schema",
        )
        self.assertNotIn("research_plan", outcome.draft)
        self.assertNotIn("authorities", outcome.draft)
        self.assertNotIn("evidence_spans", outcome.draft)

    def test_product_orchestration_returns_and_publishes_a_valid_v5_bundle(self) -> None:
        case_input, intake = self._case_and_intake()
        fixture = self.add_provision_document(
            token="306",
            document_id="DOC-306",
            document_type="LEY",
            number="306",
            year=2026,
            filename="ley_0306_2026.htm",
            text=(
                "textoomega regla tributaria especial con contenido jurídico "
                "exacto y verificable para investigación."
            ),
            designation="Artículo 1",
        )
        case_root = Path(self.tmp.name) / "cases"

        before = sqlite3.connect(self.db)
        try:
            raw_before = before.execute(
                "SELECT sha256 FROM manifestations WHERE manifestation_id = ?",
                (fixture["manifestation_id"],),
            ).fetchone()[0]
        finally:
            before.close()

        outcome = analyze_case_v5(
            case_input=case_input,
            db_path=self.db,
            case_root=case_root,
            structurer=self._structurer(intake),
        )
        validate_legal_research_bundle(outcome.bundle)

        self.assertEqual(outcome.bundle["case_input"], case_input)
        self.assertEqual(outcome.bundle["contract_version"], "5.0.0")
        self.assertTrue(outcome.bundle["research_plan"]["aspects"])
        self.assertTrue(outcome.bundle["research_result"]["trace"])
        self.assertTrue(outcome.bundle["research_result"]["evidence_selections"])
        self.assertTrue(outcome.bundle["research_result"]["aspect_coverage"])
        self.assertTrue(outcome.bundle["evidence_spans"])
        self.assertEqual(outcome.bundle["rule_fragments"], [])
        self.assertEqual(outcome.bundle["deterministic_evaluations"], [])
        self.assertEqual(outcome.bundle["calculation_traces"], [])

        # The unknown topic is deliberately generic-limited rather than guessed.
        self.assertEqual(outcome.bundle["status"], "partial")
        self.assertIn(
            "generic_scope",
            outcome.bundle["research_result"]["aspect_coverage"][0]["limitation_codes"],
        )

        after = sqlite3.connect(self.db)
        try:
            raw_after = after.execute(
                "SELECT sha256 FROM manifestations WHERE manifestation_id = ?",
                (fixture["manifestation_id"],),
            ).fetchone()[0]
            persisted = after.execute(
                "SELECT COUNT(*) FROM case_v5_bundles WHERE bundle_ref = ?",
                (outcome.bundle["bundle_ref"],),
            ).fetchone()[0]
        finally:
            after.close()
        self.assertEqual(raw_before, raw_after)
        self.assertEqual(persisted, 1)

        repeated = publish_v5_legal_research_bundle(
            case_ref=outcome.case_ref,
            bundle=outcome.bundle,
            db_path=self.db,
            case_root=case_root,
            dry_run=False,
        )
        self.assertEqual(repeated.persistence["action"], "reuse")

    def test_rest_v2_application_executes_the_real_v5_orchestrator(self) -> None:
        case_input, intake = self._case_and_intake()
        self.add_provision_document(
            token="306-rest",
            document_id="DOC-306-rest",
            document_type="LEY",
            number="307",
            year=2026,
            filename="ley_0307_2026.htm",
            text="textoomega regla tributaria especial evidencia REST v2.",
            designation="Artículo 2",
        )
        case_root = Path(self.tmp.name) / "cases-rest"
        structurer = self._structurer(intake)

        def researcher(value: dict, *, request_fingerprints=None) -> dict:
            return analyze_case_v5(
                case_input=value,
                db_path=self.db,
                case_root=case_root,
                structurer=structurer,
                request_fingerprints=request_fingerprints,
            ).bundle

        application = CaseRESTApplication(
            researcher,
            forward_request_fingerprints=True,
        )
        bundle = application.research(
            case_input,
            request_fingerprints={
                "raw_request_sha256": "1" * 64,
                "case_input_sha256": "2" * 64,
            },
        )
        self.assertEqual(bundle["contract_version"], "5.0.0")
        self.assertEqual(bundle["case_input"], case_input)

    def test_runtime_bootstrap_requires_and_applies_existing_v5_migration(self) -> None:
        bootstrap_db = Path(self.tmp.name) / "bootstrap.sqlite"
        result = prepare_case_v5_runtime_database(
            db_path=bootstrap_db,
            schema_dir=ROOT / "schema",
        )
        self.assertIn(
            "017_case_v5_bundle_persistence.sql",
            set(result["applied"]) | set(result["already_applied"]),
        )
        con = sqlite3.connect(bootstrap_db)
        try:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()
        self.assertTrue({"case_v5_bundles", "case_v5_artifacts"} <= tables)


if __name__ == "__main__":
    unittest.main()
