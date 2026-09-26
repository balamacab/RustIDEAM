from __future__ import annotations

import unittest

from tools.case_attempt_policy import (
    PolicyError,
    same_envelope_retry_allowed,
    validate_attempt_manifest,
    validate_validation_disposition,
    validation_parent_may_close,
)


def attempt_manifest(
    *,
    attempt_id: str = "ATT-BLOCK",
    designation: str = "canonical",
    status: str = "failed",
    failure_class: str = "E_APPLICATION_CONTRACT",
) -> dict:
    value = {
        "schema_version": 1,
        "parent_validation_issue": 67,
        "attempt_id": attempt_id,
        "designation": designation,
        "status": status,
        "failure_class": failure_class,
        "artifact_root": f"artifacts/{attempt_id}",
        "timestamps": {
            "started_at": "2026-09-25T00:00:00Z",
            "ended_at": "2026-09-25T00:15:00Z",
        },
        "code": {
            "git_sha": "a" * 40,
            "image_identity": "sha256:" + "b" * 64,
        },
        "profile": {
            "id": "issue67-controlled-validation-v2",
            "sha256": "c" * 64,
        },
        "input": {
            "request_sha256": "d" * 64,
            "case_input_sha256": "e" * 64,
            "db_baseline_sha256": "f" * 64,
            "raw_evidence_manifest_sha256": "1" * 64,
        },
        "provider": {
            "provider": "local-openai-compatible",
            "backend": "llama.cpp",
            "model": "gemma-e2b",
            "model_artifact_identity": "model:" + "2" * 64,
            "backend_build_identity": "llama.cpp:build-abc",
            "generation_parameters": {"temperature": 0},
            "request_reached_provider": True,
            "raw_response_sha256": "3" * 64,
            "rejected_output_artifact": "audit/rejected/ATT-BLOCK",
            "http_status": 502,
            "error": "INVALID_CASE_DRAFT",
            "finish_reason": "stop",
            "usage": None,
            "timing": {"elapsed_seconds": 1122},
        },
        "outcome": {
            "case_id": None,
            "case_result_state": "rejected",
            "persistence_state": "not_started",
            "materialization_state": "not_started",
            "validator_state": "fail",
            "provenance_state": "not_reached",
            "doctor_state": "not_reached",
        },
        "lineage": {
            "kind": "initial",
            "previous_attempt": None,
            "previous_artifact_root": None,
            "previous_evidence_preserved": False,
            "reason": None,
            "amendment_reference": None,
            "fix_reference": None,
            "baseline_reference": None,
            "retry_number": None,
        },
        "control": {
            "semantic_payload_inspected_before_independent_control": False,
            "semantic_repair_applied": False,
        },
    }
    if designation == "diagnostic":
        value["lineage"]["kind"] = "diagnostic"
    return value


def disposition(
    *,
    kind: str = "resume_same_validation",
    failure_class: str = "E_APPLICATION_CONTRACT",
    parent_open: bool | None = None,
    blockers: list[int] | None = None,
    successor: int | None = None,
    controller_reference: str | None = None,
    phase_a_valid: bool = False,
    phase_b_executed: bool = False,
    phase_b_completed: bool = False,
) -> dict:
    diagnostic_complete = kind == "diagnostic_complete_with_successor"
    if parent_open is None:
        parent_open = not diagnostic_complete
    if blockers is None:
        blockers = [91] if failure_class in {
            "C_RUNTIME_ENVELOPE",
            "D_STRUCTURED_COMPATIBILITY",
            "E_APPLICATION_CONTRACT",
            "F_DOWNSTREAM_SYSTEM",
        } else []
    if diagnostic_complete and successor is None:
        successor = 94
    if diagnostic_complete and controller_reference is None:
        controller_reference = "issue#67-closeout-controller-decision"

    status = "failed"
    if failure_class == "G_LEGAL_QUALITY":
        status = "completed_with_findings"
    elif failure_class == "H_OPERATOR_ABORTED":
        status = "aborted"

    return {
        "schema_version": 1,
        "disposition": kind,
        "parent_validation_issue": 67,
        "parent_issue_open": parent_open,
        "blocking_failure_class": failure_class,
        "blocking_attempt_id": "ATT-BLOCK",
        "blocking_artifact_reference": "artifacts/ATT-BLOCK",
        "blocking_attempt_status": status,
        "blocking_evidence_preserved": True,
        "controller_decision_reference": controller_reference,
        "blocker_issue_references": blockers,
        "successor_validation_issue": successor,
        "future_rerun_parent_issue": None if diagnostic_complete else 67,
        "legal_pass": False,
        "phase_a_valid": phase_a_valid,
        "phase_b_executed": phase_b_executed,
        "phase_b_completed": phase_b_completed,
        "reason": (
            "close the diagnostic milestone and continue with a fresh validation"
            if diagnostic_complete
            else "preserve the parent and continue the same frozen validation"
        ),
    }


