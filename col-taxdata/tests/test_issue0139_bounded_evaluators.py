from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation_v4 import (
    intake_draft_generation_schema,
    validate_intake_draft,
)
from case_evaluators import (
    GROSS_INCOME_KEY,
    GROSS_PATRIMONY_KEY,
    evaluate_supported_rules,
)


NOW = "2026-09-27T11:30:00+00:00"
AS_OF = "2026-09-27"
AUTHORITY_REF = "authority:DOC-et-592"
EVIDENCE_REF = "evidence:article-592-thresholds"
RULE_REF = "rule:article-592-thresholds"

RULE_TEXT = (
    "ARTÍCULO 592. QUIÉNES NO ESTÁN OBLIGADOS A DECLARAR. "
    "Para este supuesto, el patrimonio bruto no exceda de 4.500 UVT "
    "y los ingresos brutos sean inferiores a 1.400 UVT."
)


def case_input(
    *,
    income: str = "1.399",
    patrimony: str = "4.500",
) -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": (
            "Una persona natural residente en Colombia obtiene ingresos por "
            "transmisiones por webcam. "
            f"Sus ingresos brutos fueron {income} UVT en 2025. "
            f"Su patrimonio bruto fue {patrimony} UVT en 2025. "
            "Pregunta si debe declarar renta."
        ),
        "as_of_date": AS_OF,
    }


def intake(
    *,
    income_decimal: str = "1399",
    patrimony_decimal: str = "4500",
    include_income: bool = True,
    income_state: str = "user_provided",
    income_year: int = 2025,
    patrimony_year: int = 2025,
) -> dict:
    source = case_input(
        income=(
            f"{int(Decimal(income_decimal)):,}".replace(",", ".")
            if Decimal(income_decimal) == Decimal(income_decimal).to_integral()
            else income_decimal
        ),
        patrimony=(
            f"{int(Decimal(patrimony_decimal)):,}".replace(",", ".")
            if Decimal(patrimony_decimal) == Decimal(patrimony_decimal).to_integral()
            else patrimony_decimal
        ),
    )
    facts: list[dict] = []
    if include_income:
        income_fact = {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:gross-income",
            "label": "Ingresos brutos informados por el cliente",
            "value": income_decimal,
            "semantic_key": GROSS_INCOME_KEY,
            "measurement": {
                "decimal_value": income_decimal,
                "unit": "UVT",
                "uvt_year": income_year,
            },
            "state": income_state,
            "source_quote": (
                f"Sus ingresos brutos fueron "
                f"{int(Decimal(income_decimal)):,}".replace(",", ".")
                + " UVT en 2025."
            ),
            "requires_confirmation": income_state != "user_provided",
        }
        facts.append(income_fact)

    facts.append(
        {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:gross-patrimony",
            "label": "Patrimonio bruto informado por el cliente",
            "value": patrimony_decimal,
            "semantic_key": GROSS_PATRIMONY_KEY,
            "measurement": {
                "decimal_value": patrimony_decimal,
                "unit": "UVT",
                "uvt_year": patrimony_year,
            },
            "state": "user_provided",
            "source_quote": (
                f"Su patrimonio bruto fue "
                f"{int(Decimal(patrimony_decimal)):,}".replace(",", ".")
                + " UVT en 2025."
            ),
            "requires_confirmation": False,
        }
    )
    fact_refs = [fact["fact_ref"] for fact in facts]
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue139",
        "problem_text": source["problem_text"],
        "as_of_date": AS_OF,
        "facts": facts,
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:filing",
                "text": "¿Debe declarar renta?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": fact_refs,
            }
        ],
        "search_hints": [],
        "model_metadata": {
            "adapter": "fixture",
            "provider": "fixture",
            "model": "fixture",
            "schema_version": "4.0.0",
            "prompt_template_id": "case-intake-v4",
            "prompt_template_version": "1",
            "run_reference": "run:issue139",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
        },
    }


def authority(*, resolution_state: str = "resolved", effective=True) -> dict:
    return {
        "authority_ref": AUTHORITY_REF,
        "temporal_state": {
            "resolution_state": resolution_state,
            "effective": effective,
            "basis_evidence_refs": [],
            "as_of_date": AS_OF,
        },
    }


def evidence(
    *,
    exact_text: str = RULE_TEXT,
    evidence_ref: str = EVIDENCE_REF,
) -> dict:
    return {
        "evidence_ref": evidence_ref,
        "exact_text": exact_text,
        "text_sha256": hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
    }


