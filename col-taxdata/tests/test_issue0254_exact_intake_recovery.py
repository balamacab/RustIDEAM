from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation_v4 import normalize_intake_draft
from deterministic_intake_adapter import DeterministicIntakeAdapter
from llm_client import CaseStructuringService, LLMPlatformConfig, ModelRoute


AS_OF = "2026-09-27"

CASE_A = (
    "Una persona natural residente fiscal en Colombia obtuvo durante el año "
    "gravable 2025 ingresos brutos por 1.100 UVT y tenía un patrimonio bruto "
    "de 3.900 UVT al 31 de diciembre de 2025. Los dos valores están expresados "
    "usando la UVT del año 2025. Sus ingresos provinieron de actividades "
    "digitales prestadas por cuenta propia. A 27 de septiembre de 2026 quiere "
    "saber qué condiciones legales deben revisarse para establecer si estaba "
    "obligada a presentar declaración de renta por el año gravable 2025, qué "
    "parte puede evaluarse de forma objetiva con esos datos y qué aspectos no "
    "pueden concluirse sin información adicional."
)

CASE_B = (
    "Una SAS colombiana responsable del IVA presta desde Bogotá servicios de "
    "analítica y optimización de campañas digitales a una sociedad domiciliada "
    "en Canadá. El cliente extranjero no tiene domicilio, sucursal, "
    "establecimiento permanente, empleados ni activos en Colombia. El trabajo "
    "se ejecuta desde Colombia, pero los informes, tableros y recomendaciones "
    "se usan exclusivamente por el cliente para campañas dirigidas a Canadá y "
    "Chile; no se usan ni se explotan en Colombia. La SAS conserva contrato "
    "escrito, facturas, comprobantes bancarios, entregables y constancias de "
    "aceptación del cliente. En agosto de 2026 factura y recibe el pago del "
    "servicio. A 27 de septiembre de 2026 pregunta si el servicio puede "
    "tratarse como exportación de servicios para efectos del IVA y qué "
    "requisitos, autoridades y soportes deben revisarse para sustentar ese "
    "tratamiento."
)

# Exact canonical candidate bytes preserved by #142 r5.  The SHA assertions
# below make fixture drift visible: these are not hand-simplified replicas.
CANDIDATE_A_JSON = """{"contract_version":"4.0.0","facts":[{"contract_version":"4.0.0","fact_ref":"fact:1","kind":"intake_fact","label":"Ingresos brutos por el año gravable 2025","needed_information":"El valor de los ingresos brutos por el año gravable 2025 debe ser confirmado.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:2","kind":"intake_fact","label":"Patrimonio bruto al 31 de diciembre de 2025","needed_information":"El valor del patrimonio bruto al 31 de diciembre de 2025 debe ser confirmado.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:3","kind":"intake_fact","label":"Fuente de los ingresos","requires_confirmation":false,"source_quote":"Sus ingresos provinieron de actividades digitales prestadas por cuenta propia.","state":"user_provided"},{"contract_version":"4.0.0","fact_ref":"fact:4","kind":"intake_fact","label":"Residencia fiscal","requires_confirmation":false,"source_quote":"Una persona natural residente fiscal en Colombia obtuvo durante el año gravable 2025 ingresos brutos por 1.100 UVT y tenía un patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025. Los dos valores están expresados usando la UVT del año 2025. Sus ingresos provinieron de actividades digitales prestadas por cuenta propia. A 27 de septiembre de 2026 quiere saber qué condiciones legales deben revisarse para establecer si estaba obligada a presentar declaración de renta por el año gravable 2025, qué parte puede evaluarse de forma objetiva con esos datos y qué aspectos no pueden concluirse sin información adicional.","state":"user_provided"}],"intake_ref":"intake:12345","kind":"intake_draft","questions":[{"category":"legal","contract_version":"4.0.0","kind":"case_question","question_ref":"question:1","status":"open","text":"¿Qué condiciones legales deben revisarse para establecer si la persona natural estaba obligada a presentar declaración de renta por el año gravable 2025, considerando los ingresos brutos de 1.100 UVT y el patrimonio bruto de 3.900 UVT?"},{"category":"legal","contract_version":"4.0.0","kind":"case_question","question_ref":"question:2","status":"open","text":"¿Qué parte de la obligación de declarar renta puede evaluarse de forma objetiva con los datos proporcionados (ingresos brutos y patrimonio bruto)?"},{"category":"legal","contract_version":"4.0.0","kind":"case_question","question_ref":"question:3","status":"open","text":"¿Qué aspectos no pueden concluirse sin información adicional?"}],"search_hints":[{"contract_version":"4.0.0","hint_ref":"hint:1","kind":"search_hint","origin":"internal_intake_model","related_question_refs":["question:1","question:2"],"terms":["obligación de declarar renta Colombia","ingresos brutos patrimonio renta Colombia","reglamento declaración de renta Colombia"]}]}"""
CANDIDATE_A_SHA256 = "d4b44af5e1710f9b89be4020eb427d242b5d57ac3d3bedfcb6a6790d62d5cd20"

