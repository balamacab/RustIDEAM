from __future__ import annotations

import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "mcp_gateway"))

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    INVALID_LEGAL_RESEARCH_BUNDLE,
    intake_draft_generation_schema,
    validate_legal_research_bundle,
)
from case_evaluators import evaluate_supported_rules
from case_research import PlatformResearchService, build_research_plan
from deterministic_intake_adapter import DeterministicIntakeAdapter
from gateway import TOOL_NAMES, _REQUIRED_BUNDLE_FIELDS
from llm_client import CaseStructuringService, LLMPlatformConfig, ModelRoute


NOW = "2026-09-27T10:50:00+00:00"
AS_OF = "2026-09-27"
PROBLEM = (
    "Una persona natural residente en Colombia obtuvo ingresos y pregunta "
    "si debe declarar renta."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": PROBLEM,
        "as_of_date": AS_OF,
        "client_reference": "client:issue141",
    }


def generated_intake(*, hints: list[dict] | None = None) -> dict:
    """Model candidate before application-owned execution metadata is attached."""
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue141",
        "problem_text": PROBLEM,
        "as_of_date": AS_OF,
        "client_reference": "client:issue141",
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:person",
                "label": "Persona natural residente",
                "value": "Persona natural residente en Colombia con ingresos",
                "state": "user_provided",
                "source_quote": PROBLEM,
                "requires_confirmation": False,
            }
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:filing",
                "text": "¿Debe declarar renta?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:person"],
            }
        ],
        "search_hints": [] if hints is None else hints,
    }


def accepted_intake(*, hints: list[dict] | None = None) -> dict:
    """Application-accepted v4 intake with diagnostic-only model metadata."""
    value = generated_intake(hints=hints)
    value["model_metadata"] = {
        "adapter": "deterministic-intake",
        "provider": "deterministic-test",
        "model": "issue141-model",
        "schema_version": "4.0.0",
        "prompt_template_id": "case-intake-v4",
        "prompt_template_version": "1",
        "run_reference": "run:issue141",
        "generated_at": NOW,
        "routing_role": "intake_structuring",
        "structured_generation_mechanism": "deterministic-test-schema",
    }
    return value


def config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="issue141-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("issue141-model", "primary", 100_000, 2048),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _top_level_import_modules(path: str) -> set[str]:
    tree = ast.parse(_source(path))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _schema() -> dict:
    return json.loads(
        (ROOT / "specs/application/schemas/case-contracts-v4.schema.json")
        .read_text(encoding="utf-8")
    )


def _complete_bundle() -> dict:
    response = json.loads(
        (
            ROOT
            / "specs/application/examples/case-rest-v1/complete-response.json"
        ).read_text(encoding="utf-8")
    )
    return response["bundle"]


