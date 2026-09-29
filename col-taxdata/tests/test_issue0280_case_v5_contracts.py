from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_dispatch import (
    validate_analysis_result,
    validate_case_input as dispatch_case_input,
    validate_structured_intake,
)
from case_contract_validation import CaseContractError
from case_contract_validation_v5 import (
    INVALID_INTAKE_DRAFT,
    V5_COMPLETE_001,
    V5_CONSUMER_001,
    V5_CONTEXT_001,
    V5_EVALUATOR_001,
    V5_FACT_001,
    V5_ID_001,
    V5_OMISSION_001,
    V5_REF_ASPECT_001,
    V5_REF_COVERAGE_003,
    V5_REF_SELECTION_002,
    V5_SCOPE_001,
    V5_TEMPORAL_001,
    validate_contract_object,
    validate_intake_draft,
    validate_legal_research_bundle,
    validate_research_continuation_request,
    validate_research_plan,
)


EXAMPLES = (
    ROOT
    / "specs"
    / "application"
    / "examples"
    / "case-v5"
    / "research-coverage-examples.json"
)

PROBLEM = "El cliente solicita investigar la regla tributaria aplicable."
PROFILE_SHA = "e" * 64


def _case_input(as_of_date: str | None) -> dict:
    value = {
        "kind": "case_input",
        "contract_version": "5.0.0",
        "problem_text": PROBLEM,
    }
    if as_of_date is not None:
        value["as_of_date"] = as_of_date
    return value


def _intake(as_of_date: str | None, *, missing_personal_fact: bool = False) -> dict:
    facts = []
    if missing_personal_fact:
        facts.append(
            {
                "kind": "intake_fact",
                "contract_version": "5.0.0",
                "fact_ref": "fact:personal",
                "label": "Dato personal para evaluación",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Aportar el dato personal faltante.",
            }
        )
    value = {
        "kind": "intake_draft",
        "contract_version": "5.0.0",
        "intake_ref": "intake:issue280",
        "problem_text": PROBLEM,
        "facts": facts,
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "5.0.0",
                "question_ref": "question:q1",
                "text": "¿Qué regla tributaria resulta relevante?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": [],
            }
        ],
        "search_hints": [],
        "model_metadata": {
            "adapter": "deterministic-fixture",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "schema_version": "5.0.0",
            "prompt_template_id": "case-intake-v5",
            "prompt_template_version": "1",
            "run_reference": "run:issue280",
            "generated_at": "2026-09-28T21:00:00Z",
            "routing_role": "intake_structuring",
            "structured_generation_mechanism": "fixture",
        },
    }
    if as_of_date is not None:
        value["as_of_date"] = as_of_date
    return value


def _source() -> dict:
    return {
        "kind": "official_source",
        "contract_version": "5.0.0",
        "source_ref": "source:fixture",
        "authority": "Autoridad oficial de prueba",
        "source_uri": "https://example.invalid/official",
        "source_kind": "official_publication",
        "title": "Fuente oficial de prueba",
    }


def _authority(ref: str, evidence_refs: list[str]) -> dict:
    suffix = ref.split(":", 1)[1]
    return {
        "kind": "canonical_authority",
        "contract_version": "5.0.0",
        "authority_ref": ref,
        "document_ref": f"document:{suffix}",
        "provision_refs": [f"provision:{suffix}"],
        "display_name": f"Autoridad {suffix}",
        "document_type": "Ley",
        "issuer": "Congreso de Colombia",
        "jurisdiction_scope": "Colombia",
        "source_family": "official",
        "legal_function": "normative",
        "classification_state": "resolved",
        "temporal_state": {
            "resolution_state": "resolved",
            "effective": True,
            "basis_evidence_refs": list(evidence_refs),
        },
        "evidence_refs": list(evidence_refs),
        "relationship_refs": [],
        "source_refs": ["source:fixture"],
        "publication_metadata": {
            "state": "resolved",
            "publication_dates": ["2020-01-01"],
            "promulgation_dates": [],
            "publication_reference": "Diario Oficial de prueba",
            "evidence_refs": list(evidence_refs),
        },
    }


