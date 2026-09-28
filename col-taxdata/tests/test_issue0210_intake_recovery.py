from __future__ import annotations

from copy import deepcopy
import hashlib
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
from case_evaluators import evaluate_supported_rules
from deterministic_intake_adapter import DeterministicIntakeAdapter
from llm_client import CaseStructuringService, LLMPlatformConfig, ModelRoute


AS_OF = "2026-09-27"
NOW = "2026-09-27T18:00:00+00:00"

CASE_A = (
    "Una persona natural residente fiscal en Colombia obtuvo durante el año "
    "gravable 2025 ingresos brutos por 1.100 UVT y tenía un patrimonio bruto "
    "de 3.900 UVT al 31 de diciembre de 2025. Los dos valores están expresados "
    "usando la UVT del año 2025. Sus ingresos provinieron de actividades "
    "digitales prestadas por cuenta propia. A 27 de septiembre de 2026 quiere "
    "saber qué condiciones legales deben revisarse para establecer si estaba "
    "obligada a presentar declaración de renta por el año gravable 2025."
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
    "tratarse como exportación de servicios para efectos del IVA."
)

CASE_C = (
    "Una SAS colombiana contrató con una sociedad residente fiscal en España "
    "una solución empresarial compuesta por acceso SaaS, implementación remota, "
    "soporte técnico, capacitación y un conector instalable en servidores del "
    "cliente en Colombia. A 27 de septiembre de 2026 la SAS pregunta cómo debe "
    "analizar el IVA colombiano para cada componente."
)


def case_input(problem_text: str, *, version: str = "4.0.0") -> dict:
    return {
        "kind": "case_input",
        "contract_version": version,
        "problem_text": problem_text,
        "as_of_date": AS_OF,
    }


def unresolved(
    fact_ref: str,
    label: str,
    needed_information: str,
    *,
    state: str = "missing",
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


def question(ref: str, text: str, category: str = "legal") -> dict:
    return {
        "kind": "case_question",
        "contract_version": "4.0.0",
        "question_ref": ref,
        "text": text,
        "category": category,
        "status": "open",
    }


def draft(
    problem_text: str,
    facts: list[dict],
    *,
    questions: list[dict] | None = None,
) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue210",
        "problem_text": problem_text,
        "as_of_date": AS_OF,
        "facts": facts,
        "questions": [] if questions is None else questions,
        "search_hints": [],
    }


def config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="deterministic",
        provider="issue210-provider",
        base_url="http://127.0.0.1:1/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("issue210-model", "primary", 100_000, 4096),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


def structure(ci: dict, generated: dict) -> dict:
    return CaseStructuringService(
        config(),
        DeterministicIntakeAdapter([generated]),
    ).structure(ci).intake


