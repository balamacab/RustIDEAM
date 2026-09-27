from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_dispatch import (
    INVALID_CASE_CONTRACT_KIND,
    UNSUPPORTED_CASE_CONTRACT_VERSION,
    validate_analysis_result,
    validate_case_input as dispatch_case_input,
    validate_structured_intake,
)
from case_contract_validation import (
    CaseContractError,
    validate_case_draft as validate_v3_case_draft,
)
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    INVALID_LEGAL_RESEARCH_BUNDLE,
    INVALID_RESEARCH_PLAN,
    INVALID_RESEARCH_RESULT,
    validate_intake_draft,
    validate_legal_research_bundle,
    validate_research_plan,
    validate_research_result,
)


PROBLEM = (
    "El contrato registra dos fechas posibles: 1 y 15 de septiembre de 2026.\r\n"
    "El cliente pide determinar cuál fecha controla el tratamiento jurídico."
)
SOURCE_QUOTE = (
    "El contrato registra dos fechas posibles: 1 y 15 de septiembre de 2026."
)


def v4_case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": PROBLEM,
        "as_of_date": "2026-09-27",
        "client_reference": "client:issue134",
        "caller_metadata": {
            "channel": "test",
            "attempt": 1,
            "review": False,
            "nullable": None,
        },
    }


def v4_intake_draft() -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue134",
        "problem_text": PROBLEM,
        "as_of_date": "2026-09-27",
        "client_reference": "client:issue134",
        "caller_metadata": {
            "channel": "test",
            "attempt": 1,
            "review": False,
            "nullable": None,
        },
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:dates",
                "label": "Fechas registradas",
                "value": "1 y 15 de septiembre de 2026",
                "state": "user_provided",
                "source_quote": SOURCE_QUOTE,
                "requires_confirmation": False,
            },
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:controlling-date",
                "label": "Fecha jurídicamente aplicable",
                "state": "ambiguous",
                "requires_confirmation": True,
                "needed_information": (
                    "Determinar con evidencia cuál de las dos fechas controla."
                ),
            },
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:date-effect",
                "text": "¿Cuál fecha produce el efecto jurídico relevante?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:dates"],
            }
        ],
        "search_hints": [
            {
                "kind": "search_hint",
                "contract_version": "4.0.0",
                "hint_ref": "hint:temporal",
                "terms": ["vigencia", "fecha aplicable"],
                "origin": "internal_intake_model",
                "related_question_refs": ["question:date-effect"],
            }
        ],
        "model_metadata": {
            "adapter": "deterministic-fixture",
            "provider": "descriptive-provider",
            "model": "fixture-model",
            "schema_version": "4.0.0",
            "prompt_template_id": "case-intake-v4",
            "prompt_template_version": "1",
            "run_reference": "run:issue134",
            "generated_at": "2026-09-27T07:00:00Z",
            "routing_role": "intake_structuring",
            "structured_generation_mechanism": "fixture",
        },
    }


def v4_research_plan() -> dict:
    return {
        "kind": "research_plan",
        "contract_version": "4.0.0",
        "plan_ref": "plan:issue134",
        "intake_ref": "intake:issue134",
        "as_of_date": "2026-09-27",
        "tasks": [
            {
                "kind": "research_task",
                "contract_version": "4.0.0",
                "task_ref": "task:date-effect",
                "question_ref": "question:date-effect",
                "origin": "platform_required",
                "purpose": "primary_research",
                "query_text": "vigencia efecto jurídico fecha",
                "generated_from_fact_refs": ["fact:dates"],
                "hint_refs": ["hint:temporal"],
                "depth": 0,
            }
        ],
        "bounds": {
            "max_rounds": 2,
            "max_queries_per_question": 3,
            "max_hits_per_query": 10,
            "max_reference_depth": 1,
            "max_total_authorities": 20,
        },
        "stop_conditions": [
            "questions_satisfied",
            "bounds_exhausted",
        ],
        "planner_version": "planner-test-1",
        "generated_at": "2026-09-27T07:01:00Z",
    }


