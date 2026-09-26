#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    ADMISSION = "admission_preflight"
    TRANSIENT_OPERATIONAL = "transient_operational"
    RUNTIME_ENVELOPE = "runtime_envelope_incompatibility"
    STRUCTURED_COMPATIBILITY = "structured_generation_compatibility"
    APPLICATION_CONTRACT = "application_contract"
    DOWNSTREAM_SYSTEM = "downstream_system"
    LEGAL_QUALITY = "legal_semantic_quality"
    HUMAN_ABORT = "human_abort"


class ProviderContactState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    DISPATCH_ATTEMPTED = "dispatch_attempted"
    RESPONSE_RECEIVED = "response_received"
    UNKNOWN = "unknown"


class UpstreamStage(str, Enum):
    NONE = "none"
    CASE_DRAFT = "case_draft"
    CASE_RESULT = "case_result"


class ParentResolutionMode(str, Enum):
    SAME_VALIDATION_RESUME = "same_validation_resume"
    DIAGNOSTIC_COMPLETION = "diagnostic_completion"


@dataclass(frozen=True)
class Disposition:
    same_envelope_retry: bool
    contract_amendment: str
    model_substitution: str
    semantic_repair: bool
    parent_blocked: bool


_DISPOSITIONS = {
    FailureClass.ADMISSION: Disposition(True, "if_contract_changes", "only_if_authorized", False, True),
    FailureClass.TRANSIENT_OPERATIONAL: Disposition(True, "not_required", "no", False, False),
    FailureClass.RUNTIME_ENVELOPE: Disposition(False, "required", "no", False, True),
    FailureClass.STRUCTURED_COMPATIBILITY: Disposition(False, "if_design_changes", "separate_declared_run_only", False, True),
    FailureClass.APPLICATION_CONTRACT: Disposition(False, "only_explicit_contract_change", "no", False, True),
    FailureClass.DOWNSTREAM_SYSTEM: Disposition(False, "only_if_contract_changes", "no", False, True),
    FailureClass.LEGAL_QUALITY: Disposition(False, "no_to_improve_score", "diagnostic_only", False, False),
    FailureClass.HUMAN_ABORT: Disposition(False, "if_purpose_or_contract_changes", "no", False, True),
}

TERMINAL_STATUSES = {"failed", "accepted", "aborted"}
DESIGNATIONS = {"canonical", "diagnostic"}
RERUN_KINDS = {"same_contract_post_fix", "amended_contract", "new_baseline"}
SYSTEMIC_DIAGNOSTIC_COMPLETION_CLASSES = {
    FailureClass.RUNTIME_ENVELOPE,
    FailureClass.STRUCTURED_COMPATIBILITY,
    FailureClass.APPLICATION_CONTRACT,
    FailureClass.DOWNSTREAM_SYSTEM,
}


def disposition_for(failure_class: FailureClass | str) -> Disposition:
    """Return deterministic retry/disposition policy for one declared class."""
    return _DISPOSITIONS[FailureClass(failure_class)]


def _failure_class(value: Any) -> FailureClass | None:
    if value in (None, ""):
        return None
    try:
        return FailureClass(value)
    except (TypeError, ValueError):
        return None


def _structured_reason(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("reason"), str)
        and bool(value["reason"].strip())
        and isinstance(value.get("reference"), str)
        and bool(value["reference"].strip())
    )