class Issue0210IntakeRecoveryTests(unittest.TestCase):
    def test_a_style_provider_downgrades_are_promoted_from_exact_client_text(self):
        facts = [
            unresolved(
                "fact:residence",
                "Persona natural residente fiscal en Colombia",
                "Confirmar la residencia fiscal de la persona natural en Colombia.",
                state="ambiguous",
            ),
            unresolved(
                "fact:gross-income",
                "Ingresos brutos por 1.100 UVT durante el año gravable 2025",
                "Confirmar los ingresos brutos por 1.100 UVT del año 2025.",
                state="ambiguous",
            ),
            unresolved(
                "fact:gross-patrimony",
                "Patrimonio bruto de 3.900 UVT al 31 de diciembre de 2025",
                "Confirmar el patrimonio bruto de 3.900 UVT del año 2025.",
                state="ambiguous",
            ),
            unresolved(
                "fact:digital-activity",
                "Actividades digitales prestadas por cuenta propia",
                "Confirmar las actividades digitales prestadas por cuenta propia.",
                state="ambiguous",
            ),
        ]
        result = structure(case_input(CASE_A), draft(CASE_A, facts))
        by_ref = {fact["fact_ref"]: fact for fact in result["facts"]}

        for fact in by_ref.values():
            self.assertEqual(fact["state"], "user_provided")
            self.assertFalse(fact["requires_confirmation"])
            self.assertNotIn("needed_information", fact)
            self.assertIn(fact["source_quote"], CASE_A)

        income = by_ref["fact:gross-income"]
        patrimony = by_ref["fact:gross-patrimony"]
        self.assertEqual(
            income["semantic_key"],
            "col.tax.natural_person.gross_income",
        )
        self.assertEqual(
            income["measurement"],
            {"decimal_value": "1100", "unit": "UVT", "uvt_year": 2025},
        )
        self.assertEqual(
            patrimony["semantic_key"],
            "col.tax.natural_person.gross_patrimony",
        )
        self.assertEqual(
            patrimony["measurement"],
            {"decimal_value": "3900", "unit": "UVT", "uvt_year": 2025},
        )
        self.assertEqual(income["source_quote"].count("UVT"), 1)
        self.assertEqual(patrimony["source_quote"].count("UVT"), 1)

        rule_text = (
            "ARTÍCULO 592. Para este supuesto, el patrimonio bruto no exceda "
            "de 4.500 UVT y los ingresos brutos sean inferiores a 1.400 UVT."
        )
        authority_ref = "authority:DOC-et-592"
        evidence_ref = "evidence:article-592"
        rule_ref = "rule:article-592"
        outcome = evaluate_supported_rules(
            case_input=case_input(CASE_A),
            intake_draft=result,
            authorities=[
                {
                    "authority_ref": authority_ref,
                    "temporal_state": {
                        "resolution_state": "resolved",
                        "effective": True,
                        "basis_evidence_refs": [],
                        "as_of_date": AS_OF,
                    },
                }
            ],
            evidence_spans=[
                {
                    "evidence_ref": evidence_ref,
                    "exact_text": rule_text,
                    "text_sha256": hashlib.sha256(
                        rule_text.encode("utf-8")
                    ).hexdigest(),
                }
            ],
            rule_fragments=[
                {
                    "kind": "rule_fragment",
                    "contract_version": "4.0.0",
                    "rule_ref": rule_ref,
                    "rule_type": "canonical_source_statement",
                    "rule_schema_version": "1",
                    "structured_data": {
                        "statement_scope": "canonical_provision",
                        "document_ref": "document:DOC-et-592",
                        "authority_ref": authority_ref,
                        "evidence_refs": [evidence_ref],
                        "provision_ref": "provision:ART-592",
                        "provision_type": "article",
                        "designation": "Artículo 592",
                    },
                    "derivation": {
                        "method": "extractive_normalization",
                        "version": "1",
                    },
                    "authority_refs": [authority_ref],
                    "evidence_refs": [evidence_ref],
                    "as_of_date": AS_OF,
                }
            ],
            generated_at=NOW,
        )
        self.assertEqual(len(outcome.evaluations), 1)
        self.assertEqual(outcome.evaluations[0]["status"], "determined")
        self.assertEqual(len(outcome.calculations), 2)

    def test_b_style_confirmation_requests_are_promoted_without_inventing_facts(self):
        facts = [
            unresolved(
                "fact:sas",
                "SAS colombiana prestadora de servicios",
                "Confirmar que el prestador es una SAS colombiana.",
            ),
            unresolved(
                "fact:bogota",
                "Ubicación del prestador de servicios",
                "Confirmación de que el servicio se ejecuta desde Bogotá.",
            ),
            unresolved(
                "fact:customer",
                "Domicilio del cliente",
                "Confirmación de que el cliente es una sociedad domiciliada en Canadá.",
            ),
            unresolved(
                "fact:presence",
                "Ausencia de presencia física del cliente en Colombia",
                "Confirmar la ausencia de domicilio, sucursal, establecimiento permanente, empleados y activos en Colombia.",
            ),
            unresolved(
                "fact:execution",
                "Ejecución del servicio",
                "Confirmación de que el trabajo se ejecuta desde Colombia.",
            ),
            unresolved(
                "fact:use",
                "Uso exclusivo extranjero de los entregables",
                "Confirmar que los entregables se usan exclusivamente fuera de Colombia.",
            ),
            unresolved(
                "fact:documents",
                "Documentación y soportes conservados",
                "Confirmar contrato, facturas, comprobantes, entregables y constancias de aceptación.",
            ),
            unresolved(
                "fact:payment",
                "Fecha de facturación y pago",
                "Confirmar facturación y pago en agosto de 2026.",
            ),
        ]
        result = structure(
            case_input(CASE_B),
            draft(
                CASE_B,
                facts,
                questions=[
                    question(
                        "question:iva-export",
                        "¿Puede tratarse como exportación de servicios para efectos del IVA?",
                    )
                ],
            ),
        )

        self.assertEqual(len(result["facts"]), len(facts))
        for fact in result["facts"]:
            self.assertEqual(fact["state"], "user_provided", fact["fact_ref"])
            self.assertFalse(fact["requires_confirmation"])
            self.assertNotIn("needed_information", fact)
            self.assertIn(fact["source_quote"], CASE_B)
            self.assertNotIn("semantic_key", fact)
            self.assertNotIn("measurement", fact)

    def test_genuine_client_ambiguity_remains_ambiguous(self):
        problem = "El cliente indica que su domicilio podría ser Canadá o Chile."
        generated = draft(
            problem,
            [
                unresolved(
                    "fact:domicile",
                    "Domicilio del cliente en Canadá",
                    "Confirmar si el domicilio del cliente es Canadá o Chile.",
                    state="ambiguous",
                )
            ],
        )
        result = structure(case_input(problem), generated)
        self.assertEqual(result["facts"][0]["state"], "ambiguous")
        self.assertTrue(result["facts"][0]["requires_confirmation"])

    def test_genuinely_missing_fact_remains_missing(self):
        problem = "Una SAS colombiana presta servicios digitales."
        generated = draft(
            problem,
            [
                unresolved(
                    "fact:customer",
                    "Domicilio del cliente canadiense",
                    "Indicar el país de domicilio del cliente.",
                )
            ],
        )
        result = structure(case_input(problem), generated)
        self.assertEqual(result["facts"][0]["state"], "missing")

    def test_duplicate_exact_candidate_span_is_not_guessed(self):
        sentence = "La sociedad cliente está domiciliada en Canadá."
        problem = f"{sentence} {sentence}"
        generated = draft(
            problem,
            [
                unresolved(
                    "fact:customer",
                    "Domicilio de la sociedad cliente en Canadá",
                    "Confirmar que la sociedad cliente está domiciliada en Canadá.",
                )
            ],
        )
        normalized = normalize_intake_draft(case_input(problem), generated)
        self.assertEqual(normalized["facts"][0]["state"], "missing")
        self.assertNotIn("source_quote", normalized["facts"][0])

    def test_unsupported_semantic_concept_is_not_synthesized(self):
        problem = "El contrato anual de 2026 vale USD 96.000."
        generated = draft(
            problem,
            [
                unresolved(
                    "fact:contract-value",
                    "Valor anual del contrato",
                    "Confirmar el valor anual de USD 96.000.",
                )
            ],
        )
        normalized = normalize_intake_draft(case_input(problem), generated)
        self.assertEqual(normalized, generated)

    def test_unknown_fields_fail_before_normalization_can_hide_them(self):
        generated = draft(
            CASE_A,
            [
                {
                    **unresolved(
                        "fact:gross-income",
                        "Ingresos brutos por 1.100 UVT durante 2025",
                        "Confirmar ingresos brutos por 1.100 UVT en 2025.",
                        state="ambiguous",
                    ),
                    "invented_field": "must not be dropped",
                }
            ],
        )
        with self.assertRaises(CaseContractError) as raised:
            structure(case_input(CASE_A), generated)
        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_c_style_legal_question_is_preserved_without_relabeling(self):
        generated = draft(
            CASE_C,
            [],
            questions=[
                question(
                    "question:iva",
                    "¿Cómo debe analizar el IVA colombiano para cada componente?",
                    "legal",
                )
            ],
        )
        result = structure(case_input(CASE_C), generated)
        self.assertEqual(result["questions"][0]["category"], "legal")

    def test_normalization_is_idempotent_and_does_not_mutate_input(self):
        generated = draft(
            CASE_A,
            [
                unresolved(
                    "fact:gross-income",
                    "Ingresos brutos por 1.100 UVT durante el año gravable 2025",
                    "Confirmar ingresos brutos por 1.100 UVT durante 2025.",
                    state="ambiguous",
                )
            ],
        )
        original = deepcopy(generated)
        first = normalize_intake_draft(case_input(CASE_A), generated)
        second = normalize_intake_draft(case_input(CASE_A), first)
        self.assertEqual(generated, original)
        self.assertEqual(first, second)

    def test_v3_payload_is_not_rewritten_by_v4_normalizer(self):
        v3_case = {
            "kind": "case_input",
            "contract_version": "3.0.0",
            "problem_text": "Texto histórico.",
        }
        historical = {"kind": "case_draft", "contract_version": "3.0.0"}
        self.assertEqual(
            normalize_intake_draft(v3_case, historical),
            historical,
        )


if __name__ == "__main__":
    unittest.main()