def rule(
    *,
    evidence_ref: str = EVIDENCE_REF,
    rule_ref: str = RULE_REF,
    as_of_date: str = AS_OF,
) -> dict:
    return {
        "kind": "rule_fragment",
        "contract_version": "4.0.0",
        "rule_ref": rule_ref,
        "rule_type": "canonical_source_statement",
        "rule_schema_version": "1",
        "structured_data": {
            "statement_scope": "canonical_provision",
            "document_ref": "document:DOC-et-592",
            "authority_ref": AUTHORITY_REF,
            "evidence_refs": [evidence_ref],
            "provision_ref": "provision:ART-592",
            "provision_type": "article",
            "designation": "Artículo 592",
        },
        "derivation": {
            "method": "extractive_normalization",
            "version": "1",
        },
        "authority_refs": [AUTHORITY_REF],
        "evidence_refs": [evidence_ref],
        "as_of_date": as_of_date,
    }


def evaluate(
    draft: dict,
    *,
    case: dict | None = None,
    authorities: list[dict] | None = None,
    evidence_spans: list[dict] | None = None,
    rule_fragments: list[dict] | None = None,
):
    return evaluate_supported_rules(
        case_input=case or case_input(),
        intake_draft=draft,
        authorities=authorities or [authority()],
        evidence_spans=evidence_spans or [evidence()],
        rule_fragments=rule_fragments or [rule()],
        generated_at=NOW,
    )