def validate_attempt_manifest(
    manifest: dict[str, Any],
    *,
    require_admission_manifest: bool = False,
) -> list[str]:
    """Validate controlled-attempt lifecycle semantics.

    This validates policy shape only. Persistence and broad execution provenance
    remain owned by the runtime evidence layer and issue #11.
    """
    errors: list[str] = []
    required = {
        "parent_validation_issue",
        "attempt_id",
        "artifact_root",
        "status",
        "designation",
        "started_at",
        "git_sha",
        "image_identity",
        "execution_profile_id",
        "execution_profile_sha256",
        "request_sha256",
        "case_input_sha256",
        "baseline_sha256",
        "raw_evidence_manifest_sha256",
        "provider_identity",
        "generation_parameters",
        "provider_contact_state",
        "accepted_upstream_stage",
        "provider_evidence_ref",
        "semantic_payload_inspected_before_control",
    }
    if require_admission_manifest:
        required.add("admission_manifest_ref")

    for field in sorted(required):
        if field not in manifest:
            errors.append(f"missing:{field}")

    status = manifest.get("status")
    designation = manifest.get("designation")
    failure = _failure_class(manifest.get("failure_class"))

    if designation not in DESIGNATIONS:
        errors.append("designation:invalid")
    if status not in TERMINAL_STATUSES | {"running"}:
        errors.append("status:invalid")
    if manifest.get("failure_class") and failure is None:
        errors.append("failure_class:invalid")

    canonical_flag = manifest.get("canonical")
    if canonical_flag is not None and canonical_flag != (designation == "canonical"):
        errors.append("designation:canonical_flag_mismatch")

    try:
        contact = ProviderContactState(manifest.get("provider_contact_state"))
    except (TypeError, ValueError):
        contact = None
        errors.append("provider_contact_state:invalid")

    try:
        upstream = UpstreamStage(manifest.get("accepted_upstream_stage"))
    except (TypeError, ValueError):
        upstream = None
        errors.append("accepted_upstream_stage:invalid")

    if status in TERMINAL_STATUSES and not manifest.get("ended_at"):
        errors.append("terminal:ended_at_required")
    if status == "running" and manifest.get("ended_at"):
        errors.append("running:ended_at_forbidden")

    if status == "running" and failure is not None:
        errors.append("running:failure_class_forbidden")
    elif status == "failed":
        if failure is None:
            errors.append("failed:failure_class_required")
        elif failure in {FailureClass.LEGAL_QUALITY, FailureClass.HUMAN_ABORT}:
            errors.append("failed:classification_incompatible")
    elif status == "aborted":
        if failure != FailureClass.HUMAN_ABORT:
            errors.append("aborted:human_abort_class_required")
        if not manifest.get("abort_reason"):
            errors.append("aborted:reason_required")
        if manifest.get("resulting_case_id"):
            errors.append("aborted:cannot_have_resulting_case_id")
    elif status == "accepted":
        if failure not in {None, FailureClass.LEGAL_QUALITY}:
            errors.append("accepted:failure_class_incompatible")
        if upstream != UpstreamStage.CASE_RESULT:
            errors.append("accepted:case_result_stage_required")
        if not manifest.get("resulting_case_id"):
            errors.append("accepted:resulting_case_id_required")

    if failure == FailureClass.ADMISSION:
        if contact != ProviderContactState.NOT_ATTEMPTED:
            errors.append("admission:provider_contact_forbidden")
        if upstream != UpstreamStage.NONE:
            errors.append("admission:upstream_stage_forbidden")

    if failure in {
        FailureClass.TRANSIENT_OPERATIONAL,
        FailureClass.RUNTIME_ENVELOPE,
        FailureClass.STRUCTURED_COMPATIBILITY,
    }:
        if contact == ProviderContactState.NOT_ATTEMPTED:
            errors.append("provider_failure:contact_attempt_required")
        if upstream != UpstreamStage.NONE:
            errors.append("provider_failure:accepted_upstream_forbidden")

    if failure == FailureClass.APPLICATION_CONTRACT:
        if contact != ProviderContactState.RESPONSE_RECEIVED:
            errors.append("application_contract:provider_response_required")
        if upstream != UpstreamStage.NONE:
            errors.append("application_contract:accepted_upstream_forbidden")

    if failure in {
        FailureClass.TRANSIENT_OPERATIONAL,
        FailureClass.RUNTIME_ENVELOPE,
        FailureClass.STRUCTURED_COMPATIBILITY,
        FailureClass.APPLICATION_CONTRACT,
    } and contact != ProviderContactState.NOT_ATTEMPTED and not manifest.get(
        "provider_evidence_ref"
    ):
        errors.append("provider_failure:provider_evidence_ref_required")

    if failure == FailureClass.DOWNSTREAM_SYSTEM and upstream not in {
        UpstreamStage.CASE_DRAFT,
        UpstreamStage.CASE_RESULT,
    }:
        errors.append("downstream_system:accepted_upstream_required")

    if failure == FailureClass.LEGAL_QUALITY:
        if status != "accepted":
            errors.append("legal_quality:structural_acceptance_required")
        if upstream != UpstreamStage.CASE_RESULT:
            errors.append("legal_quality:case_result_required")

    if (
        status == "accepted"
        and failure is None
        and upstream != UpstreamStage.CASE_RESULT
    ):
        errors.append("accepted:case_result_stage_required")

    predecessor = manifest.get("previous_attempt")
    amendment = manifest.get("contract_amendment")
    if predecessor and predecessor == manifest.get("attempt_id"):
        errors.append("lineage:self_reference")
    if amendment and not predecessor:
        errors.append("amendment:previous_attempt_required")
    if amendment and not _structured_reason(amendment):
        errors.append("amendment:reason_reference_required")
    if manifest.get("rerun_kind") == "amended_contract" and not amendment:
        errors.append("amended_rerun:contract_amendment_required")

    if require_admission_manifest and not manifest.get("admission_manifest_ref"):
        errors.append("admission_manifest_ref:required")
    return errors


