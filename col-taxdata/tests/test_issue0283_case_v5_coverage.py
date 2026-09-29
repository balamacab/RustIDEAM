from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_research_coverage_v5 import (
    CoverageBuildError,
    build_research_result_v5,
    research_context_for_coverage_v5,
)
from case_research_planning_v5 import (
    build_research_plan_v5,
    planner_profile_set_from_data,
)


NOW = "2026-09-29T18:30:00Z"


def _case_input(problem: str, *, as_of_date: str | None = None) -> dict:
    value = {
        "kind": "case_input",
        "contract_version": "5.0.0",
        "problem_text": problem,
    }
    if as_of_date is not None:
        value["as_of_date"] = as_of_date
    return value


def _question(ref: str, text: str) -> dict:
    return {
        "kind": "case_question",
        "contract_version": "5.0.0",
        "question_ref": ref,
        "text": text,
        "category": "legal",
        "status": "open",
        "depends_on_fact_refs": [],
    }


def _intake(
    problem: str,
    questions: list[dict],
    *,
    facts: list[dict] | None = None,
    intake_ref: str = "intake:issue283",
) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "5.0.0",
        "intake_ref": intake_ref,
        "problem_text": problem,
        "facts": facts or [],
        "questions": questions,
        "search_hints": [],
        "model_metadata": {
            "adapter": "deterministic-fixture",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "schema_version": "5.0.0",
            "prompt_template_id": "case-intake-v5",
            "prompt_template_version": "1",
            "run_reference": "run:issue283",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
            "structured_generation_mechanism": "fixture",
        },
    }


def _profile(*dimensions: tuple[str, list[str], bool]) -> object:
    return planner_profile_set_from_data(
        {
            "profile_set_version": "issue283-fixture-1",
            "profiles": [
                {
                    "profile_id": "fixture.coverage",
                    "profile_version": "1",
                    "match": {
                        "any_phrases": ["coverage fixture"],
                        "all_token_groups": [],
                    },
                    "dimensions": [
                        {
                            "dimension_key": key,
                            "research_goal": f"Investigate {key} without deciding the legal outcome.",
                            "query_terms": [f"coverage fixture {key}"],
                            "fact_semantic_keys": fact_keys,
                            "uses_question_dependency_facts": use_dependencies,
                        }
                        for key, fact_keys, use_dependencies in dimensions
                    ],
                }
            ],
        }
    )


def _plan(
    dimensions: tuple[tuple[str, list[str], bool], ...],
    *,
    as_of_date: str | None = None,
    facts: list[dict] | None = None,
) -> tuple[dict, dict, dict]:
    problem = "Coverage fixture for deterministic aspect research."
    case_input = _case_input(problem, as_of_date=as_of_date)
    intake = _intake(
        problem,
        [_question("question:q1", "What support should the coverage fixture research?")],
        facts=facts,
    )
    plan = build_research_plan_v5(
        case_input,
        intake,
        profile_set=_profile(*dimensions),
        generated_at=NOW,
    )
    return case_input, intake, plan


def _context(plan: dict) -> dict:
    return research_context_for_coverage_v5(
        plan,
        corpus_snapshot_sha256=None,
        schema_migration_fingerprint=None,
        retrieval_config_sha256=None,
        retrieval_version="fixture-retrieval-1",
        graph_selection_version="pre-issue284",
    )


def _task_by_dimension(plan: dict) -> dict[str, dict]:
    aspects = {item["aspect_ref"]: item for item in plan["aspects"]}
    return {
        aspects[task["aspect_ref"]]["dimension_key"]: task
        for task in plan["tasks"]
        if task["required"]
    }


def _authority(token: str) -> dict:
    return {"authority_ref": f"authority:{token}"}


def _evidence(token: str, authority_ref: str) -> dict:
    return {
        "evidence_ref": f"evidence:{token}",
        "authority_ref": authority_ref,
    }


def _trace(
    task: dict,
    token: str,
    *,
    outcome: str = "hits",
    retrieved: list[str] | None = None,
    selected_authorities: list[str] | None = None,
    selected_evidence: list[str] | None = None,
    unresolved: list[str] | None = None,
) -> dict:
    retrieved = retrieved or []
    selected_authorities = selected_authorities or []
    selected_evidence = selected_evidence or []
    return {
        "kind": "research_trace_step",
        "contract_version": "5.0.0",
        "trace_ref": f"trace:{token}",
        "task_ref": task["task_ref"],
        "aspect_ref": task["aspect_ref"],
        "round": 1,
        "executed_target": deepcopy(task["target"]),
        "outcome": outcome,
        "hit_count": 1 if outcome == "hits" else 0,
        "retrieved_authority_refs": retrieved,
        "selected_authority_refs": selected_authorities,
        "selected_evidence_refs": selected_evidence,
        "unresolved_refs": unresolved or [],
    }