def v4_research_result() -> dict:
    return {
        "kind": "research_result",
        "contract_version": "4.0.0",
        "result_ref": "research:issue134",
        "plan_ref": "plan:issue134",
        "status": "complete",
        "trace": [
            {
                "kind": "research_trace_step",
                "contract_version": "4.0.0",
                "trace_ref": "trace:date-effect",
                "task_ref": "task:date-effect",
                "round": 1,
                "query_text": "vigencia efecto jurídico fecha",
                "outcome": "hits",
                "hit_count": 1,
                "authority_refs": ["authority:law"],
                "unresolved_refs": [],
                "stop_reason": "questions_satisfied",
            }
        ],
        "authority_refs": ["authority:law"],
        "unresolved_refs": [],
        "research_context": {
            "corpus_snapshot_sha256": "a" * 64,
            "schema_migration_fingerprint": "schema-test-1",
            "retrieval_config_sha256": "b" * 64,
            "planner_version": "planner-test-1",
            "retrieval_version": "retrieval-test-1",
            "as_of_date": "2026-09-27",
            "unavailable_fields": [],
        },
        "generated_at": "2026-09-27T07:02:00Z",
    }


def v4_bundle() -> dict:
    return {
        "kind": "legal_research_bundle",
        "contract_version": "4.0.0",
        "bundle_ref": "bundle:issue134",
        "status": "complete",
        "case_input": v4_case_input(),
        "intake_draft": v4_intake_draft(),
        "research_plan": v4_research_plan(),
        "research_result": v4_research_result(),
        "sources": [
            {
                "kind": "official_source",
                "contract_version": "4.0.0",
                "source_ref": "source:dian",
                "authority": "DIAN",
                "source_uri": "https://example.invalid/official/authority",
                "source_kind": "official_publication",
                "title": "Fuente oficial de prueba",
            }
        ],
        "authorities": [
            {
                "kind": "canonical_authority",
                "contract_version": "4.0.0",
                "authority_ref": "authority:law",
                "document_ref": "document:law",
                "provision_refs": ["provision:article-1"],
                "display_name": "Documento jurídico de prueba",
                "document_type": "Ley",
                "issuer": "Congreso de Colombia",
                "jurisdiction_scope": "Colombia",
                "source_family": "official",
                "legal_function": "normative",
                "classification_state": "resolved",
                "temporal_state": {
                    "as_of_date": "2026-09-27",
                    "resolution_state": "resolved",
                    "effective": True,
                    "basis_evidence_refs": ["evidence:article-1"],
                },
                "evidence_refs": ["evidence:article-1"],
                "relationship_refs": [],
                "source_refs": ["source:dian"],
                "publication_metadata": {
                    "state": "resolved",
                    "publication_dates": ["2020-01-01"],
                    "promulgation_dates": [],
                    "publication_reference": "Diario Oficial de prueba",
                    "evidence_refs": ["evidence:article-1"],
                },
            }
        ],
        "evidence_spans": [
            {
                "kind": "evidence_span",
                "contract_version": "4.0.0",
                "evidence_ref": "evidence:article-1",
                "span_ref": "span:article-1",
                "authority_ref": "authority:law",
                "document_ref": "document:law",
                "provision_ref": "provision:article-1",
                "exact_text": "Artículo 1. Texto jurídico exacto de prueba.",
                "source_ref": "source:dian",
                "source_sha256": "c" * 64,
                "text_sha256": "d" * 64,
                "provenance_ref": "provenance:article-1",
                "anchor_version": "1",
                "retrieved_at": "2026-09-27T07:00:00Z",
            }
        ],
        "normative_relationships": [],
        "rule_fragments": [],
        "deterministic_evaluations": [],
        "calculation_traces": [],
        "unresolved": [],
        "generated_at": "2026-09-27T07:03:00Z",
    }


def v3_case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": "Hecho histórico v3.",
    }


def v3_case_draft() -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": "Hecho histórico v3.",
        "facts": [],
        "questions": [],
        "candidate_claims": [],
        "unresolved": [],
        "model_metadata": {
            "adapter": "fake-llm",
            "provider": "test",
            "model": "fixture-model",
            "schema_version": "3.0.0",
            "prompt_template_id": "case-structuring-v3",
            "prompt_template_version": "5",
            "run_reference": "run:v3-history",
            "generated_at": "2026-09-24T12:00:00Z",
            "routing_role": "primary",
        },
    }