def detect_comparability_drift(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Return semantic/environment fields that must not drift for same-contract post-fix comparison."""
    fields = (
        "request_sha256",
        "case_input_sha256",
        "baseline_sha256",
        "raw_evidence_manifest_sha256",
        "execution_profile_id",
        "execution_profile_sha256",
        "provider_identity",
        "generation_parameters",
    )
    return [field for field in fields if previous.get(field) != current.get(field)]


def detect_same_envelope_retry_drift(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Return fields that must remain identical for a bounded operational retry."""
    fields = ("git_sha", "image_identity")
    drift = [field for field in fields if previous.get(field) != current.get(field)]
    return drift + detect_comparability_drift(previous, current)


def same_envelope_retry_allowed(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    retry_number: int,
    max_retries: int,
    previous_evidence_preserved: bool,
) -> tuple[bool, list[str]]:
    """Validate a bounded retry of a demonstrably transient operational failure."""
    errors = validate_attempt_manifest(current)
    if previous.get("status") != "failed":
        errors.append("retry:previous_attempt_not_failed")
    if _failure_class(previous.get("failure_class")) != FailureClass.TRANSIENT_OPERATIONAL:
        errors.append("retry:previous_failure_not_transient_operational")
    if current.get("status") != "running":
        errors.append("retry:status_must_be_running")
    if current.get("attempt_id") == previous.get("attempt_id"):
        errors.append("retry:attempt_id_must_change")
    if current.get("artifact_root") == previous.get("artifact_root"):
        errors.append("retry:artifact_root_must_change")
    if current.get("previous_attempt") != previous.get("attempt_id"):
        errors.append("retry:previous_attempt_mismatch")
    if not previous_evidence_preserved:
        errors.append("retry:previous_evidence_must_be_preserved")
    if retry_number < 1 or max_retries < 1 or retry_number > max_retries:
        errors.append("retry:budget_exceeded_or_invalid")
    if current.get("contract_amendment"):
        errors.append("retry:contract_amendment_forbidden")
    errors.extend(
        f"retry_drift:{field}"
        for field in detect_same_envelope_retry_drift(previous, current)
    )
    return not errors, errors


def post_fix_rerun_allowed(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    defect_reference: str | None,
    regression_verified: bool,
    previous_evidence_preserved: bool,
) -> tuple[bool, list[str]]:
    """Check the minimum gate for a declared post-fix controlled rerun."""
    errors = validate_attempt_manifest(current)
    if previous.get("status") != "failed":
        errors.append("rerun:previous_attempt_not_failed")
    if current.get("status") != "running":
        errors.append("rerun:status_must_be_running")
    if current.get("attempt_id") == previous.get("attempt_id"):
        errors.append("rerun:attempt_id_must_change")
    if current.get("artifact_root") == previous.get("artifact_root"):
        errors.append("rerun:artifact_root_must_change")
    if current.get("previous_attempt") != previous.get("attempt_id"):
        errors.append("rerun:previous_attempt_mismatch")
    if not defect_reference:
        errors.append("rerun:defect_reference_required")
    if not regression_verified:
        errors.append("rerun:regression_verification_required")
    if not previous_evidence_preserved:
        errors.append("rerun:previous_evidence_must_be_preserved")

    kind = current.get("rerun_kind")
    if kind not in RERUN_KINDS:
        errors.append("rerun:kind_invalid")
        return not errors, errors

    if kind == "same_contract_post_fix":
        errors.extend(
            f"same_contract_drift:{field}"
            for field in detect_comparability_drift(previous, current)
        )
        if current.get("contract_amendment"):
            errors.append("same_contract:amendment_forbidden")

    elif kind == "amended_contract":
        amendment = current.get("contract_amendment")
        if not _structured_reason(amendment):
            errors.append("amended_rerun:reason_reference_required")
        if current.get("execution_profile_id") == previous.get("execution_profile_id"):
            errors.append("amended_rerun:new_profile_id_required")
        if current.get("execution_profile_sha256") == previous.get(
            "execution_profile_sha256"
        ):
            errors.append("amended_rerun:new_profile_sha_required")

    elif kind == "new_baseline":
        baseline_change = current.get("baseline_change")
        if not _structured_reason(baseline_change):
            errors.append("new_baseline:reason_reference_required")
        if current.get("baseline_sha256") == previous.get("baseline_sha256"):
            errors.append("new_baseline:baseline_sha_must_change")

    return not errors, errors


def validate_parent_resolution(resolution: dict[str, Any]) -> list[str]:
    """Validate whether a failed validation resumes in-place or closes diagnostically."""
    errors: list[str] = []
    required = {
        "parent_validation_issue",
        "mode",
        "decision_authority",
        "decision_reference",
        "failed_attempts_preserved",
        "close_parent",
        "case_result_legal_pass",
    }
    for field in sorted(required):
        if field not in resolution:
            errors.append(f"missing:{field}")

    try:
        mode = ParentResolutionMode(resolution.get("mode"))
    except (TypeError, ValueError):
        mode = None
        errors.append("parent_resolution:mode_invalid")

    authority = resolution.get("decision_authority")
    if authority not in {"controller", "operator", "controller_operator"}:
        errors.append("parent_resolution:decision_authority_invalid")
    if not resolution.get("decision_reference"):
        errors.append("parent_resolution:decision_reference_required")
    if resolution.get("failed_attempts_preserved") is not True:
        errors.append("parent_resolution:failed_attempts_must_be_preserved")

    if mode == ParentResolutionMode.SAME_VALIDATION_RESUME:
        if resolution.get("close_parent") is not False:
            errors.append("same_validation_resume:parent_must_remain_open")
        if resolution.get("same_case_post_fix_rerun") is not True:
            errors.append("same_validation_resume:post_fix_rerun_required")
        if resolution.get("successor_validation_issue") not in (None, ""):
            errors.append("same_validation_resume:successor_forbidden")

    elif mode == ParentResolutionMode.DIAGNOSTIC_COMPLETION:
        if resolution.get("close_parent") is not True:
            errors.append("diagnostic_completion:close_parent_required")
        if resolution.get("case_result_legal_pass") is not False:
            errors.append("diagnostic_completion:legal_pass_forbidden")
        if resolution.get("outcome") != "diagnostic_blocker":
            errors.append("diagnostic_completion:outcome_must_be_diagnostic_blocker")
        if resolution.get("blockers_owned_separately") is not True:
            errors.append("diagnostic_completion:blockers_must_be_separately_owned")

        blockers = resolution.get("blocker_issues")
        if not isinstance(blockers, list) or not blockers:
            errors.append("diagnostic_completion:blocker_issues_required")
        elif resolution.get("parent_validation_issue") in blockers:
            errors.append("diagnostic_completion:blocker_must_be_separate_child")

        successor = resolution.get("successor_validation_issue")
        if not successor:
            errors.append("diagnostic_completion:successor_required")
        elif successor == resolution.get("parent_validation_issue"):
            errors.append("diagnostic_completion:successor_must_be_distinct")

        failure = _failure_class(resolution.get("blocking_failure_class"))
        if failure not in SYSTEMIC_DIAGNOSTIC_COMPLETION_CLASSES:
            errors.append("diagnostic_completion:systemic_blocking_class_required")
        if resolution.get("same_case_post_fix_rerun") is True:
            errors.append("diagnostic_completion:same_case_rerun_forbidden")

    return errors


def parent_may_close(resolution: dict[str, Any]) -> bool:
    """Return True only for a fully valid explicit diagnostic completion."""
    return (
        not validate_parent_resolution(resolution)
        and resolution.get("mode") == ParentResolutionMode.DIAGNOSTIC_COMPLETION.value
    )