CANDIDATE_B_JSON = """{"contract_version":"4.0.0","facts":[{"contract_version":"4.0.0","fact_ref":"fact:1","kind":"intake_fact","label":"SAS colombiana responsable del IVA presta servicios de analítica y optimización de campañas digitales.","needed_information":"The specific nature of the services provided (analítica y optimización de campañas digitales).","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:2","kind":"intake_fact","label":"El cliente es una sociedad domiciliada en Canadá.","needed_information":"Confirmation of the client's domicile in Canada.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:3","kind":"intake_fact","label":"El cliente extranjero no tiene domicilio, sucursal, establecimiento permanente, empleados ni activos en Colombia.","needed_information":"Confirmation that the client has no domicile, branch, permanent establishment, employees, or assets in Colombia.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:4","kind":"intake_fact","label":"El trabajo se ejecuta desde Colombia.","needed_information":"Confirmation that the work is executed from Colombia.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:5","kind":"intake_fact","label":"Los informes, tableros y recomendaciones se usan exclusivamente por el cliente para campañas dirigidas a Canadá y Chile; no se usan ni se explotan en Colombia.","needed_information":"Confirmation that the deliverables are exclusively used for campaigns directed to Canada and Chile and are not used or exploited in Colombia.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:6","kind":"intake_fact","label":"La SAS conserva contrato escrito, facturas, comprobantes bancarios, entregables y constancias de aceptación del cliente.","requires_confirmation":false,"source_quote":"Una SAS colombiana responsable del IVA presta desde Bogotá servicios de analítica y optimización de campañas digitales a una sociedad domiciliada en Canadá. El cliente extranjero no tiene domicilio, sucursal, establecimiento permanente, empleados ni activos en Colombia. El trabajo se ejecuta desde Colombia, pero los informes, tableros y recomendaciones se usan exclusivamente por el cliente para campañas dirigidas a Canadá y Chile; no se usan ni se explotan en Colombia. La SAS conserva contrato escrito, facturas, comprobantes bancarios, entregables y constancias de aceptación del cliente. En agosto de 2026 factura y recibe el pago del servicio. A 27 de septiembre de 2026 pregunta si el servicio puede tratarse como exportación de servicios para efectos del IVA y qué requisitos, autoridades y soportes deben revisarse para sustentar ese tratamiento.","state":"user_provided"},{"contract_version":"4.0.0","fact_ref":"fact:7","kind":"intake_fact","label":"La SAS factura y recibe el pago del servicio en agosto de 2026.","needed_information":"Confirmation of the exact date of invoicing and payment.","requires_confirmation":true,"state":"missing"},{"contract_version":"4.0.0","fact_ref":"fact:8","kind":"intake_fact","label":"La pregunta se realiza el 27 de septiembre de 2026.","needed_information":"Confirmation of the exact date the question was asked.","requires_confirmation":true,"state":"missing"}],"intake_ref":"intake:1","kind":"intake_draft","questions":[{"category":"legal","contract_version":"4.0.0","kind":"case_question","question_ref":"question:1","status":"open","text":"¿Puede el servicio prestado por la SAS colombiana tratarse como exportación de servicios para efectos del IVA?"},{"category":"legal","contract_version":"4.0.0","kind":"case_question","question_ref":"question:2","status":"open","text":"¿Qué requisitos, autoridades y soportes deben revisarse para sustentar el tratamiento del servicio como exportación de servicios para efectos del IVA?"}],"search_hints":[{"contract_version":"4.0.0","hint_ref":"hint:1","kind":"search_hint","origin":"internal_intake_model","related_question_refs":["question:1","question:2"],"terms":["exportación de servicios IVA Colombia","reglas IVA servicios digitales","establecimiento permanente IVA"]}]}"""
CANDIDATE_B_SHA256 = "f9cab69520927ff8dd1289f4af25ba1f4dadb92d19beae43fe14b32dd6eb169b"


def case_input(problem_text: str) -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": problem_text,
        "as_of_date": AS_OF,
    }


def config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="deterministic",
        provider="issue254-provider",
        base_url="http://127.0.0.1:1/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("issue254-model", "primary", 100_000, 4096),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


def structure(problem_text: str, candidate_json: str) -> dict:
    candidate = json.loads(candidate_json)
    return CaseStructuringService(
        config(),
        DeterministicIntakeAdapter([candidate]),
    ).structure(case_input(problem_text)).intake


def unresolved_draft(problem_text: str, fact: dict) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue254-negative",
        "problem_text": problem_text,
        "as_of_date": AS_OF,
        "facts": [fact],
        "questions": [],
        "search_hints": [],
    }