def _evidence(ref: str, authority_ref: str) -> dict:
    suffix = authority_ref.split(":", 1)[1]
    return {
        "kind": "evidence_span",
        "contract_version": "5.0.0",
        "evidence_ref": ref,
        "span_ref": f"span:{ref.split(':', 1)[1]}",
        "authority_ref": authority_ref,
        "document_ref": f"document:{suffix}",
        "provision_ref": f"provision:{suffix}",
        "exact_text": "Artículo de prueba con texto jurídico exacto.",
        "source_ref": "source:fixture",
        "source_sha256": "a" * 64,
        "text_sha256": "b" * 64,
        "provenance_ref": f"provenance:{ref.split(':', 1)[1]}",
        "anchor_version": "1",
        "retrieved_at": "2026-09-28T21:00:00Z",
    }


def _materialize_scenario(scenario: dict) -> dict:
    """Inflate the accepted #279 semantic vector into a full v5 bundle fixture."""
    as_of_date = scenario["case_as_of_date"]
    is_missing_personal = scenario["id"] == "mixed-missing-personalization-fact"
    intake = _intake(as_of_date, missing_personal_fact=is_missing_personal)

    aspects = []
    for index, item in enumerate(scenario["plan"]["aspects"]):
        aspect = {
            "kind": "research_aspect",
            "contract_version": "5.0.0",
            **deepcopy(item),
            "dimension_key": item["aspect_ref"].split(":", 1)[1],
            "research_goal": "Localizar y contextualizar evidencia jurídica relevante.",
            "fact_refs": [],
            "sequence": index,
            "decomposition_status": "certain",
        }
        if item["origin"] == "profile":
            aspect["profile_id"] = "profile:test"
            aspect["profile_version"] = "1"
        if item["aspect_ref"] == "aspect:personal-threshold-evaluation":
            aspect["fact_refs"] = ["fact:personal"]
        aspects.append(aspect)

    tasks = []
    for index, item in enumerate(scenario["plan"]["tasks"]):
        tasks.append(
            {
                "kind": "research_task",
                "contract_version": "5.0.0",
                **deepcopy(item),
                "origin": "platform_required",
                "purpose": "primary_research",
                "strategy": "thematic_search",
                "target": {
                    "kind": "query",
                    "query_text": f"consulta de prueba {index}",
                },
                "depth": 0,
                "sequence": index,
            }
        )

    plan = {
        "kind": "research_plan",
        "contract_version": "5.0.0",
        "plan_ref": "plan:issue280",
        "intake_ref": intake["intake_ref"],
        "aspects": aspects,
        "tasks": tasks,
        "budgets": {
            "research": {
                "max_rounds": 2,
                "max_tasks": max(4, len(tasks)),
                "max_queries_per_aspect": 3,
                "max_hits_per_query": 10,
                "max_reference_depth": 2,
                "max_total_authorities": max(
                    10, len(scenario["authority_registry"])
                ),
            },
            "support": {
                "max_selected_evidence_per_aspect": 8,
                "max_context_expansions_per_aspect": 4,
                "max_relationships_per_aspect": 4,
                "max_total_evidence_spans": max(
                    16, len(scenario["evidence_registry"])
                ),
            },
        },
        "fairness_policy": {
            "policy": "required_aspects_round_robin",
            "max_consecutive_optional_tasks": 0,
        },
        "stop_conditions": ["required_support_closure", "bounds_exhausted"],
        "planner_version": "planner-v5-test-1",
        "profile_set_version": "profiles-v5-test-1",
        "profile_set_sha256": PROFILE_SHA,
        "generated_at": "2026-09-28T21:01:00Z",
    }
    if as_of_date is not None:
        plan["as_of_date"] = as_of_date

    selections = []
    for item in scenario["result"]["selections"]:
        selections.append(
            {
                "kind": "evidence_selection",
                "contract_version": "5.0.0",
                **deepcopy(item),
                "basis": "thematic_relevance",
            }
        )

    omissions = []
    for item in scenario["result"]["omissions"]:
        omissions.append(
            {
                "kind": "omitted_work",
                "contract_version": "5.0.0",
                **deepcopy(item),
                "description": "Trabajo pendiente declarado por el escenario.",
            }
        )

    unresolved = []
    if is_missing_personal:
        unresolved.append(
            {
                "kind": "unresolved_item",
                "contract_version": "5.0.0",
                "unresolved_ref": "unresolved:personal-fact",
                "stage": "coverage",
                "category": "missing_fact",
                "description": "Falta un dato para la evaluación personalizada.",
                "related_fact_refs": ["fact:personal"],
                "related_question_refs": ["question:q1"],
                "related_aspect_refs": [
                    "aspect:personal-threshold-evaluation"
                ],
                "related_task_refs": ["task:personal-eval"],
                "next_action": "ask_client",
            }
        )

    coverage = []
    for item in scenario["result"]["coverage"]:
        value = {
            "kind": "aspect_coverage",
            "contract_version": "5.0.0",
            **deepcopy(item),
            "unresolved_refs": [],
        }
        if (
            is_missing_personal
            and item["aspect_ref"]
            == "aspect:personal-threshold-evaluation"
        ):
            value["unresolved_refs"] = ["unresolved:personal-fact"]
        coverage.append(value)

    selections_by_task: dict[str, list[dict]] = {}
    for selection in selections:
        selections_by_task.setdefault(
            selection["task_ref"], []
        ).append(selection)
    trace = []
    for index, task in enumerate(tasks):
        task_selections = selections_by_task.get(task["task_ref"], [])
        authority_refs = sorted(
            {x["authority_ref"] for x in task_selections}
        )
        evidence_refs = sorted(
            {
                ref
                for x in task_selections
                for ref in x["evidence_refs"]
            }
        )
        trace.append(
            {
                "kind": "research_trace_step",
                "contract_version": "5.0.0",
                "trace_ref": f"trace:{index}",
                "task_ref": task["task_ref"],
                "aspect_ref": task["aspect_ref"],
                "round": 1,
                "executed_target": deepcopy(task["target"]),
                "outcome": "hits" if authority_refs else "no_hits",
                "hit_count": len(authority_refs),
                "retrieved_authority_refs": authority_refs,
                "selected_authority_refs": authority_refs,
                "selected_evidence_refs": evidence_refs,
                "unresolved_refs": [],
            }
        )

    result = {
        "kind": "research_result",
        "contract_version": "5.0.0",
        "result_ref": "research:issue280",
        "plan_ref": plan["plan_ref"],
        "status": scenario["result"]["status"],
        "trace": trace,
        "authority_refs": deepcopy(scenario["authority_registry"]),
        "evidence_selections": selections,
        "aspect_coverage": coverage,
        "omitted_work": omissions,
        "unresolved_refs": [
            item["unresolved_ref"] for item in unresolved
        ],
        "research_context": {
            "corpus_snapshot_sha256": "c" * 64,
            "schema_migration_fingerprint": "schema-test-1",
            "retrieval_config_sha256": "d" * 64,
            "planner_version": plan["planner_version"],
            "retrieval_version": "retrieval-test-1",
            "profile_set_version": plan["profile_set_version"],
            "profile_set_sha256": plan["profile_set_sha256"],
            "coverage_policy_version": "coverage-test-1",
            "support_selection_version": "support-test-1",
            "graph_selection_version": "graph-test-1",
            "as_of_date": as_of_date,
            "unavailable_fields": (
                [] if as_of_date is not None else ["as_of_date"]
            ),
        },
        "generated_at": "2026-09-28T21:02:00Z",
    }

    evidence_owner: dict[str, str] = {}
    for selection in selections:
        for ref in selection["evidence_refs"]:
            if ref in scenario["evidence_registry"]:
                evidence_owner[ref] = selection["authority_ref"]

    authorities = []
    for authority_ref in scenario["authority_registry"]:
        owned = sorted(
            ref
            for ref, owner in evidence_owner.items()
            if owner == authority_ref
        )
        authorities.append(_authority(authority_ref, owned))

    evidence_spans = [
        _evidence(ref, evidence_owner[ref])
        for ref in scenario["evidence_registry"]
        if ref in evidence_owner
    ]

    return {
        "kind": "legal_research_bundle",
        "contract_version": "5.0.0",
        "bundle_ref": "bundle:issue280",
        "status": result["status"],
        "case_input": _case_input(as_of_date),
        "intake_draft": intake,
        "research_plan": plan,
        "research_result": result,
        "sources": [_source()],
        "authorities": authorities,
        "evidence_spans": evidence_spans,
        "normative_relationships": [],
        "rule_fragments": [],
        "deterministic_evaluations": [],
        "calculation_traces": [],
        "unresolved": unresolved,
        "generated_at": "2026-09-28T21:03:00Z",
    }


