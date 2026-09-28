from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import INVALID_INTAKE_DRAFT
from test_issue0210_intake_recovery import CASE_A, case_input, draft, structure
from test_issue0239_uvt_semantic_consistency import (
    GROSS_INCOME_KEY,
    GROSS_PATRIMONY_KEY,
    INCOME_MEASUREMENT,
    INCOME_QUOTE,
    PATRIMONY_MEASUREMENT,
    PATRIMONY_QUOTE,
    user_uvt_fact,
)


class Issue0246UVTLabelMeasurementRecoveryTests(unittest.TestCase):
    def test_exact_issue244_income_shape_recovers_without_uvt_in_label(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:3",
                    label="Ingresos brutos",
                    semantic_key=GROSS_INCOME_KEY,
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

    def test_label_only_patrimony_uses_structured_uvt_unit_as_unit_signal(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:patrimony",
                    label="Patrimonio bruto",
                    semantic_key=GROSS_PATRIMONY_KEY,
                    measurement=PATRIMONY_MEASUREMENT,
                    source_quote=INCOME_QUOTE,
                )
            ],
        )

        result = structure(case_input(CASE_A), generated)
        fact = result["facts"][0]

        self.assertEqual(fact["semantic_key"], GROSS_PATRIMONY_KEY)
        self.assertEqual(fact["measurement"], PATRIMONY_MEASUREMENT)
        self.assertEqual(fact["source_quote"], PATRIMONY_QUOTE)

    def test_generic_label_remains_unrecoverable_and_rejected(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:generic",
                    label="Dato tributario",
                    semantic_key=GROSS_INCOME_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )

        with self.assertRaises(CaseContractError) as raised:
            structure(case_input(CASE_A), generated)

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("contradict", raised.exception.detail)

    def test_non_uvt_measurement_does_not_activate_label_only_family_selector(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:income-cop",
                    label="Ingresos brutos",
                    semantic_key=GROSS_INCOME_KEY,
                    measurement={
                        "decimal_value": "1100",
                        "unit": "COP",
                    },
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )

        with self.assertRaises(CaseContractError) as raised:
            structure(case_input(CASE_A), generated)

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("contradict", raised.exception.detail)

    def test_ambiguous_bounded_label_is_not_guessed(self):
        generated = draft(
            CASE_A,
            [
                user_uvt_fact(
                    fact_ref="fact:mixed",
                    label="Ingresos brutos y patrimonio bruto",
                    semantic_key=GROSS_INCOME_KEY,
                    measurement=INCOME_MEASUREMENT,
                    source_quote=PATRIMONY_QUOTE,
                )
            ],
        )

        with self.assertRaises(CaseContractError) as raised:
            structure(case_input(CASE_A), generated)

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("contradict", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
