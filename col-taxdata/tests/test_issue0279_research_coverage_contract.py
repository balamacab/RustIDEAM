from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "application" / "case-contracts-v5.md"
SCHEMA = ROOT / "specs" / "application" / "schemas" / "case-contracts-v5.schema.json"
EXAMPLES = (
    ROOT
    / "specs"
    / "application"
    / "examples"
    / "case-v5"
    / "research-coverage-examples.json"
)
ADR = (
    ROOT
    / "specs"
    / "architecture"
    / "adr"
    / "ADR-0011-case-v5-research-aspect-coverage.md"
)


def _semantic_errors(scenario: dict) -> set[str]:
    """Evaluate the focused #279 semantic vectors.

    The vectors intentionally exercise cross-reference/status invariants rather
    than pretending to be full runtime LegalResearchBundle fixtures. Runtime
    validation of these invariants belongs to #280.
    """

    errors: set[str] = set()
    plan = scenario["plan"]
    result = scenario["result"]

    aspects = {item["aspect_ref"]: item for item in plan["aspects"]}
    tasks = {item["task_ref"]: item for item in plan["tasks"]}
    selections = {
        item["selection_ref"]: item for item in result.get("selections", [])
    }
    omissions = {
        item["omission_ref"]: item for item in result.get("omissions", [])
    }
    coverages = {
        item["aspect_ref"]: item for item in result.get("coverage", [])
    }
    evidence_refs = set(scenario.get("evidence_registry", []))
    authority_refs = set(scenario.get("authority_registry", []))

    for task in tasks.values():
        aspect = aspects.get(task["aspect_ref"])
        if aspect is None or aspect["question_ref"] != task["question_ref"]:
            errors.add("V5-REF-ASPECT-001")

    for selection in selections.values():
        if (
            selection["aspect_ref"] not in aspects
            or selection["task_ref"] not in tasks
            or tasks.get(selection["task_ref"], {}).get("aspect_ref")
            != selection["aspect_ref"]
            or selection["authority_ref"] not in authority_refs
            or any(ref not in evidence_refs for ref in selection["evidence_refs"])
        ):
            errors.add("V5-REF-SELECTION-002")

    for coverage in coverages.values():
        if (
            coverage["aspect_ref"] not in aspects
            or any(ref not in tasks for ref in coverage["task_refs"])
            or any(ref not in selections for ref in coverage["selection_refs"])
            or any(ref not in omissions for ref in coverage["omission_refs"])
        ):
            errors.add("V5-REF-COVERAGE-003")

        if coverage["support_closure"] == "complete":
            selected = [
                selections[ref]
                for ref in coverage["selection_refs"]
                if ref in selections
            ]
            if any(item["context_status"] == "incomplete" for item in selected):
                errors.add("V5-CONTEXT-001")

    if scenario["case_as_of_date"] is None:
        for coverage in coverages.values():
            if (
                coverage["temporal_status"] != "unassessed"
                or "temporal_unassessed"
                not in coverage.get("limitation_codes", [])
            ):
                errors.add("V5-TEMPORAL-001")

    if result["status"] == "complete":
        complete_ok = True
        for aspect in aspects.values():
            if not aspect["required"]:
                continue

            coverage = coverages.get(aspect["aspect_ref"])
            if aspect["scope_status"] in {"generic_limited", "unknown_unplanned"}:
                errors.add("V5-SCOPE-001")
                complete_ok = False

            if coverage is None or coverage["support_closure"] != "complete":
                complete_ok = False

            required_omissions = [
                item
                for item in omissions.values()
                if item["aspect_ref"] == aspect["aspect_ref"] and item["required"]
            ]
            if required_omissions:
                errors.add("V5-OMISSION-001")
                complete_ok = False

            if coverage is not None:
                if coverage["execution_status"] != "complete":
                    complete_ok = False
                if coverage["evidence_status"] != "context_ready":
                    complete_ok = False
                if coverage["authority_status"] != "resolved":
                    complete_ok = False

                selected = [
                    selections[ref]
                    for ref in coverage["selection_refs"]
                    if ref in selections
                ]
                if any(item["context_status"] == "incomplete" for item in selected):
                    complete_ok = False

        if not complete_ok:
            errors.add("V5-COMPLETE-001")

    return errors


