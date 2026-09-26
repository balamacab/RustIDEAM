from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    validate_case_draft,
)
from llm_client import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT


FROZEN_PROBLEM = (
    "Una SAS colombiana, responsable del IVA y contribuyente del impuesto "
    "sobre la renta, presta desde Colombia servicios de diseño, gestión y "
    "optimización de campañas de publicidad digital a una sociedad constituida "
    "y domiciliada en Estados Unidos. El cliente extranjero no tiene domicilio, "
    "sucursal, establecimiento permanente, empleados, activos ni desarrolla "
    "negocios o actividades en Colombia. Todo el trabajo se realiza desde "
    "Colombia, pero las campañas, entregables y resultados son utilizados "
    "exclusivamente por el cliente para promocionar sus productos en Estados "
    "Unidos y otros mercados fuera de Colombia; ninguna campaña se dirige al "
    "mercado colombiano ni se utiliza en Colombia. La SAS conserva contrato "
    "escrito, facturas, comprobantes de pago y constancias de aceptación de los "
    "servicios. La SAS cumple las condiciones para estar sometida a la "
    "autorretención especial a título del impuesto sobre la renta. En septiembre "
    "de 2026 recibe el pago de una factura por esos servicios.\n\n"
    "A 24 de septiembre de 2026, ¿debe cobrar IVA del 19 % o puede tratar la "
    "operación como exportación de servicios exenta de IVA? ¿Qué condiciones y "
    "soportes son relevantes para sostener ese tratamiento? Además, ¿el ingreso "
    "recibido del cliente extranjero forma parte de la base de la autorretención "
    "especial a título de renta y qué tarifa debe aplicar la SAS?"
)


def case_input(problem_text: str) -> dict:
    return {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
    }


def case_fact(
    *,
    fact_ref: str,
    label: str,
    state: str,
    value: str | None = None,
    source_quote: str | None = None,
    needed_information: str | None = None,
) -> dict:
    fact = {
        "kind": "case_fact",
        "contract_version": "3.0.0",
        "fact_ref": fact_ref,
        "label": label,
        "state": state,
        "requires_confirmation": state != "user_provided",
    }
    if value is not None:
        fact["value"] = value
    if source_quote is not None:
        fact["source_quote"] = source_quote
    if needed_information is not None:
        fact["needed_information"] = needed_information
    return fact


def draft(problem_text: str, facts: list[dict]) -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
        "facts": facts,
        "questions": [],
        "candidate_claims": [],
        "unresolved": [],
        "model_metadata": {
            "adapter": "fake-llm",
            "provider": "test",
            "model": "fixture-model",
            "schema_version": "3.0.0",
            "prompt_template_id": "case-structuring-v3",
            "prompt_template_version": "4",
            "run_reference": "run:issue63",
            "generated_at": "2026-09-24T12:00:00Z",
            "routing_role": "primary",
        },
    }


