from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_research import _treaty_topic_queries
from case_research_planning_v5 import (
    PLANNER_VERSION,
    ResearchPlanningError,
    build_research_plan_v5,
    load_planner_profile_set,
    planner_profile_set_from_data,
    research_context_fingerprint_v5,
    schedule_research_tasks,
)


GENERATED_AT = "2026-09-28T22:30:00Z"


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


def _hint(ref: str, question_ref: str, terms: list[str]) -> dict:
    return {
        "kind": "search_hint",
        "contract_version": "5.0.0",
        "hint_ref": ref,
        "terms": terms,
        "origin": "internal_intake_model",
        "related_question_refs": [question_ref],
    }


def _intake(
    problem: str,
    questions: list[dict],
    *,
    facts: list[dict] | None = None,
    hints: list[dict] | None = None,
    intake_ref: str = "intake:issue281",
) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "5.0.0",
        "intake_ref": intake_ref,
        "problem_text": problem,
        "facts": facts or [],
        "questions": questions,
        "search_hints": hints or [],
        "model_metadata": {
            "adapter": "deterministic-fixture",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "schema_version": "5.0.0",
            "prompt_template_id": "case-intake-v5",
            "prompt_template_version": "1",
            "run_reference": "run:issue281",
            "generated_at": GENERATED_AT,
            "routing_role": "intake_structuring",
            "structured_generation_mechanism": "fixture",
        },
    }


def _required_tasks(plan: dict) -> list[dict]:
    return [task for task in plan["tasks"] if task["required"]]


