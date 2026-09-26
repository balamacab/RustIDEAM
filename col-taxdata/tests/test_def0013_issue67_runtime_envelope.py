from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_benchmark
import case_validation
from case_http import build_runtime_application
from llm_client import (
    CASE_PROVIDER_TIMEOUT,
    LLMClientError,
    OpenAICompatibleLLMClient,
    load_platform_config,
)


class Def0013Issue67RuntimeEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = case_validation.load_json(case_validation.DEFAULT_PROFILE)

    def verify_external_profile(self, profile: dict) -> dict:
        """Verify an external profile while resolving references from this project."""
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
        """Build the minimum isolated tree needed for referenced-profile drift tests."""
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

    def test_historical_issue65_envelope_remains_exact_900_6144(self) -> None:
        historical_path = ROOT / self.profile["historical_benchmark"]["config_path"]
        historical = case_benchmark.load_json(historical_path)
        observed = {
            name: historical["generation"][name]
            for name in case_validation.GENERATION_FIELDS
        }
        self.assertEqual(observed, case_validation.HISTORICAL_ISSUE65_GENERATION)
        self.assertEqual(observed["provider_timeout_seconds"], 900)
        self.assertEqual(observed["max_output_tokens"], 6144)
        verification = case_benchmark.verify_package(historical_path)
        self.assertTrue(verification["valid"], verification["errors"])
        self.assertEqual(
            verification["problem_text_sha256"],
            "ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1",
        )
        self.assertEqual(
            verification["canonical_case_input_sha256"],
            "9a88c7d1f818e22ef310ef52a4185d2795d3e51ddd374d22b25e713b522171d4",
        )
        self.assertEqual(
            verification["request_sha256"],
            "b0b36bf6ab5c5d46572aee434933b4a87f830c953ef26ee17c78734c82a9b763",
        )

    def test_historical_reference_v1_remains_900_6144(self) -> None:
        v1 = case_validation.load_json(
            ROOT / "config" / "llm" / "case-validation-reference.yaml"
        )
        self.assertEqual(v1["profile_id"], "case-validation-reference-v1")
        self.assertEqual(v1["version"], 1)
        self.assertEqual(v1["request_timeout_seconds"], 900)
        self.assertEqual(v1["models"]["primary"]["context_tokens"], 16384)
        self.assertEqual(v1["models"]["primary"]["max_output_tokens"], 6144)

    def test_current_issue67_envelope_is_exact_amended_contract(self) -> None:
        self.assertEqual(
            self.profile["generation"],
            case_validation.ISSUE67_CANONICAL_GENERATION,
        )
        self.assertEqual(self.profile["amendment_issue_number"], 92)
        result = case_validation.verify_profile()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["current_generation"], self.profile["generation"])

    def test_plan_distinguishes_complete_historical_and_current_envelopes(self) -> None:
        plan = case_validation.build_validation_plan(self.profile)
        historical = plan["envelopes"]["historical_issue65"]
        current = plan["envelopes"]["current_issue67"]
        self.assertEqual(historical["role"], "historical_benchmark")
        self.assertEqual(historical["source_issue_number"], 65)
        self.assertEqual(
            historical["generation"],
            case_validation.HISTORICAL_ISSUE65_GENERATION,
        )
        self.assertEqual(current["role"], "canonical_validation")
        self.assertEqual(current["source_issue_number"], 67)
        self.assertEqual(current["amendment_issue_number"], 92)
        self.assertEqual(
            current["generation"],
            case_validation.ISSUE67_CANONICAL_GENERATION,
        )
        run = plan["required_phase_a"][0]
        self.assertEqual(run["generation"], case_validation.ISSUE67_CANONICAL_GENERATION)
        self.assertEqual(run["run_id"], "issue67-phase-a-reference")
        self.assertEqual(
            run["runtime_profile"]["profile_id"],
            "case-validation-reference-v2",
        )

    def test_committed_profiles_are_versioned_and_recordable(self) -> None:
        result = case_validation.verify_profile()
        plan = case_validation.build_validation_plan(self.profile)
        self.assertEqual(result["profile_id"], "issue67-controlled-validation-v2")
        self.assertEqual(result["validation_profile"]["schema_version"], 2)
        self.assertEqual(result["runtime_profile"]["profile_id"], "case-validation-reference-v2")
        self.assertEqual(result["runtime_profile"]["version"], 2)
        self.assertEqual(len(result["validation_profile"]["sha256"]), 64)
        self.assertEqual(len(result["runtime_profile"]["sha256"]), 64)
        self.assertEqual(plan["validation_profile"], result["validation_profile"])
        self.assertEqual(plan["runtime_profile"], result["runtime_profile"])
        self.assertEqual(
            plan["runtime_profile"]["path"],
            "config/llm/case-validation-reference-v2.yaml",
        )
        self.assertEqual(
            plan["required_phase_a"][0]["runtime_profile"],
            result["runtime_profile"],
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
                plan["runtime_profile"]["path"],
                "config/llm/case-validation-reference-v2.yaml",
            )
            self.assertEqual(
                plan["validation_profile"]["path"],
                str(profile_path.resolve()),
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
            self.assertNotEqual(
                first["validation_profile"]["sha256"],
                second["validation_profile"]["sha256"],
            )
            self.assertNotEqual(
                first["runtime_profile"]["sha256"],
                second["runtime_profile"]["sha256"],
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

        v1_fallback = deepcopy(self.profile)
        v1_fallback["application"][
            "llm_platform_config"
        ] = "config/llm/case-validation-reference.yaml"
        result = self.verify_external_profile(v1_fallback)
        self.assertFalse(result["valid"])
        self.assertIn("llm_profile:version", result["errors"])
        self.assertIn("llm_profile:profile_id", result["errors"])
        self.assertIn("llm_profile:timeout", result["errors"])
        self.assertIn("llm_profile:max_output_tokens", result["errors"])

    def test_verify_rejects_unapproved_validation_profile_changes(self) -> None:
        mutations = [
            ("temperature", 0.1),
            ("thinking", True),
            ("context_tokens", 8192),
            ("max_output_tokens", 8999),
            ("provider_timeout_seconds", 7199),
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

        mutated = deepcopy(self.profile)
        mutated["schema_version"] = 3
        result = self.verify_external_profile(mutated)
        self.assertFalse(result["valid"])
        self.assertIn("profile:schema_version", result["errors"])

    def test_verify_rejects_envelope_history_drift(self) -> None:
        cases = [
            (
                "historical_generation",
                lambda value: value["envelope_history"]["historical_issue65"][
                    "generation"
                ].__setitem__("max_output_tokens", 9000),
                "envelope_history:historical_generation",
            ),
            (
                "current_generation",
                lambda value: value["envelope_history"]["current_issue67"][
                    "generation"
                ].__setitem__("provider_timeout_seconds", 900),
                "envelope_history:current_generation",
            ),
            (
                "amendment_issue",
                lambda value: value["envelope_history"]["current_issue67"].__setitem__(
                    "amendment_issue_number", 75
                ),
                "envelope_history:amendment_issue",
            ),
        ]
        for name, mutate, expected in cases:
            with self.subTest(name=name):
                mutated = deepcopy(self.profile)
                mutate(mutated)
                result = self.verify_external_profile(mutated)
                self.assertFalse(result["valid"])
                self.assertIn(expected, result["errors"])

    def test_actual_openai_request_materializes_exact_generation_options(self) -> None:
        config = load_platform_config(
            ROOT / self.profile["application"]["llm_platform_config"]
        )
        client = OpenAICompatibleLLMClient(config)
        case_input = {
            "kind": "case_input",
            "contract_version": "3.0.0",
            "problem_text": "La sociedad solicita una validación tributaria.",
        }

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            side_effect=TimeoutError("test stop after request construction"),
        ) as opened:
            with self.assertRaises(LLMClientError) as raised:
                client.complete_case_draft(
                    case_input=case_input,
                    route=config.primary,
                )

        self.assertEqual(raised.exception.code, CASE_PROVIDER_TIMEOUT)
        request_payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(request_payload["temperature"], 0)
        self.assertEqual(request_payload["max_tokens"], 9000)
        self.assertEqual(request_payload["top_p"], 1)
        self.assertEqual(request_payload["top_k"], 0)
        self.assertFalse(request_payload["stream"])
        self.assertEqual(request_payload["n"], 1)
        self.assertFalse(
            request_payload["chat_template_kwargs"]["enable_thinking"]
        )
        self.assertEqual(opened.call_args.kwargs["timeout"], 7200)

    def test_clean_runtime_can_select_committed_v2_without_host_edit(self) -> None:
        config_path = ROOT / self.profile["application"]["llm_platform_config"]
        application, provider, model = build_runtime_application(
            db_path=ROOT / "data" / "state" / "not-opened.sqlite",
            case_root=ROOT / "data" / "cases",
            config_path=config_path,
            dry_run=True,
        )
        self.assertIsNotNone(application)
        self.assertEqual(provider, "local-llama-cpp")
        self.assertEqual(model, "gemma-4-E2B-it-Q4_K_M")
        config = load_platform_config(config_path)
        self.assertEqual(config.timeout_seconds, 7200)
        self.assertEqual(config.primary.max_output_tokens, 9000)

    def test_verify_rejects_selected_llm_runtime_profile_drift(self) -> None:
        cases = [
            ("version", lambda value: value.__setitem__("version", 3)),
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
            ("top_p", lambda value: value["request_options"].__setitem__("top_p", 0.9)),
            ("top_k", lambda value: value["request_options"].__setitem__("top_k", 10)),
            ("stream", lambda value: value["request_options"].__setitem__("stream", True)),
            ("n", lambda value: value["request_options"].__setitem__("n", 2)),
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
            (
                "primary_attempts",
                lambda value: value["routing"].__setitem__("primary_attempts", 2),
            ),
            (
                "review_fallback_forbidden",
                lambda value: value["routing"].__setitem__(
                    "review_on_provider_error", True
                ),
            ),
            (
                "silent_truncation",
                lambda value: value["context"].__setitem__("silent_truncation", True),
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