class Issue0063CaseFactFidelityTests(unittest.TestCase):
    def test_frozen_issue63_missing_placeholders_are_rejected(self):
        facts = [
            case_fact(
                fact_ref="fact:1",
                label="Cliente extranjero",
                state="missing",
                needed_information=(
                    "¿Qué información sobre el cliente extranjero se requiere "
                    "para determinar si es un contribuyente colombiano o no?"
                ),
            ),
            case_fact(
                fact_ref="fact:2",
                label="Servicios prestados",
                state="missing",
                needed_information=(
                    "¿Qué información sobre los servicios prestados se requiere "
                    "para determinar si son exentos de IVA o no?"
                ),
            ),
            case_fact(
                fact_ref="fact:3",
                label="Condiciones de autorretención especial",
                state="missing",
                needed_information=(
                    "¿Qué información sobre las condiciones de autorretención "
                    "especial se requiere para determinar si se aplica la tarifa "
                    "del 19 % o no?"
                ),
            ),
            case_fact(
                fact_ref="fact:4",
                label="Ingreso del cliente extranjero",
                state="missing",
                needed_information=(
                    "¿Qué información sobre el ingreso del cliente extranjero "
                    "se requiere para determinar si forma parte de la base de la "
                    "autorretención especial y qué tarifa se aplica?"
                ),
            ),
        ]
        with self.assertRaises(CaseContractError) as raised:
            validate_case_draft(
                case_input(FROZEN_PROBLEM),
                draft(FROZEN_PROBLEM, facts),
            )
        self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
        self.assertIn("$.facts[0].state", raised.exception.detail)

    def test_each_safely_explicit_declarative_topic_is_rejected(self):
        cases = [
            (
                "Cliente extranjero",
                "¿Qué información sobre el cliente extranjero se requiere?",
            ),
            (
                "Servicios prestados",
                "¿Qué información sobre los servicios prestados se requiere?",
            ),
            (
                "Condiciones de autorretención especial",
                (
                    "¿Qué información sobre las condiciones de autorretención "
                    "especial se requiere?"
                ),
            ),
        ]
        for index, (label, needed) in enumerate(cases, start=1):
            with self.subTest(label=label):
                fact = case_fact(
                    fact_ref=f"fact:{index}",
                    label=label,
                    state="missing",
                    needed_information=needed,
                )
                with self.assertRaises(CaseContractError) as raised:
                    validate_case_draft(
                        case_input(FROZEN_PROBLEM),
                        draft(FROZEN_PROBLEM, [fact]),
                    )
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_verbatim_user_provided_fact_is_accepted(self):
        quote = (
            "El cliente extranjero no tiene domicilio, sucursal, establecimiento "
            "permanente, empleados, activos ni desarrolla negocios o actividades "
            "en Colombia."
        )
        fact = case_fact(
            fact_ref="fact:client",
            label="Cliente extranjero",
            state="user_provided",
            value="Sin presencia o actividad en Colombia",
            source_quote=quote,
        )
        validate_case_draft(
            case_input(FROZEN_PROBLEM),
            draft(FROZEN_PROBLEM, [fact]),
        )

    def test_concrete_genuinely_missing_fact_is_preserved(self):
        problem = "La fecha efectiva de disolución no fue informada."
        fact = case_fact(
            fact_ref="fact:date",
            label="Fecha efectiva de disolución",
            state="missing",
            needed_information="Indicar la fecha efectiva de disolución.",
        )
        validate_case_draft(case_input(problem), draft(problem, [fact]))

    def test_question_only_topic_does_not_prove_fact_presence(self):
        problem = "¿Cuál es la fecha efectiva de disolución?"
        fact = case_fact(
            fact_ref="fact:date",
            label="Fecha efectiva de disolución",
            state="missing",
            needed_information=(
                "¿Qué información sobre la fecha efectiva de disolución "
                "se requiere para responder?"
            ),
        )
        validate_case_draft(case_input(problem), draft(problem, [fact]))

    def test_ambiguous_fact_remains_ambiguous(self):
        problem = (
            "El contrato menciona dos fechas de terminación: "
            "1 y 15 de septiembre de 2026."
        )
        fact = case_fact(
            fact_ref="fact:end-date",
            label="Fecha de terminación",
            state="ambiguous",
            needed_information=(
                "Confirmar cuál de las dos fechas corresponde a la terminación."
            ),
        )
        validate_case_draft(case_input(problem), draft(problem, [fact]))

    def test_prompt_revision_encodes_issue63_fidelity_rule(self):
        self.assertEqual(PROMPT_TEMPLATE_VERSION, "5")
        self.assertIn("never downgrade that fact to missing", SYSTEM_PROMPT)
        self.assertIn("concrete datum absent from problem_text", SYSTEM_PROMPT)
        self.assertIn("Truly ambiguous information remains ambiguous", SYSTEM_PROMPT)
        self.assertIn("select source_quote exactly", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
