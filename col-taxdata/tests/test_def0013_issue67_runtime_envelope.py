from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
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

    def verify_external_profile(self, profile: dict) -> dict:
        """Verify a profile stored outside config/validation against this project root."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
        ) as handle:
            json.dump(profile, handle)
            handle.flush()
            return case_validation.verify_profile(
                Path(handle.name),
                project_root=ROOT,
            )

    def isolated_project(self) -> tuple[tempfile.TemporaryDirectory, Path, Path, Path]:
        """Build the minimum isolated tree needed to test referenced-profile drift."""
        temp = tempfile.TemporaryDirectory()
        project_root = Path(temp.name)
        benchmark_dst = project_root / "config" / "benchmarks" / "issue65"
        benchmark_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "config" / "benchmarks" / "issue65", benchmark_dst)

        llm_path = project_root / "config" / "llm" / "case-validation-reference-v2.yaml"
        llm_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            ROOT / self.profile["application"]["llm_platform_config"],
            llm_path,
        )

        profile_path = project_root / "external-profiles" / "issue67.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(case_validation.DEFAULT_PROFILE, profile_path)
        return temp, project_root, profile_path, llm_path

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
            case_validation.ISSUE67_CANONICAL_GENERATION,
        )
        self.assertEqual(
            plan["required_phase_a"][0]["run_id"],
            "issue67-phase-a-reference",
        )

    def test_committed_runtime_profile_is_versioned_and_recordable(self) -> None:
        result = case_validation.verify_profile()
        plan = case_validation.build_validation_plan(self.profile)
        self.assertEqual(result["profile_id"], "issue67-controlled-validation-v2")
        self.assertEqual(result["llm_profile_id"], "case-validation-reference-v2")
        self.assertEqual(len(result["profile_sha256"]), 64)
        self.assertEqual(len(result["llm_profile_sha256"]), 64)
        self.assertEqual(plan["profile_sha256"], result["profile_sha256"])
        self.assertEqual(
            plan["llm_profile"]["sha256"], result["llm_profile_sha256"]
        )
        self.assertEqual(
            plan["llm_profile"]["path"],
            "config/llm/case-validation-reference-v2.yaml",
        )

    def test_profile_outside_default_path_resolves_from_explicit_project_root(self) -> None:
        temp, project_root, profile_path, _ = self.isolated_project()
        try:
            result = case_validation.verify_profile(
                profile_path,
                project_root=project_root,
            )
            self.assertTrue(result["valid"], result["errors"])
            profile = case_validation.load_json(profile_path)
            plan = case_validation.build_validation_plan(
                profile,
                profile_path,
                project_root=project_root,
            )
            self.assertEqual(
                plan["llm_profile"]["path"],
                "config/llm/case-validation-reference-v2.yaml",
            )
        finally:
            temp.cleanup()

    def test_profile_hashes_cover_exact_selected_bytes(self) -> None:
        temp, project_root, profile_path, llm_path = self.isolated_project()
        try:
            first = case_validation.verify_profile(
                profile_path,
                project_root=project_root,
            )
            self.assertTrue(first["valid"], first["errors"])

            profile_path.write_bytes(profile_path.read_bytes() + b"\n")
            llm_path.write_bytes(llm_path.read_bytes() + b"\n")
            second = case_validation.verify_profile(
                profile_path,
                project_root=project_root,
            )
            self.assertTrue(second["valid"], second["errors"])
            self.assertNotEqual(first["profile_sha256"], second["profile_sha256"])
            self.assertNotEqual(
                first["llm_profile_sha256"],
                second["llm_profile_sha256"],
            )
        finally:
            temp.cleanup()

    def test_verify_rejects_fallback_to_historical_900_6144(self) -> None:
        mutated = deepcopy(self.profile)
        mutated["generation"]["max_output_tokens"] = 6144
        mutated["generation"]["provider_timeout_seconds"] = 900
        result = self.verify_external_profile(mutated)
        self.assertFalse(result["valid"])
        self.assertIn("generation:strict_envelope", result["errors"])

    def test_verify_rejects_unapproved_validation_profile_changes(self) -> None:
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
                result = self.verify_external_profile(mutated)
                self.assertFalse(result["valid"])
                self.assertIn("generation:strict_envelope", result["errors"])

        mutated = deepcopy(self.profile)
        mutated["reference_backend"]["requested_model_name"] = "other-model"
        result = self.verify_external_profile(mutated)
        self.assertFalse(result["valid"])
        self.assertIn("reference_backend:model", result["errors"])

        mutated = deepcopy(self.profile)
        mutated["profile_id"] = "different-validation-profile"
        result = self.verify_external_profile(mutated)
        self.assertFalse(result["valid"])
        self.assertIn("profile:profile_id", result["errors"])

    def test_verify_rejects_selected_llm_runtime_profile_drift(self) -> None:
        cases = [
            ("timeout", lambda value: value.__setitem__("request_timeout_seconds", 900)),
            (
                "context_tokens",
                lambda value: value["models"]["primary"].__setitem__(
                    "context_tokens", 8192
                ),
            ),
            (
                "max_output_tokens",
                lambda value: value["models"]["primary"].__setitem__(
                    "max_output_tokens", 6144
                ),
            ),
            (
                "primary_model",
                lambda value: value["models"]["primary"].__setitem__(
                    "name", "other-model"
                ),
            ),
            (
                "top_p",
                lambda value: value["request_options"].__setitem__("top_p", 0.9),
            ),
            (
                "top_k",
                lambda value: value["request_options"].__setitem__("top_k", 10),
            ),
            (
                "stream",
                lambda value: value["request_options"].__setitem__("stream", True),
            ),
            (
                "n",
                lambda value: value["request_options"].__setitem__("n", 2),
            ),
            (
                "thinking",
                lambda value: value["request_options"]["chat_template_kwargs"].__setitem__(
                    "enable_thinking", True
                ),
            ),
            (
                "profile_id",
                lambda value: value.__setitem__("profile_id", "unexpected-profile"),
            ),
        ]

        for expected_error, mutate in cases:
            with self.subTest(expected_error=expected_error):
                temp, project_root, profile_path, llm_path = self.isolated_project()
                try:
                    llm = case_validation.load_json(llm_path)
                    mutate(llm)
                    llm_path.write_text(json.dumps(llm), encoding="utf-8")
                    result = case_validation.verify_profile(
                        profile_path,
                        project_root=project_root,
                    )
                    self.assertFalse(result["valid"])
                    self.assertIn(
                        f"llm_profile:{expected_error}",
                        result["errors"],
                    )
                finally:
                    temp.cleanup()

    def test_verify_rejects_clean_provider_semantic_drift(self) -> None:
        cases = [
            ("reset_before_controlled_run", False, "clean_provider_state:reset"),
            ("warm_session_reuse_allowed", True, "clean_provider_state:warm_reuse"),
            ("discard_probe_state", False, "clean_provider_state:probe_state"),
        ]
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                mutated = deepcopy(self.profile)
                mutated["clean_provider_state"][field] = value
                result = self.verify_external_profile(mutated)
                self.assertFalse(result["valid"])
                self.assertIn(expected_error, result["errors"])


if __name__ == "__main__":
    unittest.main()
