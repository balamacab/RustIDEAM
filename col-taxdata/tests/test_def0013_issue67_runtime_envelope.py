from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_benchmark
import case_validation


class Def0013Issue67RuntimeEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = case_validation.load_json(case_validation.DEFAULT_PROFILE)

    def test_historical_issue65_envelope_remains_900_6144(self) -> None:
        historical_path = ROOT / self.profile["historical_benchmark"]["config_path"]
        historical = case_benchmark.load_json(historical_path)
        observed = {
            name: historical["generation"][name]
            for name in case_validation.HISTORICAL_ISSUE65_GENERATION
        }
        self.assertEqual(observed, case_validation.HISTORICAL_ISSUE65_GENERATION)
        self.assertEqual(observed["provider_timeout_seconds"], 900)
        self.assertEqual(observed["max_output_tokens"], 6144)
        self.assertTrue(case_benchmark.verify_package(historical_path)["valid"])

    def test_current_issue67_envelope_is_exact_amended_contract(self) -> None:
        self.assertEqual(
            self.profile["generation"],
            {
                "temperature": 0,
                "thinking": False,
                "context_tokens": 16384,
                "max_output_tokens": 9000,
                "provider_timeout_seconds": 7200,
                "top_p": 1,
                "top_k": 0,
                "stream": False,
                "n": 1,
            },
        )
        result = case_validation.verify_profile()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["current_generation"], self.profile["generation"])

    def test_plan_distinguishes_historical_and_current_envelopes(self) -> None:
        plan = case_validation.build_validation_plan(self.profile)
        self.assertEqual(
            plan["envelopes"]["historical_issue65"]["role"],
            "historical_benchmark",
        )
        self.assertEqual(
            plan["envelopes"]["current_issue67"]["role"],
            "canonical_validation",
        )
        self.assertEqual(
            plan["envelopes"]["historical_issue65"]["max_output_tokens"], 6144
        )
        self.assertEqual(
            plan["envelopes"]["current_issue67"]["max_output_tokens"], 9000
        )
        self.assertEqual(
            plan["required_phase_a"][0]["generation"],
            case_validation.EXPECTED_GENERATION,
        )

    def test_committed_issue67_runtime_profile_is_selectable_and_recordable(self) -> None:
        result = case_validation.verify_profile()
        plan = case_validation.build_validation_plan(self.profile)
        self.assertEqual(result["profile_id"], "issue67-controlled-validation-v2")
        self.assertEqual(
            result["llm_profile_id"], "case-validation-issue67-canonical-v2"
        )
        self.assertEqual(len(result["profile_sha256"]), 64)
        self.assertEqual(len(result["llm_profile_sha256"]), 64)
        self.assertEqual(plan["profile_sha256"], result["profile_sha256"])
        self.assertEqual(
            plan["llm_profile"]["sha256"], result["llm_profile_sha256"]
        )
        self.assertEqual(
            plan["llm_profile"]["path"],
            "config/llm/case-validation-issue67-v2.yaml",
        )

    def test_verify_rejects_fallback_to_historical_900_6144(self) -> None:
        mutated = deepcopy(self.profile)
        mutated["generation"]["max_output_tokens"] = 6144
        mutated["generation"]["provider_timeout_seconds"] = 900
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=ROOT / "config" / "validation",
            encoding="utf-8",
        ) as handle:
            json.dump(mutated, handle)
            handle.flush()
            result = case_validation.verify_profile(Path(handle.name))
        self.assertFalse(result["valid"])
        self.assertIn("generation:strict_envelope", result["errors"])

    def test_verify_rejects_unapproved_generation_or_model_changes(self) -> None:
        mutations = [
            ("temperature", 0.1),
            ("thinking", True),
            ("context_tokens", 8192),
            ("top_p", 0.9),
            ("top_k", 10),
            ("stream", True),
            ("n", 2),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                mutated = deepcopy(self.profile)
                mutated["generation"][field] = value
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".json",
                    dir=ROOT / "config" / "validation",
                    encoding="utf-8",
                ) as handle:
                    json.dump(mutated, handle)
                    handle.flush()
                    result = case_validation.verify_profile(Path(handle.name))
                self.assertFalse(result["valid"])
                self.assertIn("generation:strict_envelope", result["errors"])

        mutated = deepcopy(self.profile)
        mutated["reference_backend"]["requested_model_name"] = "other-model"
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=ROOT / "config" / "validation",
            encoding="utf-8",
        ) as handle:
            json.dump(mutated, handle)
            handle.flush()
            result = case_validation.verify_profile(Path(handle.name))
        self.assertFalse(result["valid"])
        self.assertIn("reference_backend:model", result["errors"])


if __name__ == "__main__":
    unittest.main()
