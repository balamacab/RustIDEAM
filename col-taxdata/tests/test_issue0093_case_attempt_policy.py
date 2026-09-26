from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_attempt_policy import (
    FailureClass,
    ParentResolutionMode,
    ProviderContactState,
    UpstreamStage,
    detect_comparability_drift,
    detect_same_envelope_retry_drift,
    disposition_for,
    parent_may_close,
    post_fix_rerun_allowed,
    same_envelope_retry_allowed,
    validate_attempt_manifest,
    validate_parent_resolution,
)


def manifest(
    attempt_id: str = "ATTEMPT-001",
    *,
    failure_class: FailureClass = FailureClass.APPLICATION_CONTRACT,
) -> dict:
    return {
        "parent_validation_issue": 67,
        "attempt_id": attempt_id,
        "artifact_root": f"attempts/{attempt_id}",
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
        "generation_parameters": {"temperature": 0, "max_output_tokens": 9000},
        "provider_contact_state": ProviderContactState.RESPONSE_RECEIVED.value,
        "accepted_upstream_stage": UpstreamStage.NONE.value,
        "provider_evidence_ref": {
            "attempt_id": "attempt-llm-001",
            "manifest_path": "_audit/rejected-structuring-attempts/attempt-llm-001/manifest.json",
        },
        "failure_class": failure_class.value,
        "semantic_payload_inspected_before_control": False,
    }


def prospective_rerun(previous: dict, attempt_id: str = "ATTEMPT-002") -> dict:
    current = deepcopy(previous)
    current["attempt_id"] = attempt_id
    current["artifact_root"] = f"attempts/{attempt_id}"
    current["status"] = "running"
    current.pop("ended_at", None)
    current.pop("failure_class", None)
    current["provider_contact_state"] = ProviderContactState.NOT_ATTEMPTED.value
    current["accepted_upstream_stage"] = UpstreamStage.NONE.value
    current["provider_evidence_ref"] = None
    current["previous_attempt"] = previous["attempt_id"]
    return current