def v3_case_result() -> dict:
    draft = v3_case_draft()
    return {
        "kind": "case_result",
        "contract_version": "3.0.0",
        "case_ref": "case:history",
        "analysis_status": "complete",
        "facts": deepcopy(draft["facts"]),
        "questions": deepcopy(draft["questions"]),
        "supported_claims": [],
        "remaining_candidate_claims": [],
        "unresolved": [],
        "evidence": [],
        "sources": [],
        "documents": [],
        "provisions": [],
        "model_metadata": deepcopy(draft["model_metadata"]),
        "generated_at": "2026-09-24T12:01:00Z",
    }


class Issue0134CaseV4ContractTests(unittest.TestCase):
    def test_valid_v4_intake_is_accepted(self):
        case_input = v4_case_input()
        draft = v4_intake_draft()
        validate_intake_draft(case_input, draft)
        self.assertEqual(validate_structured_intake(case_input, draft), "4.0.0")

    def test_v4_caller_owned_bytes_values_and_presence_are_fail_closed(self):
        case_input = v4_case_input()

        for mutation in ("problem_text", "as_of_date", "client_reference", "caller_metadata"):
            with self.subTest(mutation=mutation):
                draft = v4_intake_draft()
                if mutation == "problem_text":
                    draft[mutation] = draft[mutation].replace("\r\n", "\n")
                elif mutation == "caller_metadata":
                    draft[mutation]["attempt"] = 2
                else:
                    draft.pop(mutation)
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(case_input, draft)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_model_legal_conclusion_and_platform_objects_are_rejected(self):
        forbidden = {
            "candidate_claims": [],
            "legal_conclusion": "Debe aplicarse la norma X.",
            "research_plan": v4_research_plan(),
            "evidence_spans": [],
            "unresolved": [],
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                draft = v4_intake_draft()
                draft[field] = value
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(v4_case_input(), draft)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_model_search_vocabulary_cannot_inject_typed_canonical_ids(self):
        for ref in (
            "document:DOC-1",
            "provision:PROV-1",
            "evidence:EVD-1",
            "authority:AUTH-1",
            "source:SRC-1",
        ):
            with self.subTest(ref=ref):
                draft = v4_intake_draft()
                draft["search_hints"][0]["terms"] = [ref]
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(v4_case_input(), draft)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_model_fact_or_question_text_cannot_inject_platform_ids(self):
        mutations = [
            lambda draft: draft["facts"][0].update(value="document:DOC-1"),
            lambda draft: draft["facts"][1].update(
                needed_information="Consultar provision:PROV-1"
            ),
            lambda draft: draft["questions"][0].update(
                text="¿Qué dice evidence:EVD-1?"
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                draft = v4_intake_draft()
                mutate(draft)
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(v4_case_input(), draft)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_missing_and_ambiguous_fact_states_remain_explicit(self):
        case_input = v4_case_input()
        draft = v4_intake_draft()
        draft["facts"].append(
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:missing-document",
                "label": "Documento no aportado",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Aportar el documento faltante.",
            }
        )
        before = deepcopy(draft)
        validate_intake_draft(case_input, draft)
        self.assertEqual(draft, before)
        states = {item["state"] for item in draft["facts"]}
        self.assertIn("missing", states)
        self.assertIn("ambiguous", states)

    def test_exact_source_quote_fidelity_applies_to_normalized_facts_too(self):
        draft = v4_intake_draft()
        draft["facts"][0]["state"] = "llm_normalized"
        draft["facts"][0]["requires_confirmation"] = True
        draft["facts"][0]["source_quote"] = "Paráfrasis no presente."
        with self.assertRaises(CaseContractError) as raised:
            validate_intake_draft(v4_case_input(), draft)
        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_intake_typed_refs_are_semantically_enforced(self):
        mutations = [
            lambda draft: draft["questions"][0].update(
                depends_on_fact_refs=["fact:absent"]
            ),
            lambda draft: draft["search_hints"][0].update(
                related_question_refs=["question:absent"]
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                draft = v4_intake_draft()
                mutate(draft)
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(v4_case_input(), draft)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_open_legal_question_requires_platform_origin_research(self):
        plan = v4_research_plan()
        plan["tasks"][0]["origin"] = "intake_hint_expansion"
        with self.assertRaises(CaseContractError) as raised:
            validate_research_plan(
                v4_intake_draft(),
                plan,
                case_input=v4_case_input(),
            )
        self.assertEqual(raised.exception.code, INVALID_RESEARCH_PLAN)

    def test_research_fingerprint_null_availability_is_explicit(self):
        result = v4_research_result()
        result["research_context"]["corpus_snapshot_sha256"] = None
        with self.assertRaises(CaseContractError) as raised:
            validate_research_result(v4_research_plan(), result)
        self.assertEqual(raised.exception.code, INVALID_RESEARCH_RESULT)

        result["research_context"]["unavailable_fields"] = [
            "corpus_snapshot_sha256"
        ]
        validate_research_result(v4_research_plan(), result)

    def test_valid_v4_bundle_and_typed_graph_are_accepted(self):
        bundle = v4_bundle()
        validate_legal_research_bundle(bundle)
        self.assertEqual(validate_analysis_result(bundle), "4.0.0")

    def test_bundle_wrong_type_or_dangling_reference_fails_closed(self):
        bundle = v4_bundle()
        bundle["evidence_spans"][0]["source_ref"] = "source:absent"
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bundle)
        self.assertEqual(
            raised.exception.code,
            INVALID_LEGAL_RESEARCH_BUNDLE,
        )

        bundle = v4_bundle()
        bundle["evidence_spans"][0]["document_ref"] = "document:other"
        with self.assertRaises(CaseContractError):
            validate_legal_research_bundle(bundle)

    def test_unknown_rule_fragment_semantics_fail_closed_until_registered(self):
        bundle = v4_bundle()
        bundle["rule_fragments"] = [
            {
                "kind": "rule_fragment",
                "contract_version": "4.0.0",
                "rule_ref": "rule:unknown",
                "rule_type": "unregistered_rule",
                "rule_schema_version": "1",
                "structured_data": {"outcome": "model-authored"},
                "derivation": {
                    "method": "extractive_normalization",
                    "version": "1",
                },
                "authority_refs": ["authority:law"],
                "evidence_refs": ["evidence:article-1"],
            }
        ]
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bundle)
        self.assertEqual(
            raised.exception.code,
            INVALID_LEGAL_RESEARCH_BUNDLE,
        )

    def test_malformed_extra_and_non_scalar_caller_metadata_fail_closed(self):
        draft = v4_intake_draft()
        draft["model_metadata"]["legal_authority"] = True
        with self.assertRaises(CaseContractError) as raised:
            validate_intake_draft(v4_case_input(), draft)
        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

        case_input = v4_case_input()
        case_input["caller_metadata"]["not_scalar"] = ["hidden", "facts"]
        with self.assertRaises(CaseContractError):
            dispatch_case_input(case_input)

    def test_frozen_v3_intake_and_result_remain_interpretable(self):
        case_input = v3_case_input()
        draft = v3_case_draft()
        result = v3_case_result()
        validate_v3_case_draft(case_input, draft)
        self.assertEqual(dispatch_case_input(case_input), "3.0.0")
        self.assertEqual(validate_structured_intake(case_input, draft), "3.0.0")
        self.assertEqual(validate_analysis_result(result), "3.0.0")

    def test_v3_object_cannot_masquerade_as_v4_by_relabeling(self):
        case_input = v4_case_input()
        relabeled = v3_case_draft()
        relabeled["contract_version"] = "4.0.0"
        with self.assertRaises(CaseContractError) as raised:
            validate_structured_intake(case_input, relabeled)
        self.assertEqual(raised.exception.code, INVALID_CASE_CONTRACT_KIND)

    def test_unsupported_major_version_is_explicit(self):
        case_input = v4_case_input()
        case_input["contract_version"] = "5.0.0"
        with self.assertRaises(CaseContractError) as raised:
            dispatch_case_input(case_input)
        self.assertEqual(
            raised.exception.code,
            UNSUPPORTED_CASE_CONTRACT_VERSION,
        )

    def test_validation_never_mutates_raw_hash_or_provenance_fields(self):
        bundle = v4_bundle()
        before = deepcopy(bundle)
        validate_legal_research_bundle(bundle)
        validate_analysis_result(bundle)
        self.assertEqual(bundle, before)
        self.assertEqual(
            bundle["evidence_spans"][0]["source_sha256"],
            "c" * 64,
        )
        self.assertEqual(
            bundle["evidence_spans"][0]["provenance_ref"],
            "provenance:article-1",
        )


if __name__ == "__main__":
    unittest.main()
