from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_benchmark
import case_validation
from llm_client import load_platform_config


class Issue75ReferenceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = case_validation.load_json(case_validation.DEFAULT_PROFILE)
        self.reference = self.profile["reference_backend"]
        self.generation = deepcopy(self.profile["generation"])

    def capability(
        self,
        backend: dict,
        *,
        available: bool = True,
        capability_pass: bool = True,
        served_model: str | None = None,
        generation: dict | None = None,
    ) -> dict:
        record = {
            "available": available,
            "capability_pass": capability_pass,
            "served_model": served_model or backend["requested_model_name"],
            "generation": deepcopy(generation or self.generation),
        }
        if "artifact_sha256" in backend:
            record["model_artifact_sha256"] = backend["artifact_sha256"]
        return record

    def test_reference_profile_and_historical_package_verify(self) -> None:
        result = case_validation.verify_profile()
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["historical_benchmark_valid"])
        self.assertEqual(result["historical_planned_runs"], 9)
        self.assertEqual(
            result["problem_text_sha256"],
            "ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1",
        )
        self.assertEqual(
            result["canonical_case_input_sha256"],
            "9a88c7d1f818e22ef310ef52a4185d2795d3e51ddd374d22b25e713b522171d4",
        )
        self.assertEqual(
            result["request_sha256"],
            "b0b36bf6ab5c5d46572aee434933b4a87f830c953ef26ee17c78734c82a9b763",
        )
        self.assertEqual(
            result["expected_case_id"],
            "CASE-31fdda05d776558393b16095880202d7",
        )

    def test_historical_issue65_plan_remains_three_by_three(self) -> None:
        historical = case_benchmark.load_json(case_benchmark.DEFAULT_SPEC)
        self.assertEqual(len(historical["model_matrix"]), 3)
        self.assertEqual(len(case_benchmark.build_run_plan(historical)), 9)

    def test_reference_llm_profile_routes_structuring_through_gemma(self) -> None:
        config = load_platform_config(
            ROOT / self.profile["application"]["llm_platform_config"]
        )
        self.assertEqual(config.adapter, "openai-compatible")
        self.assertEqual(config.provider, "local-llama-cpp")
        self.assertEqual(config.primary.name, "gemma-4-E2B-it-Q4_K_M")
        self.assertEqual(config.primary.routing_role, "primary")
        self.assertEqual(config.primary.context_tokens, 16384)
        self.assertEqual(config.primary.max_output_tokens, 9000)
        self.assertEqual(config.timeout_seconds, 7200)
        self.assertEqual(config.primary_attempts, 1)
        self.assertFalse(config.review_on_invalid_output)
        self.assertFalse(config.review_on_provider_error)

    def test_primary_validation_plan_contains_exactly_one_required_reference_run(self) -> None:
        plan = case_validation.build_validation_plan(self.profile)
        self.assertEqual(len(plan["required_phase_a"]), 1)
        run = plan["required_phase_a"][0]
        self.assertTrue(run["required"])
        self.assertEqual(run["backend_id"], self.reference["id"])
        self.assertEqual(run["generation"], self.generation)
        self.assertEqual(
            run["http"],
            {
                "method": "POST",
                "endpoint": "/v1/cases",
                "adapter": "tools/case_http.py",
            },
        )
        self.assertEqual(len(plan["supplemental_diagnostics"]), 2)
        self.assertTrue(all(not item["required"] for item in plan["supplemental_diagnostics"]))

    def test_core_readiness_passes_when_fastflowlm_is_unavailable(self) -> None:
        report = {
            "backends": {
                self.reference["id"]: self.capability(self.reference),
            }
        }
        result = case_validation.evaluate_readiness(report, self.profile)
        self.assertTrue(result["core_ready"])
        self.assertFalse(result["experimental_backends_gate_core"])
        self.assertTrue(all(not item["blocking"] for item in result["experimental_backends"]))
        self.assertTrue(all(item["status"] == "unavailable" for item in result["experimental_backends"]))

    def test_unavailable_experimental_backend_is_reported_but_non_blocking(self) -> None:
        optional = self.profile["experimental_backends"][0]
        report = {
            "backends": {
                self.reference["id"]: self.capability(self.reference),
                optional["id"]: {"available": False},
            }
        }
        result = case_validation.evaluate_readiness(report, self.profile)
        observed = next(
            item for item in result["experimental_backends"]
            if item["backend_id"] == optional["id"]
        )
        self.assertEqual(observed["status"], "unavailable")
        self.assertFalse(observed["blocking"])
        self.assertTrue(result["core_ready"])

    def test_optional_backend_cannot_substitute_model_or_generation(self) -> None:
        optional = self.profile["experimental_backends"][0]
        drift = deepcopy(self.generation)
        drift["top_p"] = 0.95
        report = {
            "backends": {
                self.reference["id"]: self.capability(self.reference),
                optional["id"]: self.capability(
                    optional,
                    served_model="different-model",
                    generation=drift,
                ),
            }
        }
        result = case_validation.evaluate_readiness(report, self.profile)
        observed = next(
            item for item in result["experimental_backends"]
            if item["backend_id"] == optional["id"]
        )
        self.assertEqual(observed["status"], "ineligible")
        self.assertIn("model_identity_mismatch", observed["failures"])
        self.assertIn("generation_envelope_mismatch", observed["failures"])
        self.assertFalse(observed["blocking"])
        self.assertTrue(result["core_ready"])

    def test_reference_generation_or_artifact_drift_blocks_core_readiness(self) -> None:
        drift = deepcopy(self.generation)
        drift["max_output_tokens"] = 4096
        reference = self.capability(self.reference, generation=drift)
        reference["model_artifact_sha256"] = "0" * 64
        result = case_validation.evaluate_readiness(
            {"backends": {self.reference["id"]: reference}},
            self.profile,
        )
        self.assertFalse(result["core_ready"])
        self.assertEqual(result["reference_backend"]["status"], "ineligible")
        self.assertIn(
            "generation_envelope_mismatch",
            result["reference_backend"]["failures"],
        )
        self.assertIn(
            "model_artifact_sha256_mismatch",
            result["reference_backend"]["failures"],
        )

    def test_phase_b_depends_only_on_frozen_required_phase_a(self) -> None:
        self.assertTrue(
            case_validation.phase_b_ready(
                phase_a_passed=True,
                phase_a_frozen=True,
            )
        )
        self.assertFalse(
            case_validation.phase_b_ready(
                phase_a_passed=False,
                phase_a_frozen=True,
            )
        )
        self.assertFalse(
            case_validation.phase_b_ready(
                phase_a_passed=True,
                phase_a_frozen=False,
            )
        )
        self.assertFalse(
            self.profile["validation_plan"]["phase_b"][
                "requires_experimental_backend"
            ]
        )

    def test_reference_envelope_is_exact_and_thinking_is_disabled(self) -> None:
        self.assertEqual(self.profile["generation"], case_validation.EXPECTED_GENERATION)
        llm = case_validation.load_json(
            ROOT / self.profile["application"]["llm_platform_config"]
        )
        self.assertEqual(llm["request_timeout_seconds"], 7200)
        self.assertEqual(llm["request_options"]["top_p"], 1)
        self.assertEqual(llm["request_options"]["top_k"], 0)
        self.assertFalse(llm["request_options"]["stream"])
        self.assertEqual(llm["request_options"]["n"], 1)
        self.assertFalse(
            llm["request_options"]["chat_template_kwargs"]["enable_thinking"]
        )

    def test_application_boundary_remains_openai_compatible_and_http(self) -> None:
        application = self.profile["application"]
        self.assertEqual(application["transport"], "openai-compatible")
        self.assertTrue(application["provider_neutral_boundary"])
        self.assertEqual(application["http_adapter"], "tools/case_http.py")
        self.assertEqual(application["http_method"], "POST")
        self.assertEqual(application["http_endpoint"], "/v1/cases")


if __name__ == "__main__":
    unittest.main()
