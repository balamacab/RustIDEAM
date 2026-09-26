from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_admission
from case_http import prepare_case_request


class Issue95Case0003AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = case_admission.load_json(case_admission.DEFAULT_PROFILE)
        self.frozen = self.profile["frozen_input"]

    def test_frozen_case0003_package_reproduces_issue94_fingerprints(self) -> None:
        result = case_admission.verify_admission_profile()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(
            result["problem_text"],
            {
                "bytes": 2817,
                "sha256": "da85617ba3ea5d75461fdb2da8945bfa3bd223d9eeed63422de5faf49cb356b8",
            },
        )
        self.assertEqual(
            result["raw_http_request"],
            {
                "bytes": 2868,
                "sha256": "a8c4672393310437a083fb8a34b081588a3422bc62d303b57dda7583958027ac",
            },
        )
        self.assertEqual(
            result["canonical_case_input"],
            {
                "bytes": 2915,
                "sha256": "4eaae3fc2dca4c214d8cf4a50cb6d3158d456a69db40d648e22800fa5cab3d5c",
            },
        )
        self.assertRegex(result["expected_case_id"], r"^CASE-[0-9a-f]{32}$")

    def test_http_request_is_exact_sorted_json_with_client_reference_omitted(self) -> None:
        problem = (
            ROOT / self.frozen["problem_text_path"]
        ).read_text(encoding="utf-8")
        raw = (ROOT / self.frozen["raw_http_request_path"]).read_bytes()
        expected = json.dumps(
            {"as_of_date": "2026-09-25", "problem_text": problem},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(raw, expected)
        self.assertFalse(raw.endswith(b"\n"))
        prepared = prepare_case_request(raw)
        self.assertNotIn("client_reference", prepared.case_input)
        self.assertEqual(set(prepared.case_input), {
            "kind",
            "contract_version",
            "problem_text",
            "as_of_date",
        })

    def test_admission_identity_is_distinct_from_issue67_execution_identity(self) -> None:
        self.assertEqual(
            self.profile["profile_id"],
            "case0003-issue94-admission-v1",
        )
        self.assertEqual(self.profile["admission_issue_number"], 95)
        self.assertEqual(self.profile["execution_issue_number"], 94)
        self.assertNotIn("issue67", self.profile["profile_id"].lower())
        self.assertEqual(
            self.profile["application"]["llm_platform_config"],
            "config/llm/case-validation-reference-v2.yaml",
        )

    def test_runtime_v2_exact_envelope_is_reused_without_validation_id_reuse(self) -> None:
        result = case_admission.verify_admission_profile()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(
            result["runtime_profile"]["profile_id"],
            "case-validation-reference-v2",
        )
        self.assertEqual(result["runtime_profile"]["version"], 2)
        self.assertRegex(result["runtime_profile"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["generation"], {
            "temperature": 0,
            "thinking": False,
            "context_tokens": 16384,
            "max_output_tokens": 9000,
            "provider_timeout_seconds": 7200,
            "top_p": 1,
            "top_k": 0,
            "stream": False,
            "n": 1,
        })

    def test_reference_model_artifact_and_no_substitution_are_frozen(self) -> None:
        backend = self.profile["reference_backend"]
        self.assertEqual(backend["backend"], "llama.cpp")
        self.assertEqual(
            backend["requested_model_name"],
            "gemma-4-E2B-it-Q4_K_M",
        )
        self.assertEqual(
            backend["artifact_sha256"],
            "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8",
        )
        self.assertFalse(backend["allow_model_substitution"])
        self.assertFalse(backend["allow_generation_substitution"])

    def test_clean_provider_contract_and_non_consumption_are_fail_closed(self) -> None:
        self.assertEqual(self.profile["clean_provider_state"], {
            "reset_before_controlled_run": True,
            "warm_session_reuse_allowed": False,
            "discard_probe_state": True,
        })
        self.assertEqual(self.profile["admission_state"], {
            "case0003_consumed": False,
            "frozen_case_provider_exposure_allowed": False,
            "frozen_case_persistence_allowed": False,
            "synthetic_smoke_only": True,
        })
        plan = case_admission.build_admission_plan()
        self.assertTrue(plan["valid"], plan["errors"])
        self.assertFalse(plan["case0003_consumed"])
        self.assertFalse(plan["frozen_case_provider_exposure_allowed"])
        self.assertFalse(plan["frozen_case_persistence_allowed"])
        self.assertEqual(
            plan["allowed_runtime_smoke_input"],
            "synthetic_non_case0003_only",
        )

    def test_final_manifest_contract_names_all_mandatory_runtime_evidence(self) -> None:
        required = set(self.profile["final_manifest"]["required_fields"])
        self.assertTrue({
            "issue_94_reference",
            "main_sha",
            "application_image",
            "case_contract_version",
            "runtime_profile",
            "admission_profile",
            "model_artifact_sha256",
            "backend_identity",
            "database_baseline_sha256",
            "raw_provenance_fingerprint",
            "schema_migration_state",
            "frozen_input_verification",
            "synthetic_http_smoke",
            "rejected_output_capture_smoke",
            "provider_reset",
            "writable_store",
            "case0003_consumed",
            "unresolved_blockers",
        }.issubset(required))


if __name__ == "__main__":
    unittest.main()
