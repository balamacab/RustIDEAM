from __future__ import annotations

from copy import deepcopy

import pytest

from tools.case_attempt_policy import (
    FAILURE_CLASSES,
    PolicyError,
    failure_policy,
    independent_control_ready,
    same_envelope_retry_allowed,
    validate_attempt_manifest,
    validate_successor_attempt,
)


def manifest(
    *,
    attempt_id: str = "ATT-001",
    artifact_root: str = "artifacts/ATT-001",
    designation: str = "canonical",
    status: str = "failed",
    failure_class: str | None = "B_OPERATIONAL",
    lineage_kind: str = "initial",
) -> dict:
    value = {
        "schema_version": 1,
        "parent_validation_issue": 67,
        "attempt_id": attempt_id,
        "designation": designation,
        "status": status,
        "failure_class": failure_class,
        "artifact_root": artifact_root,
        "timestamps": {
            "started_at": "2026-09-25T00:00:00Z",
            "ended_at": "2026-09-25T00:15:00Z",
        },
        "code": {
            "git_sha": "a" * 40,
            "image_identity": "sha256:" + "b" * 64,
        },
        "profile": {
            "id": "issue67-controlled-validation-v1",
            "sha256": "c" * 64,
        },
        "input": {
            "request_sha256": "d" * 64,
            "case_input_sha256": "e" * 64,
            "db_baseline_sha256": "f" * 64,
            "raw_evidence_manifest_sha256": "1" * 64,
        },
        "provider": {
            "name": "local-llama-cpp",
            "model": "gemma-e2b",
            "artifact_or_build_identity": "model:" + "2" * 64,
            "generation_parameters": {
                "temperature": 0,
                "context_tokens": 16384,
                "max_output_tokens": 6144,
            },
            "request_reached_provider": True,
            "raw_response_sha256": None,
            "rejected_output_artifact": None,
            "http_status": 504,
            "error": "timeout",
            "finish_reason": None,
            "usage": None,
            "timing": {"elapsed_seconds": 900},
        },
        "outcome": {
            "case_id": None,
            "case_result_state": "not_produced",
            "persistence_state": "not_started",
            "materialization_state": "not_started",
            "validator_state": "not_reached",
            "provenance_state": "not_reached",
            "doctor_state": "not_reached",
        },
        "lineage": {
            "kind": lineage_kind,
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


def linked(previous: dict, *, kind: str, attempt_id: str = "ATT-002") -> dict:
    current = deepcopy(previous)
    current["attempt_id"] = attempt_id
    current["artifact_root"] = f"artifacts/{attempt_id}"
    current["lineage"].update(
        {
            "kind": kind,
            "previous_attempt": previous["attempt_id"],
            "previous_artifact_root": previous["artifact_root"],
            "previous_evidence_preserved": True,
            "reason": "declared successor",
            "retry_number": 1 if kind == "same_envelope_retry" else None,
        }
    )
    return current


def test_retry_matrix_is_deterministic_and_never_allows_semantic_repair():
    assert set(FAILURE_CLASSES) == {
        "A_ADMISSION",
        "B_OPERATIONAL",
        "C_RUNTIME_ENVELOPE",
        "D_STRUCTURED_COMPATIBILITY",
        "E_APPLICATION_CONTRACT",
        "F_DOWNSTREAM_SYSTEM",
        "G_LEGAL_QUALITY",
        "H_OPERATOR_ABORTED",
    }
    assert all(not failure_policy(code)["semantic_repair"] for code in FAILURE_CLASSES)
    assert failure_policy("E_APPLICATION_CONTRACT")["same_envelope_retry"] == "forbidden"
    assert failure_policy("G_LEGAL_QUALITY")["same_envelope_retry"] == "forbidden"


@pytest.mark.parametrize(
    "failure_class",
    [
        "C_RUNTIME_ENVELOPE",
        "E_APPLICATION_CONTRACT",
        "F_DOWNSTREAM_SYSTEM",
        "G_LEGAL_QUALITY",
        "H_OPERATOR_ABORTED",
    ],
)
def test_non_operational_classes_never_get_same_envelope_retry(failure_class):
    assert not same_envelope_retry_allowed(
        failure_class, retry_number=1, retry_limit=1, operational_cause=True
    )


def test_application_failure_cannot_be_retried_to_get_lucky_answer():
    assert not same_envelope_retry_allowed(
        "E_APPLICATION_CONTRACT", retry_number=1, retry_limit=2
    )
    previous = manifest(failure_class="E_APPLICATION_CONTRACT")
    current = linked(previous, kind="same_envelope_retry")
    with pytest.raises(PolicyError, match="not eligible"):
        validate_successor_attempt(previous, current, retry_limit=2)


def test_operational_retry_is_bounded_and_requires_same_envelope():
    previous = manifest()
    current = linked(previous, kind="same_envelope_retry")
    validate_successor_attempt(previous, current, retry_limit=1)

    with pytest.raises(PolicyError, match="not eligible"):
        validate_successor_attempt(previous, current, retry_limit=0)

    drifted = deepcopy(current)
    drifted["profile"]["sha256"] = "9" * 64
    with pytest.raises(PolicyError, match="comparability drift.*profile.sha256"):
        validate_successor_attempt(previous, drifted, retry_limit=1)


def test_structured_compatibility_retry_requires_proven_operational_cause():
    previous = manifest(failure_class="D_STRUCTURED_COMPATIBILITY")
    current = linked(previous, kind="same_envelope_retry")
    with pytest.raises(PolicyError, match="not eligible"):
        validate_successor_attempt(previous, current, retry_limit=1)
    validate_successor_attempt(
        previous, current, retry_limit=1, operational_cause=True
    )


def test_admission_failure_requires_provider_not_reached_and_gate_fixed_for_retry():
    previous = manifest(failure_class="A_ADMISSION")
    previous["provider"]["request_reached_provider"] = False
    validate_attempt_manifest(previous)

    current = linked(previous, kind="same_envelope_retry")
    with pytest.raises(PolicyError, match="not eligible"):
        validate_successor_attempt(previous, current, retry_limit=1)
    validate_successor_attempt(
        previous, current, retry_limit=1, admission_gate_fixed=True
    )


def test_attempt_ids_and_artifact_roots_are_distinct_and_predecessor_is_preserved():
    previous = manifest()
    current = linked(previous, kind="same_envelope_retry")
    validate_successor_attempt(previous, current, retry_limit=1)

    same_id = deepcopy(current)
    same_id["attempt_id"] = previous["attempt_id"]
    with pytest.raises(PolicyError, match="distinct attempt_id"):
        validate_successor_attempt(previous, same_id, retry_limit=1)

    overwritten = deepcopy(current)
    overwritten["artifact_root"] = previous["artifact_root"]
    with pytest.raises(PolicyError, match="distinct artifact_root"):
        validate_successor_attempt(previous, overwritten, retry_limit=1)

    not_preserved = deepcopy(current)
    not_preserved["lineage"]["previous_evidence_preserved"] = False
    with pytest.raises(PolicyError, match="preserved predecessor evidence|preserve predecessor"):
        validate_successor_attempt(previous, not_preserved, retry_limit=1)


def test_contract_amended_attempt_requires_predecessor_amendment_and_new_profile_identity():
    previous = manifest(failure_class="C_RUNTIME_ENVELOPE")
    current = linked(previous, kind="amended_contract_rerun")
    current["lineage"]["amendment_reference"] = "issue#67-comment-123"
    current["profile"]["id"] = "issue67-controlled-validation-v2"
    current["profile"]["sha256"] = "3" * 64
    current["provider"]["generation_parameters"]["max_output_tokens"] = 9000
    validate_successor_attempt(previous, current)

    same_profile = deepcopy(current)
    same_profile["profile"]["id"] = previous["profile"]["id"]
    with pytest.raises(PolicyError, match="new execution profile id"):
        validate_successor_attempt(previous, same_profile)


def test_diagnostic_and_canonical_attempts_cannot_be_confused():
    diagnostic = manifest(
        designation="diagnostic",
        attempt_id="ATT-D1",
        artifact_root="artifacts/ATT-D1",
    )
    validate_attempt_manifest(diagnostic)

    mislabeled = deepcopy(diagnostic)
    mislabeled["designation"] = "canonical"
    with pytest.raises(PolicyError, match="diagnostic lineage"):
        validate_attempt_manifest(mislabeled)

    canonical = manifest()
    canonical["lineage"]["kind"] = "diagnostic"
    with pytest.raises(PolicyError, match="diagnostic lineage"):
        validate_attempt_manifest(canonical)


def test_aborted_attempt_cannot_be_marked_completed():
    aborted = manifest(status="aborted", failure_class="H_OPERATOR_ABORTED")
    aborted["lineage"]["reason"] = "operator stopped diagnostic after purpose changed"
    validate_attempt_manifest(aborted)

    relabeled = deepcopy(aborted)
    relabeled["status"] = "completed"
    with pytest.raises(PolicyError, match="completed attempt|class H"):
        validate_attempt_manifest(relabeled)


def test_legal_quality_failure_is_frozen_completed_result_not_execution_failure():
    result = manifest(
        status="completed_with_findings",
        failure_class="G_LEGAL_QUALITY",
    )
    result["outcome"]["case_result_state"] = "accepted"
    result["outcome"]["validator_state"] = "pass"
    validate_attempt_manifest(result)
    assert not same_envelope_retry_allowed(
        "G_LEGAL_QUALITY", retry_number=1, retry_limit=1
    )


def test_same_contract_post_fix_allows_code_change_but_detects_profile_request_or_baseline_drift():
    previous = manifest(failure_class="E_APPLICATION_CONTRACT")
    current = linked(previous, kind="same_contract_post_fix")
    current["lineage"]["fix_reference"] = "PR#123@merge-sha"
    current["code"]["git_sha"] = "4" * 40
    current["code"]["image_identity"] = "sha256:" + "5" * 64
    validate_successor_attempt(previous, current)

    for section, key in [
        ("profile", "sha256"),
        ("input", "request_sha256"),
        ("input", "db_baseline_sha256"),
        ("provider", "artifact_or_build_identity"),
    ]:
        drifted = deepcopy(current)
        drifted[section][key] = "8" * 64
        with pytest.raises(PolicyError, match="comparability drift"):
            validate_successor_attempt(previous, drifted)


def test_new_baseline_rerun_requires_explicit_reference_and_changed_baseline():
    previous = manifest(failure_class="F_DOWNSTREAM_SYSTEM")
    current = linked(previous, kind="new_baseline_rerun")
    current["lineage"]["baseline_reference"] = "baseline:v2"
    current["input"]["db_baseline_sha256"] = "6" * 64
    current["input"]["raw_evidence_manifest_sha256"] = "7" * 64
    validate_successor_attempt(previous, current)

    unchanged = deepcopy(current)
    unchanged["input"]["db_baseline_sha256"] = previous["input"]["db_baseline_sha256"]
    with pytest.raises(PolicyError, match="changed baseline SHA"):
        validate_successor_attempt(previous, unchanged)


def test_semantic_repair_is_rejected_for_every_attempt():
    value = manifest()
    value["control"]["semantic_repair_applied"] = True
    with pytest.raises(PolicyError, match="semantic repair"):
        validate_attempt_manifest(value)


def test_independent_control_requires_valid_uninspected_canonical_case_result():
    completed = manifest(status="completed", failure_class=None)
    completed["outcome"]["case_id"] = "CASE-abc"
    completed["outcome"]["case_result_state"] = "accepted"
    completed["outcome"]["validator_state"] = "pass"
    validate_attempt_manifest(completed)
    assert independent_control_ready(completed)

    rejected = manifest(failure_class="E_APPLICATION_CONTRACT")
    assert not independent_control_ready(rejected)

    inspected = deepcopy(completed)
    inspected["control"]["semantic_payload_inspected_before_independent_control"] = True
    assert not independent_control_ready(inspected)


def test_manifest_requires_explicit_evidence_keys_even_when_values_are_unavailable():
    value = manifest()
    del value["provider"]["raw_response_sha256"]
    with pytest.raises(PolicyError, match="missing provider fields"):
        validate_attempt_manifest(value)
