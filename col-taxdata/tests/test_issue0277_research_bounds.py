from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import (
    validate_contract_object,
    validate_research_result,
)
from case_research import PlatformResearchService
from test_issue0137_evidence_first_research import (
    GENERAL_RULE,
    Issue0137EvidenceFirstResearchTests,
    NOW,
    REFERENCE_RULE,
    case_input,
    intake,
)


class Issue0277ResearchBoundsTests(unittest.TestCase):
    # Reuse only the fixture helpers, not the base class, so #137's complete
    # test suite is not duplicated by unittest inheritance.
    setUp = Issue0137EvidenceFirstResearchTests.setUp
    tearDown = Issue0137EvidenceFirstResearchTests.tearDown
    add_document_with_segment = (
        Issue0137EvidenceFirstResearchTests.add_document_with_segment
    )
    add_resolved_reference = Issue0137EvidenceFirstResearchTests.add_resolved_reference

    @staticmethod
    def no_as_of_case() -> dict:
        value = deepcopy(case_input())
        value.pop("as_of_date", None)
        return value

    @staticmethod
    def no_as_of_intake(*, hints: list[dict] | None = None) -> dict:
        value = deepcopy(intake(hints=hints))
        value.pop("as_of_date", None)
        return value

    def add_second_segment(
        self,
        document: dict[str, str],
        *,
        token: str,
        text: str,
    ) -> str:
        segment_id = f"SEG-{token}"
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO extracted_segments(
                    extracted_segment_id, extraction_id, sequence_no,
                    segment_type, section_path, char_start, char_end,
                    text, text_sha256
                ) VALUES (?, ?, 2, 'paragraph', NULL, 0, ?, ?, ?)
                """,
                (
                    segment_id,
                    document["extraction_id"],
                    len(text),
                    text,
                    text_sha,
                ),
            )
            con.execute(
                """
                INSERT INTO extracted_segments_fts(
                    extracted_segment_id, text, section_path
                ) VALUES (?, ?, NULL)
                """,
                (segment_id, text),
            )
            con.execute(
                """
                UPDATE text_extractions
                SET segment_count = 2
                WHERE extraction_id = ?
                """,
                (document["extraction_id"],),
            )
            con.commit()
        finally:
            con.close()
        return segment_id

    @staticmethod
    def bound_descriptions(execution) -> list[str]:
        return [
            item["description"]
            for item in execution.unresolved
            if item["category"] == "other"
            and item["description"].startswith("Research bound ")
        ]

    def test_authority_limit_one_rejects_new_authority_before_candidate_admission(self):
        for index in range(3):
            self.add_document_with_segment(
                document_id=f"DOC-cap-{index}",
                number=str(index + 1),
                year=2026,
                text=f"{GENERAL_RULE} Variante {index}.",
                filename=f"ley_cap_{index}.htm",
            )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_total_authorities": 1, "max_hits_per_query": 10},
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )

        self.assertEqual(len(execution.result["authority_refs"]), 1)
        self.assertEqual(len(execution.authorities), 1)
        admitted = set(execution.result["authority_refs"])
        self.assertTrue(execution.evidence_candidates)
        self.assertTrue(
            all(
                candidate.get("document_ref", "").replace("document:", "authority:", 1)
                in admitted
                for candidate in execution.evidence_candidates
                if candidate.get("document_ref")
            )
        )
        self.assertEqual(execution.result["status"], "partial")
        self.assertEqual(
            execution.result["trace"][-1]["stop_reason"],
            "bounds_exhausted",
        )
        self.assertTrue(
            any(
                "max_total_authorities" in text
                for text in self.bound_descriptions(execution)
            )
        )

    def test_exact_authority_and_hit_limits_after_finished_work_are_not_false_exhaustion(self):
        self.add_document_with_segment(
            document_id="DOC-exact-one",
            number="11",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_exact_one.htm",
        )

        execution = PlatformResearchService(
            self.db,
            bounds={
                "max_total_authorities": 1,
                "max_hits_per_query": 1,
                "max_queries_per_question": 1,
            },
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )

        self.assertEqual(execution.result["authority_refs"], ["authority:DOC-exact-one"])
        self.assertEqual(execution.result["status"], "complete")
        self.assertEqual(
            execution.result["trace"][-1]["stop_reason"],
            "questions_satisfied",
        )
        self.assertEqual(self.bound_descriptions(execution), [])

    def test_n_plus_one_authority_is_partial_without_overshoot(self):
        for index in range(3):
            self.add_document_with_segment(
                document_id=f"DOC-nplus-{index}",
                number=str(20 + index),
                year=2026,
                text=f"{GENERAL_RULE} N-plus-one {index}.",
                filename=f"ley_nplus_{index}.htm",
            )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_total_authorities": 2, "max_hits_per_query": 10},
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )

        self.assertEqual(len(execution.result["authority_refs"]), 2)
        self.assertLessEqual(len(execution.authorities), 2)
        self.assertEqual(execution.result["status"], "partial")
        self.assertEqual(
            execution.result["trace"][-1]["stop_reason"],
            "bounds_exhausted",
        )

    def test_duplicate_authority_does_not_consume_slot_and_can_add_bounded_evidence(self):
        hint = {
            "kind": "search_hint",
            "contract_version": "4.0.0",
            "hint_ref": "hint:extra-evidence",
            "terms": ["evidencia secundaria especial adicional"],
            "origin": "internal_intake_model",
            "related_question_refs": ["question:filing"],
        }
        document = self.add_document_with_segment(
            document_id="DOC-one-authority-two-spans",
            number="30",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_two_spans.htm",
        )
        second_segment = self.add_second_segment(
            document,
            token="one-authority-extra",
            text="Evidencia secundaria especial adicional para el mismo documento.",
        )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_total_authorities": 1, "max_hits_per_query": 4},
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(hints=[hint]),
            generated_at=NOW,
        )

        self.assertEqual(
            execution.result["authority_refs"],
            ["authority:DOC-one-authority-two-spans"],
        )
        candidate_ids = {
            item["extracted_segment_id"] for item in execution.evidence_candidates
        }
        self.assertIn(document["segment_id"], candidate_ids)
        self.assertIn(second_segment, candidate_ids)
        self.assertFalse(
            any(
                "max_total_authorities" in text
                for text in self.bound_descriptions(execution)
            )
        )
        self.assertEqual(execution.result["status"], "complete")

    def test_hit_limit_reports_pending_work_and_never_admits_sentinel(self):
        for index in range(2):
            self.add_document_with_segment(
                document_id=f"DOC-hit-{index}",
                number=str(40 + index),
                year=2026,
                text=f"{GENERAL_RULE} Hit limit {index}.",
                filename=f"ley_hit_{index}.htm",
            )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_hits_per_query": 1, "max_total_authorities": 10},
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )

        self.assertEqual(execution.result["trace"][0]["hit_count"], 1)
        self.assertEqual(len(execution.evidence_candidates), 1)
        self.assertEqual(len(execution.result["authority_refs"]), 1)
        self.assertEqual(execution.result["status"], "partial")
        self.assertTrue(
            any(
                "max_hits_per_query" in text
                for text in self.bound_descriptions(execution)
            )
        )

    def test_query_depth_and_round_bounds_make_dropped_reference_work_observable(self):
        source = self.add_document_with_segment(
            document_id="DOC-bound-source",
            number="50",
            year=2026,
            text=GENERAL_RULE + " Véase LEY 999 DE 2020.",
            filename="ley_bound_source.htm",
        )
        target = self.add_document_with_segment(
            document_id="DOC-bound-target",
            number="999",
            year=2020,
            text=REFERENCE_RULE,
            filename="ley_bound_target.htm",
        )
        self.add_resolved_reference(
            source=source,
            target=target,
            normalized_reference="LEY 999 DE 2020",
        )

        scenarios = (
            ({"max_queries_per_question": 1}, "max_queries_per_question"),
            ({"max_reference_depth": 0}, "max_reference_depth"),
            ({"max_rounds": 1}, "max_rounds"),
        )
        for overrides, expected_bound in scenarios:
            with self.subTest(bound=expected_bound):
                execution = PlatformResearchService(
                    self.db,
                    bounds=overrides,
                ).research(
                    case_input=self.no_as_of_case(),
                    intake_draft=self.no_as_of_intake(),
                    generated_at=NOW,
                )
                self.assertNotIn(
                    f"authority:{target['document_id']}",
                    execution.result["authority_refs"],
                )
                self.assertEqual(execution.result["status"], "partial")
                self.assertEqual(
                    execution.result["trace"][-1]["stop_reason"],
                    "bounds_exhausted",
                )
                self.assertTrue(
                    any(
                        expected_bound in text
                        for text in self.bound_descriptions(execution)
                    )
                )

    def test_multi_question_queue_continues_after_authority_cap_for_fair_observation(self):
        self.add_document_with_segment(
            document_id="DOC-filing",
            number="60",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_filing.htm",
        )
        self.add_document_with_segment(
            document_id="DOC-withholding",
            number="61",
            year=2026,
            text=(
                "La retención en la fuente corresponde al agente retenedor "
                "según los supuestos aplicables."
            ),
            filename="ley_withholding.htm",
        )
        draft = self.no_as_of_intake()
        draft["questions"].append(
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:withholding",
                "text": "¿Aplica retención en la fuente?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:person"],
            }
        )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_total_authorities": 1},
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=draft,
            generated_at=NOW,
        )

        task_by_ref = {
            task["task_ref"]: task for task in execution.plan["tasks"]
        }
        traced_questions = {
            task_by_ref[step["task_ref"]]["question_ref"]
            for step in execution.result["trace"]
        }
        self.assertEqual(
            traced_questions,
            {"question:filing", "question:withholding"},
        )
        self.assertEqual(len(execution.result["authority_refs"]), 1)
        self.assertEqual(execution.result["status"], "partial")
        self.assertTrue(
            any(
                item.get("related_question_refs") == ["question:withholding"]
                and "max_total_authorities" in item["description"]
                for item in execution.unresolved
            )
        )

    def test_empty_hits_and_blocked_missing_fact_behavior_remain_explicit(self):
        empty = PlatformResearchService(self.db).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )
        self.assertEqual(empty.result["authority_refs"], [])
        self.assertEqual(empty.result["status"], "partial")
        self.assertTrue(
            any(
                item["category"] == "no_relevant_corpus_evidence"
                for item in empty.unresolved
            )
        )

        blocked = deepcopy(intake())
        blocked["facts"].append(
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:tax-year",
                "label": "Periodo gravable",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Indicar el periodo gravable consultado.",
            }
        )
        blocked["questions"][0]["status"] = "blocked"
        blocked["questions"][0]["depends_on_fact_refs"] = [
            "fact:person",
            "fact:tax-year",
        ]
        blocked_execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=blocked,
            generated_at=NOW,
        )
        self.assertEqual(blocked_execution.result["status"], "blocked")
        self.assertEqual(blocked_execution.result["trace"], [])
        self.assertTrue(
            any(item["category"] == "missing_fact" for item in blocked_execution.unresolved)
        )

    def test_bound_execution_is_repeatable_and_does_not_mutate_corpus(self):
        for index in range(2):
            self.add_document_with_segment(
                document_id=f"DOC-stable-{index}",
                number=str(70 + index),
                year=2026,
                text=f"{GENERAL_RULE} Stable {index}.",
                filename=f"ley_stable_{index}.htm",
            )
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        service = PlatformResearchService(
            self.db,
            bounds={"max_total_authorities": 1},
        )
        first = service.research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )
        second = service.research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(before, after)
        self.assertEqual(first, second)
        self.assertEqual(first.result["status"], "partial")

    def _valid_execution(self):
        self.add_document_with_segment(
            document_id="DOC-validator",
            number="80",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_validator.htm",
        )
        return PlatformResearchService(
            self.db,
            bounds={
                "max_total_authorities": 1,
                "max_hits_per_query": 1,
                "max_queries_per_question": 1,
            },
        ).research(
            case_input=self.no_as_of_case(),
            intake_draft=self.no_as_of_intake(),
            generated_at=NOW,
        )

    def test_semantic_validation_rejects_impossible_bound_trace_result_combinations(self):
        execution = self._valid_execution()
        plan = execution.plan
        result = execution.result

        cases: list[tuple[str, dict, dict]] = []

        authority_overflow = deepcopy(result)
        authority_overflow["authority_refs"].append("authority:overflow")
        cases.append(("authority overflow", deepcopy(plan), authority_overflow))

        hit_overflow = deepcopy(result)
        hit_overflow["trace"][0]["hit_count"] = 2
        cases.append(("hit overflow", deepcopy(plan), hit_overflow))

        round_mismatch = deepcopy(result)
        round_mismatch["trace"][0]["round"] = 2
        cases.append(("round mismatch", deepcopy(plan), round_mismatch))

        query_overflow = deepcopy(result)
        duplicate_step = deepcopy(query_overflow["trace"][0])
        duplicate_step["trace_ref"] = "trace:second"
        duplicate_step.pop("stop_reason", None)
        query_overflow["trace"].insert(0, duplicate_step)
        cases.append(("query overflow", deepcopy(plan), query_overflow))

        false_complete = deepcopy(result)
        false_complete["trace"][-1]["stop_reason"] = "bounds_exhausted"
        false_complete["unresolved_refs"] = ["unresolved:pending"]
        cases.append(("complete after bounds", deepcopy(plan), false_complete))

        trace_authority_mismatch = deepcopy(result)
        trace_authority_mismatch["trace"][0]["authority_refs"] = ["authority:not-admitted"]
        cases.append(
            ("trace authority not admitted", deepcopy(plan), trace_authority_mismatch)
        )

        for label, case_plan, case_result in cases:
            with self.subTest(case=label):
                with self.assertRaises(CaseContractError):
                    validate_research_result(case_plan, case_result)

    def test_interpretive_handoff_is_not_blanket_rejected_by_research_cross_field_validation(self):
        execution = self._valid_execution()
        handoff = {
            "kind": "unresolved_item",
            "contract_version": "4.0.0",
            "unresolved_ref": "unresolved:interpretive",
            "stage": "evaluation",
            "category": "requires_interpretive_synthesis",
            "description": "External consumer must synthesize the supported evidence.",
            "related_question_refs": ["question:filing"],
            "next_action": "external_interpretive_synthesis",
        }
        validate_contract_object(handoff)

        result = deepcopy(execution.result)
        result["unresolved_refs"] = [handoff["unresolved_ref"]]
        # ResearchResult validation deliberately enforces execution/budget
        # coherence, not the later bundle unresolved-category policy.
        validate_research_result(execution.plan, result)


if __name__ == "__main__":
    unittest.main()
