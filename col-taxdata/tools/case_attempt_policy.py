#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = 1

FAILURE_CLASSES = {
    "A_ADMISSION": {
        "label": "pre_execution_admission_failure",
        "same_envelope_retry": "after_gate_fixed",
        "contract_amendment": "only_if_contract_changes",
        "backend_substitution": "only_if_explicitly_authorized",
        "semantic_repair": False,
        "parent_disposition": "remain_at_admission_gate",
    },
    "B_OPERATIONAL": {
        "label": "transport_provider_operational_failure",
        "same_envelope_retry": "allowed_bounded",
        "contract_amendment": "not_required",
        "backend_substitution": "forbidden",
        "semantic_repair": False,
        "parent_disposition": "retry_or_block_after_bound",
    },
    "C_RUNTIME_ENVELOPE": {
        "label": "runtime_envelope_incompatibility",
        "same_envelope_retry": "forbidden",
        "contract_amendment": "required_before_canonical_rerun",
        "backend_substitution": "forbidden",
        "semantic_repair": False,
        "parent_disposition": "blocked_pending_amendment",
    },
    "D_STRUCTURED_COMPATIBILITY": {
        "label": "structured_generation_compatibility_failure",
        "same_envelope_retry": "operational_cause_only",
        "contract_amendment": "explicit_design_change_if_needed",
        "backend_substitution": "separate_declared_run_only",
        "semantic_repair": False,
        "parent_disposition": "blocked_if_systemic",
    },
    "E_APPLICATION_CONTRACT": {
        "label": "application_contract_failure",
        "same_envelope_retry": "forbidden",
        "contract_amendment": "explicit_authoritative_change_only",
        "backend_substitution": "forbidden",
        "semantic_repair": False,
        "parent_disposition": "blocked_pending_defect_or_contract_change",
    },
    "F_DOWNSTREAM_SYSTEM": {
        "label": "valid_draft_invalid_downstream_state",
        "same_envelope_retry": "forbidden",
        "contract_amendment": "only_if_contract_changes",
        "backend_substitution": "forbidden",
        "semantic_repair": False,
        "parent_disposition": "blocked_on_downstream_subsystem",
    },
    "G_LEGAL_QUALITY": {
        "label": "valid_structural_result_poor_or_incorrect_legal_result",
        "same_envelope_retry": "forbidden",
        "contract_amendment": "forbidden_to_improve_score",
        "backend_substitution": "separate_diagnostic_only",
        "semantic_repair": False,
        "parent_disposition": "freeze_score_and_diagnose",
    },
    "H_OPERATOR_ABORTED": {
        "label": "human_operator_aborted_attempt",
        "same_envelope_retry": "forbidden",
        "contract_amendment": "only_if_purpose_or_contract_changes",
        "backend_substitution": "forbidden",
        "semantic_repair": False,
        "parent_disposition": "explicit_new_attempt_if_resumed",
    },
}

TERMINAL_STATUSES = {
    "failed",
    "aborted",
    "completed",
    "completed_with_findings",
}

DESIGNATIONS = {"canonical", "diagnostic"}

LINEAGE_KINDS = {
    "initial",
    "same_envelope_retry",
    "same_contract_post_fix",
    "amended_contract_rerun",
    "new_baseline_rerun",
    "diagnostic",
}

_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "parent_validation_issue",
    "attempt_id",
    "designation",
    "status",
    "failure_class",
    "artifact_root",
    "timestamps",
    "code",
    "profile",
    "input",
    "provider",
    "outcome",
    "lineage",
    "control",
}

_REQUIRED_NESTED = {
    "timestamps": {"started_at", "ended_at"},
    "code": {"git_sha", "image_identity"},
    "profile": {"id", "sha256"},
    "input": {
        "request_sha256",
        "case_input_sha256",
        "db_baseline_sha256",
        "raw_evidence_manifest_sha256",
    },
    "provider": {
        "name",
        "model",
        "artifact_or_build_identity",
        "generation_parameters",
        "request_reached_provider",
        "raw_response_sha256",
        "rejected_output_artifact",
        "http_status",
        "error",
        "finish_reason",
        "usage",
        "timing",
    },
    "outcome": {
        "case_id",
        "case_result_state",
        "persistence_state",
        "materialization_state",
        "validator_state",
        "provenance_state",
        "doctor_state",
    },
    "lineage": {
        "kind",
        "previous_attempt",
        "previous_artifact_root",
        "previous_evidence_preserved",
        "reason",
        "amendment_reference",
        "fix_reference",
        "baseline_reference",
        "retry_number",
    },
    "control": {
        "semantic_payload_inspected_before_independent_control",
        "semantic_repair_applied",
    },
}


