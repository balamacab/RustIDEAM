from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    intake_draft_generation_schema,
    validate_intake_draft,
)
from case_evaluators import (
    GROSS_INCOME_KEY,
    GROSS_PATRIMONY_KEY,
    evaluate_supported_rules,
)
from llm_client import V4_PROMPT_TEMPLATE_VERSION, V4_SYSTEM_PROMPT


NOW = "2026-09-27T18:00:00+00:00"
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

CASE_C = (
    "Una SAS colombiana contrató con una sociedad residente fiscal en España "
    "una solución empresarial compuesta por acceso SaaS, implementación remota, "
    "soporte técnico, capacitación y un conector instalable en servidores del "
    "cliente en Colombia. El contrato anual de 2026 vale USD 96.000. "
    "A 27 de septiembre de 2026 la SAS pregunta: (1) cómo debe analizar el IVA "
    "colombiano para cada componente; (2) si procede retención en la fuente a "
    "título de renta y de qué depende."
)

INCOME_QUOTE = (
    "Una persona natural residente fiscal en Colombia obtuvo durante el año "
    "gravable 2025 ingresos brutos por 1.100 UVT"
)
PATRIMONY_QUOTE = (
    "tenía un patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025."
)
DIGITAL_QUOTE = (
    "Sus ingresos provinieron de actividades digitales prestadas por cuenta propia."
)


def case_input(problem_text: str) -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": problem_text,
        "as_of_date": AS_OF,
    }


def metadata() -> dict:
    return {
        "adapter": "fixture",
        "provider": "fixture",
        "model": "fixture",
        "schema_version": "4.0.0",
        "prompt_template_id": "case-intake-v4",
        "prompt_template_version": V4_PROMPT_TEMPLATE_VERSION,
        "run_reference": "run:issue188",
        "generated_at": NOW,
        "routing_role": "intake_structuring",
    }


def draft(
    problem_text: str,
    *,
    facts: list[dict] | None = None,
    questions: list[dict] | None = None,
) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue188",
        "problem_text": problem_text,
        "as_of_date": AS_OF,
        "facts": facts or [],
        "questions": questions or [],
        "search_hints": [],
        "model_metadata": metadata(),
    }


def unresolved_fact(
    *,
    fact_ref: str,
    label: str,
    state: str,
    needed_information: str,
) -> dict:
    return {
        "kind": "intake_fact",
        "contract_version": "4.0.0",
        "fact_ref": fact_ref,
        "label": label,
        "state": state,
        "requires_confirmation": True,
        "needed_information": needed_information,
    }


def question(*, ref: str, text: str, category: str) -> dict:
    return {
        "kind": "case_question",
        "contract_version": "4.0.0",
        "question_ref": ref,
        "text": text,
        "category": category,
        "status": "open",
    }


def corrected_a_draft() -> dict:
    facts = [
        {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:residence",
            "label": "Persona natural residente fiscal en Colombia",
            "value": "Colombia",
            "state": "user_provided",
            "source_quote": INCOME_QUOTE,
            "requires_confirmation": False,
        },
        {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:gross-income",
            "label": "Ingresos brutos informados por el cliente",
            "value": "1100",
            "semantic_key": GROSS_INCOME_KEY,
            "measurement": {
                "decimal_value": "1100",
                "unit": "UVT",
                "uvt_year": 2025,
            },
            "state": "user_provided",
            "source_quote": INCOME_QUOTE,
            "requires_confirmation": False,
        },
        {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:gross-patrimony",
            "label": "Patrimonio bruto informado por el cliente",
            "value": "3900",
            "semantic_key": GROSS_PATRIMONY_KEY,
            "measurement": {
                "decimal_value": "3900",
                "unit": "UVT",
                "uvt_year": 2025,
            },
            "state": "user_provided",
            "source_quote": PATRIMONY_QUOTE,
            "requires_confirmation": False,
        },
        {
            "kind": "intake_fact",
            "contract_version": "4.0.0",
            "fact_ref": "fact:digital-activity",
            "label": "Actividades digitales por cuenta propia",
            "value": "actividades digitales prestadas por cuenta propia",
            "state": "user_provided",
            "source_quote": DIGITAL_QUOTE,
            "requires_confirmation": False,
        },
    ]
    legal_question = {
        **question(
            ref="question:filing",
            text=(
                "¿Qué condiciones legales deben revisarse para establecer si "
                "estaba obligada a presentar declaración de renta?"
            ),
            category="legal",
        ),
        "depends_on_fact_refs": [
            "fact:gross-income",
            "fact:gross-patrimony",
        ],
    }
    return draft(CASE_A, facts=facts, questions=[legal_question])


