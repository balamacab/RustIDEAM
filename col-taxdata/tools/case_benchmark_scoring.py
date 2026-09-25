from __future__ import annotations

from typing import Any


def assessment_failures(
    assessment: Any,
    *,
    version: str,
    required_ids: list[str],
    prefix: str,
) -> list[str]:
    """Require a PASS plus auditable evidence for every frozen semantic item."""
    failures: list[str] = []
    if not isinstance(assessment, dict):
        return [f"{prefix}:must_be_object"]
    if assessment.get("version") != version:
        failures.append(f"{prefix}:version")
    items = assessment.get("items")
    if not isinstance(items, dict):
        return failures + [f"{prefix}.items:must_be_object"]
    for item_id in required_ids:
        item = items.get(item_id)
        if not isinstance(item, dict):
            failures.append(f"{prefix}:{item_id}:missing")
            continue
        if item.get("status") != "pass":
            failures.append(f"{prefix}:{item_id}:not_pass")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(value, str) and value.strip() for value in evidence
        ):
            failures.append(f"{prefix}:{item_id}:evidence_required")
    return failures


def score_run(
    record: dict[str, Any],
    spec: dict[str, Any],
    expected_generation: dict[str, Any],
) -> dict[str, Any]:
    """Score one frozen measurement record; never repair model output."""
    failures: list[str] = []
    case = spec["case"]
    expected_fingerprints = {
        "problem_text_sha256": case["problem_text_sha256"],
        "raw_request_sha256": case["http_request"]["sha256"],
        "canonical_case_input_sha256": case["canonical_case_input"]["sha256"],
        "case_id": case["canonical_case_input"]["expected_case_id"],
    }
    fingerprints = record.get("fingerprints", {})
    for name, expected in expected_fingerprints.items():
        if fingerprints.get(name) != expected:
            failures.append(f"fingerprint:{name}")

    backend_ids = {item["id"] for item in spec["model_matrix"]}
    backend_id = record.get("backend_id")
    run_index = record.get("run_index")
    if backend_id not in backend_ids:
        failures.append("backend_id")
    if not isinstance(run_index, int) or run_index not in (1, 2, 3):
        failures.append("run_index")

    app = record.get("application", {})
    contract = spec["application_contract"]
    for name in ("contract_version", "prompt_template_id", "prompt_template_version"):
        if app.get(name) != contract[name]:
            failures.append(f"application:{name}")
    if record.get("generation") != expected_generation:
        failures.append("generation:does_not_match_frozen_policy")

    baseline = record.get("baseline", {})
    for name in spec["isolation"]["baseline_fields_required"]:
        if not isinstance(baseline.get(name), str) or not baseline[name].strip():
            failures.append(f"baseline:{name}")

    identity = record.get("runtime_identity", {})
    for name in ("served_model", "model_artifact_identity", "backend_build_identity"):
        if not isinstance(identity.get(name), str) or not identity[name].strip():
            failures.append(f"runtime_identity:{name}")
    if identity.get("clean_state_policy_id") != spec["clean_model_state"]["policy_id"]:
        failures.append("runtime_identity:clean_state_policy_id")
    if identity.get("clean_state_established") is not True:
        failures.append("runtime_identity:clean_state_not_established")

    runtime = record.get("runtime", {})
    max_output = spec["generation"]["max_output_tokens"]
    if runtime.get("max_output_tokens") != max_output:
        failures.append("runtime:max_output_tokens")
    completion = runtime.get("completion_tokens")
    if not isinstance(completion, int) or isinstance(completion, bool) or completion < 0:
        failures.append("runtime:completion_tokens")
    elif completion >= max_output:
        failures.append("runtime:output_ceiling")
    if not isinstance(runtime.get("prompt_tokens"), int):
        failures.append("runtime:prompt_tokens")
    for name in ("total_seconds", "model_load_seconds"):
        value = runtime.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            failures.append(f"runtime:{name}")
    if not isinstance(runtime.get("finish_reason"), str) or not runtime["finish_reason"]:
        failures.append("runtime:finish_reason")
    for name in (
        "malformed_or_incomplete_structured_output", "case_draft_contract_failure",
        "timeout", "backend_crash", "context_budget_rejection", "truncated",
    ):
        if runtime.get(name) is not False:
            failures.append(f"runtime:{name}")

    gates = record.get("gates", {})
    for gate_id in spec["mandatory_run_gates"]:
        if gates.get(gate_id) is not True:
            failures.append(f"gate:{gate_id}")

    rubric = spec["semantic_rubric"]
    failures.extend(assessment_failures(
        record.get("semantic_assessment"),
        version=rubric["rubric_version"],
        required_ids=list(rubric["rules"]),
        prefix="semantic_assessment",
    ))
    run_id = (
        f"{backend_id}-run-{run_index}"
        if backend_id in backend_ids and isinstance(run_index, int)
        else None
    )
    return {"run_id": run_id, "pass": not failures, "failures": failures}


def score_suite(
    suite: dict[str, Any],
    spec: dict[str, Any],
    run_plan: list[dict[str, Any]],
    expected_generation: dict[str, Any],
) -> dict[str, Any]:
    """Score all nine runs plus the E2B cross-platform semantic assessment."""
    failures: list[str] = []
    runs = suite.get("runs")
    if not isinstance(runs, list):
        return {"pass": False, "failures": ["runs:must_be_array"], "run_results": []}

    expected = {(r["backend_id"], r["run_index"]) for r in run_plan}
    actual = {
        (r.get("backend_id"), r.get("run_index"))
        for r in runs if isinstance(r, dict)
    }
    if len(runs) != 9 or actual != expected:
        failures.append("suite:run_matrix")
    results = [
        score_run(r, spec, expected_generation)
        for r in runs if isinstance(r, dict)
    ]
    for result in results:
        if not result["pass"]:
            failures.append(f"run:{result['run_id']}:failed")

    baselines = {
        (
            r.get("baseline", {}).get("main_sha"),
            r.get("baseline", {}).get("database_sha256"),
            r.get("baseline", {}).get("raw_evidence_manifest_sha256"),
        )
        for r in runs if isinstance(r, dict)
    }
    if len(baselines) != 1 or (None, None, None) in baselines:
        failures.append("suite:frozen_baseline_mismatch")

    concordance = suite.get("e2b_concordance")
    if not isinstance(concordance, dict):
        failures.append("e2b_concordance:must_be_object")
    else:
        if concordance.get("backend_pair") != spec["cross_platform_same_model_pair"]:
            failures.append("e2b_concordance:backend_pair")
        contract = spec["e2b_concordance"]
        failures.extend(assessment_failures(
            concordance,
            version=contract["assessment_version"],
            required_ids=list(contract["dimensions"]),
            prefix="e2b_concordance",
        ))
    return {"pass": not failures, "failures": failures, "run_results": results}