class Issue0254ExactIntakeRecoveryTests(unittest.TestCase):
    def test_a_exact_rejected_candidate_recovers_uvt_facts_from_client_text(self):
        self.assertEqual(
            hashlib.sha256(CANDIDATE_A_JSON.encode("utf-8")).hexdigest(),
            CANDIDATE_A_SHA256,
        )

        result = structure(CASE_A, CANDIDATE_A_JSON)
        by_ref = {fact["fact_ref"]: fact for fact in result["facts"]}

        income = by_ref["fact:1"]
        patrimony = by_ref["fact:2"]
        self.assertEqual(income["state"], "user_provided")
        self.assertEqual(
            income["source_quote"],
            (
                "Una persona natural residente fiscal en Colombia obtuvo durante "
                "el año gravable 2025 ingresos brutos por 1.100 UVT"
            ),
        )
        self.assertEqual(
            income["semantic_key"],
            "col.tax.natural_person.gross_income",
        )
        self.assertEqual(
            income["measurement"],
            {"decimal_value": "1100", "unit": "UVT", "uvt_year": 2025},
        )

        self.assertEqual(patrimony["state"], "user_provided")
        self.assertEqual(
            patrimony["source_quote"],
            "tenía un patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025.",
        )
        self.assertEqual(
            patrimony["semantic_key"],
            "col.tax.natural_person.gross_patrimony",
        )
        self.assertEqual(
            patrimony["measurement"],
            {"decimal_value": "3900", "unit": "UVT", "uvt_year": 2025},
        )
        self.assertFalse(income["requires_confirmation"])
        self.assertFalse(patrimony["requires_confirmation"])
        self.assertNotIn("needed_information", income)
        self.assertNotIn("needed_information", patrimony)

        # Facts that the provider already grounded remain provider-selected;
        # the fix does not rewrite unrelated user-provided facts.
        self.assertEqual(by_ref["fact:3"]["state"], "user_provided")
        self.assertEqual(by_ref["fact:4"]["state"], "user_provided")

    def test_b_exact_rejected_candidate_recovers_only_literal_service_facts(self):
        self.assertEqual(
            hashlib.sha256(CANDIDATE_B_JSON.encode("utf-8")).hexdigest(),
            CANDIDATE_B_SHA256,
        )

        result = structure(CASE_B, CANDIDATE_B_JSON)
        by_ref = {fact["fact_ref"]: fact for fact in result["facts"]}

        expected_promoted = {
            "fact:1",
            "fact:2",
            "fact:3",
            "fact:4",
            "fact:5",
            "fact:7",
        }
        for fact_ref in expected_promoted:
            fact = by_ref[fact_ref]
            self.assertEqual(fact["state"], "user_provided", fact_ref)
            self.assertFalse(fact["requires_confirmation"], fact_ref)
            self.assertNotIn("needed_information", fact)
            self.assertIn(fact["source_quote"], CASE_B)
            self.assertNotIn("semantic_key", fact)
            self.assertNotIn("measurement", fact)

        self.assertEqual(
            by_ref["fact:3"]["source_quote"],
            (
                "El cliente extranjero no tiene domicilio, sucursal, "
                "establecimiento permanente, empleados ni activos en Colombia."
            ),
        )

        # The already-grounded support-document fact stays untouched.
        self.assertEqual(by_ref["fact:6"]["state"], "user_provided")
        self.assertEqual(
            by_ref["fact:6"]["source_quote"],
            CASE_B,
        )

        # The model also emitted a redundant request to confirm the question
        # date. It is outside the bounded service/export recovery families and
        # must not be promoted merely to make this candidate pass.
        self.assertEqual(by_ref["fact:8"]["state"], "missing")
        self.assertNotIn("source_quote", by_ref["fact:8"])

    def test_yearless_unitless_uvt_descriptor_is_not_used_as_selector(self):
        problem = "La persona informa ingresos brutos por 1.100 UVT."
        generated = unresolved_draft(
            problem,
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:generic-income",
                "label": "Ingresos brutos",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Confirmar los ingresos brutos.",
            },
        )

        normalized = normalize_intake_draft(case_input(problem), generated)
        self.assertEqual(normalized["facts"][0]["state"], "missing")
        self.assertNotIn("source_quote", normalized["facts"][0])

    def test_duplicate_no_presence_span_remains_unresolved(self):
        sentence = (
            "El cliente extranjero no tiene domicilio, sucursal, "
            "establecimiento permanente, empleados ni activos en Colombia."
        )
        problem = f"{sentence} {sentence}"
        generated = unresolved_draft(
            problem,
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:presence",
                "label": sentence,
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": (
                    "Confirmar que el cliente no tiene domicilio, sucursal, "
                    "establecimiento permanente, empleados ni activos en Colombia."
                ),
            },
        )

        normalized = normalize_intake_draft(case_input(problem), generated)
        self.assertEqual(normalized["facts"][0]["state"], "missing")
        self.assertNotIn("source_quote", normalized["facts"][0])


if __name__ == "__main__":
    unittest.main()
