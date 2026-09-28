from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
for path in (TESTS, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from deterministic_intake_adapter import DeterministicIntakeAdapter
from issue0237_intake_boundary import (
    CASE_TEXTS,
    PROFILE_PATH,
    RawCandidateObserver,
    ValidationRunnerError,
    execute_case,
    load_issue0237_profile,
    recovery_path_exercised,
    score_boundary,
)
import issue0237_intake_boundary as runner
from test_issue0210_intake_recovery import (
    CASE_A,
    CASE_B,
    CASE_C,
    config,
    draft,
    question,
    unresolved,
)


PROTECTED_SHA = "a" * 40


def raw_a() -> dict:
    return draft(
        CASE_A,
        [
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
        ],
    )


def raw_b() -> dict:
    return draft(
        CASE_B,
        [
            unresolved("fact:sas", "SAS colombiana prestadora de servicios", "Confirmar que el prestador es una SAS colombiana."),
            unresolved("fact:bogota", "Ubicación del prestador de servicios", "Confirmación de que el servicio se ejecuta desde Bogotá."),
            unresolved("fact:customer", "Domicilio del cliente", "Confirmación de que el cliente es una sociedad domiciliada en Canadá."),
            unresolved("fact:presence", "Ausencia de presencia física del cliente en Colombia", "Confirmar la ausencia de domicilio, sucursal, establecimiento permanente, empleados y activos en Colombia."),
            unresolved("fact:execution", "Ejecución del servicio", "Confirmación de que el trabajo se ejecuta desde Colombia."),
            unresolved("fact:use", "Uso exclusivo extranjero de los entregables", "Confirmar que los entregables se usan exclusivamente fuera de Colombia."),
            unresolved("fact:documents", "Documentación y soportes conservados", "Confirmar contrato, facturas, comprobantes, entregables y constancias de aceptación."),
            unresolved("fact:payment", "Fecha de facturación y pago", "Confirmar facturación y pago en agosto de 2026."),
        ],
        questions=[
            question(
                "question:iva-export",
                "¿Puede tratarse como exportación de servicios para efectos del IVA?",
            )
        ],
    )


def raw_c() -> dict:
    return draft(
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


class IdentityDelegate:
    adapter_id = "identity-test"
    provider_id = "identity-provider"
    structured_generation_capability = DeterministicIntakeAdapter.structured_generation_capability

    def __init__(self, candidate: dict):
        self.candidate = candidate
        self.calls = 0

    def structure_intake(self, *, case_input: dict, route: object) -> dict:
        del case_input, route
        self.calls += 1
        return self.candidate


class Issue0237BoundaryRunnerTests(unittest.TestCase):
    def test_runner_reuses_exact_issue210_case_objects(self):
        self.assertIs(CASE_TEXTS["A"], CASE_A)
        self.assertIs(CASE_TEXTS["B"], CASE_B)
        self.assertIs(CASE_TEXTS["C"], CASE_C)

    def test_observer_returns_delegate_candidate_unchanged_and_snapshots_raw(self):
        candidate = raw_c()
        original = deepcopy(candidate)
        delegate = IdentityDelegate(candidate)
        observer = RawCandidateObserver(delegate)

        returned = observer.structure_intake(case_input={}, route=object())

        self.assertIs(returned, candidate)
        self.assertEqual(candidate, original)
        self.assertEqual(observer.raw_candidate, original)
        self.assertIsNot(observer.raw_candidate, candidate)
        self.assertEqual(observer.adapter_id, delegate.adapter_id)
        self.assertEqual(observer.provider_id, delegate.provider_id)
        self.assertIs(
            observer.structured_generation_capability,
            delegate.structured_generation_capability,
        )

    def test_observer_blocks_second_provider_inference_before_delegate(self):
        delegate = IdentityDelegate(raw_c())
        observer = RawCandidateObserver(delegate)
        observer.structure_intake(case_input={}, route=object())
        with self.assertRaises(ValidationRunnerError):
            observer.structure_intake(case_input={}, route=object())
        self.assertEqual(delegate.calls, 1)
        self.assertEqual(observer.provider_calls, 1)

    def test_admitted_profile_is_exactly_one_attempt_without_review(self):
        profile, loaded = load_issue0237_profile(PROFILE_PATH)
        self.assertEqual(profile["profile_id"], "case-migration-rtx3070-v1")
        self.assertEqual(profile["admission"]["issue_number"], 133)
        self.assertEqual(loaded.primary_attempts, 1)
        self.assertFalse(loaded.review_on_invalid_output)
        self.assertFalse(loaded.review_on_provider_error)
        self.assertEqual(loaded.request_options.get("n"), 1)

    def test_a_boundary_recovers_raw_downgrades_and_scores_only_intake(self):
        adapter = DeterministicIntakeAdapter([raw_a()])
        result = execute_case(
            "A",
            config=config(),
            profile_id="test",
            protected_main_sha=PROTECTED_SHA,
            adapter=adapter,
            require_provider_evidence=False,
        )
        self.assertEqual(result["status"], "PASS", result["failure_cause"])
        self.assertEqual(result["provider_calls"], 1)
        self.assertTrue(result["RECOVERY_PATH_EXERCISED"])
        self.assertNotEqual(
            result["candidate_raw_sha256"],
            result["final_intake_sha256"],
        )
        raw_states = {fact["fact_ref"]: fact["state"] for fact in result["RAW_PROVIDER"]["facts"]}
        final_states = {fact["fact_ref"]: fact["state"] for fact in result["FINAL_INTAKE"]["facts"]}
        self.assertEqual(raw_states["fact:gross-income"], "ambiguous")
        self.assertEqual(final_states["fact:gross-income"], "user_provided")

    def test_b_and_c_boundary_scoring_preserves_exact_scope(self):
        b_adapter = DeterministicIntakeAdapter([raw_b()])
        b = execute_case(
            "B",
            config=config(),
            profile_id="test",
            protected_main_sha=PROTECTED_SHA,
            adapter=b_adapter,
            require_provider_evidence=False,
        )
        self.assertEqual(b["status"], "PASS", b["failure_cause"])
        self.assertTrue(b["RECOVERY_PATH_EXERCISED"])

        c_adapter = DeterministicIntakeAdapter([raw_c()])
        c = execute_case(
            "C",
            config=config(),
            profile_id="test",
            protected_main_sha=PROTECTED_SHA,
            adapter=c_adapter,
            require_provider_evidence=False,
        )
        self.assertEqual(c["status"], "PASS", c["failure_cause"])
        self.assertFalse(c["RECOVERY_PATH_EXERCISED"])
        self.assertEqual(c["FINAL_INTAKE"]["questions"][0]["category"], "legal")

    def test_scoring_fails_only_boundary_invariants_not_downstream_components(self):
        final = raw_c()
        final["questions"][0]["category"] = "procedural"
        failures = score_boundary("C", final)
        self.assertTrue(any("category=legal" in failure or "degraded" in failure for failure in failures))

        with patch.dict(sys.modules, {"case_application": object()}):
            adapter = DeterministicIntakeAdapter([raw_c()])
            result = execute_case(
                "C",
                config=config(),
                profile_id="test",
                protected_main_sha=PROTECTED_SHA,
                adapter=adapter,
                require_provider_evidence=False,
            )
        self.assertEqual(result["status"], "PASS", result["failure_cause"])

    def test_runner_source_has_no_downstream_or_persistence_import_path(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = {
            "case_application",
            "sqlite3",
            "case_mcp_gateway",
            "case_rest_api",
            "case_research",
            "case_authority_resolution",
        }
        self.assertTrue(forbidden.isdisjoint(imported), imported.intersection(forbidden))
        self.assertNotIn("TestCasePool", source)
        self.assertNotIn("analyze_case(", source)

    def test_recovery_flag_requires_same_fact_ref_raw_to_final_transition(self):
        raw = raw_a()
        final = deepcopy(raw)
        final["facts"][0].update(
            {
                "state": "user_provided",
                "requires_confirmation": False,
                "source_quote": "Una persona natural residente fiscal en Colombia",
            }
        )
        final["facts"][0].pop("needed_information", None)
        self.assertTrue(recovery_path_exercised(raw, final, CASE_A))
        final["facts"][0]["fact_ref"] = "fact:different"
        self.assertFalse(recovery_path_exercised(raw, final, CASE_A))


if __name__ == "__main__":
    unittest.main()
