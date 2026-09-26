#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from case_application import canonical_case_input_json
from case_contract_validation import CONTRACT_VERSION
from case_http import prepare_case_request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = (
    ROOT / "config" / "validation" / "case0003-issue94" / "admission-v1.json"
)

PROFILE_ID = "case0003-issue94-admission-v1"
RUNTIME_PROFILE_ID = "case-validation-reference-v2"
REFERENCE_BACKEND_ID = "quadro-m620-gemma-e2b-llamacpp"
REFERENCE_MODEL = "gemma-4-E2B-it-Q4_K_M"
REFERENCE_MODEL_SHA256 = (
    "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8"
)
EXPECTED_GENERATION = {
    "temperature": 0,
    "thinking": False,
    "context_tokens": 16384,
    "max_output_tokens": 9000,
    "provider_timeout_seconds": 7200,
    "top_p": 1,
    "top_k": 0,
    "stream": False,
    "n": 1,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object without accepting scalar/list roots."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project_path(project_root: Path, relative: str) -> Path:
    """Resolve a repository-relative path without permitting root escape."""
    root = project_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"profile path escapes project root: {relative}") from exc
    return candidate


def _display_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _file_evidence(path: Path, project_root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": _display_path(path, project_root),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _runtime_generation(runtime: dict[str, Any]) -> dict[str, Any]:
    primary = runtime.get("models", {}).get("primary", {})
    options = runtime.get("request_options", {})
    return {
        "temperature": 0,
        "thinking": options.get("chat_template_kwargs", {}).get("enable_thinking"),
        "context_tokens": primary.get("context_tokens"),
        "max_output_tokens": primary.get("max_output_tokens"),
        "provider_timeout_seconds": runtime.get("request_timeout_seconds"),
        "top_p": options.get("top_p"),
        "top_k": options.get("top_k"),
        "stream": options.get("stream"),
        "n": options.get("n"),
    }


def _expected_case_id(canonical_json: str) -> str:
    return "CASE-" + uuid.uuid5(
        uuid.NAMESPACE_URL,
        "col-taxdata:case-input:v3:" + canonical_json,
    ).hex


def verify_admission_profile(
    profile_path: Path = DEFAULT_PROFILE,
    *,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Verify CASE-0003 admission bytes/profile without network or model access."""
    project_root = project_root.resolve()
    profile_path = profile_path.resolve()
    errors: list[str] = []

    try:
        profile = load_json(profile_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"profile:{exc}"]}

    if profile.get("schema_version") != 1:
        errors.append("profile:schema_version")
    if profile.get("profile_id") != PROFILE_ID:
        errors.append("profile:profile_id")
    if "issue67" in str(profile.get("profile_id", "")).lower():
        errors.append("profile:issue67_identity_reuse")
    if profile.get("admission_issue_number") != 95:
        errors.append("profile:admission_issue_number")
    if profile.get("execution_issue_number") != 94:
        errors.append("profile:execution_issue_number")
    if profile.get("human_case_label") != "CASE-0003":
        errors.append("profile:human_case_label")
    if profile.get("case_contract_version") != CONTRACT_VERSION:
        errors.append("profile:case_contract_version")

    frozen = profile.get("frozen_input", {})
    problem_path = _project_path(
        project_root,
        frozen.get("problem_text_path", ""),
    )
    request_path = _project_path(
        project_root,
        frozen.get("raw_http_request_path", ""),
    )
    try:
        problem_bytes = problem_path.read_bytes()
        request_bytes = request_path.read_bytes()
    except OSError as exc:
        return {
            "valid": False,
            "errors": errors + [f"frozen_input:{exc}"],
        }

    if problem_bytes.endswith(b"\n"):
        errors.append("frozen_input:problem_text_trailing_newline")
    if len(problem_bytes) != frozen.get("problem_text_bytes"):
        errors.append("frozen_input:problem_text_bytes")
    if _sha256(problem_bytes) != frozen.get("problem_text_sha256"):
        errors.append("frozen_input:problem_text_sha256")
    try:
        problem_text = problem_bytes.decode(
            frozen.get("problem_text_encoding", "UTF-8")
        )
    except (LookupError, UnicodeDecodeError):
        problem_text = ""
        errors.append("frozen_input:problem_text_encoding")

    if frozen.get("client_reference_present") is not False:
        errors.append("frozen_input:client_reference_must_be_omitted")
    expected_request = json.dumps(
        {
            "as_of_date": frozen.get("as_of_date"),
            "problem_text": problem_text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if request_bytes.endswith(b"\n"):
        errors.append("frozen_input:request_trailing_newline")
    if request_bytes != expected_request:
        errors.append("frozen_input:request_exact_bytes")
    if len(request_bytes) != frozen.get("raw_http_request_bytes"):
        errors.append("frozen_input:request_bytes")
    if _sha256(request_bytes) != frozen.get("raw_http_request_sha256"):
        errors.append("frozen_input:request_sha256")

    prepared = None
    try:
        prepared = prepare_case_request(request_bytes)
    except Exception as exc:  # authoritative adapter supplies the exact reason below
        errors.append(f"frozen_input:prepare_case_request:{type(exc).__name__}")

    canonical_bytes = b""
    expected_case_id = None
    if prepared is not None:
        if set(prepared.case_input) != {
            "kind",
            "contract_version",
            "problem_text",
            "as_of_date",
        }:
            errors.append("frozen_input:case_input_field_set")
        if prepared.case_input.get("problem_text") != problem_text:
            errors.append("frozen_input:case_input_problem_text")
        if prepared.case_input.get("as_of_date") != frozen.get("as_of_date"):
            errors.append("frozen_input:case_input_as_of_date")
        if prepared.case_input.get("contract_version") != CONTRACT_VERSION:
            errors.append("frozen_input:case_input_contract_version")
        if prepared.raw_request_sha256 != frozen.get("raw_http_request_sha256"):
            errors.append("frozen_input:adapter_request_sha256")
        if prepared.case_input_sha256 != frozen.get("canonical_case_input_sha256"):
            errors.append("frozen_input:adapter_case_input_sha256")

        canonical_json = canonical_case_input_json(prepared.case_input)
        canonical_bytes = canonical_json.encode("utf-8")
        if len(canonical_bytes) != frozen.get("canonical_case_input_bytes"):
            errors.append("frozen_input:canonical_case_input_bytes")
        if _sha256(canonical_bytes) != frozen.get("canonical_case_input_sha256"):
            errors.append("frozen_input:canonical_case_input_sha256")
        expected_case_id = _expected_case_id(canonical_json)

    application = profile.get("application", {})
    expected_application = {
        "transport": "openai-compatible",
        "provider_neutral_boundary": True,
        "http_adapter": "tools/case_http.py",
        "http_method": "POST",
        "http_endpoint": "/v1/cases",
    }
    for name, expected in expected_application.items():
        if application.get(name) != expected:
            errors.append(f"application:{name}")

    runtime_path = _project_path(
        project_root,
        application.get("llm_platform_config", ""),
    )
    runtime_evidence: dict[str, Any]
    try:
        runtime = load_json(runtime_path)
        runtime_evidence = _file_evidence(runtime_path, project_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        runtime = {}
        runtime_evidence = {
            "path": _display_path(runtime_path, project_root),
            "sha256": None,
            "bytes": None,
        }
        errors.append(f"runtime:{exc}")

    runtime_evidence["profile_id"] = runtime.get("profile_id")
    runtime_evidence["version"] = runtime.get("version")
    if runtime.get("profile_id") != RUNTIME_PROFILE_ID:
        errors.append("runtime:profile_id")
    if runtime.get("version") != 2:
        errors.append("runtime:version")
    if runtime.get("adapter") != "openai-compatible":
        errors.append("runtime:adapter")
    if runtime.get("provider") != "local-llama-cpp":
        errors.append("runtime:provider")
    if _runtime_generation(runtime) != EXPECTED_GENERATION:
        errors.append("runtime:generation")
    primary = runtime.get("models", {}).get("primary", {})
    if primary.get("name") != REFERENCE_MODEL:
        errors.append("runtime:model")
    routing = runtime.get("routing", {})
    if routing.get("primary_attempts") != 1:
        errors.append("runtime:primary_attempts")
    if routing.get("review_on_invalid_output") is not False:
        errors.append("runtime:review_on_invalid_output")
    if routing.get("review_on_provider_error") is not False:
        errors.append("runtime:review_on_provider_error")
    if runtime.get("context", {}).get("silent_truncation") is not False:
        errors.append("runtime:silent_truncation")

    if profile.get("generation") != EXPECTED_GENERATION:
        errors.append("profile:generation")

    backend = profile.get("reference_backend", {})
    if backend.get("id") != REFERENCE_BACKEND_ID:
        errors.append("reference_backend:id")
    if backend.get("backend") != "llama.cpp":
        errors.append("reference_backend:backend")
    if backend.get("requested_model_name") != REFERENCE_MODEL:
        errors.append("reference_backend:model")
    if backend.get("artifact_sha256") != REFERENCE_MODEL_SHA256:
        errors.append("reference_backend:model_artifact_sha256")
    if backend.get("allow_model_substitution") is not False:
        errors.append("reference_backend:model_substitution")
    if backend.get("allow_generation_substitution") is not False:
        errors.append("reference_backend:generation_substitution")

    clean = profile.get("clean_provider_state", {})
    if clean != {
        "reset_before_controlled_run": True,
        "warm_session_reuse_allowed": False,
        "discard_probe_state": True,
    }:
        errors.append("clean_provider_state")

    admission = profile.get("admission_state", {})
    if admission != {
        "case0003_consumed": False,
        "frozen_case_provider_exposure_allowed": False,
        "frozen_case_persistence_allowed": False,
        "synthetic_smoke_only": True,
    }:
        errors.append("admission_state")

    future = profile.get("future_execution_state", {})
    if not all(
        future.get(name) is True
        for name in (
            "independent_database_required",
            "independent_case_root_required",
            "unconsumed_marker_required",
            "immutable_reference_baseline_required",
        )
    ):
        errors.append("future_execution_state")

    required_manifest_fields = profile.get("final_manifest", {}).get(
        "required_fields", []
    )
    if len(required_manifest_fields) != len(set(required_manifest_fields)):
        errors.append("final_manifest:duplicate_required_fields")
    for name in (
        "main_sha",
        "application_image",
        "runtime_profile",
        "admission_profile",
        "database_baseline_sha256",
        "raw_provenance_fingerprint",
        "frozen_input_verification",
        "synthetic_http_smoke",
        "rejected_output_capture_smoke",
        "provider_reset",
        "writable_store",
        "case0003_consumed",
        "unresolved_blockers",
    ):
        if name not in required_manifest_fields:
            errors.append(f"final_manifest:missing:{name}")

    validation_evidence = _file_evidence(profile_path, project_root)
    validation_evidence.update(
        {
            "profile_id": profile.get("profile_id"),
            "schema_version": profile.get("schema_version"),
        }
    )
    return {
        "valid": not errors,
        "errors": errors,
        "case0003_consumed": False,
        "problem_text": {
            "bytes": len(problem_bytes),
            "sha256": _sha256(problem_bytes),
        },
        "raw_http_request": {
            "bytes": len(request_bytes),
            "sha256": _sha256(request_bytes),
        },
        "canonical_case_input": {
            "bytes": len(canonical_bytes),
            "sha256": _sha256(canonical_bytes) if canonical_bytes else None,
        },
        "expected_case_id": expected_case_id,
        "admission_profile": validation_evidence,
        "runtime_profile": runtime_evidence,
        "reference_model_artifact_sha256": REFERENCE_MODEL_SHA256,
        "generation": EXPECTED_GENERATION,
    }


def build_admission_plan(
    profile_path: Path = DEFAULT_PROFILE,
    *,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Return the safe #95 plan; it can never authorize frozen-case execution."""
    verification = verify_admission_profile(
        profile_path,
        project_root=project_root,
    )
    return {
        "valid": verification["valid"],
        "errors": verification["errors"],
        "admission_issue_number": 95,
        "execution_issue_number": 94,
        "case0003_consumed": False,
        "frozen_case_provider_exposure_allowed": False,
        "frozen_case_persistence_allowed": False,
        "allowed_runtime_smoke_input": "synthetic_non_case0003_only",
        "admission_profile": verification.get("admission_profile"),
        "runtime_profile": verification.get("runtime_profile"),
        "frozen_input_verification": {
            "problem_text": verification.get("problem_text"),
            "raw_http_request": verification.get("raw_http_request"),
            "canonical_case_input": verification.get("canonical_case_input"),
            "expected_case_id": verification.get("expected_case_id"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify or plan CASE-0003/#94 environment admission without "
            "network/model access or persisted CASE mutation."
        )
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-profile")
    commands.add_parser("plan")
    args = parser.parse_args()

    if args.command == "verify-profile":
        result = verify_admission_profile(
            args.profile,
            project_root=args.project_root,
        )
    else:
        result = build_admission_plan(
            args.profile,
            project_root=args.project_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