class Issue0141AuthorityBoundaryTests(unittest.TestCase):
    def test_application_depends_on_port_not_concrete_provider(self):
        active_application_modules = (
            "tools/case_application.py",
            "tools/analyze_case.py",
            "tools/case_http.py",
            "tools/case_rest_api.py",
        )
        for path in active_application_modules:
            with self.subTest(path=path):
                self.assertNotIn(
                    "openai_compatible_intake_adapter",
                    _top_level_import_modules(path),
                )

        llm_imports = _top_level_import_modules("tools/llm_client.py")
        self.assertIn("case_intake_inference", llm_imports)
        self.assertNotIn("openai_compatible_intake_adapter", llm_imports)

    def test_legal_authority_modules_have_no_provider_transport_dependency(self):
        authority_modules = (
            "tools/case_research.py",
            "tools/case_evidence_graph.py",
            "tools/case_evaluators.py",
            "tools/case_bundle_persistence_v4.py",
        )
        for path in authority_modules:
            with self.subTest(path=path):
                imports = _top_level_import_modules(path)
                roots = {module.split(".", 1)[0] for module in imports}
                self.assertNotIn("openai_compatible_intake_adapter", imports)
                self.assertNotIn("case_intake_factory", imports)
                self.assertNotIn("urllib", roots)

    def test_fake_adapter_cannot_inject_model_owned_legal_authority(self):
        forbidden_payloads = {
            "legal_conclusion": "Debe presentar declaración.",
            "candidate_claims": [{"text": "Debe presentar declaración."}],
            "evidence_spans": [{"exact_text": "modelo"}],
            "rule_fragments": [{"text": "modelo"}],
            "deterministic_evaluations": [{"result": "modelo"}],
            "calculation_traces": [{"result": "modelo"}],
        }
        for field, value in forbidden_payloads.items():
            with self.subTest(field=field):
                payload = generated_intake()
                payload[field] = value
                with self.assertRaises(CaseContractError) as raised:
                    CaseStructuringService(
                        config(),
                        DeterministicIntakeAdapter([payload]),
                    ).structure(case_input())
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_model_visible_schema_contains_intake_only(self):
        schema = intake_draft_generation_schema(case_input())
        self.assertEqual(
            set(schema["$defs"]),
            {
                "IntakeDraft",
                "IntakeFact",
                "FactMeasurement",
                "DecimalString",
                "CaseQuestion",
                "SearchHint",
            },
        )
        properties = schema["$defs"]["IntakeDraft"]["properties"]
        self.assertTrue(
            {
                "candidate_claims",
                "legal_conclusion",
                "research_plan",
                "research_result",
                "sources",
                "authorities",
                "evidence_spans",
                "rule_fragments",
                "deterministic_evaluations",
                "calculation_traces",
                "final_answer",
            }.isdisjoint(properties)
        )

    def test_research_entry_rejects_candidate_only_model_prose(self):
        candidate_only = accepted_intake()
        candidate_only["facts"] = []
        candidate_only["questions"] = []
        candidate_only["search_hints"] = []
        candidate_only["candidate_claims"] = [
            {
                "claim_ref": "claim:model",
                "text": "El contribuyente no está obligado a declarar.",
            }
        ]

        with self.assertRaises(CaseContractError) as raised:
            build_research_plan(case_input(), candidate_only, generated_at=NOW)
        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_optional_hint_cannot_suppress_platform_required_query(self):
        misleading_hint = {
            "kind": "search_hint",
            "contract_version": "4.0.0",
            "hint_ref": "hint:misleading",
            "terms": ["respuesta propuesta por el modelo"],
            "origin": "internal_intake_model",
            "related_question_refs": ["question:filing"],
        }
        without_hint = build_research_plan(
            case_input(), accepted_intake(), generated_at=NOW
        )
        with_hint = build_research_plan(
            case_input(),
            accepted_intake(hints=[misleading_hint]),
            generated_at=NOW,
        )
        required_without = [
            task for task in without_hint["tasks"]
            if task["origin"] == "platform_required"
        ]
        required_with = [
            task for task in with_hint["tasks"]
            if task["origin"] == "platform_required"
        ]
        self.assertEqual(required_without, required_with)
        self.assertTrue(required_with)
        self.assertTrue(
            any(
                task["origin"] == "intake_hint_expansion"
                for task in with_hint["tasks"]
            )
        )

    def test_active_v4_research_has_no_candidate_claim_search_axis(self):
        research_source = _source("tools/case_research.py")
        self.assertNotIn("candidate_claim", research_source)
        self.assertEqual(
            list(inspect.signature(build_research_plan).parameters)[:2],
            ["case_input", "intake_draft"],
        )

    def test_artifact_contracts_require_provenance_and_explicit_inputs(self):
        defs = _schema()["$defs"]
        self.assertTrue(
            {
                "authority_ref",
                "document_ref",
                "source_ref",
                "exact_text",
                "source_sha256",
                "text_sha256",
                "provenance_ref",
                "span_ref",
            }.issubset(defs["EvidenceSpan"]["required"])
        )

        rule = defs["RuleFragment"]
        self.assertTrue(
            {
                "rule_type",
                "rule_schema_version",
                "derivation",
                "authority_refs",
                "evidence_refs",
            }.issubset(rule["required"])
        )
        self.assertGreaterEqual(rule["properties"]["authority_refs"]["minItems"], 1)
        self.assertGreaterEqual(rule["properties"]["evidence_refs"]["minItems"], 1)

        self.assertTrue(
            {
                "evaluator_id",
                "evaluator_version",
                "fact_refs",
                "rule_refs",
                "evidence_refs",
                "calculation_trace_refs",
                "unresolved_refs",
            }.issubset(defs["DeterministicEvaluation"]["required"])
        )
        self.assertTrue(
            {
                "calculator_id",
                "calculator_version",
                "inputs",
                "formula",
                "formula_language",
                "rule_refs",
                "evidence_refs",
            }.issubset(defs["CalculationTrace"]["required"])
        )

    def test_unsupported_interpretation_stays_requires_synthesis(self):
        outcome = evaluate_supported_rules(
            case_input=case_input(),
            intake_draft=accepted_intake(),
            authorities=[],
            evidence_spans=[],
            rule_fragments=[],
            generated_at=NOW,
        )
        self.assertEqual(outcome.evaluations, ())
        self.assertEqual(outcome.calculations, ())
        self.assertTrue(
            any(
                item["category"] == "requires_interpretive_synthesis"
                and item["next_action"] == "external_interpretive_synthesis"
                for item in outcome.unresolved
            )
        )

    def test_absence_of_evidence_never_becomes_affirmative_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.sqlite"
            con = sqlite3.connect(db)
            try:
                for migration in sorted((ROOT / "schema").glob("*.sql")):
                    con.executescript(migration.read_text(encoding="utf-8"))
                con.commit()
            finally:
                con.close()

            outcome = PlatformResearchService(db).research(
                case_input=case_input(),
                intake_draft=accepted_intake(),
                generated_at=NOW,
            )

        self.assertEqual(outcome.authorities, ())
        self.assertEqual(outcome.evidence_candidates, ())
        self.assertTrue(
            any(
                item["category"] == "no_relevant_corpus_evidence"
                for item in outcome.unresolved
            )
        )

    def test_internal_model_diagnostics_cannot_be_bundle_authority(self):
        bundle = _complete_bundle()
        bundle["authorities"][0]["internal_model_prose"] = (
            "El modelo considera que esta es la norma aplicable."
        )
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bundle)
        self.assertEqual(
            raised.exception.code, INVALID_LEGAL_RESEARCH_BUNDLE
        )

    def test_external_consumer_inference_has_no_canonical_writeback_path(self):
        bundle = _complete_bundle()
        bundle["consumer_inference"] = {
            "owner": "external_llm",
            "answer": "Conclusión sintetizada por el consumidor.",
        }
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bundle)
        self.assertEqual(
            raised.exception.code, INVALID_LEGAL_RESEARCH_BUNDLE
        )
        self.assertTrue(
            all(
                not any(
                    token in name
                    for token in ("write", "persist", "promote", "submit_inference")
                )
                for name in TOOL_NAMES
            )
        )

    def test_bundle_and_mcp_keep_authority_classes_distinct(self):
        defs = _schema()["$defs"]
        expected_kinds = {
            "EvidenceSpan": "evidence_span",
            "RuleFragment": "rule_fragment",
            "DeterministicEvaluation": "deterministic_evaluation",
            "CalculationTrace": "calculation_trace",
            "UnresolvedItem": "unresolved_item",
        }
        for definition, expected_kind in expected_kinds.items():
            with self.subTest(definition=definition):
                self.assertEqual(
                    defs[definition]["properties"]["kind"]["const"],
                    expected_kind,
                )
                self.assertFalse(defs[definition]["additionalProperties"])

        self.assertTrue(
            {
                "evidence_spans",
                "rule_fragments",
                "deterministic_evaluations",
                "calculation_traces",
                "unresolved",
            }.issubset(_REQUIRED_BUNDLE_FIELDS)
        )
        self.assertFalse(defs["LegalResearchBundle"]["additionalProperties"])

    def test_v3_compatibility_is_not_active_v4_authority_logic(self):
        application_source = _source("tools/case_application.py")
        tree = ast.parse(application_source)
        analyze = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "analyze_case"
        )
        v4_branch = next(
            node for node in analyze.body
            if isinstance(node, ast.If)
            and "V4_CONTRACT_VERSION" in ast.unparse(node.test)
        )
        v4_source = ast.get_source_segment(application_source, v4_branch)
        self.assertIsNotNone(v4_source)
        self.assertIn("PlatformResearchService", v4_source)
        self.assertIn("build_legal_research_bundle", v4_source)
        self.assertNotIn("candidate_claim", v4_source)
        self.assertIn("candidate_claims", application_source)

        for path in (
            "tools/case_research.py",
            "tools/case_evidence_graph.py",
            "tools/case_evaluators.py",
            "tools/case_bundle_persistence_v4.py",
        ):
            with self.subTest(path=path):
                self.assertNotIn(
                    "case_contract_validation",
                    _top_level_import_modules(path),
                )


if __name__ == "__main__":
    unittest.main()
