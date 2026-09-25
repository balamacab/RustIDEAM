#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from case_benchmark_scoring import score_run as _score_run, score_suite as _score_suite


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "config" / "benchmarks" / "issue65" / "benchmark.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_generation(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the generation parameters that a measured run must record exactly."""
    fields = (
        "temperature", "thinking", "context_tokens", "max_output_tokens",
        "provider_timeout_seconds", "top_p", "top_k", "stream", "n",
    )
    return {name: spec["generation"][name] for name in fields}


def build_run_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the fixed 3x3 matrix without touching runtime state."""
    isolation = spec["isolation"]
    runs: list[dict[str, Any]] = []
    for backend in spec["model_matrix"]:
        for index in range(1, spec["run_plan"]["repetitions_per_configuration"] + 1):
            values = {"backend_id": backend["id"], "run_index": index}
            runs.append({
                "run_id": f"{backend['id']}-run-{index}",
                "backend_id": backend["id"],
                "run_index": index,
                "runtime_dir": isolation["runtime_layout_template"].format(**values),
                "database": isolation["writable_database_template"].format(**values),
                "case_store": isolation["case_store_template"].format(**values),
                "generation": expected_generation(spec),
            })
    return runs



def score_run(record: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Score one run using the generation policy frozen in the spec."""
    return _score_run(record, spec, expected_generation(spec))


def score_suite(suite: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Score the fixed nine-run suite and E2B concordance."""
    return _score_suite(suite, spec, build_run_plan(spec), expected_generation(spec))

def verify_package(spec_path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    """Verify frozen bytes, CASE identity, matrix and execution invariants."""
    spec = load_json(spec_path)
    errors: list[str] = []
    case = spec["case"]
    project_root = spec_path.resolve().parents[3]

    problem = (project_root / case["problem_text_path"]).read_bytes()
    if len(problem) != case["problem_text_bytes"]:
        errors.append("problem_text_byte_count_mismatch")
    if problem.count(b"\n") != case["problem_text_lf_count"]:
        errors.append("problem_text_lf_count_mismatch")
    if sha256(problem) != case["problem_text_sha256"]:
        errors.append("problem_text_sha256_mismatch")
    try:
        problem_text = problem.decode(case["problem_text_encoding"])
    except UnicodeDecodeError:
        problem_text = ""
        errors.append("problem_text_not_valid_utf8")

    case_input = {
        "kind": "case_input",
        "contract_version": spec["application_contract"]["contract_version"],
        "problem_text": problem_text,
        "as_of_date": case["as_of_date"],
    }
    canonical = compact_json(case_input).encode()
    frozen = case["canonical_case_input"]
    if len(canonical) != frozen["bytes"]:
        errors.append("canonical_case_input_byte_count_mismatch")
    if sha256(canonical) != frozen["sha256"]:
        errors.append("canonical_case_input_sha256_mismatch")
    case_id = "CASE-" + uuid.uuid5(
        uuid.NAMESPACE_URL,
        "col-taxdata:case-input:v3:" + canonical.decode(),
    ).hex
    if case_id != frozen["expected_case_id"]:
        errors.append("expected_case_id_mismatch")

    request_spec = case["http_request"]
    request = (project_root / request_spec["path"]).read_bytes()
    if request.endswith(b"\n"):
        errors.append("http_request_has_forbidden_trailing_newline")
    if len(request) != request_spec["bytes"]:
        errors.append("http_request_byte_count_mismatch")
    if sha256(request) != request_spec["sha256"]:
        errors.append("http_request_sha256_mismatch")
    try:
        parsed = json.loads(request)
    except json.JSONDecodeError:
        parsed = None
        errors.append("http_request_invalid_json")
    if parsed != {"as_of_date": case["as_of_date"], "problem_text": problem_text}:
        errors.append("http_request_semantics_mismatch")

    transport = spec["application_contract"].get("http_transport", {})
    if transport.get("adapter") != "tools/case_http.py":
        errors.append("http_transport:adapter")
    if transport.get("method") != "POST" or transport.get("endpoint") != "/v1/cases":
        errors.append("http_transport:route")
    if transport.get("required_success_fingerprints") != [
        "raw_request_sha256", "case_input_sha256"
    ]:
        errors.append("http_transport:fingerprints")

    failure_codes = spec["application_contract"].get("failure_codes", {})
    expected_failure_codes = {
        "provider_timeout": "CASE_PROVIDER_TIMEOUT",
        "output_ceiling": "CASE_OUTPUT_LIMIT",
        "context_budget_rejection": "CASE_CONTEXT_LIMIT",
        "malformed_or_contract_failure": "INVALID_CASE_DRAFT",
    }
    if failure_codes != expected_failure_codes:
        errors.append("http_transport:failure_codes")

    generation = spec["generation"]
    fixed = {
        "temperature": 0, "thinking": False, "context_tokens": 16384,
        "max_output_tokens": 6144, "top_p": 1.0, "top_k": 0,
        "stream": False, "n": 1,
    }
    for name, value in fixed.items():
        if generation.get(name) != value:
            errors.append(f"generation:{name}")
    if generation["provider_timeout_seconds"] < 600:
        errors.append("generation:provider_timeout_seconds")
    if generation["additional_request_generation_parameters_allowed"]:
        errors.append("generation:additional_parameters_not_frozen")
    if not generation["capability_probe_required"] or generation["capability_probe_is_measured_run"]:
        errors.append("generation:capability_probe_contract")

    backend_ids = [item["id"] for item in spec["model_matrix"]]
    if len(backend_ids) != 3 or len(set(backend_ids)) != 3:
        errors.append("model_matrix")
    plan = build_run_plan(spec)
    if len(plan) != 9:
        errors.append("run_plan")
    if len({item["database"] for item in plan}) != 9:
        errors.append("database_isolation")
    if len({item["case_store"] for item in plan}) != 9:
        errors.append("case_store_isolation")
    if spec["complex_benchmark_execution_authorized"]:
        errors.append("issue65_must_not_authorize_execution")

    return {
        "benchmark_id": spec["benchmark_id"],
        "valid": not errors,
        "errors": errors,
        "problem_text_sha256": sha256(problem),
        "canonical_case_input_sha256": sha256(canonical),
        "request_sha256": sha256(request),
        "expected_case_id": case_id,
        "planned_runs": len(plan),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify/score issue #65 benchmark records without model/network calls."
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-package")
    commands.add_parser("plan")
    run_parser = commands.add_parser("score-run")
    run_parser.add_argument("--record", type=Path, required=True)
    suite_parser = commands.add_parser("score-suite")
    suite_parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()

    verification = verify_package(args.spec)
    if not verification["valid"]:
        print(json.dumps(verification, ensure_ascii=False, indent=2))
        return 2
    spec = load_json(args.spec)
    if args.command == "verify-package":
        result, code = verification, 0
    elif args.command == "plan":
        result, code = {"benchmark_id": spec["benchmark_id"], "runs": build_run_plan(spec)}, 0
    elif args.command == "score-run":
        result = score_run(load_json(args.record), spec)
        code = 0 if result["pass"] else 1
    else:
        result = score_suite(load_json(args.record), spec)
        code = 0 if result["pass"] else 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
