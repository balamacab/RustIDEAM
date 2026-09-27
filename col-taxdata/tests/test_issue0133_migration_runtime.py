from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from llm_client import load_platform_config


PROFILE_PATH = ROOT / "config" / "llm" / "case-migration-rtx3070-v1.yaml"
HISTORICAL_RUNTIME_PATH = ROOT / "config" / "llm" / "case-validation-reference-v2.yaml"
EXPECTED_MODEL_SHA256 = (
    "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8"
)
EXPECTED_IMAGE_DIGEST = (
    "ghcr.io/ggml-org/llama.cpp@"
    "sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6"
)


class Issue133MigrationRuntimeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_text = PROFILE_PATH.read_text(encoding="utf-8")
        self.profile = json.loads(self.profile_text)

    def test_profile_is_explicitly_migration_test_only(self) -> None:
        admission = self.profile["admission"]
        self.assertEqual(self.profile["profile_id"], "case-migration-rtx3070-v1")
        self.assertEqual(self.profile["provider"], "operator-llama-cpp-migration-test")
        self.assertEqual(admission["issue_number"], 133)
        self.assertEqual(admission["program_issue_number"], 130)
        self.assertEqual(admission["purpose"], "case-v4-migration-test-only")
        self.assertFalse(admission["production_backend"])
        self.assertFalse(admission["historical_reference_runtime"])

    def test_profile_is_distinct_from_historical_case0003_runtime(self) -> None:
        historical = json.loads(HISTORICAL_RUNTIME_PATH.read_text(encoding="utf-8"))
        self.assertNotEqual(self.profile["profile_id"], historical["profile_id"])
        self.assertNotEqual(self.profile["provider"], historical["provider"])
        self.assertEqual(historical["profile_id"], "case-validation-reference-v2")

    def test_endpoint_is_environment_injectable_without_operator_ip_in_repository(self) -> None:
        admission = self.profile["admission"]
        self.assertEqual(admission["endpoint_env"], "COL_TAXDATA_LLM_BASE_URL")
        self.assertEqual(self.profile["base_url"], "http://127.0.0.1:8080/v1")
        self.assertNotIn("192.168.101.27", self.profile_text)

        with mock.patch.dict(
            os.environ,
            {"COL_TAXDATA_LLM_BASE_URL": "http://migration-test-host:18080/v1"},
            clear=False,
        ):
            loaded = load_platform_config(PROFILE_PATH)

        self.assertEqual(loaded.base_url, "http://migration-test-host:18080/v1")

    def test_profile_freezes_current_application_envelope(self) -> None:
        loaded = load_platform_config(PROFILE_PATH)
        self.assertEqual(loaded.primary.name, "gemma-4-E2B-it-Q4_K_M")
        self.assertEqual(loaded.primary.context_tokens, 16384)
        self.assertEqual(loaded.primary.max_output_tokens, 9000)
        self.assertEqual(loaded.timeout_seconds, 7200)
        self.assertEqual(loaded.primary_attempts, 1)
        self.assertFalse(loaded.review_on_invalid_output)
        self.assertFalse(loaded.review_on_provider_error)
        self.assertEqual(
            loaded.request_options,
            {
                "top_p": 1,
                "top_k": 0,
                "stream": False,
                "n": 1,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )

    def test_profile_freezes_verified_artifact_and_runtime_identity(self) -> None:
        admission = self.profile["admission"]
        self.assertEqual(admission["expected_model_artifact_sha256"], EXPECTED_MODEL_SHA256)
        self.assertEqual(len(EXPECTED_MODEL_SHA256), 64)
        int(EXPECTED_MODEL_SHA256, 16)

        observed = admission["observed_http_identity"]
        self.assertEqual(observed["llama_cpp_build_info"], "b11176-f805c57a2")
        self.assertEqual(observed["model_alias"], "gemma-4-E2B-it-Q4_K_M")
        self.assertEqual(observed["model_format"], "gguf")
        self.assertEqual(observed["model_ftype"], "Q4_K - Medium")
        self.assertEqual(observed["model_path"], "/models/gemma-4-E2B-it-Q4_K_M.gguf")
        self.assertEqual(observed["context_tokens"], 16384)
        self.assertEqual(observed["total_slots"], 4)

        verified = admission["verified_runtime_identity"]
        self.assertEqual(verified["model_artifact_sha256"], EXPECTED_MODEL_SHA256)
        self.assertEqual(verified["model_artifact_size_bytes"], 3106738272)
        self.assertEqual(verified["container_repo_digest"], EXPECTED_IMAGE_DIGEST)
        self.assertEqual(
            verified["container_image_id"],
            "sha256:c5daab599318142f2b16a75d05d4c4c6763eba8b2574a9eaab85df8ffd86fce3",
        )
        self.assertTrue(verified["container_model_mount_read_only"])
        self.assertEqual(verified["gpu_model"], "NVIDIA GeForce RTX 3070 Laptop GPU")
        self.assertEqual(verified["gpu_vram_mib"], 8192)
        self.assertEqual(verified["nvidia_driver"], "596.36")
        self.assertEqual(verified["effective_context_tokens"], 16384)
        self.assertEqual(verified["effective_gpu_layers_argument"], 99)
        self.assertEqual(verified["llama_cpp_build_info"], "b11176-f805c57a2")

    def test_silent_truncation_and_hidden_fallback_remain_forbidden(self) -> None:
        self.assertFalse(self.profile["context"]["silent_truncation"])
        self.assertEqual(self.profile["routing"]["primary_attempts"], 1)
        self.assertFalse(self.profile["routing"]["review_on_invalid_output"])
        self.assertFalse(self.profile["routing"]["review_on_provider_error"])


if __name__ == "__main__":
    unittest.main()
