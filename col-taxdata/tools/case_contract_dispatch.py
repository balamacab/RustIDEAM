from __future__ import annotations

from typing import Any

from case_contract_validation import (
    CaseContractError,
    validate_case_draft as validate_v3_case_draft,
    validate_case_input as validate_v3_case_input,
    validate_case_result as validate_v3_case_result,
)
from case_contract_validation_v4 import (
    validate_case_input as validate_v4_case_input,
    validate_intake_draft as validate_v4_intake_draft,
    validate_legal_research_bundle as validate_v4_legal_research_bundle,
)
from case_contract_validation_v5 import (
    validate_case_input as validate_v5_case_input,
    validate_intake_draft as validate_v5_intake_draft,
    validate_legal_research_bundle as validate_v5_legal_research_bundle,
)


V3_CONTRACT_VERSION = "3.0.0"
V4_CONTRACT_VERSION = "4.0.0"
V5_CONTRACT_VERSION = "5.0.0"
SUPPORTED_CONTRACT_VERSIONS = frozenset(
    {V3_CONTRACT_VERSION, V4_CONTRACT_VERSION, V5_CONTRACT_VERSION}
)

UNSUPPORTED_CASE_CONTRACT_VERSION = "UNSUPPORTED_CASE_CONTRACT_VERSION"
CASE_CONTRACT_VERSION_MISMATCH = "CASE_CONTRACT_VERSION_MISMATCH"
INVALID_CASE_CONTRACT_KIND = "INVALID_CASE_CONTRACT_KIND"


def _fail(code: str, path: str, detail: str) -> None:
    raise CaseContractError(code, f"{path}: {detail}")


def _version(value: dict[str, Any], *, path: str = "$") -> str:
    if not isinstance(value, dict):
        _fail(
            UNSUPPORTED_CASE_CONTRACT_VERSION,
            path,
            "contract object must be a JSON object",
        )
    version = value.get("contract_version")
    if not isinstance(version, str) or version not in SUPPORTED_CONTRACT_VERSIONS:
        _fail(
            UNSUPPORTED_CASE_CONTRACT_VERSION,
            f"{path}.contract_version",
            f"unsupported CASE contract version {version!r}",
        )
    return version


def validate_case_input(case_input: dict[str, Any]) -> str:
    """Dispatch CaseInput validation by its explicit major contract version."""
    version = _version(case_input)
    if case_input.get("kind") != "case_input":
        _fail(
            INVALID_CASE_CONTRACT_KIND,
            "$.kind",
            f"expected 'case_input', got {case_input.get('kind')!r}",
        )
    if version == V3_CONTRACT_VERSION:
        validate_v3_case_input(case_input)
    elif version == V4_CONTRACT_VERSION:
        validate_v4_case_input(case_input)
    else:
        validate_v5_case_input(case_input)
    return version


def validate_structured_intake(
    case_input: dict[str, Any],
    structured_intake: dict[str, Any],
) -> str:
    """Validate model-owned intake under the caller's explicit CASE version.

    v3 remains CaseDraft. v4/v5 are IntakeDraft. A version or kind mismatch is
    never repaired or relabeled across this compatibility boundary.
    """
    version = validate_case_input(case_input)
    structured_version = _version(structured_intake)
    if structured_version != version:
        _fail(
            CASE_CONTRACT_VERSION_MISMATCH,
            "$.contract_version",
            (
                f"CaseInput uses {version!r} but structured intake uses "
                f"{structured_version!r}"
            ),
        )

    expected_kind = (
        "case_draft" if version == V3_CONTRACT_VERSION else "intake_draft"
    )
    if structured_intake.get("kind") != expected_kind:
        _fail(
            INVALID_CASE_CONTRACT_KIND,
            "$.kind",
            (
                f"{version} model-owned object must be {expected_kind!r}; "
                f"got {structured_intake.get('kind')!r}"
            ),
        )

    if version == V3_CONTRACT_VERSION:
        validate_v3_case_draft(case_input, structured_intake)
    elif version == V4_CONTRACT_VERSION:
        validate_v4_intake_draft(case_input, structured_intake)
    else:
        validate_v5_intake_draft(case_input, structured_intake)
    return version


def validate_analysis_result(result: dict[str, Any]) -> str:
    """Validate a frozen v3 result or versioned v4/v5 research bundle.

    Dispatch is intentionally version-driven rather than shape-driven. A stored
    historical object remains governed by the semantics it declares, and a
    breaking v5 graph cannot acquire v4 meaning by relabeling its version.
    """
    version = _version(result)
    expected_kind = (
        "case_result" if version == V3_CONTRACT_VERSION else "legal_research_bundle"
    )
    if result.get("kind") != expected_kind:
        _fail(
            INVALID_CASE_CONTRACT_KIND,
            "$.kind",
            (
                f"{version} analysis result must be {expected_kind!r}; "
                f"got {result.get('kind')!r}"
            ),
        )

    if version == V3_CONTRACT_VERSION:
        validate_v3_case_result(result)
    elif version == V4_CONTRACT_VERSION:
        validate_v4_legal_research_bundle(result)
    else:
        validate_v5_legal_research_bundle(result)
    return version