class Issue93AttemptPolicyTests(unittest.TestCase):
    def test_application_failure_is_never_retryable_or_repairable(self) -> None:
        policy = disposition_for(FailureClass.APPLICATION_CONTRACT)
        self.assertFalse(policy.same_envelope_retry)
        self.assertFalse(policy.semantic_repair)
        self.assertTrue(policy.parent_blocked)

    def test_every_failure_class_forbids_semantic_repair(self) -> None:
        for failure_class in FailureClass:
            with self.subTest(failure_class=failure_class):
                self.assertFalse(disposition_for(failure_class).semantic_repair)

    def test_structurally_accepted_legal_quality_finding_is_representable(self) -> None:
        current = manifest(failure_class=FailureClass.LEGAL_QUALITY)
        current["status"] = "accepted"
        current["accepted_upstream_stage"] = UpstreamStage.CASE_RESULT.value
        current["resulting_case_id"] = "CASE-abc"
        current["provider_evidence_ref"] = None
        self.assertEqual(validate_attempt_manifest(current), [])

    def test_legal_quality_cannot_be_mislabeled_as_failed_execution(self) -> None:
        current = manifest(failure_class=FailureClass.LEGAL_QUALITY)
        self.assertIn(
            "failed:classification_incompatible",
            validate_attempt_manifest(current),
        )

    def test_abort_requires_human_abort_class_reason_and_no_case_id(self) -> None:
        current = manifest(failure_class=FailureClass.HUMAN_ABORT)
        current["status"] = "aborted"
        current["provider_contact_state"] = ProviderContactState.UNKNOWN.value
        current["provider_evidence_ref"] = None
        current["abort_reason"] = "operator superseded diagnostic purpose"
        self.assertEqual(validate_attempt_manifest(current), [])

        invalid = deepcopy(current)
        invalid["failure_class"] = FailureClass.TRANSIENT_OPERATIONAL.value
        invalid["resulting_case_id"] = "CASE-invalid"
        errors = validate_attempt_manifest(invalid)
        self.assertIn("aborted:human_abort_class_required", errors)
        self.assertIn("aborted:cannot_have_resulting_case_id", errors)

    def test_failed_attempt_cannot_use_human_abort_class(self) -> None:
        current = manifest(failure_class=FailureClass.HUMAN_ABORT)
        self.assertIn(
            "failed:classification_incompatible",
            validate_attempt_manifest(current),
        )

    def test_terminal_attempt_requires_end_timestamp(self) -> None:
        current = manifest()
        current.pop("ended_at")
        self.assertIn("terminal:ended_at_required", validate_attempt_manifest(current))

    def test_application_contract_requires_provider_response_and_rejected_evidence_ref(self) -> None:
        current = manifest()
        current["provider_contact_state"] = ProviderContactState.DISPATCH_ATTEMPTED.value
        current["provider_evidence_ref"] = None
        errors = validate_attempt_manifest(current)
        self.assertIn("application_contract:provider_response_required", errors)
        self.assertIn("provider_failure:provider_evidence_ref_required", errors)

    def test_provider_reaching_operational_failure_requires_evidence_reference(self) -> None:
        current = manifest(failure_class=FailureClass.TRANSIENT_OPERATIONAL)
        current["provider_contact_state"] = ProviderContactState.DISPATCH_ATTEMPTED.value
        current["provider_evidence_ref"] = None
        self.assertIn(
            "provider_failure:provider_evidence_ref_required",
            validate_attempt_manifest(current),
        )

    def test_rejected_evidence_attempt_id_is_not_conflated_with_controlled_attempt_id(self) -> None:
        current = manifest()
        self.assertNotEqual(
            current["attempt_id"],
            current["provider_evidence_ref"]["attempt_id"],
        )
        self.assertEqual(validate_attempt_manifest(current), [])

    def test_downstream_failure_requires_accepted_upstream_stage(self) -> None:
        current = manifest(failure_class=FailureClass.DOWNSTREAM_SYSTEM)
        current["provider_evidence_ref"] = None
        current["accepted_upstream_stage"] = UpstreamStage.NONE.value
        self.assertIn(
            "downstream_system:accepted_upstream_required",
            validate_attempt_manifest(current),
        )
        current["accepted_upstream_stage"] = UpstreamStage.CASE_DRAFT.value
        self.assertEqual(validate_attempt_manifest(current), [])

    def test_admission_failure_is_provider_unconsumed(self) -> None:
        current = manifest(failure_class=FailureClass.ADMISSION)
        current["provider_contact_state"] = ProviderContactState.NOT_ATTEMPTED.value
        current["provider_evidence_ref"] = None
        self.assertEqual(validate_attempt_manifest(current), [])

        current["provider_contact_state"] = ProviderContactState.DISPATCH_ATTEMPTED.value
        self.assertIn(
            "admission:provider_contact_forbidden",
            validate_attempt_manifest(current),
        )

    def test_external_admission_manifest_can_be_required_without_becoming_attempt_identity(self) -> None:
        current = prospective_rerun(manifest())
        errors = validate_attempt_manifest(current, require_admission_manifest=True)
        self.assertIn("missing:admission_manifest_ref", errors)
        self.assertIn("admission_manifest_ref:required", errors)

        current["admission_manifest_ref"] = {
            "issue": 95,
            "status": "PASS",
            "case0003_consumed": False,
        }
        errors = validate_attempt_manifest(current, require_admission_manifest=True)
        self.assertNotIn("admission_manifest_ref:required", errors)
        self.assertFalse(any(item.startswith("missing:admission_manifest_ref") for item in errors))

    def test_diagnostic_attempt_cannot_claim_canonical_boolean(self) -> None:
        current = manifest()
        current["designation"] = "diagnostic"
        current["canonical"] = True
        self.assertIn(
            "designation:canonical_flag_mismatch",
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

    def test_same_envelope_retry_also_freezes_code_and_image(self) -> None:
        previous = manifest(failure_class=FailureClass.TRANSIENT_OPERATIONAL)
        previous["provider_contact_state"] = ProviderContactState.DISPATCH_ATTEMPTED.value
        previous["provider_evidence_ref"] = None
        current = prospective_rerun(previous)
        current["git_sha"] = "0" * 40
        current["image_identity"] = {"reference": "case:other", "digest": "sha256:" + "8" * 64}
        self.assertEqual(
            detect_same_envelope_retry_drift(previous, current)[:2],
            ["git_sha", "image_identity"],
        )

    def test_transient_retry_is_bounded_unique_and_preserves_prior_evidence(self) -> None:
        previous = manifest(failure_class=FailureClass.TRANSIENT_OPERATIONAL)
        previous["provider_contact_state"] = ProviderContactState.DISPATCH_ATTEMPTED.value
        previous["provider_evidence_ref"] = None
        current = prospective_rerun(previous)

        allowed, errors = same_envelope_retry_allowed(
            previous,
            current,
            retry_number=1,
            max_retries=1,
            previous_evidence_preserved=True,
        )
        self.assertTrue(allowed, errors)

        allowed, errors = same_envelope_retry_allowed(
            previous,
            current,
            retry_number=2,
            max_retries=1,
            previous_evidence_preserved=False,
        )
        self.assertFalse(allowed)
        self.assertIn("retry:budget_exceeded_or_invalid", errors)
        self.assertIn("retry:previous_evidence_must_be_preserved", errors)

    def test_non_operational_failure_cannot_use_same_envelope_retry(self) -> None:
        previous = manifest(failure_class=FailureClass.APPLICATION_CONTRACT)
        current = prospective_rerun(previous)
        allowed, errors = same_envelope_retry_allowed(
            previous,
            current,
            retry_number=1,
            max_retries=1,
            previous_evidence_preserved=True,
        )
        self.assertFalse(allowed)
        self.assertIn("retry:previous_failure_not_transient_operational", errors)

    def test_same_contract_post_fix_rejects_drift_and_requires_preserved_history(self) -> None:
        previous = manifest()
        current = prospective_rerun(previous)
        current["rerun_kind"] = "same_contract_post_fix"
        current["request_sha256"] = "0" * 64

        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#91",
            regression_verified=True,
            previous_evidence_preserved=False,
        )
        self.assertFalse(allowed)
        self.assertIn("same_contract_drift:request_sha256", errors)
        self.assertIn("rerun:previous_evidence_must_be_preserved", errors)

    def test_valid_same_contract_post_fix_rerun(self) -> None:
        previous = manifest()
        current = prospective_rerun(previous)
        current["rerun_kind"] = "same_contract_post_fix"
        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#91",
            regression_verified=True,
            previous_evidence_preserved=True,
        )
        self.assertTrue(allowed, errors)

    def test_amended_contract_requires_reason_reference_and_new_profile_identity(self) -> None:
        previous = manifest()
        current = prospective_rerun(previous)
        current["rerun_kind"] = "amended_contract"
        current["contract_amendment"] = {
            "reason": "runtime envelope incompatible",
            "reference": "#67 operator amendment",
        }

        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#92",
            regression_verified=True,
            previous_evidence_preserved=True,
        )
        self.assertFalse(allowed)
        self.assertIn("amended_rerun:new_profile_id_required", errors)
        self.assertIn("amended_rerun:new_profile_sha_required", errors)

        current["execution_profile_id"] = "issue67-v3"
        current["execution_profile_sha256"] = "1" * 64
        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#92",
            regression_verified=True,
            previous_evidence_preserved=True,
        )
        self.assertTrue(allowed, errors)

    def test_new_baseline_requires_reason_and_actual_baseline_change(self) -> None:
        previous = manifest()
        current = prospective_rerun(previous)
        current["rerun_kind"] = "new_baseline"
        current["baseline_change"] = {
            "reason": "post-fix corpus baseline intentionally refreshed",
            "reference": "#95 admission manifest",
        }

        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#91",
            regression_verified=True,
            previous_evidence_preserved=True,
        )
        self.assertFalse(allowed)
        self.assertIn("new_baseline:baseline_sha_must_change", errors)

        current["baseline_sha256"] = "7" * 64
        allowed, errors = post_fix_rerun_allowed(
            previous,
            current,
            defect_reference="#91",
            regression_verified=True,
            previous_evidence_preserved=True,
        )
        self.assertTrue(allowed, errors)

    def test_same_validation_resume_requires_parent_to_remain_open(self) -> None:
        resolution = {
            "parent_validation_issue": 94,
            "mode": ParentResolutionMode.SAME_VALIDATION_RESUME.value,
            "decision_authority": "controller",
            "decision_reference": "#94 comment-1",
            "failed_attempts_preserved": True,
            "close_parent": False,
            "case_result_legal_pass": False,
            "same_case_post_fix_rerun": True,
            "successor_validation_issue": None,
        }
        self.assertEqual(validate_parent_resolution(resolution), [])
        self.assertFalse(parent_may_close(resolution))

        resolution["close_parent"] = True
        self.assertIn(
            "same_validation_resume:parent_must_remain_open",
            validate_parent_resolution(resolution),
        )

    def test_diagnostic_completion_requires_successor_blockers_and_non_pass_language(self) -> None:
        resolution = {
            "parent_validation_issue": 67,
            "mode": ParentResolutionMode.DIAGNOSTIC_COMPLETION.value,
            "decision_authority": "controller_operator",
            "decision_reference": "#67 closeout decision",
            "failed_attempts_preserved": True,
            "close_parent": True,
            "case_result_legal_pass": False,
            "outcome": "diagnostic_blocker",
            "blockers_owned_separately": True,
            "blocker_issues": [90, 91, 92, 93],
            "successor_validation_issue": 94,
            "blocking_failure_class": FailureClass.APPLICATION_CONTRACT.value,
            "same_case_post_fix_rerun": False,
        }
        self.assertEqual(validate_parent_resolution(resolution), [])
        self.assertTrue(parent_may_close(resolution))

    def test_diagnostic_completion_cannot_escape_legal_quality_or_transient_failure(self) -> None:
        base = {
            "parent_validation_issue": 94,
            "mode": ParentResolutionMode.DIAGNOSTIC_COMPLETION.value,
            "decision_authority": "operator",
            "decision_reference": "#94 diagnostic decision",
            "failed_attempts_preserved": True,
            "close_parent": True,
            "case_result_legal_pass": False,
            "outcome": "diagnostic_blocker",
            "blockers_owned_separately": True,
            "blocker_issues": [123],
            "successor_validation_issue": 124,
            "same_case_post_fix_rerun": False,
        }
        for failure in (
            FailureClass.LEGAL_QUALITY,
            FailureClass.TRANSIENT_OPERATIONAL,
            FailureClass.ADMISSION,
            FailureClass.HUMAN_ABORT,
        ):
            with self.subTest(failure=failure):
                resolution = deepcopy(base)
                resolution["blocking_failure_class"] = failure.value
                self.assertIn(
                    "diagnostic_completion:systemic_blocking_class_required",
                    validate_parent_resolution(resolution),
                )

    def test_diagnostic_completion_cannot_close_without_separate_ownership_or_successor(self) -> None:
        resolution = {
            "parent_validation_issue": 94,
            "mode": ParentResolutionMode.DIAGNOSTIC_COMPLETION.value,
            "decision_authority": "controller",
            "decision_reference": "#94 comment",
            "failed_attempts_preserved": True,
            "close_parent": True,
            "case_result_legal_pass": False,
            "outcome": "diagnostic_blocker",
            "blockers_owned_separately": False,
            "blocker_issues": [],
            "successor_validation_issue": None,
            "blocking_failure_class": FailureClass.DOWNSTREAM_SYSTEM.value,
            "same_case_post_fix_rerun": False,
        }
        errors = validate_parent_resolution(resolution)
        self.assertIn("diagnostic_completion:blockers_must_be_separately_owned", errors)
        self.assertIn("diagnostic_completion:blocker_issues_required", errors)
        self.assertIn("diagnostic_completion:successor_required", errors)
        self.assertFalse(parent_may_close(resolution))

    def test_diagnostic_completion_blocker_cannot_be_parent_issue(self) -> None:
        resolution = {
            "parent_validation_issue": 94,
            "mode": ParentResolutionMode.DIAGNOSTIC_COMPLETION.value,
            "decision_authority": "controller",
            "decision_reference": "#94 comment",
            "failed_attempts_preserved": True,
            "close_parent": True,
            "case_result_legal_pass": False,
            "outcome": "diagnostic_blocker",
            "blockers_owned_separately": True,
            "blocker_issues": [94],
            "successor_validation_issue": 124,
            "blocking_failure_class": FailureClass.APPLICATION_CONTRACT.value,
            "same_case_post_fix_rerun": False,
        }
        self.assertIn(
            "diagnostic_completion:blocker_must_be_separate_child",
            validate_parent_resolution(resolution),
        )


if __name__ == "__main__":
    unittest.main()