def _selection(
    task: dict,
    authority_ref: str,
    evidence_refs: list[str],
    *,
    context_status: str = "exact_sufficient",
    authority_status: str = "resolved",
    temporal_status: str = "unassessed",
    basis: str = "thematic_relevance",
) -> dict:
    return {
        "aspect_ref": task["aspect_ref"],
        "task_ref": task["task_ref"],
        "authority_ref": authority_ref,
        "evidence_refs": evidence_refs,
        "basis": basis,
        "context_status": context_status,
        "authority_status": authority_status,
        "temporal_status": temporal_status,
    }


def _coverage_by_dimension(plan: dict, result: dict) -> dict[str, dict]:
    aspects = {item["aspect_ref"]: item for item in plan["aspects"]}
    return {
        aspects[item["aspect_ref"]]["dimension_key"]: item
        for item in result["aspect_coverage"]
    }


class Issue0283CaseV5CoverageTests(unittest.TestCase):
    def test_complete_narrow_support_can_require_external_interpretive_synthesis(self):
        case_input, intake, plan = _plan(
            (("narrow_rule", [], False),),
        )
        task = _task_by_dimension(plan)["narrow_rule"]
        authority = _authority("narrow")
        evidence = _evidence("narrow", authority["authority_ref"])
        trace = _trace(
            task,
            "narrow",
            retrieved=[authority["authority_ref"]],
            selected_authorities=[authority["authority_ref"]],
            selected_evidence=[evidence["evidence_ref"]],
        )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                )
            ],
            authorities=[authority],
            evidence_spans=[evidence],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(coverage["support_closure"], "complete")
        self.assertEqual(
            coverage["synthesis_status"], "requires_interpretive_synthesis"
        )
        self.assertEqual(coverage["temporal_status"], "unassessed")
        self.assertIn("temporal_unassessed", coverage["limitation_codes"])

    def test_retrieved_hit_cannot_cover_an_unselected_aspect(self):
        case_input, intake, plan = _plan(
            (
                ("rule_scope", [], False),
                ("exception_scope", [], False),
            )
        )
        tasks = _task_by_dimension(plan)
        authority = _authority("shared-hit")
        evidence = _evidence("rule", authority["authority_ref"])
        trace = [
            _trace(
                tasks["rule_scope"],
                "rule",
                retrieved=[authority["authority_ref"]],
                selected_authorities=[authority["authority_ref"]],
                selected_evidence=[evidence["evidence_ref"]],
            ),
            _trace(
                tasks["exception_scope"],
                "exception",
                retrieved=[authority["authority_ref"]],
            ),
        ]

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=trace,
            selection_inputs=[
                _selection(
                    tasks["rule_scope"],
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                )
            ],
            authorities=[authority],
            evidence_spans=[evidence],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = _coverage_by_dimension(plan, result)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["rule_scope"]["support_closure"], "complete")
        self.assertEqual(
            coverage["exception_scope"]["evidence_status"], "candidate_only"
        )
        self.assertEqual(
            coverage["exception_scope"]["support_closure"], "incomplete"
        )
        self.assertEqual(coverage["exception_scope"]["selection_refs"], [])

    def test_context_incomplete_selection_is_visible_and_cannot_close(self):
        case_input, intake, plan = _plan(
            (("heading_context", [], False),),
        )
        task = _task_by_dimension(plan)["heading_context"]
        authority = _authority("heading")
        evidence = _evidence("heading", authority["authority_ref"])
        trace = _trace(
            task,
            "heading",
            retrieved=[authority["authority_ref"]],
            selected_authorities=[authority["authority_ref"]],
            selected_evidence=[evidence["evidence_ref"]],
        )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                    context_status="incomplete",
                )
            ],
            authorities=[authority],
            evidence_spans=[evidence],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["evidence_status"], "context_incomplete")
        self.assertEqual(coverage["support_closure"], "incomplete")
        self.assertIn("context_gap", coverage["limitation_codes"])
        self.assertTrue(
            any(
                item["reason"] == "context_unavailable"
                and item["class"] == "support"
                for item in result["omitted_work"]
            )
        )

    def test_generic_unknown_scope_stays_explicitly_partial_even_with_support(self):
        problem = "Investigate the zeta-xylophone tax topic with no known profile."
        case_input = _case_input(problem)
        intake = _intake(
            problem,
            [_question("question:unknown", "What law governs zeta-xylophone taxation?")],
            intake_ref="intake:unknown-283",
        )
        plan = build_research_plan_v5(case_input, intake, generated_at=NOW)
        task = next(item for item in plan["tasks"] if item["required"])
        authority = _authority("generic")
        evidence = _evidence("generic", authority["authority_ref"])
        trace = _trace(
            task,
            "generic",
            retrieved=[authority["authority_ref"]],
            selected_authorities=[authority["authority_ref"]],
            selected_evidence=[evidence["evidence_ref"]],
        )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                )
            ],
            authorities=[authority],
            evidence_spans=[evidence],
            unresolved=[],
            facts=[],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["support_closure"], "unsupported_scope")
        self.assertIn("generic_scope", coverage["limitation_codes"])
        self.assertTrue(
            any(
                item["reason"] == "unsupported_scope" and item["required"]
                for item in result["omitted_work"]
            )
        )

    def test_missing_personal_fact_blocks_only_affected_aspects(self):
        problem = (
            "La persona consulta si debe presentar renta, pero falta el dato de "
            "ingresos brutos necesario para evaluar los topes."
        )
        missing_fact = {
            "kind": "intake_fact",
            "contract_version": "5.0.0",
            "fact_ref": "fact:gross-income",
            "label": "Ingresos brutos",
            "semantic_key": "tax.gross_income",
            "state": "missing",
            "requires_confirmation": True,
            "needed_information": "Informar los ingresos brutos del período.",
        }
        case_input = _case_input(problem, as_of_date="2025-12-31")
        intake = _intake(
            problem,
            [_question("question:filing", "¿Quién debe presentar renta y qué topes aplican?")],
            facts=[missing_fact],
            intake_ref="intake:filing-283",
        )
        plan = build_research_plan_v5(case_input, intake, generated_at=NOW)
        tasks = _task_by_dimension(plan)

        authorities: list[dict] = []
        evidence_spans: list[dict] = []
        trace: list[dict] = []
        selections: list[dict] = []
        affected = {"threshold_measurements", "case_specific_inputs"}
        for dimension, task in tasks.items():
            if dimension in affected:
                trace.append(
                    _trace(
                        task,
                        f"blocked-{dimension}",
                        outcome="blocked",
                    )
                )
                continue
            authority = _authority(dimension)
            evidence = _evidence(dimension, authority["authority_ref"])
            authorities.append(authority)
            evidence_spans.append(evidence)
            trace.append(
                _trace(
                    task,
                    dimension,
                    retrieved=[authority["authority_ref"]],
                    selected_authorities=[authority["authority_ref"]],
                    selected_evidence=[evidence["evidence_ref"]],
                )
            )
            selections.append(
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                    temporal_status="effective_as_of",
                )
            )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=trace,
            selection_inputs=selections,
            authorities=authorities,
            evidence_spans=evidence_spans,
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = _coverage_by_dimension(plan, result)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["subject_scope"]["support_closure"], "complete")
        self.assertEqual(coverage["filing_mechanics"]["support_closure"], "complete")
        for dimension in affected:
            self.assertEqual(coverage[dimension]["execution_status"], "blocked")
            self.assertEqual(coverage[dimension]["fact_status"], "missing")
            self.assertEqual(
                coverage[dimension]["synthesis_status"], "requires_facts"
            )
            self.assertEqual(coverage[dimension]["support_closure"], "incomplete")
            self.assertIn("missing_facts", coverage[dimension]["limitation_codes"])

    def test_conflicting_temporal_support_is_not_silently_current(self):
        case_input, intake, plan = _plan(
            (("temporal_rule", [], False),),
            as_of_date="2025-12-31",
        )
        task = _task_by_dimension(plan)["temporal_rule"]
        current = _authority("current")
        conflict = _authority("conflict")
        current_ev = _evidence("current", current["authority_ref"])
        conflict_ev = _evidence("conflict", conflict["authority_ref"])
        trace = _trace(
            task,
            "temporal",
            retrieved=[current["authority_ref"], conflict["authority_ref"]],
            selected_authorities=[current["authority_ref"], conflict["authority_ref"]],
            selected_evidence=[current_ev["evidence_ref"], conflict_ev["evidence_ref"]],
        )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[
                _selection(
                    task,
                    current["authority_ref"],
                    [current_ev["evidence_ref"]],
                    temporal_status="effective_as_of",
                ),
                _selection(
                    task,
                    conflict["authority_ref"],
                    [conflict_ev["evidence_ref"]],
                    authority_status="conflicting",
                    temporal_status="ambiguous",
                    basis="conflict_dependency",
                ),
            ],
            authorities=[current, conflict],
            evidence_spans=[current_ev, conflict_ev],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["authority_status"], "conflicting")
        self.assertEqual(coverage["temporal_status"], "ambiguous")
        self.assertEqual(coverage["support_closure"], "incomplete")
        self.assertIn("authority_conflict", coverage["limitation_codes"])

    def test_non_effective_support_cannot_close_for_requested_date(self):
        case_input, intake, plan = _plan(
            (("dated_rule", [], False),),
            as_of_date="2025-12-31",
        )
        task = _task_by_dimension(plan)["dated_rule"]
        authority = _authority("expired")
        evidence = _evidence("expired", authority["authority_ref"])
        trace = _trace(
            task,
            "expired",
            retrieved=[authority["authority_ref"]],
            selected_authorities=[authority["authority_ref"]],
            selected_evidence=[evidence["evidence_ref"]],
        )

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"]],
                    temporal_status="not_effective_as_of",
                )
            ],
            authorities=[authority],
            evidence_spans=[evidence],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(coverage["temporal_status"], "assessed")
        self.assertEqual(coverage["support_closure"], "incomplete")
        self.assertEqual(result["status"], "partial")

    def test_required_budget_exhaustion_never_produces_complete(self):
        case_input, intake, plan = _plan(
            (("budgeted_rule", [], False),),
        )
        task = _task_by_dimension(plan)["budgeted_rule"]
        trace = _trace(task, "budget", outcome="budget_exhausted")

        result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[],
            authorities=[],
            evidence_spans=[],
            unresolved=[],
            facts=intake["facts"],
            research_context=_context(plan),
            generated_at=NOW,
        )

        coverage = result["aspect_coverage"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(coverage["execution_status"], "budget_exhausted")
        self.assertEqual(coverage["support_closure"], "incomplete")
        self.assertIn("budget_exhausted", coverage["limitation_codes"])
        self.assertTrue(
            any(item["reason"] == "budget_exhausted" for item in result["omitted_work"])
        )

    def test_deduplicated_final_registry_preserves_refs_and_repeatability(self):
        case_input, intake, plan = _plan(
            (("dedup_rule", [], False),),
        )
        task = _task_by_dimension(plan)["dedup_rule"]
        authority = _authority("dedup")
        evidence = _evidence("dedup", authority["authority_ref"])
        graph_only = _authority("graph-endpoint")
        trace = _trace(
            task,
            "dedup",
            retrieved=[authority["authority_ref"]],
            selected_authorities=[authority["authority_ref"]],
            selected_evidence=[evidence["evidence_ref"]],
        )
        kwargs = {
            "case_input": case_input,
            "trace": [trace],
            "selection_inputs": [
                _selection(
                    task,
                    authority["authority_ref"],
                    [evidence["evidence_ref"], evidence["evidence_ref"]],
                )
            ],
            "authorities": [authority, graph_only],
            "evidence_spans": [evidence],
            "unresolved": [],
            "facts": intake["facts"],
            "research_context": _context(plan),
            "generated_at": NOW,
        }

        first = build_research_result_v5(plan, **kwargs)
        second = build_research_result_v5(plan, **kwargs)

        self.assertEqual(first, second)
        self.assertEqual(
            first["evidence_selections"][0]["evidence_refs"],
            [evidence["evidence_ref"]],
        )
        self.assertNotIn(graph_only["authority_ref"], first["authority_refs"])

        bad = deepcopy(kwargs)
        bad["selection_inputs"] = [
            _selection(
                task,
                authority["authority_ref"],
                ["evidence:missing-after-dedup"],
            )
        ]
        with self.assertRaises(CoverageBuildError):
            build_research_result_v5(plan, **bad)


if __name__ == "__main__":
    unittest.main()