class PolicyError(ValueError):
    """Raised when a controlled-validation attempt violates issue #93 policy."""


def failure_policy(failure_class: str) -> dict[str, Any]:
    """Return the deterministic retry/disposition policy for one declared class."""
    try:
        return deepcopy(FAILURE_CLASSES[failure_class])
    except KeyError as exc:
        raise PolicyError(f"unknown failure class: {failure_class}") from exc


def same_envelope_retry_allowed(
    failure_class: str,
    *,
    admission_gate_fixed: bool = False,
    operational_cause: bool = False,
    retry_number: int | None = None,
    retry_limit: int | None = None,
) -> bool:
    """Evaluate only same-envelope retry eligibility.

    The policy intentionally requires the caller/profile to supply the retry bound;
    #93 defines that retries are bounded but does not invent a universal count.
    """
    rule = failure_policy(failure_class)["same_envelope_retry"]
    if rule == "after_gate_fixed":
        return admission_gate_fixed
    if rule == "allowed_bounded":
        return _within_bound(retry_number, retry_limit)
    if rule == "operational_cause_only":
        return operational_cause and _within_bound(retry_number, retry_limit)
    return False


def _within_bound(retry_number: int | None, retry_limit: int | None) -> bool:
    return (
        isinstance(retry_number, int)
        and isinstance(retry_limit, int)
        and retry_limit > 0
        and 1 <= retry_number <= retry_limit
    )


