from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_attempt_policy import (
    FailureClass,
    detect_comparability_drift,
    disposition_for,
    post_fix_rerun_allowed,
    validate_attempt_manifest,
)


def manifest(attempt_id: str = "ATTEMPT-001") -> dict:
    return {
        "parent_validation_issue": 67,
        "attempt_id": attempt_id,
        "status": "failed",
        "designation": "canonical",
        "started_at": "2026-09-25T00:00:00Z",
        "ended_at": "2026-09-25T00:01:00Z",
        "git_sha": "a" * 40,
        "image_identity": {"reference": "case:test", "digest": "sha256:" + "9" * 64},
        "execution_profile_id": "issue67-v2",
        "execution_profile_sha256": "b" * 64,
        "request_sha256": "c" * 64,
        "case_input_sha256": "d" * 64,
        "baseline_sha256": "e" * 64,
        "raw_evidence_manifest_sha256": "f" * 64,
        "provider_identity": {"backend": "llama.cpp", "model": "gemma"},
        "generation_parameters": {"temperature": 0},
        "failure_class": FailureClass.APPLICATION_CONTRACT.value,
        "artifact_root": f"attempts/{attempt_id}",
        "semantic_payload_inspected_before_control": False,
    }


class Issue93AttemptPolicyTests(unittest.TestCase):
    def test_application_failure_is_never_retryable_or_repairable(self) -> None:
        policy = disposition_for(FailureClass.APPLICATION_CONTRACT)
        self.assertFalse(policy.same_envelope_retry)
        self.assertFalse(policy.semantic_repair)
        self.assertTrue(policy.parent_blocked)

    def test_legal_quality_failure_cannot_retry_to_improve_score(self) -> None:
        policy = disposition_for(FailureClass.LEGAL_QUALITY)
        self.assertFalse(policy.same_envelope_retry)
        self.assertEqual(policy.contract_amendment, "no_to_improve_score")
        self.assertFalse(policy.semantic_repair)

    def test_transient_operational_retry_is_the_bounded_same_envelope_case(self) -> None:
        policy = disposition_for(FailureClass.TRANSIENT_OPERATIONAL)
        self.assertTrue(policy.same_envelope_retry)
        self.assertFalse(policy.semantic_repair)

    def test_runtime_envelope_requires_amendment_not_blind_retry(self) -> None:
        policy = disposition_for(FailureClass.RUNTIME_ENVELOPE)
        self.assertFalse(policy.same_envelope_retry)
        self.assertEqual(policy.contract_amendment, "required")

    def test_every_failure_class_forbids_semantic_repair(self) -> None:
        for failure_class in FailureClass:
            with self.subTest(failure_class=failure_class):
                self.assertFalse(disposition_for(failure_class).semantic_repair)

    def test_distinct_attempt_ids_and_artifact_roots_required_for_post_fix_rerun(self) -> None:
        previous = manifest()
        current = deepcopy(previous)
        current["status"] = "running"
        current.pop("failure_class")
        current["previous_attempt"] = previous["attempt_id"]
        current["rerun_kind"] = "same_contract_post_fix"
        allowed, errors = post_fix_rerun_allowed(
            previous, current, defect_reference="#91", regression_verified=True
        )
        self.assertFalse(allowed)
        self.assertIn("rerun:attempt_id_must_change", errors)
        self.assertIn("rerun:artifact_root_must_change", errors)

    def test_contract_amended_attempt_requires_predecessor_and_amendment(self) -> None:
        current = manifest("ATTEMPT-002")
        current["rerun_kind"] = "amended_contract"
        self.assertIn(
            "amended_rerun:contract_amendment_required",
            validate_attempt_manifest(current),
        )
        current["previous_attempt"] = "ATTEMPT-001"
        current["contract_amendment"] = {"reason": "runtime envelope incompatible"}
        self.assertNotIn(
            "amended_rerun:contract_amendment_required",
            validate_attempt_manifest(current),
        )

    def test_diagnostic_attempt_cannot_be_marked_canonical(self) -> None:
        current = manifest()
        current["designation"] = "diagnostic"
        current["canonical"] = True
        self.assertIn("diagnostic:cannot_be_canonical", validate_attempt_manifest(current))

    def test_aborted_attempt_cannot_be_completed_with_case_id(self) -> None:
        current = manifest()
        current["status"] = "aborted"
        current.pop("failure_class")
        current["resulting_case_id"] = "CASE-should-not-exist"
        self.assertIn(
            "aborted:cannot_have_resulting_case_id",
            validate_attempt_manifest(current),
        )

    def test_profile_request_and_baseline_drift_is_detected(self) -> None:
        previous = manifest()
        current = deepcopy(previous)
        current["execution_profile_sha256"] = "1" * 64
        current["request_sha256"] = "2" * 64
        current["baseline_sha256"] = "3" * 64
        self.assertEqual(
            detect_comparability_drift(previous, current),
            ["request_sha256", "baseline_sha256", "execution_profile_sha256"],
        )

    def test_same_contract_post_fix_rejects_comparability_drift(self) -> None:
        previous = manifest()
        current = deepcopy(previous)
        current["attempt_id"] = "ATTEMPT-002"
        current["artifact_root"] = "attempts/ATTEMPT-002"
        current["status"] = "running"
        current.pop("failure_class")
        current["previous_attempt"] = "ATTEMPT-001"
        current["rerun_kind"] = "same_contract_post_fix"
        current["request_sha256"] = "0" * 64
        allowed, errors = post_fix_rerun_allowed(
            previous, current, defect_reference="#91", regression_verified=True
        )
        self.assertFalse(allowed)
        self.assertIn("same_contract_drift:request_sha256", errors)

    def test_post_fix_rerun_preserves_old_attempt_and_accepts_new_identity(self) -> None:
        previous = manifest()
        current = deepcopy(previous)
        current["attempt_id"] = "ATTEMPT-002"
        current["artifact_root"] = "attempts/ATTEMPT-002"
        current["status"] = "running"
        current.pop("failure_class")
        current["previous_attempt"] = "ATTEMPT-001"
        current["rerun_kind"] = "same_contract_post_fix"
        allowed, errors = post_fix_rerun_allowed(
            previous, current, defect_reference="#91", regression_verified=True
        )
        self.assertTrue(allowed, errors)
        self.assertEqual(previous["attempt_id"], "ATTEMPT-001")
        self.assertEqual(previous["artifact_root"], "attempts/ATTEMPT-001")


if __name__ == "__main__":
    unittest.main()
