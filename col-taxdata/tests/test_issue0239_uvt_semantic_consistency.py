from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    normalize_intake_draft,
)
from test_issue0210_intake_recovery import (
    CASE_A,
    case_input,
    draft,
    structure,
)


GROSS_INCOME_KEY = "col.tax.natural_person.gross_income"
GROSS_PATRIMONY_KEY = "col.tax.natural_person.gross_patrimony"
INCOME_QUOTE = (
    "Una persona natural residente fiscal en Colombia obtuvo durante el año "
    "gravable 2025 ingresos brutos por 1.100 UVT"
)
PATRIMONY_QUOTE = (
    "tenía un patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025."
)
INCOME_MEASUREMENT = {
    "decimal_value": "1100",
    "unit": "UVT",
    "uvt_year": 2025,
}
PATRIMONY_MEASUREMENT = {
    "decimal_value": "3900",
    "unit": "UVT",
    "uvt_year": 2025,
}


def user_uvt_fact(
    *,
    fact_ref: str,
    label: str,
    semantic_key: str,
    measurement: dict,
    source_quote: str,
) -> dict:
    return {
        "kind": "intake_fact",
        "contract_version": "4.0.0",
        "fact_ref": fact_ref,
        "label": label,
        "state": "user_provided",
        "source_quote": source_quote,
        "requires_confirmation": False,
        "semantic_key": semantic_key,
        "measurement": deepcopy(measurement),
    }


class Issue0239UVTSemanticConsistencyTests(unittest.TestCase):
    def test_exact_issue237_a_mismatch_is_recovered_from_exact_client_text(self):
        # Reproduces the #237 final-A contradiction: 1100 UVT/2025 is attached
        # to the gross-patrimony key and the exact 3900-UVT patrimony quote.
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:gross-income",
                    label="Ingresos brutos por 1.100 UVT durante el año gravable 2025",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )

        result = structure(case_input(CASE_A), generated)
        fact = result["facts"][0]

        self.assertEqual(fact["semantic_key"], GROSS_INCOME_KEY)
        self.assertEqual(fact["measurement"], INCOME_MEASUREMENT)
        self.assertEqual(fact["source_quote"], INCOME_QUOTE)
        self.assertIn(fact["source_quote"], CASE_A)

    def test_unrecoverable_supported_uvt_contradiction_is_rejected(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:generic",
                    label="Dato tributario informado por el cliente",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )

        with self.assertRaises(CaseContractError) as raised:
            structure(case_input(CASE_A), generated)

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("contradict", raised.exception.detail)

    def test_valid_income_and_patrimony_mappings_remain_accepted(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:gross-income",
                    label="Ingresos brutos por 1.100 UVT durante el año gravable 2025",
                    semantic_key=GROSS_INCOME_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=INCOME_QUOTE,
                ),
                user_uvt_fact(
                    fact_ref="fact:gross-patrimony",
                    label="Patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=PATRIMONY_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                ),
            ],
        )

        result = structure(case_input(CASE_A), generated)
        by_ref = {fact["fact_ref"]: fact for fact in result["facts"]}

        self.assertEqual(
            by_ref["fact:gross-income"]["measurement"],
            INCOME_MEASUREMENT,
        )
        self.assertEqual(
            by_ref["fact:gross-patrimony"]["measurement"],
            PATRIMONY_MEASUREMENT,
        )

    def test_exact_quote_and_measurement_can_recover_only_wrong_supported_key(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:gross-income",
                    label="Dato UVT informado",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=INCOME_QUOTE,
                )
            ],
        )

        result = structure(case_input(CASE_A), generated)
        fact = result["facts"][0]

        self.assertEqual(fact["semantic_key"], GROSS_INCOME_KEY)
        self.assertEqual(fact["source_quote"], INCOME_QUOTE)
        self.assertEqual(fact["measurement"], INCOME_MEASUREMENT)

    def test_unsupported_user_semantic_concept_is_not_synthesized_or_rewritten(self):
        problem = "El contrato anual de 2026 vale USD 96.000."
        generated = draft(
            problem,
            [
                {
                    "kind": "intake_fact",
                    "contract_version": "4.0.0",
                    "fact_ref": "fact:contract-value",
                    "label": "Valor anual del contrato",
                    "state": "user_provided",
                    "source_quote": problem,
                    "requires_confirmation": False,
                    "semantic_key": "col.contract.annual_value",
                }
            ],
        )
        original = deepcopy(generated)

        normalized = normalize_intake_draft(case_input(problem), generated)

        self.assertEqual(normalized, original)
        self.assertEqual(generated, original)

    def test_user_uvt_recovery_is_idempotent_and_does_not_mutate_input(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:gross-income",
                    label="Ingresos brutos por 1.100 UVT durante el año gravable 2025",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )
        original = deepcopy(generated)

        first = normalize_intake_draft(case_input(CASE_A), generated)
        second = normalize_intake_draft(case_input(CASE_A), first)

        self.assertEqual(generated, original)
        self.assertEqual(first, second)
        self.assertEqual(first["facts"][0]["semantic_key"], GROSS_INCOME_KEY)
        self.assertEqual(first["facts"][0]["source_quote"], INCOME_QUOTE)


if __name__ == "__main__":
    unittest.main()