def validate_attempt_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the #93 controlled-attempt overlay.

    This is intentionally not the broad processing-run manifest owned by issue #11.
    Values may be None when evidence is genuinely unavailable, but the key remains
    present so absence is explicit rather than silently omitted or guessed.
    """
    missing = _REQUIRED_TOP_LEVEL.difference(manifest)
    if missing:
        raise PolicyError(f"missing attempt fields: {sorted(missing)}")

    if manifest["schema_version"] != POLICY_SCHEMA_VERSION:
        raise PolicyError("unsupported attempt policy schema_version")
    if not isinstance(manifest["parent_validation_issue"], int):
        raise PolicyError("parent_validation_issue must be an integer issue number")
    if not _nonempty_string(manifest["attempt_id"]):
        raise PolicyError("attempt_id must be non-empty")
    if manifest["designation"] not in DESIGNATIONS:
        raise PolicyError("designation must be canonical or diagnostic")
    if manifest["status"] not in TERMINAL_STATUSES:
        raise PolicyError("attempt status must be terminal")
    if not _nonempty_string(manifest["artifact_root"]):
        raise PolicyError("artifact_root must be non-empty")

    for section, keys in _REQUIRED_NESTED.items():
        value = manifest[section]
        if not isinstance(value, Mapping):
            raise PolicyError(f"{section} must be an object")
        section_missing = keys.difference(value)
        if section_missing:
            raise PolicyError(
                f"missing {section} fields: {sorted(section_missing)}"
            )

    failure_class = manifest["failure_class"]
    status = manifest["status"]
    if failure_class is not None and failure_class not in FAILURE_CLASSES:
        raise PolicyError(f"unknown failure class: {failure_class}")

    if status == "completed":
        if failure_class is not None:
            raise PolicyError("completed attempt cannot carry a failure class")
    elif status == "completed_with_findings":
        if failure_class != "G_LEGAL_QUALITY":
            raise PolicyError(
                "completed_with_findings is reserved for class G legal-quality findings"
            )
    elif status == "aborted":
        if failure_class != "H_OPERATOR_ABORTED":
            raise PolicyError("aborted status requires class H")
        if not _nonempty_string(manifest["lineage"]["reason"]):
            raise PolicyError("aborted attempt requires an explicit reason")
    elif status == "failed":
        if failure_class not in {
            "A_ADMISSION",
            "B_OPERATIONAL",
            "C_RUNTIME_ENVELOPE",
            "D_STRUCTURED_COMPATIBILITY",
            "E_APPLICATION_CONTRACT",
            "F_DOWNSTREAM_SYSTEM",
        }:
            raise PolicyError("failed status requires failure class A-F")

    if failure_class == "H_OPERATOR_ABORTED" and status != "aborted":
        raise PolicyError("class H can only be recorded as aborted")
    if failure_class == "G_LEGAL_QUALITY" and status != "completed_with_findings":
        raise PolicyError("class G is a completed structural result with findings")

    if manifest["control"]["semantic_repair_applied"] is not False:
        raise PolicyError("post-response semantic repair is never authorized")

    if failure_class == "A_ADMISSION":
        if manifest["provider"]["request_reached_provider"] is not False:
            raise PolicyError("admission failure must occur before provider execution")

    kind = manifest["lineage"]["kind"]
    if kind not in LINEAGE_KINDS:
        raise PolicyError(f"unknown lineage kind: {kind}")
    if kind == "diagnostic" and manifest["designation"] != "diagnostic":
        raise PolicyError("diagnostic lineage requires diagnostic designation")
    if manifest["designation"] == "diagnostic" and kind != "diagnostic":
        raise PolicyError("diagnostic attempts must be explicitly labeled diagnostic")
    if kind == "initial":
        _require_no_predecessor(manifest)
    elif kind == "same_envelope_retry":
        _require_predecessor_fields(manifest)
        if not _positive_int(manifest["lineage"]["retry_number"]):
            raise PolicyError("same-envelope retry requires positive retry_number")
        if not _nonempty_string(manifest["lineage"]["reason"]):
            raise PolicyError("same-envelope retry requires a reason")
    elif kind == "same_contract_post_fix":
        _require_predecessor_fields(manifest)
        if not _nonempty_string(manifest["lineage"]["fix_reference"]):
            raise PolicyError("post-fix rerun requires fix_reference")
        if not _nonempty_string(manifest["lineage"]["reason"]):
            raise PolicyError("post-fix rerun requires a reason")
    elif kind == "amended_contract_rerun":
        _require_predecessor_fields(manifest)
        if not _nonempty_string(manifest["lineage"]["amendment_reference"]):
            raise PolicyError("amended rerun requires amendment_reference")
        if not _nonempty_string(manifest["lineage"]["reason"]):
            raise PolicyError("amended rerun requires a reason")
    elif kind == "new_baseline_rerun":
        _require_predecessor_fields(manifest)
        if not _nonempty_string(manifest["lineage"]["baseline_reference"]):
            raise PolicyError("new-baseline rerun requires baseline_reference")
        if not _nonempty_string(manifest["lineage"]["reason"]):
            raise PolicyError("new-baseline rerun requires a reason")


def validate_successor_attempt(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    retry_limit: int | None = None,
    operational_cause: bool = False,
    admission_gate_fixed: bool = False,
) -> None:
    """Validate a linked retry/rerun without mutating or relabeling the predecessor."""
    validate_attempt_manifest(previous)
    validate_attempt_manifest(current)

    if previous["parent_validation_issue"] != current["parent_validation_issue"]:
        raise PolicyError("successor must belong to the same parent validation")
    if previous["attempt_id"] == current["attempt_id"]:
        raise PolicyError("successor must use a distinct attempt_id")
    if previous["artifact_root"] == current["artifact_root"]:
        raise PolicyError("successor must use a distinct artifact_root")

    lineage = current["lineage"]
    if lineage["previous_attempt"] != previous["attempt_id"]:
        raise PolicyError("successor previous_attempt does not reference predecessor")
    if lineage["previous_artifact_root"] != previous["artifact_root"]:
        raise PolicyError(
            "successor previous_artifact_root does not reference predecessor evidence"
        )
    if lineage["previous_evidence_preserved"] is not True:
        raise PolicyError("successor must explicitly preserve predecessor evidence")

    kind = lineage["kind"]
    if kind == "same_envelope_retry":
        if current["designation"] != previous["designation"]:
            raise PolicyError("same-envelope retry cannot change designation")
        failure_class = previous["failure_class"]
        if failure_class is None or not same_envelope_retry_allowed(
            failure_class,
            admission_gate_fixed=admission_gate_fixed,
            operational_cause=operational_cause,
            retry_number=lineage["retry_number"],
            retry_limit=retry_limit,
        ):
            raise PolicyError(
                f"failure class {failure_class} is not eligible for this same-envelope retry"
            )
        _require_equal_fields(previous, current, _SAME_ENVELOPE_FIELDS)
    elif kind == "same_contract_post_fix":
        _require_canonical(current)
        _require_equal_fields(previous, current, _SAME_CONTRACT_POST_FIX_FIELDS)
    elif kind == "amended_contract_rerun":
        _require_canonical(current)
        _require_equal_fields(previous, current, _AMENDED_CONTRACT_STABLE_FIELDS)
        if previous["profile"]["id"] == current["profile"]["id"]:
            raise PolicyError("contract amendment requires a new execution profile id")
        if previous["profile"]["sha256"] == current["profile"]["sha256"]:
            raise PolicyError("contract amendment requires a new execution profile SHA")
    elif kind == "new_baseline_rerun":
        _require_canonical(current)
        _require_equal_fields(previous, current, _NEW_BASELINE_STABLE_FIELDS)
        if (
            previous["input"]["db_baseline_sha256"]
            == current["input"]["db_baseline_sha256"]
        ):
            raise PolicyError("new-baseline rerun requires a changed baseline SHA")
    elif kind == "diagnostic":
        if current["designation"] != "diagnostic":
            raise PolicyError("linked diagnostic must remain diagnostic")
    else:
        raise PolicyError("initial attempt cannot be validated as a successor")


def independent_control_ready(manifest: Mapping[str, Any]) -> bool:
    """Return whether a frozen canonical Phase A may feed an isolated Phase B."""
    validate_attempt_manifest(manifest)
    return (
        manifest["designation"] == "canonical"
        and manifest["status"] == "completed"
        and manifest["failure_class"] is None
        and manifest["outcome"]["case_result_state"] == "accepted"
        and manifest["outcome"]["validator_state"] == "pass"
        and manifest["control"][
            "semantic_payload_inspected_before_independent_control"
        ]
        is False
        and manifest["control"]["semantic_repair_applied"] is False
    )


def _require_canonical(manifest: Mapping[str, Any]) -> None:
    if manifest["designation"] != "canonical":
        raise PolicyError("controlled rerun must be canonical, not diagnostic")


def _require_no_predecessor(manifest: Mapping[str, Any]) -> None:
    lineage = manifest["lineage"]
    if (
        lineage["previous_attempt"] is not None
        or lineage["previous_artifact_root"] is not None
    ):
        raise PolicyError("initial attempt cannot reference a predecessor")
    if lineage["previous_evidence_preserved"] not in (False, None):
        raise PolicyError("initial attempt cannot claim predecessor evidence")


def _require_predecessor_fields(manifest: Mapping[str, Any]) -> None:
    lineage = manifest["lineage"]
    if not _nonempty_string(lineage["previous_attempt"]):
        raise PolicyError("linked attempt requires previous_attempt")
    if not _nonempty_string(lineage["previous_artifact_root"]):
        raise PolicyError("linked attempt requires previous_artifact_root")
    if lineage["previous_evidence_preserved"] is not True:
        raise PolicyError("linked attempt requires preserved predecessor evidence")


def _require_equal_fields(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> None:
    drift = [
        ".".join(path)
        for path in paths
        if _get(previous, path) != _get(current, path)
    ]
    if drift:
        raise PolicyError(f"comparability drift detected: {', '.join(drift)}")


def _get(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        current = current[part]
    return current


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and value > 0


_SAME_ENVELOPE_FIELDS = (
    ("code", "git_sha"),
    ("code", "image_identity"),
    ("profile", "id"),
    ("profile", "sha256"),
    ("input", "request_sha256"),
    ("input", "case_input_sha256"),
    ("input", "db_baseline_sha256"),
    ("input", "raw_evidence_manifest_sha256"),
    ("provider", "name"),
    ("provider", "model"),
    ("provider", "artifact_or_build_identity"),
    ("provider", "generation_parameters"),
)

_SAME_CONTRACT_POST_FIX_FIELDS = (
    ("profile", "id"),
    ("profile", "sha256"),
    ("input", "request_sha256"),
    ("input", "case_input_sha256"),
    ("input", "db_baseline_sha256"),
    ("input", "raw_evidence_manifest_sha256"),
    ("provider", "name"),
    ("provider", "model"),
    ("provider", "artifact_or_build_identity"),
    ("provider", "generation_parameters"),
)

_AMENDED_CONTRACT_STABLE_FIELDS = (
    ("input", "request_sha256"),
    ("input", "case_input_sha256"),
    ("input", "db_baseline_sha256"),
    ("input", "raw_evidence_manifest_sha256"),
    ("provider", "name"),
    ("provider", "model"),
    ("provider", "artifact_or_build_identity"),
)

_NEW_BASELINE_STABLE_FIELDS = (
    ("profile", "id"),
    ("profile", "sha256"),
    ("input", "request_sha256"),
    ("input", "case_input_sha256"),
    ("provider", "name"),
    ("provider", "model"),
    ("provider", "artifact_or_build_identity"),
    ("provider", "generation_parameters"),
)