def _scenario(examples: dict, scenario_id: str) -> dict:
    return next(
        item
        for item in examples["scenarios"]
        if item["id"] == scenario_id
    )


class Issue0280CaseV5ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))

    def test_accepted_v5_examples_validate_with_runtime_semantics(self) -> None:
        for scenario in self.examples["scenarios"]:
            if not scenario["expected_valid"]:
                continue
            with self.subTest(scenario=scenario["id"]):
                bundle = _materialize_scenario(scenario)
                validate_legal_research_bundle(bundle)
                self.assertEqual(
                    validate_analysis_result(bundle),
                    "5.0.0",
                )

    def test_negative_contract_examples_fail_with_declared_stable_code(self) -> None:
        for scenario in self.examples["scenarios"]:
            if scenario["expected_valid"]:
                continue
            with self.subTest(scenario=scenario["id"]):
                bundle = _materialize_scenario(scenario)
                with self.assertRaises(CaseContractError) as raised:
                    validate_legal_research_bundle(bundle)
                self.assertIn(
                    raised.exception.code,
                    set(scenario["expected_error_codes"]),
                )

    def test_duplicate_and_dangling_refs_fail_closed_by_typed_registry(self) -> None:
        base = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )

        duplicate = deepcopy(base)
        duplicate["research_result"]["evidence_selections"].append(
            deepcopy(
                duplicate["research_result"]["evidence_selections"][0]
            )
        )
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(duplicate)
        self.assertEqual(
            raised.exception.code,
            V5_REF_SELECTION_002,
        )

        dangling = deepcopy(base)
        dangling["research_result"]["aspect_coverage"][0][
            "selection_refs"
        ] = ["selection:missing"]
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(dangling)
        self.assertEqual(
            raised.exception.code,
            V5_REF_COVERAGE_003,
        )

    def test_unsupported_complete_status_combinations_fail_with_specific_codes(self) -> None:
        base = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )

        partial_execution = deepcopy(base)
        partial_execution["research_result"]["aspect_coverage"][0][
            "execution_status"
        ] = "partial"
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(partial_execution)
        self.assertEqual(raised.exception.code, V5_COMPLETE_001)

        required_omission = deepcopy(base)
        omission = {
            "kind": "omitted_work",
            "contract_version": "5.0.0",
            "omission_ref": "omission:required",
            "aspect_ref": "aspect:narrow-rule",
            "task_ref": "task:narrow-rule",
            "class": "support",
            "reason": "context_unavailable",
            "required": True,
            "description": "Falta contexto requerido.",
        }
        required_omission["research_result"]["omitted_work"] = [omission]
        required_omission["research_result"]["aspect_coverage"][0][
            "omission_refs"
        ] = [omission["omission_ref"]]
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(required_omission)
        self.assertEqual(raised.exception.code, V5_OMISSION_001)

    def test_context_and_scope_cannot_masquerade_as_complete_support(self) -> None:
        context = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        context["research_result"]["evidence_selections"][0][
            "context_status"
        ] = "incomplete"
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(context)
        self.assertEqual(raised.exception.code, V5_CONTEXT_001)

        generic = _materialize_scenario(
            _scenario(self.examples, "invalid-complete-generic-scope")
        )
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(generic)
        self.assertEqual(raised.exception.code, V5_SCOPE_001)

    def test_no_evaluator_is_required_for_complete_evidence_handoff(self) -> None:
        bundle = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        self.assertEqual(bundle["deterministic_evaluations"], [])
        coverage = bundle["research_result"]["aspect_coverage"][0]
        self.assertEqual(coverage["support_closure"], "complete")
        self.assertEqual(
            coverage["synthesis_status"],
            "requires_interpretive_synthesis",
        )
        validate_legal_research_bundle(bundle)

        false_completed = deepcopy(bundle)
        false_completed["research_result"]["aspect_coverage"][0][
            "synthesis_status"
        ] = "deterministic_completed"
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(false_completed)
        self.assertEqual(raised.exception.code, V5_EVALUATOR_001)

    def test_model_owned_intake_cannot_inject_v5_platform_ids_or_coverage(self) -> None:
        case_input = _case_input(None)
        for injected in (
            "aspect:forced",
            "selection:forced",
            "coverage:forced",
            "omission:forced",
            "continuation:forced",
        ):
            with self.subTest(injected=injected):
                draft = _intake(None)
                draft["questions"][0]["text"] = f"¿Qué dice {injected}?"
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(case_input, draft)
                self.assertEqual(
                    raised.exception.code,
                    INVALID_INTAKE_DRAFT,
                )

    def test_version_dispatch_preserves_v4_and_rejects_cross_major_masquerade(self) -> None:
        v4_input = {
            "kind": "case_input",
            "contract_version": "4.0.0",
            "problem_text": "Objeto histórico v4.",
        }
        self.assertEqual(dispatch_case_input(v4_input), "4.0.0")

        v5_input = _case_input(None)
        v5_intake = _intake(None)
        self.assertEqual(
            validate_structured_intake(v5_input, v5_intake),
            "5.0.0",
        )

        relabeled = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        relabeled["contract_version"] = "4.0.0"
        with self.assertRaises(CaseContractError):
            validate_analysis_result(relabeled)

    def test_fingerprint_and_temporal_identity_are_fail_closed(self) -> None:
        base = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        bad_profile = deepcopy(base)
        bad_profile["research_result"]["research_context"][
            "profile_set_sha256"
        ] = "f" * 64
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bad_profile)
        self.assertEqual(raised.exception.code, V5_ID_001)

        dated = _materialize_scenario(
            _scenario(
                self.examples,
                "ambiguous-mixed-temporal-support",
            )
        )
        dated["research_result"]["research_context"][
            "as_of_date"
        ] = "2020-07-01"
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(dated)
        self.assertEqual(raised.exception.code, V5_TEMPORAL_001)

    def test_missing_fact_must_be_owned_by_the_affected_aspect(self) -> None:
        bundle = _materialize_scenario(
            _scenario(
                self.examples,
                "mixed-missing-personalization-fact",
            )
        )
        personal = next(
            item
            for item in bundle["research_plan"]["aspects"]
            if item["aspect_ref"]
            == "aspect:personal-threshold-evaluation"
        )
        personal["fact_refs"] = []
        with self.assertRaises(CaseContractError) as raised:
            validate_legal_research_bundle(bundle)
        self.assertEqual(raised.exception.code, V5_FACT_001)

    def test_continuation_request_is_noncanonical_and_refs_known_bundle_material(self) -> None:
        bundle = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        request = {
            "kind": "research_continuation_request",
            "contract_version": "5.0.0",
            "continuation_ref": "continuation:issue280",
            "bundle_ref": bundle["bundle_ref"],
            "question_ref": "question:q1",
            "aspect_ref": "aspect:narrow-rule",
            "request_kind": "expand_aspect",
            "requested_focus": (
                "Profundizar contexto sin proponer conclusión jurídica."
            ),
            "known_authority_refs": ["authority:narrow-1"],
            "known_evidence_refs": ["evidence:narrow-1"],
        }
        before = deepcopy(request)
        validate_research_continuation_request(
            request,
            bundle=bundle,
        )
        self.assertEqual(request, before)

        bad = deepcopy(request)
        bad["known_evidence_refs"] = ["evidence:missing"]
        with self.assertRaises(CaseContractError) as raised:
            validate_research_continuation_request(
                bad,
                bundle=bundle,
            )
        self.assertEqual(raised.exception.code, V5_CONSUMER_001)

    def test_validators_are_read_only_for_hashes_refs_and_fingerprints(self) -> None:
        bundle = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        before = deepcopy(bundle)
        validate_legal_research_bundle(bundle)
        self.assertEqual(validate_analysis_result(bundle), "5.0.0")
        self.assertEqual(bundle, before)
        self.assertEqual(
            bundle["evidence_spans"][0]["source_sha256"],
            "a" * 64,
        )
        self.assertEqual(
            bundle["research_result"]["research_context"][
                "profile_set_sha256"
            ],
            PROFILE_SHA,
        )

    def test_individual_v5_primitives_use_the_accepted_closed_schema(self) -> None:
        bundle = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        validate_contract_object(
            bundle["research_plan"]["aspects"][0]
        )
        validate_contract_object(
            bundle["research_result"]["evidence_selections"][0]
        )
        validate_contract_object(
            bundle["research_result"]["aspect_coverage"][0]
        )

        aspect = deepcopy(bundle["research_plan"]["aspects"][0])
        aspect["unexpected"] = "not allowed"
        with self.assertRaises(CaseContractError):
            validate_contract_object(aspect)

    def test_plan_question_aspect_task_ownership_is_explicit(self) -> None:
        bundle = _materialize_scenario(
            _scenario(self.examples, "narrow-finite-no-evaluator")
        )
        plan = deepcopy(bundle["research_plan"])
        plan["tasks"][0]["aspect_ref"] = "aspect:missing"
        with self.assertRaises(CaseContractError) as raised:
            validate_research_plan(
                bundle["intake_draft"],
                plan,
            )
        self.assertEqual(raised.exception.code, V5_REF_ASPECT_001)


if __name__ == "__main__":
    unittest.main()