RULE_TEXT = (
    "ARTÍCULO 592. QUIÉNES NO ESTÁN OBLIGADOS A DECLARAR. "
    "Para este supuesto, el patrimonio bruto no exceda de 4.500 UVT "
    "y los ingresos brutos sean inferiores a 1.400 UVT."
)
AUTHORITY_REF = "authority:DOC-et-592"
EVIDENCE_REF = "evidence:article-592-thresholds"
RULE_REF = "rule:article-592-thresholds"


class Issue0188IntakeFidelityTests(unittest.TestCase):
    def test_a_style_explicit_facts_cannot_be_downgraded_to_ambiguous(self):
        actual_failed_facts = [
            (
                "fact:1",
                "Persona natural residente fiscal en Colombia.",
                "Confirmar la residencia fiscal de la persona natural en Colombia.",
            ),
            (
                "fact:2",
                "Ingresos brutos por 1.100 UVT durante el año gravable 2025.",
                (
                    "Confirmar la naturaleza de los ingresos (si son ingresos "
                    "gravables) y la forma exacta de cálculo de la UVT para el año 2025."
                ),
            ),
            (
                "fact:3",
                "Patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025.",
                (
                    "Confirmar la naturaleza del patrimonio (si es patrimonio bruto "
                    "gravable) y la forma exacta de cálculo de la UVT para el año 2025."
                ),
            ),
            (
                "fact:4",
                "Los ingresos provinieron de actividades digitales prestadas por cuenta propia.",
                (
                    "Detallar la naturaleza jurídica de las actividades digitales "
                    "prestadas por cuenta propia para determinar el régimen tributario aplicable."
                ),
            ),
        ]
        for fact_ref, label, needed in actual_failed_facts:
            with self.subTest(fact_ref=fact_ref):
                payload = draft(
                    CASE_A,
                    facts=[
                        unresolved_fact(
                            fact_ref=fact_ref,
                            label=label,
                            state="ambiguous",
                            needed_information=needed,
                        )
                    ],
                )
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(case_input(CASE_A), payload)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
                self.assertIn("already stated", raised.exception.detail)

    def test_b_style_confirmation_requests_cannot_hide_stated_facts_as_missing(self):
        actual_failed_facts = [
            (
                "location",
                "Ubicación del prestador de servicios",
                "Confirmación de que el servicio se ejecuta desde Bogotá.",
            ),
            (
                "customer",
                "Domicilio del cliente",
                "Confirmación de que el cliente es una sociedad domiciliada en Canadá.",
            ),
            (
                "presence",
                "Ausencia de presencia física del cliente en Colombia",
                (
                    "Confirmación de que el cliente no tiene domicilio, sucursal, "
                    "establecimiento permanente, empleados ni activos en Colombia."
                ),
            ),
            (
                "execution",
                "Ejecución del servicio",
                "Confirmación de que el trabajo se ejecuta desde Colombia.",
            ),
            (
                "use",
                "Uso de los entregables",
                (
                    "Confirmación de que los informes, tableros y recomendaciones "
                    "se usan exclusivamente por el cliente para campañas dirigidas "
                    "a Canadá y Chile y no se usan ni se explotan en Colombia."
                ),
            ),
            (
                "documents",
                "Documentación existente",
                (
                    "Confirmación de que la SAS conserva contrato escrito, facturas, "
                    "comprobantes bancarios, entregables y constancias de aceptación del cliente."
                ),
            ),
            (
                "payment",
                "Fecha de facturación y pago",
                "Confirmación de que la factura se emitió y recibió el pago en agosto de 2026.",
            ),
        ]
        for suffix, label, needed in actual_failed_facts:
            with self.subTest(fact=suffix):
                payload = draft(
                    CASE_B,
                    facts=[
                        unresolved_fact(
                            fact_ref=f"fact:{suffix}",
                            label=label,
                            state="missing",
                            needed_information=needed,
                        )
                    ],
                )
                with self.assertRaises(CaseContractError) as raised:
                    validate_intake_draft(case_input(CASE_B), payload)
                self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
                self.assertIn("already stated", raised.exception.detail)

    def test_substantive_iva_treatment_question_cannot_be_temporal(self):
        payload = draft(
            CASE_C,
            questions=[
                question(
                    ref="question:iva",
                    text="(1) cómo debe analizar el IVA colombiano para cada componente?",
                    category="temporal",
                )
            ],
        )
        with self.assertRaises(CaseContractError) as raised:
            validate_intake_draft(case_input(CASE_C), payload)
        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("incompatible non-legal category", raised.exception.detail)

    def test_export_iva_treatment_question_cannot_be_temporal(self):
        text = (
            "¿Puede el servicio prestado por la SAS colombiana tratarse como "
            "exportación de servicios para efectos del IVA?"
        )
        payload = draft(
            CASE_B,
            questions=[
                question(ref="question:export-iva", text=text, category="temporal")
            ],
        )
        with self.assertRaises(CaseContractError):
            validate_intake_draft(case_input(CASE_B), payload)

    def test_genuinely_missing_and_ambiguous_facts_remain_allowed(self):
        missing_problem = "Una SAS colombiana presta servicios digitales."
        missing = draft(
            missing_problem,
            facts=[
                unresolved_fact(
                    fact_ref="fact:client-domicile",
                    label="Domicilio del cliente extranjero",
                    state="missing",
                    needed_information="País de domicilio del cliente extranjero.",
                )
            ],
        )
        validate_intake_draft(case_input(missing_problem), missing)

        ambiguous_problem = (
            "El cliente indica que su domicilio podría ser Canadá o Chile."
        )
        ambiguous = draft(
            ambiguous_problem,
            facts=[
                unresolved_fact(
                    fact_ref="fact:client-domicile",
                    label="Domicilio del cliente",
                    state="ambiguous",
                    needed_information="Confirmar si el domicilio es Canadá o Chile.",
                )
            ],
        )
        validate_intake_draft(case_input(ambiguous_problem), ambiguous)

    def test_genuine_temporal_tax_question_remains_temporal(self):
        problem = "La norma de IVA tiene una fecha de vigencia por establecer."
        payload = draft(
            problem,
            questions=[
                question(
                    ref="question:effective-date",
                    text="¿Desde cuándo está vigente la norma de IVA?",
                    category="temporal",
                )
            ],
        )
        validate_intake_draft(case_input(problem), payload)

    def test_legal_qualification_uncertainty_does_not_erase_client_assertion(self):
        problem = "La persona afirma ser residente fiscal en Colombia."
        payload = draft(
            problem,
            facts=[
                {
                    "kind": "intake_fact",
                    "contract_version": "4.0.0",
                    "fact_ref": "fact:asserted-residence",
                    "label": "Residencia fiscal declarada por el cliente",
                    "value": "Colombia",
                    "state": "user_provided",
                    "source_quote": problem,
                    "requires_confirmation": False,
                }
            ],
            questions=[
                question(
                    ref="question:residence-law",
                    text="¿Cumple los requisitos legales de residencia fiscal en Colombia?",
                    category="legal",
                )
            ],
        )
        validate_intake_draft(case_input(problem), payload)
        self.assertEqual(payload["facts"][0]["state"], "user_provided")

    def test_v4_generation_offers_exact_fact_sized_quotes_for_a(self):
        schema = intake_draft_generation_schema(case_input(CASE_A))
        user_variant = next(
            variant
            for variant in schema["$defs"]["IntakeFact"]["oneOf"]
            if variant["properties"]["state"]["const"] == "user_provided"
        )
        candidates = user_variant["properties"]["source_quote"]["enum"]

        self.assertIn(INCOME_QUOTE, candidates)
        self.assertIn(PATRIMONY_QUOTE, candidates)
        self.assertIn(DIGITAL_QUOTE, candidates)
        for candidate in candidates:
            self.assertIn(candidate, CASE_A)

    def test_corrected_a_preserves_values_year_and_can_drive_bounded_evaluator(self):
        payload = corrected_a_draft()
        ci = case_input(CASE_A)
        validate_intake_draft(ci, payload)

        authority = {
            "authority_ref": AUTHORITY_REF,
            "temporal_state": {
                "resolution_state": "resolved",
                "effective": True,
                "basis_evidence_refs": [],
                "as_of_date": AS_OF,
            },
        }
        evidence = {
            "evidence_ref": EVIDENCE_REF,
            "exact_text": RULE_TEXT,
            "text_sha256": hashlib.sha256(RULE_TEXT.encode("utf-8")).hexdigest(),
        }
        rule = {
            "kind": "rule_fragment",
            "contract_version": "4.0.0",
            "rule_ref": RULE_REF,
            "rule_type": "canonical_source_statement",
            "rule_schema_version": "1",
            "structured_data": {
                "statement_scope": "canonical_provision",
                "document_ref": "document:DOC-et-592",
                "authority_ref": AUTHORITY_REF,
                "evidence_refs": [EVIDENCE_REF],
                "provision_ref": "provision:ART-592",
                "provision_type": "article",
                "designation": "Artículo 592",
            },
            "derivation": {
                "method": "extractive_normalization",
                "version": "1",
            },
            "authority_refs": [AUTHORITY_REF],
            "evidence_refs": [EVIDENCE_REF],
            "as_of_date": AS_OF,
        }

        outcome = evaluate_supported_rules(
            case_input=ci,
            intake_draft=payload,
            authorities=[authority],
            evidence_spans=[evidence],
            rule_fragments=[rule],
            generated_at=NOW,
        )

        self.assertEqual(len(outcome.evaluations), 1)
        self.assertEqual(outcome.evaluations[0]["status"], "determined")
        self.assertEqual(len(outcome.calculations), 2)
        by_fact = {
            trace["inputs"][0]["source_fact_ref"]: trace
            for trace in outcome.calculations
        }
        self.assertEqual(
            by_fact["fact:gross-income"]["inputs"][0],
            {
                "name": "observed",
                "decimal_value": "1100",
                "unit": "UVT@2025",
                "source_fact_ref": "fact:gross-income",
            },
        )
        self.assertEqual(
            by_fact["fact:gross-patrimony"]["inputs"][0]["decimal_value"],
            "3900",
        )

    def test_prompt_v2_preserves_fact_vs_legal_uncertainty_boundary(self):
        self.assertEqual(V4_PROMPT_TEMPLATE_VERSION, "2")
        self.assertIn("do not downgrade it to missing or\nambiguous", V4_SYSTEM_PROMPT)
        self.assertIn(GROSS_INCOME_KEY, V4_SYSTEM_PROMPT)
        self.assertIn(GROSS_PATRIMONY_KEY, V4_SYSTEM_PROMPT)
        self.assertIn('category="legal"', V4_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