class Issue0115ValidationDispositionTests(unittest.TestCase):
    def test_systemic_e_failure_may_resume_same_validation(self):
        value = disposition()
        validate_validation_disposition(value, blocking_attempt=attempt_manifest())
        self.assertFalse(validation_parent_may_close(value, blocking_attempt=attempt_manifest()))

    def test_same_validation_resume_requires_parent_open_semantics(self):
        value = disposition(parent_open=False)
        with self.assertRaisesRegex(PolicyError, "parent-open"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_requires_controller_blocker_and_distinct_successor(self):
        value = disposition(kind="diagnostic_complete_with_successor")
        validate_validation_disposition(value, blocking_attempt=attempt_manifest())
        self.assertTrue(validation_parent_may_close(value, blocking_attempt=attempt_manifest()))

        missing_controller = disposition(kind="diagnostic_complete_with_successor")
        missing_controller["controller_decision_reference"] = None
        with self.assertRaisesRegex(PolicyError, "controller/operator authority"):
            validate_validation_disposition(missing_controller)

    def test_diagnostic_completion_cannot_be_legal_or_case_result_pass(self):
        value = disposition(kind="diagnostic_complete_with_successor")
        value["legal_pass"] = True
        with self.assertRaisesRegex(PolicyError, "legal/CaseResult PASS"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_same_parent_as_successor(self):
        value = disposition(kind="diagnostic_complete_with_successor", successor=67)
        with self.assertRaisesRegex(PolicyError, "distinct from the parent"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_missing_blocker_ownership(self):
        value = disposition(
            kind="diagnostic_complete_with_successor",
            blockers=[],
        )
        with self.assertRaisesRegex(PolicyError, "separately owned blocker/fix"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_class_a(self):
        value = disposition(
            kind="diagnostic_complete_with_successor",
            failure_class="A_ADMISSION",
            blockers=[91],
        )
        with self.assertRaisesRegex(PolicyError, "not eligible"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_retryable_class_b(self):
        self.assertTrue(
            same_envelope_retry_allowed(
                "B_OPERATIONAL",
                retry_number=1,
                retry_limit=1,
            )
        )
        value = disposition(
            kind="diagnostic_complete_with_successor",
            failure_class="B_OPERATIONAL",
            blockers=[91],
        )
        with self.assertRaisesRegex(PolicyError, "not eligible"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_class_g(self):
        value = disposition(
            kind="diagnostic_complete_with_successor",
            failure_class="G_LEGAL_QUALITY",
            blockers=[91],
        )
        with self.assertRaisesRegex(PolicyError, "not eligible"):
            validate_validation_disposition(value)

    def test_diagnostic_completion_rejects_class_h_without_separate_disposition(self):
        value = disposition(
            kind="diagnostic_complete_with_successor",
            failure_class="H_OPERATOR_ABORTED",
            blockers=[91],
        )
        with self.assertRaisesRegex(PolicyError, "not eligible"):
            validate_validation_disposition(value)

    def test_incomplete_phase_b_cannot_be_marked_completed(self):
        value = disposition(
            phase_a_valid=True,
            phase_b_executed=False,
            phase_b_completed=True,
        )
        with self.assertRaisesRegex(PolicyError, "Phase B cannot be completed"):
            validate_validation_disposition(value)

        no_valid_phase_a = disposition(
            phase_a_valid=False,
            phase_b_executed=True,
            phase_b_completed=False,
        )
        with self.assertRaisesRegex(PolicyError, "without a valid Phase A"):
            validate_validation_disposition(no_valid_phase_a)

    def test_diagnostic_attempt_designation_does_not_authorize_parent_closure(self):
        diagnostic_attempt = attempt_manifest(designation="diagnostic")
        validate_attempt_manifest(diagnostic_attempt)

        value = disposition(kind="resume_same_validation")
        validate_validation_disposition(value, blocking_attempt=diagnostic_attempt)
        self.assertFalse(
            validation_parent_may_close(value, blocking_attempt=diagnostic_attempt)
        )

    def test_issue67_to_issue94_history_is_representable_without_legal_pass(self):
        issue67 = disposition(
            kind="diagnostic_complete_with_successor",
            failure_class="E_APPLICATION_CONTRACT",
            blockers=[90, 91, 92, 93],
            successor=94,
            controller_reference="issue#67-final-closeout",
            phase_a_valid=False,
            phase_b_executed=False,
            phase_b_completed=False,
        )
        validate_validation_disposition(issue67, blocking_attempt=attempt_manifest())
        self.assertFalse(issue67["legal_pass"])
        self.assertTrue(validation_parent_may_close(issue67, blocking_attempt=attempt_manifest()))

    def test_blocking_attempt_cannot_be_relabelled_as_completed_by_disposition(self):
        value = disposition(kind="diagnostic_complete_with_successor")
        value["blocking_attempt_status"] = "completed"
        with self.assertRaisesRegex(PolicyError, "inconsistent"):
            validate_validation_disposition(value, blocking_attempt=attempt_manifest())


if __name__ == "__main__":
    unittest.main()