class Issue0139BoundedEvaluatorTests(unittest.TestCase):
    def test_evaluator_ready_intake_contract_is_structured_but_intake_only(self):
        draft = intake()
        validate_intake_draft(case_input(), draft)

        generation_schema = intake_draft_generation_schema(case_input())
        definitions = generation_schema["$defs"]
        self.assertIn("FactMeasurement", definitions)
        self.assertIn("DecimalString", definitions)
        serialized = str(generation_schema).casefold()
        self.assertNotIn("deterministicevaluation".casefold(), serialized)
        self.assertNotIn("calculationtrace".casefold(), serialized)

    def test_sufficient_confirmed_facts_produce_deterministic_evaluation(self):
        outcome = evaluate(intake())
        self.assertEqual(len(outcome.evaluations), 1)
        evaluation = outcome.evaluations[0]
        self.assertEqual(evaluation["status"], "determined")
        self.assertEqual(
            evaluation["result"],
            {
                "code": "non_filer_threshold_conditions_met",
                "value": True,
            },
        )
        self.assertEqual(
            evaluation["fact_refs"],
            ["fact:gross-income", "fact:gross-patrimony"],
        )
        self.assertEqual(evaluation["question_refs"], ["question:filing"])
        self.assertEqual(evaluation["rule_refs"], [RULE_REF])
        self.assertEqual(evaluation["evidence_refs"], [EVIDENCE_REF])
        self.assertEqual(evaluation["as_of_date"], AS_OF)
        self.assertEqual(len(outcome.calculations), 2)
        self.assertFalse(outcome.unresolved)

    def test_missing_required_fact_blocks_without_guessing(self):
        draft = intake(include_income=False)
        outcome = evaluate(draft)

        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertTrue(
            any(item["category"] == "missing_fact" for item in outcome.unresolved)
        )
        self.assertEqual(outcome.calculations, ())

    def test_unconfirmed_model_normalized_measurement_cannot_drive_result(self):
        draft = intake(income_state="llm_normalized")
        outcome = evaluate(draft)

        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertEqual(outcome.calculations, ())
        self.assertTrue(
            any(item["category"] == "missing_fact" for item in outcome.unresolved)
        )

    def test_threshold_equality_boundaries_preserve_operator_semantics(self):
        income_equal = evaluate(
            intake(income_decimal="1400"),
            case=case_input(income="1.400"),
        )
        self.assertFalse(income_equal.evaluations[0]["result"]["value"])

        patrimony_equal = evaluate(intake())
        self.assertTrue(patrimony_equal.evaluations[0]["result"]["value"])

        patrimony_over = evaluate(
            intake(patrimony_decimal="4501"),
            case=case_input(patrimony="4.501"),
        )
        self.assertFalse(patrimony_over.evaluations[0]["result"]["value"])

    def test_temporal_ambiguity_blocks_deterministic_evaluation(self):
        outcome = evaluate(
            intake(),
            authorities=[authority(resolution_state="ambiguous", effective=None)],
        )
        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertEqual(outcome.calculations, ())
        self.assertTrue(
            any(
                item["category"] == "temporal_uncertainty"
                for item in outcome.unresolved
            )
        )

    def test_multiple_supported_threshold_rules_block_as_conflicting(self):
        second_text = RULE_TEXT.replace("1.400", "1.300")
        second_ref = "evidence:second-threshold"
        second_rule = rule(
            evidence_ref=second_ref,
            rule_ref="rule:second-threshold",
        )
        outcome = evaluate(
            intake(),
            evidence_spans=[
                evidence(),
                evidence(exact_text=second_text, evidence_ref=second_ref),
            ],
            rule_fragments=[rule(), second_rule],
        )
        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertTrue(
            any(
                item["category"] == "conflicting_authority"
                for item in outcome.unresolved
            )
        )

    def test_repeated_input_produces_identical_result(self):
        draft = intake()
        first = evaluate(draft)
        second = evaluate(deepcopy(draft))
        self.assertEqual(first, second)

    def test_model_prose_cannot_change_evaluator_output(self):
        original = intake()
        changed = deepcopy(original)
        changed["facts"][0]["label"] = "Texto libre totalmente diferente"
        changed["facts"][1]["label"] = "Otro texto libre"
        changed["questions"][0]["text"] = "Pregunta reescrita por el modelo"
        changed["search_hints"] = [
            {
                "kind": "search_hint",
                "contract_version": "4.0.0",
                "hint_ref": "hint:noise",
                "terms": ["webcam texto modelo irrelevante"],
                "origin": "internal_intake_model",
                "related_question_refs": ["question:filing"],
            }
        ]
        self.assertEqual(evaluate(original), evaluate(changed))

    def test_measurement_must_be_verifiable_from_exact_client_quote(self):
        draft = intake()
        draft["facts"][0]["measurement"]["decimal_value"] = "1300"
        outcome = evaluate(draft)
        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertEqual(outcome.calculations, ())

    def test_uvt_year_mismatch_blocks_mixed_unit_semantics(self):
        outcome = evaluate(
            intake(income_year=2024, patrimony_year=2025),
        )
        self.assertEqual(outcome.evaluations[0]["status"], "blocked")
        self.assertTrue(
            any(item["category"] == "ambiguous_fact" for item in outcome.unresolved)
        )

    def test_calculation_trace_reproduces_result_exactly(self):
        outcome = evaluate(intake())
        by_fact = {
            trace["inputs"][0]["source_fact_ref"]: trace
            for trace in outcome.calculations
        }
        income = by_fact["fact:gross-income"]
        observed = Decimal(income["inputs"][0]["decimal_value"])
        threshold = Decimal(income["inputs"][1]["decimal_value"])
        expected = threshold - observed

        self.assertEqual(
            Decimal(income["result"]["decimal_value"]),
            expected,
        )
        self.assertEqual(
            Decimal(income["steps"][0]["result_decimal"]),
            expected,
        )
        self.assertEqual(income["formula"], "threshold - observed")
        self.assertEqual(income["rounding"], {"mode": "NONE", "scale": 0})
        self.assertEqual(income["inputs"][0]["unit"], "UVT@2025")
        self.assertEqual(income["inputs"][1]["unit"], "UVT@2025")

    def test_explicit_evidence_change_changes_output_only_through_input(self):
        lower_text = RULE_TEXT.replace("1.400", "1.300")
        lower_ref = "evidence:lower-income-threshold"
        outcome = evaluate(
            intake(),
            evidence_spans=[
                evidence(exact_text=lower_text, evidence_ref=lower_ref)
            ],
            rule_fragments=[
                rule(evidence_ref=lower_ref)
            ],
        )
        self.assertEqual(outcome.evaluations[0]["status"], "determined")
        self.assertFalse(outcome.evaluations[0]["result"]["value"])
        income_trace = next(
            trace
            for trace in outcome.calculations
            if trace["inputs"][0]["source_fact_ref"] == "fact:gross-income"
        )
        self.assertEqual(
            income_trace["inputs"][1]["decimal_value"],
            "1300",
        )

    def test_unsupported_interpretive_question_remains_external_synthesis(self):
        outcome = evaluate_supported_rules(
            case_input=case_input(),
            intake_draft=intake(),
            authorities=[authority()],
            evidence_spans=[],
            rule_fragments=[],
            generated_at=NOW,
        )
        self.assertEqual(outcome.evaluations, ())
        self.assertEqual(outcome.calculations, ())
        self.assertEqual(len(outcome.unresolved), 1)
        self.assertEqual(
            outcome.unresolved[0]["category"],
            "requires_interpretive_synthesis",
        )
        self.assertEqual(
            outcome.unresolved[0]["next_action"],
            "external_interpretive_synthesis",
        )


if __name__ == "__main__":
    unittest.main()