class Issue0279ResearchCoverageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))
        cls.spec = SPEC.read_text(encoding="utf-8")
        cls.adr = ADR.read_text(encoding="utf-8")

    def test_v5_is_an_explicit_successor_not_an_in_place_v4_extension(self) -> None:
        self.assertEqual(self.schema["x-contract-status"], "accepted-design-not-runtime-active")
        self.assertEqual(
            self.schema["$defs"]["CaseInput"]["properties"]["contract_version"]["const"],
            "5.0.0",
        )
        self.assertIn("v4 remains frozen", self.spec)
        self.assertIn("REST v1 continues to transport CASE 4.0.0", self.spec)
        self.assertIn("Use a new CASE major version", self.adr)

    def test_schema_exposes_the_complete_research_chain_and_closed_shapes(self) -> None:
        required_defs = {
            "ResearchAspect",
            "ResearchTarget",
            "ResearchExecutionBudget",
            "SupportBudget",
            "ResearchBudgets",
            "FairnessPolicy",
            "ResearchTask",
            "ResearchTraceStep",
            "EvidenceSelection",
            "OmittedWork",
            "AspectCoverage",
            "ResearchContinuationRequest",
        }
        self.assertTrue(required_defs.issubset(self.schema["$defs"]))

        for name in required_defs - {"ResearchTarget"}:
            self.assertFalse(self.schema["$defs"][name]["additionalProperties"])

        task = self.schema["$defs"]["ResearchTask"]
        self.assertIn("aspect_ref", task["required"])
        self.assertIn("strategy", task["required"])
        self.assertIn("target", task["required"])

        result = self.schema["$defs"]["ResearchResult"]
        self.assertIn("evidence_selections", result["required"])
        self.assertIn("aspect_coverage", result["required"])
        self.assertIn("omitted_work", result["required"])

    def test_coverage_dimensions_do_not_collapse_to_supported(self) -> None:
        coverage = self.schema["$defs"]["AspectCoverage"]
        for field in (
            "execution_status",
            "evidence_status",
            "authority_status",
            "temporal_status",
            "fact_status",
            "synthesis_status",
            "support_closure",
        ):
            self.assertIn(field, coverage["required"])
        self.assertNotIn("supported", coverage["properties"])

    def test_budget_classes_keep_display_limits_out_of_canonical_plan(self) -> None:
        budgets = self.schema["$defs"]["ResearchBudgets"]
        self.assertEqual(set(budgets["required"]), {"research", "support"})
        self.assertNotIn("display", budgets["properties"])
        self.assertIn("Display/context-window limits are not canonical", self.spec)
        self.assertIn("#159", self.spec)

    def test_machine_checkable_vectors_cover_required_issue_classes(self) -> None:
        classes = {scenario["class"] for scenario in self.examples["scenarios"]}
        self.assertTrue(
            {"broad", "narrow", "mixed", "ambiguous", "unsupported-topic"}
            .issubset(classes)
        )

        for scenario in self.examples["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                errors = _semantic_errors(scenario)
                expected = set(scenario["expected_error_codes"])
                self.assertTrue(expected.issubset(errors))
                if scenario["expected_valid"]:
                    self.assertEqual(errors, set())
                else:
                    self.assertTrue(errors)

    def test_no_evaluator_does_not_prevent_complete_support_closure(self) -> None:
        scenario = next(
            item
            for item in self.examples["scenarios"]
            if item["id"] == "narrow-finite-no-evaluator"
        )
        self.assertEqual(scenario["deterministic_evaluations"], [])
        self.assertEqual(scenario["result"]["status"], "complete")
        coverage = scenario["result"]["coverage"][0]
        self.assertEqual(coverage["support_closure"], "complete")
        self.assertEqual(
            coverage["synthesis_status"], "requires_interpretive_synthesis"
        )
        self.assertEqual(_semantic_errors(scenario), set())

    def test_missing_personal_fact_does_not_block_unrelated_general_research(self) -> None:
        scenario = next(
            item
            for item in self.examples["scenarios"]
            if item["id"] == "mixed-missing-personalization-fact"
        )
        by_aspect = {
            item["aspect_ref"]: item for item in scenario["result"]["coverage"]
        }
        self.assertEqual(
            by_aspect["aspect:general-threshold-rule"]["support_closure"],
            "complete",
        )
        self.assertEqual(
            by_aspect["aspect:personal-threshold-evaluation"]["fact_status"],
            "missing",
        )
        self.assertEqual(scenario["result"]["status"], "partial")

    def test_temporal_uncertainty_is_explicit_and_caller_date_is_preserved(self) -> None:
        scenario = next(
            item
            for item in self.examples["scenarios"]
            if item["id"] == "ambiguous-mixed-temporal-support"
        )
        self.assertEqual(scenario["case_as_of_date"], "2020-06-30")
        coverage = scenario["result"]["coverage"][0]
        self.assertEqual(coverage["temporal_status"], "mixed")
        self.assertEqual(scenario["result"]["status"], "partial")

        absent_date = next(
            item
            for item in self.examples["scenarios"]
            if item["id"] == "narrow-finite-no-evaluator"
        )
        self.assertIsNone(absent_date["case_as_of_date"])
        self.assertEqual(
            absent_date["result"]["coverage"][0]["temporal_status"],
            "unassessed",
        )

    def test_all_declared_semantic_invariants_have_stable_codes(self) -> None:
        expected = {
            "V5-REF-ASPECT-001",
            "V5-REF-SELECTION-002",
            "V5-REF-COVERAGE-003",
            "V5-COMPLETE-001",
            "V5-OMISSION-001",
            "V5-CONTEXT-001",
            "V5-TEMPORAL-001",
            "V5-FACT-001",
            "V5-EVALUATOR-001",
            "V5-SCOPE-001",
            "V5-CONSUMER-001",
            "V5-ID-001",
        }
        self.assertEqual(set(self.schema["x-semantic-invariants"]), expected)

    def test_consumer_continuation_has_no_expected_answer_field(self) -> None:
        continuation = self.schema["$defs"]["ResearchContinuationRequest"]
        self.assertNotIn("expected_answer", continuation["properties"])
        self.assertNotIn("proposed_legal_conclusion", continuation["properties"])
        self.assertIn("requested_focus", continuation["properties"])
        self.assertIn("non-canonical", self.spec)

    def test_representation_pressure_gate_does_not_treat_142_as_pass(self) -> None:
        self.assertIn("REPRESENTATION_PRESSURE_GATE", self.spec)
        self.assertIn("#142 is closed as not_planned", self.adr)
        self.assertIn("#288 may provide measurements", self.adr)
        self.assertIn("representation/access", self.adr)


if __name__ == "__main__":
    unittest.main()
