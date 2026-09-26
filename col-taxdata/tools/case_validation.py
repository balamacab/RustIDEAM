#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import case_benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "validation" / "issue67-reference.json"

REFERENCE_BACKEND_ID = "quadro-m620-gemma-e2b-llamacpp"
ISSUE67_PROFILE_ID = "issue67-controlled-validation-v2"
ISSUE67_PROFILE_SCHEMA_VERSION = 2
ISSUE67_AMENDMENT_ISSUE = 92
REFERENCE_LLM_PROFILE_ID = "case-validation-reference-v2"
REFERENCE_LLM_PROFILE_VERSION = 2

GENERATION_FIELDS = (
    "temperature",
    "thinking",
    "context_tokens",
    "max_output_tokens",
    "provider_timeout_seconds",
    "top_p",
    "top_k",
    "stream",
    "n",
)

ISSUE67_CANONICAL_GENERATION = {
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
HISTORICAL_ISSUE65_GENERATION = {
    "temperature": 0,
    "thinking": False,
    "context_tokens": 16384,
    "max_output_tokens": 6144,
    "provider_timeout_seconds": 900,
    "top_p": 1,
    "top_k": 0,
    "stream": False,
    "n": 1,
}


def _sha256(path: Path) -> str:
    """Return SHA-256 over the exact selected file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON-compatible project profile as an object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, relative: str) -> Path:
    """Resolve a repository-relative path without inferring root from profile depth."""
    root = project_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"profile path escapes project root: {relative}") from exc
    return candidate


def _display_path(path: Path, project_root: Path) -> str:
    """Prefer a stable project-relative evidence path when the file is in-project."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _generation(value: dict[str, Any]) -> dict[str, Any]:
    return {name: value[name] for name in GENERATION_FIELDS}


def _profile_generation(profile: dict[str, Any]) -> dict[str, Any]:
    return _generation(profile["generation"])


def _backend_map(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {profile["reference_backend"]["id"]: profile["reference_backend"]}
    for backend in profile["experimental_backends"]:
        if backend["id"] in result:
            raise ValueError(f"duplicate backend id: {backend['id']}")
        result[backend["id"]] = backend
    return result


def _runtime_profile_evidence(
    profile: dict[str, Any],
    project_root: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    runtime_path = _project_path(
        project_root,
        profile["application"]["llm_platform_config"],
    )
    runtime = load_json(runtime_path)
    evidence = {
        "profile_id": runtime.get("profile_id"),
        "version": runtime.get("version"),
        "path": _display_path(runtime_path, project_root),
        "sha256": _sha256(runtime_path),
    }
    return runtime, runtime_path, evidence


def _validate_envelope_history(
    profile: dict[str, Any],
    errors: list[str],
) -> None:
    """Require the historical/current distinction to be machine-readable and exact."""
    history = profile.get("envelope_history")
    if not isinstance(history, dict):
        errors.append("envelope_history:missing")
        return

    historical = history.get("historical_issue65")
    if not isinstance(historical, dict):
        errors.append("envelope_history:historical_issue65")
    else:
        if historical.get("role") != "historical_benchmark":
            errors.append("envelope_history:historical_role")
        if historical.get("source_issue_number") != 65:
            errors.append("envelope_history:historical_issue")
        if historical.get("generation") != HISTORICAL_ISSUE65_GENERATION:
            errors.append("envelope_history:historical_generation")

    current = history.get("current_issue67")
    if not isinstance(current, dict):
        errors.append("envelope_history:current_issue67")
    else:
        if current.get("role") != "canonical_validation":
            errors.append("envelope_history:current_role")
        if current.get("source_issue_number") != 67:
            errors.append("envelope_history:current_issue")
        if current.get("amendment_issue_number") != ISSUE67_AMENDMENT_ISSUE:
            errors.append("envelope_history:amendment_issue")
        if current.get("generation") != ISSUE67_CANONICAL_GENERATION:
            errors.append("envelope_history:current_generation")

    reason = history.get("amendment_reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("envelope_history:amendment_reason")


def _validate_llm_profile(
    profile: dict[str, Any],
    project_root: Path,
    errors: list[str],
) -> dict[str, Any]:
    runtime, _runtime_path, evidence = _runtime_profile_evidence(
        profile,
        project_root,
    )
    primary = runtime.get("models", {}).get("primary", {})
    routing = runtime.get("routing", {})
    request_options = runtime.get("request_options", {})

    expected = profile["reference_backend"]
    if runtime.get("version") != REFERENCE_LLM_PROFILE_VERSION:
        errors.append("llm_profile:version")
    if runtime.get("profile_id") != REFERENCE_LLM_PROFILE_ID:
        errors.append("llm_profile:profile_id")
    if runtime.get("adapter") != "openai-compatible":
        errors.append("llm_profile:adapter")
    if runtime.get("provider") != "local-llama-cpp":
        errors.append("llm_profile:provider")
    if (
        runtime.get("request_timeout_seconds")
        != ISSUE67_CANONICAL_GENERATION["provider_timeout_seconds"]
    ):
        errors.append("llm_profile:timeout")
    if primary.get("name") != expected["requested_model_name"]:
        errors.append("llm_profile:primary_model")
    if primary.get("routing_role") != "primary":
        errors.append("llm_profile:primary_role")
    if primary.get("context_tokens") != ISSUE67_CANONICAL_GENERATION["context_tokens"]:
        errors.append("llm_profile:context_tokens")
    if (
        primary.get("max_output_tokens")
        != ISSUE67_CANONICAL_GENERATION["max_output_tokens"]
    ):
        errors.append("llm_profile:max_output_tokens")
    if routing.get("primary_attempts") != 1:
        errors.append("llm_profile:primary_attempts")
    if routing.get("review_on_invalid_output") or routing.get("review_on_provider_error"):
        errors.append("llm_profile:review_fallback_forbidden")
    if request_options.get("top_p") != ISSUE67_CANONICAL_GENERATION["top_p"]:
        errors.append("llm_profile:top_p")
    if request_options.get("top_k") != ISSUE67_CANONICAL_GENERATION["top_k"]:
        errors.append("llm_profile:top_k")
    if request_options.get("stream") is not False:
        errors.append("llm_profile:stream")
    if request_options.get("n") != ISSUE67_CANONICAL_GENERATION["n"]:
        errors.append("llm_profile:n")
    thinking = request_options.get("chat_template_kwargs", {}).get("enable_thinking")
    if thinking is not False:
        errors.append("llm_profile:thinking")
    if runtime.get("context", {}).get("silent_truncation") is not False:
        errors.append("llm_profile:silent_truncation")
    return evidence


def verify_profile(
    profile_path: Path = DEFAULT_PROFILE,
    *,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Verify the current #67 contract without network or runtime mutation."""
    profile_path = profile_path.resolve()
    project_root = project_root.resolve()
    profile = load_json(profile_path)
    errors: list[str] = []

    if profile.get("schema_version") != ISSUE67_PROFILE_SCHEMA_VERSION:
        errors.append("profile:schema_version")
    if profile.get("profile_id") != ISSUE67_PROFILE_ID:
        errors.append("profile:profile_id")
    if (
        profile.get("issue_number") != 67
        or profile.get("driver_issue_number") != 75
        or profile.get("amendment_issue_number") != ISSUE67_AMENDMENT_ISSUE
    ):
        errors.append("profile:issue_binding")

    historical = profile["historical_benchmark"]
    if historical.get("preserve_immutable") is not True:
        errors.append("historical_benchmark:must_preserve")
    historical_path = _project_path(project_root, historical["config_path"])
    historical_result = case_benchmark.verify_package(historical_path)
    historical_config = load_json(historical_path)
    historical_generation = _generation(historical_config["generation"])
    if historical_generation != HISTORICAL_ISSUE65_GENERATION:
        errors.append("historical_benchmark:generation_envelope")
    if not historical_result["valid"]:
        errors.extend(
            f"historical_benchmark:{item}" for item in historical_result["errors"]
        )

    expected_fingerprints = {
        "problem_text_sha256": historical_result["problem_text_sha256"],
        "canonical_case_input_sha256": historical_result["canonical_case_input_sha256"],
        "raw_http_request_sha256": historical_result["request_sha256"],
        "expected_case_id": historical_result["expected_case_id"],
    }
    for name, observed in expected_fingerprints.items():
        if historical.get(name) != observed:
            errors.append(f"historical_benchmark:{name}")

    if profile.get("generation") != ISSUE67_CANONICAL_GENERATION:
        errors.append("generation:strict_envelope")

    _validate_envelope_history(profile, errors)

    application = profile["application"]
    if application.get("transport") != "openai-compatible":
        errors.append("application:transport")
    if application.get("provider_neutral_boundary") is not True:
        errors.append("application:provider_neutral_boundary")
    if (
        application.get("http_adapter") != "tools/case_http.py"
        or application.get("http_method") != "POST"
        or application.get("http_endpoint") != "/v1/cases"
    ):
        errors.append("application:http_entry_point")

    reference = profile["reference_backend"]
    if reference.get("id") != REFERENCE_BACKEND_ID:
        errors.append("reference_backend:id")
    if reference.get("requirement") != "required":
        errors.append("reference_backend:requirement")
    if reference.get("hardware") != "NVIDIA Quadro M620":
        errors.append("reference_backend:hardware")
    if reference.get("backend") != "llama.cpp":
        errors.append("reference_backend:backend")
    if reference.get("logical_model") != "Gemma E2B":
        errors.append("reference_backend:logical_model")
    if reference.get("requested_model_name") != "gemma-4-E2B-it-Q4_K_M":
        errors.append("reference_backend:model")
    if reference.get("allow_model_substitution") is not False:
        errors.append("reference_backend:model_substitution")
    if reference.get("allow_generation_substitution") is not False:
        errors.append("reference_backend:generation_substitution")

    experimental = profile["experimental_backends"]
    if len(experimental) != 2:
        errors.append("experimental_backends:count")
    for backend in experimental:
        if backend.get("requirement") != "optional_experimental":
            errors.append(f"experimental_backends:{backend.get('id')}:requirement")
        if backend.get("backend") != "FastFlowLM":
            errors.append(f"experimental_backends:{backend.get('id')}:backend")
        if backend.get("allow_model_substitution") is not False:
            errors.append(f"experimental_backends:{backend.get('id')}:model_substitution")
        if backend.get("allow_generation_substitution") is not False:
            errors.append(
                f"experimental_backends:{backend.get('id')}:generation_substitution"
            )

    clean = profile["clean_provider_state"]
    if clean.get("reset_before_controlled_run") is not True:
        errors.append("clean_provider_state:reset")
    if clean.get("warm_session_reuse_allowed") is not False:
        errors.append("clean_provider_state:warm_reuse")
    if clean.get("discard_probe_state") is not True:
        errors.append("clean_provider_state:probe_state")

    phase_a = profile["validation_plan"]["phase_a"]
    required = phase_a.get("required_runs", [])
    if required != [
        {
            "backend_id": REFERENCE_BACKEND_ID,
            "count": 1,
            "kind": "controlled_e2e",
        }
    ]:
        errors.append("validation_plan:phase_a_required_run")
    optional_ids = {item["id"] for item in experimental}
    diagnostic_ids = {
        item.get("backend_id")
        for item in phase_a.get("supplemental_diagnostics", [])
        if item.get("optional") is True
    }
    if diagnostic_ids != optional_ids:
        errors.append("validation_plan:supplemental_diagnostics")

    phase_b = profile["validation_plan"]["phase_b"]
    if phase_b.get("requires_frozen_phase_a") is not True:
        errors.append("validation_plan:phase_b_freeze")
    if phase_b.get("requires_experimental_backend") is not False:
        errors.append("validation_plan:phase_b_experimental_gate")

    try:
        _backend_map(profile)
    except ValueError as exc:
        errors.append(f"profile:{exc}")

    runtime_evidence = _validate_llm_profile(profile, project_root, errors)
    validation_evidence = {
        "profile_id": profile.get("profile_id"),
        "schema_version": profile.get("schema_version"),
        "path": _display_path(profile_path, project_root),
        "sha256": _sha256(profile_path),
    }

    return {
        "profile_id": profile.get("profile_id"),
        "profile_sha256": validation_evidence["sha256"],
        "llm_profile_id": runtime_evidence["profile_id"],
        "llm_profile_sha256": runtime_evidence["sha256"],
        "validation_profile": validation_evidence,
        "runtime_profile": runtime_evidence,
        "valid": not errors,
        "errors": errors,
        "historical_benchmark_valid": historical_result["valid"],
        "historical_planned_runs": historical_result["planned_runs"],
        "historical_generation": historical_generation,
        "current_generation": _profile_generation(profile),
        "envelopes": deepcopy(profile["envelope_history"]),
        "problem_text_sha256": historical_result["problem_text_sha256"],
        "canonical_case_input_sha256": historical_result[
            "canonical_case_input_sha256"
        ],
        "request_sha256": historical_result["request_sha256"],
        "expected_case_id": historical_result["expected_case_id"],
    }


def build_validation_plan(
    profile: dict[str, Any],
    profile_path: Path = DEFAULT_PROFILE,
    *,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Build the #67 plan with exact selected profile identity and lineage."""
    profile_path = profile_path.resolve()
    project_root = project_root.resolve()
    generation = _profile_generation(profile)
    reference = profile["reference_backend"]
    application = profile["application"]
    _runtime, _runtime_path, runtime_evidence = _runtime_profile_evidence(
        profile,
        project_root,
    )
    validation_evidence = {
        "profile_id": profile["profile_id"],
        "schema_version": profile["schema_version"],
        "path": _display_path(profile_path, project_root),
        "sha256": _sha256(profile_path),
    }

    required_phase_a = [
        {
            "run_id": "issue67-phase-a-reference",
            "phase": "A",
            "kind": "controlled_e2e",
            "required": True,
            "backend_id": reference["id"],
            "generation": deepcopy(generation),
            "runtime_profile": deepcopy(runtime_evidence),
            "http": {
                "method": application["http_method"],
                "endpoint": application["http_endpoint"],
                "adapter": application["http_adapter"],
            },
        }
    ]
    supplemental = [
        {
            "run_id": f"issue67-diagnostic-{backend['id']}",
            "phase": "diagnostic",
            "kind": "supplemental_backend_diagnostic",
            "required": False,
            "backend_id": backend["id"],
            "generation": deepcopy(generation),
        }
        for backend in profile["experimental_backends"]
    ]
    return {
        "profile_id": profile["profile_id"],
        "profile_sha256": validation_evidence["sha256"],
        "validation_profile": validation_evidence,
        "runtime_profile": runtime_evidence,
        # Compatibility alias retained for callers that previously consumed this key.
        "llm_profile": deepcopy(runtime_evidence),
        "envelopes": deepcopy(profile["envelope_history"]),
        "required_phase_a": required_phase_a,
        "supplemental_diagnostics": supplemental,
        "phase_b": deepcopy(profile["validation_plan"]["phase_b"]),
        "post_freeze_comparison": deepcopy(
            profile["validation_plan"]["post_freeze_comparison"]
        ),
    }


def _capability_status(
    backend: dict[str, Any],
    record: dict[str, Any] | None,
    generation: dict[str, Any],
) -> dict[str, Any]:
    required = backend["requirement"] == "required"
    result = {
        "backend_id": backend["id"],
        "requirement": backend["requirement"],
        "blocking": required,
        "ready": False,
        "status": "unavailable",
        "failures": [],
    }
    if not record or record.get("available") is not True:
        return result

    failures: list[str] = []
    if record.get("capability_pass") is not True:
        failures.append("capability_probe_failed")
    if record.get("served_model") != backend["requested_model_name"]:
        failures.append("model_identity_mismatch")
    if record.get("generation") != generation:
        failures.append("generation_envelope_mismatch")
    artifact_sha = backend.get("artifact_sha256")
    if artifact_sha and record.get("model_artifact_sha256") != artifact_sha:
        failures.append("model_artifact_sha256_mismatch")

    result["failures"] = failures
    if failures:
        result["status"] = "ineligible"
        return result
    result["ready"] = True
    result["status"] = "ready"
    return result


def evaluate_readiness(
    capability_report: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate core readiness while reporting optional diagnostics separately."""
    records = capability_report.get("backends", {})
    if not isinstance(records, dict):
        raise ValueError("capability report backends must be an object")

    generation = _profile_generation(profile)
    reference = _capability_status(
        profile["reference_backend"],
        records.get(profile["reference_backend"]["id"]),
        generation,
    )
    experimental = [
        _capability_status(backend, records.get(backend["id"]), generation)
        for backend in profile["experimental_backends"]
    ]
    return {
        "profile_id": profile["profile_id"],
        "core_ready": reference["ready"],
        "reference_backend": reference,
        "experimental_backends": experimental,
        "experimental_backends_gate_core": False,
    }


def phase_b_ready(*, phase_a_passed: bool, phase_a_frozen: bool) -> bool:
    """Phase B depends on frozen required Phase A, never experimental capacity."""
    return phase_a_passed and phase_a_frozen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and plan the current #67 reference validation without model calls."
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project root used to resolve repository-relative paths in the profile.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-profile")
    commands.add_parser("plan")
    readiness = commands.add_parser("readiness")
    readiness.add_argument("--capabilities", type=Path, required=True)
    args = parser.parse_args()

    verification = verify_profile(args.profile, project_root=args.project_root)
    if not verification["valid"]:
        print(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    profile = load_json(args.profile)
    if args.command == "verify-profile":
        result = verification
    elif args.command == "plan":
        result = build_validation_plan(
            profile,
            args.profile,
            project_root=args.project_root,
        )
    else:
        result = evaluate_readiness(load_json(args.capabilities), profile)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
