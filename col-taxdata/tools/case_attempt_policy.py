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


def disposition_for(failure_class: FailureClass | str) -> Disposition:
    """Return deterministic retry/disposition policy for one declared failure class."""
    return _DISPOSITIONS[FailureClass(failure_class)]


def validate_attempt_manifest(manifest: dict[str, Any]) -> list[str]:
    """Validate lifecycle invariants without pretending to implement issue #11 provenance."""
    errors: list[str] = []
    required = {
        "parent_validation_issue",
        "attempt_id",
        "status",
        "designation",
        "started_at",
        "git_sha",
        "execution_profile_id",
        "execution_profile_sha256",
        "request_sha256",
        "case_input_sha256",
        "baseline_sha256",
        "raw_evidence_manifest_sha256",
        "provider_identity",
        "generation_parameters",
        "semantic_payload_inspected_before_control",
    }
    for field in sorted(required):
        if field not in manifest:
            errors.append(f"missing:{field}")

    if manifest.get("designation") not in DESIGNATIONS:
        errors.append("designation:invalid")
    if manifest.get("status") not in TERMINAL_STATUSES | {"running"}:
        errors.append("status:invalid")
    if manifest.get("status") == "aborted" and manifest.get("resulting_case_id"):
        errors.append("aborted:cannot_have_resulting_case_id")
    if manifest.get("status") == "accepted" and manifest.get("failure_class"):
        errors.append("accepted:cannot_have_failure_class")
    if manifest.get("status") == "failed" and not manifest.get("failure_class"):
        errors.append("failed:failure_class_required")
    if manifest.get("failure_class"):
        try:
            disposition_for(manifest["failure_class"])
        except ValueError:
            errors.append("failure_class:invalid")

    predecessor = manifest.get("previous_attempt")
    amendment = manifest.get("contract_amendment")
    if amendment and not predecessor:
        errors.append("amendment:previous_attempt_required")
    if manifest.get("rerun_kind") == "amended_contract" and not amendment:
        errors.append("amended_rerun:contract_amendment_required")
    if manifest.get("designation") == "diagnostic" and manifest.get("canonical") is True:
        errors.append("diagnostic:cannot_be_canonical")
    return errors


def detect_comparability_drift(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Return frozen identity fields that changed between comparable attempts."""
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


def post_fix_rerun_allowed(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    defect_reference: str | None,
    regression_verified: bool,
) -> tuple[bool, list[str]]:
    """Check the minimum gate for a declared post-fix controlled rerun."""
    errors = validate_attempt_manifest(current)
    if current.get("attempt_id") == previous.get("attempt_id"):
        errors.append("rerun:attempt_id_must_change")
    if current.get("artifact_root") and current.get("artifact_root") == previous.get("artifact_root"):
        errors.append("rerun:artifact_root_must_change")
    if current.get("previous_attempt") != previous.get("attempt_id"):
        errors.append("rerun:previous_attempt_mismatch")
    if not defect_reference:
        errors.append("rerun:defect_reference_required")
    if not regression_verified:
        errors.append("rerun:regression_verification_required")

    drift = detect_comparability_drift(previous, current)
    kind = current.get("rerun_kind")
    if drift and kind == "same_contract_post_fix":
        errors.extend(f"same_contract_drift:{field}" for field in drift)
    if kind not in {"same_contract_post_fix", "amended_contract", "new_baseline"}:
        errors.append("rerun:kind_invalid")
    return not errors, errors