class Issue281CaseV5PlanningTests(unittest.TestCase):
    def test_simple_profile_creates_traceable_neutral_aspects(self):
        problem = "La sociedad pregunta por el régimen SIMPLE de tributación."
        intake = _intake(
            problem,
            [_question("question:simple", "¿Qué reglas del régimen SIMPLE deben investigarse?")],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )

        self.assertEqual(plan["planner_version"], PLANNER_VERSION)
        self.assertEqual(
            {aspect["profile_id"] for aspect in plan["aspects"]},
            {"tax.simple"},
        )
        self.assertEqual(
            [aspect["dimension_key"] for aspect in plan["aspects"]],
            [
                "subject_scope",
                "compliance_mechanics",
                "exclusions_and_changes",
                "case_specific_inputs",
            ],
        )
        self.assertTrue(all(aspect["required"] for aspect in plan["aspects"]))
        self.assertTrue(all(task["required"] for task in plan["tasks"]))
        self.assertTrue(
            all(task["origin"] == "platform_required" for task in plan["tasks"])
        )
        self.assertTrue(
            all(task["aspect_ref"].startswith("aspect:") for task in plan["tasks"])
        )

    def test_treaty_profile_generalizes_existing_bounded_topic_behavior(self):
        problem = (
            "Se requiere investigar un CDI entre Colombia y España para servicios "
            "y utilidades de una empresa."
        )
        intake = _intake(
            problem,
            [
                _question(
                    "question:treaty",
                    "¿Qué dimensiones del CDI deben revisarse sin caracterizar todavía la operación?",
                )
            ],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )

        aspects = {aspect["dimension_key"]: aspect for aspect in plan["aspects"]}
        self.assertIn("business_profits", aspects)
        self.assertIn("royalties_services", aspects)
        self.assertIn("permanent_establishment", aspects)

        queries = " ".join(
            task["target"]["query_text"]
            for task in _required_tasks(plan)
        ).casefold()
        self.assertIn("beneficios empresariales", queries)
        self.assertIn("cánones regalías", queries)
        self.assertIn("establecimiento permanente", queries)

        # Preservation: the frozen v4 #189 path remains unchanged while v5
        # generalizes the same neutral topic family into typed aspects.
        self.assertEqual(
            _treaty_topic_queries("convenio doble imposición tributaria"),
            [
                "beneficios empresariales",
                "cánones regalías",
                "establecimiento permanente",
            ],
        )

    def test_filing_profile_handles_unusual_wording(self):
        problem = "La persona pregunta por presentar renta y por los topes aplicables."
        intake = _intake(
            problem,
            [
                _question(
                    "question:filing",
                    "¿Quién debe presentar renta y qué topes deben revisarse?",
                )
            ],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )

        self.assertEqual(
            {aspect.get("profile_id") for aspect in plan["aspects"]},
            {"tax.filing-obligation"},
        )
        self.assertIn(
            "threshold_measurements",
            {aspect["dimension_key"] for aspect in plan["aspects"]},
        )

    def test_unknown_topic_gets_explicit_generic_limited_plan(self):
        problem = "Se consulta una servidumbre minera contractual atípica."
        intake = _intake(
            problem,
            [
                _question(
                    "question:unknown",
                    "¿Qué reglas jurídicas deben investigarse para esta servidumbre minera atípica?",
                )
            ],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )

        self.assertEqual(len(plan["aspects"]), 1)
        aspect = plan["aspects"][0]
        self.assertEqual(aspect["origin"], "generic_fallback")
        self.assertEqual(aspect["scope_status"], "generic_limited")
        self.assertEqual(aspect["decomposition_status"], "uncertain")
        self.assertEqual(plan["tasks"][0]["strategy"], "generic_fallback")

    def test_required_aspects_round_robin_before_misleading_hint(self):
        problem = (
            "Se pregunta por régimen SIMPLE y también por un CDI tributario. "
            "Una pista secundaria menciona ganadería bovina."
        )
        questions = [
            _question("question:q1", "¿Qué reglas del régimen SIMPLE deben investigarse?"),
            _question("question:q2", "¿Qué dimensiones del CDI tributario deben investigarse?"),
        ]
        intake = _intake(
            problem,
            questions,
            hints=[
                _hint(
                    "hint:misleading",
                    "question:q1",
                    ["ganadería bovina", "vacunación animal"],
                )
            ],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )

        required = _required_tasks(plan)
        self.assertGreaterEqual(len(required), 4)
        self.assertEqual(
            [task["question_ref"] for task in required[:4]],
            ["question:q1", "question:q2", "question:q1", "question:q2"],
        )

        first_optional = next(
            index for index, task in enumerate(plan["tasks"]) if not task["required"]
        )
        self.assertEqual(first_optional, len(required))
        self.assertEqual(
            plan["tasks"][first_optional]["hint_refs"],
            ["hint:misleading"],
        )

        without_hint = build_research_plan_v5(
            _case_input(problem),
            _intake(problem, questions),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(
            [task["task_ref"] for task in required],
            [task["task_ref"] for task in _required_tasks(without_hint)],
        )

    def test_scheduler_prevents_high_fanout_expansion_from_starving_required_work(self):
        def task(
            ref: str,
            question: str,
            aspect: str,
            *,
            required: bool,
            origin: str,
            depth: int = 0,
        ) -> dict:
            return {
                "task_ref": ref,
                "question_ref": question,
                "aspect_ref": aspect,
                "required": required,
                "origin": origin,
                "depth": depth,
            }

        scheduled = schedule_research_tasks(
            [
                task(
                    "task:q1a1",
                    "question:q1",
                    "aspect:q1a1",
                    required=True,
                    origin="platform_required",
                ),
                task(
                    "task:q1ref1",
                    "question:q1",
                    "aspect:q1a1",
                    required=False,
                    origin="reference_expansion",
                    depth=1,
                ),
                task(
                    "task:q1ref2",
                    "question:q1",
                    "aspect:q1a1",
                    required=False,
                    origin="reference_expansion",
                    depth=1,
                ),
                task(
                    "task:q1a2",
                    "question:q1",
                    "aspect:q1a2",
                    required=True,
                    origin="platform_required",
                ),
                task(
                    "task:q2a1",
                    "question:q2",
                    "aspect:q2a1",
                    required=True,
                    origin="platform_required",
                ),
                task(
                    "task:q1hint",
                    "question:q1",
                    "aspect:q1a1",
                    required=False,
                    origin="intake_hint_expansion",
                ),
            ]
        )

        self.assertEqual(
            [item["task_ref"] for item in scheduled[:3]],
            ["task:q1a1", "task:q2a1", "task:q1a2"],
        )
        expansion_positions = [
            index
            for index, item in enumerate(scheduled)
            if item["origin"] == "reference_expansion"
        ]
        self.assertTrue(all(index >= 3 for index in expansion_positions))

    def test_missing_fact_is_local_to_matching_dimensions_and_does_not_stop_research(self):
        problem = (
            "La persona consulta si debe presentar renta, pero no informó el valor "
            "de sus ingresos brutos."
        )
        missing = {
            "kind": "intake_fact",
            "contract_version": "5.0.0",
            "fact_ref": "fact:gross-income",
            "label": "Ingresos brutos",
            "semantic_key": "tax.gross_income",
            "state": "missing",
            "requires_confirmation": True,
            "needed_information": "Informar los ingresos brutos del período.",
        }
        intake = _intake(
            problem,
            [
                _question(
                    "question:filing",
                    "¿Quién debe presentar renta y qué topes deben revisarse?",
                )
            ],
            facts=[missing],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )
        by_dimension = {
            aspect["dimension_key"]: aspect for aspect in plan["aspects"]
        }

        self.assertEqual(by_dimension["subject_scope"]["fact_refs"], [])
        self.assertEqual(by_dimension["filing_mechanics"]["fact_refs"], [])
        self.assertEqual(
            by_dimension["threshold_measurements"]["fact_refs"],
            ["fact:gross-income"],
        )
        self.assertEqual(
            by_dimension["case_specific_inputs"]["fact_refs"],
            ["fact:gross-income"],
        )
        self.assertEqual(len(_required_tasks(plan)), len(plan["aspects"]))

        affected_tasks = [
            task
            for task in _required_tasks(plan)
            if task["aspect_ref"]
            in {
                by_dimension["threshold_measurements"]["aspect_ref"],
                by_dimension["case_specific_inputs"]["aspect_ref"],
            }
        ]
        self.assertTrue(affected_tasks)
        self.assertTrue(
            all("generated_from_fact_refs" not in task for task in affected_tasks)
        )

    def test_confirmed_fact_ref_is_preserved_when_it_contributes_to_query(self):
        problem = (
            "La persona reporta ingresos brutos de 100 y pregunta si debe presentar renta."
        )
        fact = {
            "kind": "intake_fact",
            "contract_version": "5.0.0",
            "fact_ref": "fact:gross-income",
            "label": "Ingresos brutos",
            "value": 100,
            "semantic_key": "tax.gross_income",
            "state": "user_provided",
            "source_quote": "ingresos brutos de 100",
            "requires_confirmation": False,
        }
        intake = _intake(
            problem,
            [_question("question:filing", "¿Debe presentar renta y qué topes aplican?")],
            facts=[fact],
        )
        plan = build_research_plan_v5(
            _case_input(problem),
            intake,
            generated_at=GENERATED_AT,
        )
        threshold = next(
            aspect
            for aspect in plan["aspects"]
            if aspect["dimension_key"] == "threshold_measurements"
        )
        task = next(
            item
            for item in _required_tasks(plan)
            if item["aspect_ref"] == threshold["aspect_ref"]
        )

        self.assertEqual(threshold["fact_refs"], ["fact:gross-income"])
        self.assertEqual(task["generated_from_fact_refs"], ["fact:gross-income"])
        self.assertIn("100", task["target"]["query_text"])

    def test_repeated_planning_and_context_fingerprint_are_stable(self):
        problem = "La sociedad pregunta por el régimen SIMPLE de tributación."
        intake = _intake(
            problem,
            [_question("question:simple", "¿Qué reglas del régimen SIMPLE deben investigarse?")],
        )
        case_input = _case_input(problem, as_of_date="2025-12-31")
        first = build_research_plan_v5(
            case_input,
            intake,
            generated_at=GENERATED_AT,
        )
        second = build_research_plan_v5(
            case_input,
            deepcopy(intake),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(first, second)

        context = research_context_fingerprint_v5(
            first,
            corpus_snapshot_sha256="a" * 64,
            schema_migration_fingerprint="schema-fixture",
            retrieval_config_sha256="b" * 64,
            retrieval_version="retrieval-fixture",
            coverage_policy_version="coverage-fixture",
            support_selection_version="support-fixture",
            graph_selection_version="graph-fixture",
        )
        self.assertEqual(context["planner_version"], first["planner_version"])
        self.assertEqual(
            context["profile_set_version"], first["profile_set_version"]
        )
        self.assertEqual(
            context["profile_set_sha256"], first["profile_set_sha256"]
        )
        self.assertEqual(context["as_of_date"], "2025-12-31")
        self.assertNotIn("as_of_date", context["unavailable_fields"])

    def test_material_profile_change_changes_policy_identity(self):
        profiles = load_planner_profile_set()
        changed_payload = deepcopy(profiles.payload)
        changed_payload["profiles"][0]["dimensions"][0]["query_terms"].append(
            "ámbito subjetivo del régimen"
        )
        changed_profiles = planner_profile_set_from_data(changed_payload)

        self.assertNotEqual(profiles.sha256, changed_profiles.sha256)

        problem = "La sociedad pregunta por el régimen SIMPLE de tributación."
        intake = _intake(
            problem,
            [_question("question:simple", "¿Qué reglas del régimen SIMPLE deben investigarse?")],
        )
        original = build_research_plan_v5(
            _case_input(problem),
            intake,
            profile_set=profiles,
            generated_at=GENERATED_AT,
        )
        changed = build_research_plan_v5(
            _case_input(problem),
            intake,
            profile_set=changed_profiles,
            generated_at=GENERATED_AT,
        )
        self.assertNotEqual(original["profile_set_sha256"], changed["profile_set_sha256"])
        self.assertNotEqual(original["plan_ref"], changed["plan_ref"])
        self.assertNotEqual(
            [item["aspect_ref"] for item in original["aspects"]],
            [item["aspect_ref"] for item in changed["aspects"]],
        )

    def test_profiles_reject_canonical_targets_and_numbered_norm_shortcuts(self):
        profiles = load_planner_profile_set()

        canonical = deepcopy(profiles.payload)
        canonical["profiles"][0]["dimensions"][0]["query_terms"] = [
            "document:manufactured"
        ]
        with self.assertRaises(ResearchPlanningError):
            planner_profile_set_from_data(canonical)

        numbered = deepcopy(profiles.payload)
        numbered["profiles"][0]["dimensions"][0]["query_terms"] = [
            "Ley 9999 de 2099"
        ]
        with self.assertRaises(ResearchPlanningError):
            planner_profile_set_from_data(numbered)


if __name__ == "__main__":
    unittest.main()
