from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from case_contract_validation_v5 import (
    CONTRACT_VERSION,
    validate_contract_object,
    validate_research_result,
)
from case_research_planning_v5 import research_context_fingerprint_v5


COVERAGE_POLICY_VERSION = "v5-coverage-1"
SUPPORT_SELECTION_VERSION = "v5-support-selection-1"

_LIMITATION_ORDER = (
    "generic_scope",
    "unplanned_scope",
    "missing_facts",
    "temporal_unassessed",
    "context_gap",
    "authority_conflict",
    "budget_exhausted",
    "no_evidence",
    "unsupported_topic",
)
_BLOCKING_UNRESOLVED = frozenset(
    {"integrity_failure", "context_incomplete", "conflicting_authority"}
)
_SELECTION_INPUT_FIELDS = frozenset(
    {
        "aspect_ref",
        "task_ref",
        "authority_ref",
        "evidence_refs",
        "basis",
        "context_status",
        "authority_status",
        "temporal_status",
    }
)
_OMISSION_INPUT_FIELDS = frozenset(
    {
        "aspect_ref",
        "task_ref",
        "class",
        "reason",
        "required",
        "description",
    }
)


class CoverageBuildError(RuntimeError):
    """A v5 coverage ledger cannot be built without inventing or dangling state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_ref(namespace: str, *parts: object) -> str:
    material = _compact_json(parts).encode("utf-8")
    return f"{namespace}:{hashlib.sha256(material).hexdigest()[:32]}"


def _unique_registry(
    items: Iterable[dict[str, Any]],
    key: str,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = deepcopy(raw)
        ref = item.get(key)
        if not isinstance(ref, str) or not ref:
            raise CoverageBuildError(f"{label} is missing {key}")
        if ref in registry:
            raise CoverageBuildError(f"duplicate {label} ref: {ref}")
        registry[ref] = item
    return registry


def research_context_for_coverage_v5(
    plan: dict[str, Any],
    *,
    corpus_snapshot_sha256: str | None,
    schema_migration_fingerprint: str | None,
    retrieval_config_sha256: str | None,
    retrieval_version: str,
    graph_selection_version: str,
) -> dict[str, Any]:
    """Build the #283 research-context identity with explicit policy ownership.

    Graph-selection identity remains a caller input because #284 owns that
    policy. This function does not activate graph selection or public v5.
    """
    return research_context_fingerprint_v5(
        plan,
        corpus_snapshot_sha256=corpus_snapshot_sha256,
        schema_migration_fingerprint=schema_migration_fingerprint,
        retrieval_config_sha256=retrieval_config_sha256,
        retrieval_version=retrieval_version,
        coverage_policy_version=COVERAGE_POLICY_VERSION,
        support_selection_version=SUPPORT_SELECTION_VERSION,
        graph_selection_version=graph_selection_version,
    )


def _validate_context_policy(context: dict[str, Any]) -> None:
    if context.get("coverage_policy_version") != COVERAGE_POLICY_VERSION:
        raise CoverageBuildError(
            "research_context coverage_policy_version does not match the active coverage producer"
        )
    if context.get("support_selection_version") != SUPPORT_SELECTION_VERSION:
        raise CoverageBuildError(
            "research_context support_selection_version does not match the active selection producer"
        )


def _trace_by_task(
    trace: list[dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    authorities: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    unresolved: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for step in trace:
        validate_contract_object(step)
        task_ref = step["task_ref"]
        task = tasks.get(task_ref)
        if task is None:
            raise CoverageBuildError(f"trace references unknown task: {task_ref}")
        if step["aspect_ref"] != task["aspect_ref"]:
            raise CoverageBuildError(
                f"trace {step['trace_ref']} belongs to the wrong aspect"
            )
        if step["executed_target"] != task["target"]:
            raise CoverageBuildError(
                f"trace {step['trace_ref']} does not preserve the task target"
            )
        for ref in (
            *step["retrieved_authority_refs"],
            *step["selected_authority_refs"],
        ):
            if ref not in authorities:
                raise CoverageBuildError(
                    f"trace {step['trace_ref']} references missing authority {ref}"
                )
        for ref in step["selected_evidence_refs"]:
            if ref not in evidence:
                raise CoverageBuildError(
                    f"trace {step['trace_ref']} references missing evidence {ref}"
                )
        for ref in step["unresolved_refs"]:
            if ref not in unresolved:
                raise CoverageBuildError(
                    f"trace {step['trace_ref']} references missing unresolved item {ref}"
                )
        grouped.setdefault(task_ref, []).append(deepcopy(step))

    for steps in grouped.values():
        steps.sort(key=lambda item: (item["round"], item["trace_ref"]))
    return grouped


def _latest_step(
    task_ref: str,
    trace_by_task: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    steps = trace_by_task.get(task_ref, [])
    return steps[-1] if steps else None


def _fact_status(
    aspect: dict[str, Any],
    facts: dict[str, dict[str, Any]],
) -> str:
    refs = aspect["fact_refs"]
    if not refs:
        return "not_required"
    missing_refs = [ref for ref in refs if ref not in facts]
    if missing_refs:
        raise CoverageBuildError(
            f"aspect {aspect['aspect_ref']} references unavailable facts: {missing_refs}"
        )
    states = {facts[ref]["state"] for ref in refs}
    if "ambiguous" in states:
        return "ambiguous"
    if "missing" in states:
        return "missing"
    return "sufficient"


def _make_omission(
    *,
    plan_ref: str,
    aspect_ref: str,
    task_ref: str | None,
    work_class: str,
    reason: str,
    required: bool,
    description: str,
) -> dict[str, Any]:
    omission_ref = _stable_ref(
        "omission",
        plan_ref,
        aspect_ref,
        task_ref,
        work_class,
        reason,
        required,
        description,
        COVERAGE_POLICY_VERSION,
    )
    item: dict[str, Any] = {
        "kind": "omitted_work",
        "contract_version": CONTRACT_VERSION,
        "omission_ref": omission_ref,
        "aspect_ref": aspect_ref,
        "class": work_class,
        "reason": reason,
        "required": required,
        "description": description,
    }
    if task_ref is not None:
        item["task_ref"] = task_ref
    return item


def _explicit_omission(
    raw: dict[str, Any],
    *,
    plan_ref: str,
    aspects: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fields = set(raw)
    if fields - _OMISSION_INPUT_FIELDS:
        raise CoverageBuildError(
            "explicit omission contains unsupported fields: "
            + ", ".join(sorted(fields - _OMISSION_INPUT_FIELDS))
        )
    required = _OMISSION_INPUT_FIELDS - {"task_ref"}
    missing = required - fields
    if missing:
        raise CoverageBuildError(
            "explicit omission is missing fields: " + ", ".join(sorted(missing))
        )
    aspect_ref = raw["aspect_ref"]
    if aspect_ref not in aspects:
        raise CoverageBuildError(f"omission references unknown aspect: {aspect_ref}")
    task_ref = raw.get("task_ref")
    if task_ref is not None:
        task = tasks.get(task_ref)
        if task is None or task["aspect_ref"] != aspect_ref:
            raise CoverageBuildError(
                f"omission task {task_ref!r} does not belong to {aspect_ref!r}"
            )
    return _make_omission(
        plan_ref=plan_ref,
        aspect_ref=aspect_ref,
        task_ref=task_ref,
        work_class=raw["class"],
        reason=raw["reason"],
        required=bool(raw["required"]),
        description=str(raw["description"]),
    )


def _derived_omissions(
    *,
    plan: dict[str, Any],
    aspects: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    trace_by_task: dict[str, list[dict[str, Any]]],
    facts: dict[str, dict[str, Any]],
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    omissions: list[dict[str, Any]] = []

    for aspect in aspects.values():
        if aspect["scope_status"] in {"generic_limited", "unknown_unplanned"}:
            omissions.append(
                _make_omission(
                    plan_ref=plan["plan_ref"],
                    aspect_ref=aspect["aspect_ref"],
                    task_ref=None,
                    work_class="research",
                    reason="unsupported_scope",
                    required=bool(aspect["required"]),
                    description=(
                        "The declared generic or unknown aspect scope is not a finite "
                        "basis for complete support closure."
                    ),
                )
            )

    for task in tasks.values():
        if not task["required"]:
            continue
        aspect = aspects[task["aspect_ref"]]
        step = _latest_step(task["task_ref"], trace_by_task)
        if step is None:
            omissions.append(
                _make_omission(
                    plan_ref=plan["plan_ref"],
                    aspect_ref=task["aspect_ref"],
                    task_ref=task["task_ref"],
                    work_class="research",
                    reason="not_planned",
                    required=True,
                    description="A required planned research task was not executed.",
                )
            )
            continue

        outcome = step["outcome"]
        if outcome == "budget_exhausted":
            omissions.append(
                _make_omission(
                    plan_ref=plan["plan_ref"],
                    aspect_ref=task["aspect_ref"],
                    task_ref=task["task_ref"],
                    work_class="research",
                    reason="budget_exhausted",
                    required=True,
                    description=(
                        "A required research task could not finish within the declared "
                        "research budget."
                    ),
                )
            )
        elif outcome == "blocked":
            fact_status = _fact_status(aspect, facts)
            blocked_by_facts = fact_status in {"missing", "ambiguous"}
            omissions.append(
                _make_omission(
                    plan_ref=plan["plan_ref"],
                    aspect_ref=task["aspect_ref"],
                    task_ref=task["task_ref"],
                    work_class="research",
                    reason=(
                        "blocked_by_facts" if blocked_by_facts else "integrity_failure"
                    ),
                    required=True,
                    description=(
                        "A required research task is blocked by missing or ambiguous "
                        "caller facts."
                        if blocked_by_facts
                        else "A required research task is blocked without a safe factual continuation."
                    ),
                )
            )
        elif outcome == "integrity_failure":
            omissions.append(
                _make_omission(
                    plan_ref=plan["plan_ref"],
                    aspect_ref=task["aspect_ref"],
                    task_ref=task["task_ref"],
                    work_class="research",
                    reason="integrity_failure",
                    required=True,
                    description="A required research task stopped on an integrity failure.",
                )
            )

    for selection in selections:
        if selection["context_status"] != "incomplete":
            continue
        omissions.append(
            _make_omission(
                plan_ref=plan["plan_ref"],
                aspect_ref=selection["aspect_ref"],
                task_ref=selection["task_ref"],
                work_class="support",
                reason="context_unavailable",
                required=True,
                description=(
                    "Selected evidence is context-incomplete and cannot close support."
                ),
            )
        )
    return omissions


def _selection_from_input(
    raw: dict[str, Any],
    *,
    plan: dict[str, Any],
    research_context: dict[str, Any],
    aspects: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    trace_by_task: dict[str, list[dict[str, Any]]],
    authorities: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fields = set(raw)
    if fields != _SELECTION_INPUT_FIELDS:
        missing = _SELECTION_INPUT_FIELDS - fields
        extra = fields - _SELECTION_INPUT_FIELDS
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unsupported " + ", ".join(sorted(extra)))
        raise CoverageBuildError("selection input fields are invalid: " + "; ".join(detail))

    aspect_ref = raw["aspect_ref"]
    task_ref = raw["task_ref"]
    authority_ref = raw["authority_ref"]
    task = tasks.get(task_ref)
    if aspect_ref not in aspects:
        raise CoverageBuildError(f"selection references unknown aspect: {aspect_ref}")
    if task is None or task["aspect_ref"] != aspect_ref:
        raise CoverageBuildError(
            f"selection task {task_ref!r} does not belong to {aspect_ref!r}"
        )
    if authority_ref not in authorities:
        raise CoverageBuildError(
            f"selection references unavailable authority: {authority_ref}"
        )

    evidence_refs = sorted(set(raw["evidence_refs"]))
    if not evidence_refs:
        raise CoverageBuildError("selection requires at least one exact evidence ref")
    for ref in evidence_refs:
        span = evidence.get(ref)
        if span is None:
            raise CoverageBuildError(f"selection references unavailable evidence: {ref}")
        if span.get("authority_ref") != authority_ref:
            raise CoverageBuildError(
                f"selection evidence {ref} belongs to a different authority"
            )

    steps = trace_by_task.get(task_ref, [])
    if not steps:
        raise CoverageBuildError(
            f"selection for {task_ref!r} has no execution trace"
        )
    traced_authorities = {
        ref for step in steps for ref in step["selected_authority_refs"]
    }
    traced_evidence = {
        ref for step in steps for ref in step["selected_evidence_refs"]
    }
    if authority_ref not in traced_authorities:
        raise CoverageBuildError(
            f"selection authority {authority_ref!r} was not selected by the task trace"
        )
    missing_from_trace = set(evidence_refs) - traced_evidence
    if missing_from_trace:
        raise CoverageBuildError(
            "selection evidence was not selected by the task trace: "
            + ", ".join(sorted(missing_from_trace))
        )

    temporal_status = raw["temporal_status"]
    if "as_of_date" not in plan and temporal_status != "unassessed":
        raise CoverageBuildError(
            "selection cannot assert temporal assessment without caller as_of_date"
        )

    selection_ref = _stable_ref(
        "selection",
        plan["plan_ref"],
        research_context,
        aspect_ref,
        task_ref,
        authority_ref,
        evidence_refs,
        raw["basis"],
        raw["context_status"],
        raw["authority_status"],
        temporal_status,
        SUPPORT_SELECTION_VERSION,
    )
    return {
        "kind": "evidence_selection",
        "contract_version": CONTRACT_VERSION,
        "selection_ref": selection_ref,
        "aspect_ref": aspect_ref,
        "task_ref": task_ref,
        "authority_ref": authority_ref,
        "evidence_refs": evidence_refs,
        "basis": raw["basis"],
        "context_status": raw["context_status"],
        "authority_status": raw["authority_status"],
        "temporal_status": temporal_status,
    }


def _execution_status(
    aspect_ref: str,
    tasks: dict[str, dict[str, Any]],
    trace_by_task: dict[str, list[dict[str, Any]]],
) -> str:
    aspect_tasks = [task for task in tasks.values() if task["aspect_ref"] == aspect_ref]
    required = [task for task in aspect_tasks if task["required"]]
    tracked = required or aspect_tasks
    if not tracked:
        return "not_started"

    latest = [_latest_step(task["task_ref"], trace_by_task) for task in tracked]
    present = [step for step in latest if step is not None]
    if not present:
        return "not_started"

    outcomes = {step["outcome"] for step in present}
    if "integrity_failure" in outcomes or "blocked" in outcomes:
        return "blocked"
    if "budget_exhausted" in outcomes:
        return "budget_exhausted"
    if len(present) != len(tracked):
        return "partial"
    if all(step["outcome"] in {"hits", "no_hits"} for step in present):
        return "complete"
    return "partial"


def _local_unresolved_refs(
    *,
    aspect: dict[str, Any],
    task_refs: set[str],
    selection_refs: set[str],
    trace_by_task: dict[str, list[dict[str, Any]]],
    unresolved: dict[str, dict[str, Any]],
) -> list[str]:
    refs: set[str] = set()
    for task_ref in task_refs:
        for step in trace_by_task.get(task_ref, []):
            refs.update(step["unresolved_refs"])

    for ref, item in unresolved.items():
        if aspect["aspect_ref"] in item.get("related_aspect_refs", []):
            refs.add(ref)
            continue
        if task_refs.intersection(item.get("related_task_refs", [])):
            refs.add(ref)
            continue
        if selection_refs.intersection(item.get("related_selection_refs", [])):
            refs.add(ref)
    return sorted(refs)


def _evidence_status(
    selections: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    local_unresolved: list[dict[str, Any]],
) -> str:
    if any(item.get("category") == "context_incomplete" for item in local_unresolved):
        return "context_incomplete"
    if any(item["context_status"] == "incomplete" for item in selections):
        return "context_incomplete"
    if selections:
        return "context_ready"
    if any(
        step["outcome"] == "hits"
        or step["retrieved_authority_refs"]
        or step["selected_authority_refs"]
        for step in steps
    ):
        return "candidate_only"
    if any(step["outcome"] == "no_hits" for step in steps):
        return "none_found"
    return "not_assessed"


def _authority_status(
    selections: list[dict[str, Any]],
    local_unresolved: list[dict[str, Any]],
) -> str:
    categories = {item.get("category") for item in local_unresolved}
    if "conflicting_authority" in categories:
        return "conflicting"
    if "unresolved_identity" in categories:
        return "ambiguous"
    if not selections:
        return "unassessed"
    values = {item["authority_status"] for item in selections}
    if "conflicting" in values:
        return "conflicting"
    if "ambiguous" in values:
        return "ambiguous"
    if "unassessed" in values:
        return "unassessed"
    return "resolved"


def _temporal_status(
    *,
    plan: dict[str, Any],
    selections: list[dict[str, Any]],
    local_unresolved: list[dict[str, Any]],
) -> str:
    if "as_of_date" not in plan:
        return "unassessed"
    if any(item.get("category") == "temporal_uncertainty" for item in local_unresolved):
        return "ambiguous"
    if not selections:
        return "unassessed"
    values = {item["temporal_status"] for item in selections}
    if "ambiguous" in values:
        return "ambiguous"
    if len(values) > 1:
        return "mixed"
    if values == {"unassessed"}:
        return "unassessed"
    return "assessed"


def _temporal_support_is_usable(
    *,
    plan: dict[str, Any],
    selections: list[dict[str, Any]],
    local_unresolved: list[dict[str, Any]],
) -> bool:
    if "as_of_date" not in plan:
        return True
    if any(item.get("category") == "temporal_uncertainty" for item in local_unresolved):
        return False
    return bool(selections) and all(
        item["temporal_status"] == "effective_as_of" for item in selections
    )


def _limitation_codes(
    *,
    aspect: dict[str, Any],
    execution_status: str,
    evidence_status: str,
    authority_status: str,
    fact_status: str,
    plan: dict[str, Any],
    local_unresolved: list[dict[str, Any]],
    omissions: list[dict[str, Any]],
) -> list[str]:
    codes: set[str] = set()
    if aspect["scope_status"] == "generic_limited":
        codes.add("generic_scope")
    if aspect["scope_status"] == "unknown_unplanned":
        codes.update({"unplanned_scope", "unsupported_topic"})
    if fact_status in {"missing", "ambiguous"}:
        codes.add("missing_facts")
    if "as_of_date" not in plan:
        codes.add("temporal_unassessed")
    if evidence_status == "context_incomplete":
        codes.add("context_gap")
    if authority_status in {"ambiguous", "conflicting"}:
        codes.add("authority_conflict")
    if execution_status == "budget_exhausted" or any(
        item["reason"] == "budget_exhausted" for item in omissions
    ):
        codes.add("budget_exhausted")
    if evidence_status == "none_found":
        codes.add("no_evidence")

    categories = {item.get("category") for item in local_unresolved}
    if "context_incomplete" in categories:
        codes.add("context_gap")
    if "conflicting_authority" in categories:
        codes.add("authority_conflict")
    if "budget_exhausted" in categories:
        codes.add("budget_exhausted")
    if "unsupported_topic" in categories:
        codes.add("unsupported_topic")
    if "unplanned_scope" in categories:
        codes.add("unplanned_scope")

    return [code for code in _LIMITATION_ORDER if code in codes]


def _support_closure(
    *,
    aspect: dict[str, Any],
    execution_status: str,
    evidence_status: str,
    authority_status: str,
    temporal_status: str,
    fact_status: str,
    synthesis_status: str,
    selections: list[dict[str, Any]],
    omissions: list[dict[str, Any]],
    local_unresolved: list[dict[str, Any]],
    plan: dict[str, Any],
) -> str:
    if aspect["scope_status"] in {"generic_limited", "unknown_unplanned"}:
        return "unsupported_scope"

    if execution_status != "complete":
        return "incomplete"
    if evidence_status != "context_ready" or not selections:
        return "incomplete"
    if authority_status != "resolved":
        return "incomplete"
    if any(item["required"] for item in omissions):
        return "incomplete"
    if any(item.get("category") in _BLOCKING_UNRESOLVED for item in local_unresolved):
        return "incomplete"
    if synthesis_status == "unsupported":
        return "incomplete"
    if "as_of_date" in plan:
        if temporal_status != "assessed":
            return "incomplete"
        if not _temporal_support_is_usable(
            plan=plan,
            selections=selections,
            local_unresolved=local_unresolved,
        ):
            return "incomplete"

    # Missing or ambiguous facts may be personalization-only blockers. They are
    # visible in fact/synthesis status but do not erase otherwise complete
    # general legal support.
    if fact_status in {"missing", "ambiguous"} and synthesis_status != "requires_facts":
        return "incomplete"
    return "complete"


def build_research_result_v5(
    plan: dict[str, Any],
    *,
    case_input: dict[str, Any],
    trace: Iterable[dict[str, Any]],
    selection_inputs: Iterable[dict[str, Any]],
    authorities: Iterable[dict[str, Any]],
    evidence_spans: Iterable[dict[str, Any]],
    unresolved: Iterable[dict[str, Any]],
    facts: Iterable[dict[str, Any]],
    research_context: dict[str, Any],
    omitted_work_inputs: Iterable[dict[str, Any]] = (),
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic v5 evidence-selection and per-aspect coverage ledger.

    The function consumes already-materialized exact evidence. It does not
    retrieve law, infer legal applicability, select graph relationships, mutate
    corpus state, or turn a relevance hit into support. Every EvidenceSelection
    must be explicitly justified and resolve to the final supplied registries.
    """
    validate_contract_object(case_input)
    if case_input["contract_version"] != CONTRACT_VERSION:
        raise CoverageBuildError("case_input must use CASE v5")
    if plan.get("contract_version") != CONTRACT_VERSION:
        raise CoverageBuildError("research plan must use CASE v5")
    if case_input.get("as_of_date") != plan.get("as_of_date"):
        raise CoverageBuildError(
            "ResearchPlan must preserve the caller-owned as_of_date exactly"
        )
    _validate_context_policy(research_context)

    aspects = _unique_registry(plan["aspects"], "aspect_ref", label="aspect")
    tasks = _unique_registry(plan["tasks"], "task_ref", label="task")
    authority_registry = _unique_registry(
        authorities, "authority_ref", label="authority"
    )
    evidence_registry = _unique_registry(
        evidence_spans, "evidence_ref", label="evidence"
    )
    unresolved_registry = _unique_registry(
        unresolved, "unresolved_ref", label="unresolved"
    )
    fact_registry = _unique_registry(facts, "fact_ref", label="fact")

    trace_items = [deepcopy(item) for item in trace]
    grouped_trace = _trace_by_task(
        trace_items,
        tasks,
        authority_registry,
        evidence_registry,
        unresolved_registry,
    )

    selections: list[dict[str, Any]] = []
    selection_refs: set[str] = set()
    for raw in selection_inputs:
        selection = _selection_from_input(
            deepcopy(raw),
            plan=plan,
            research_context=research_context,
            aspects=aspects,
            tasks=tasks,
            trace_by_task=grouped_trace,
            authorities=authority_registry,
            evidence=evidence_registry,
        )
        ref = selection["selection_ref"]
        if ref in selection_refs:
            continue
        selection_refs.add(ref)
        selections.append(selection)
    selections.sort(key=lambda item: item["selection_ref"])

    omissions = _derived_omissions(
        plan=plan,
        aspects=aspects,
        tasks=tasks,
        trace_by_task=grouped_trace,
        facts=fact_registry,
        selections=selections,
    )
    omissions.extend(
        _explicit_omission(
            deepcopy(raw),
            plan_ref=plan["plan_ref"],
            aspects=aspects,
            tasks=tasks,
        )
        for raw in omitted_work_inputs
    )
    omission_by_ref: dict[str, dict[str, Any]] = {}
    for item in omissions:
        prior = omission_by_ref.get(item["omission_ref"])
        if prior is not None and prior != item:
            raise CoverageBuildError(
                f"deterministic omission-ref collision: {item['omission_ref']}"
            )
        omission_by_ref[item["omission_ref"]] = item
    omissions = [omission_by_ref[ref] for ref in sorted(omission_by_ref)]

    selections_by_aspect: dict[str, list[dict[str, Any]]] = {}
    for item in selections:
        selections_by_aspect.setdefault(item["aspect_ref"], []).append(item)
    omissions_by_aspect: dict[str, list[dict[str, Any]]] = {}
    for item in omissions:
        omissions_by_aspect.setdefault(item["aspect_ref"], []).append(item)

    coverage_items: list[dict[str, Any]] = []
    for aspect in sorted(aspects.values(), key=lambda item: (item["sequence"], item["aspect_ref"])):
        aspect_ref = aspect["aspect_ref"]
        aspect_tasks = sorted(
            (task for task in tasks.values() if task["aspect_ref"] == aspect_ref),
            key=lambda item: (item["sequence"], item["task_ref"]),
        )
        task_refs = [task["task_ref"] for task in aspect_tasks]
        task_ref_set = set(task_refs)
        aspect_selections = selections_by_aspect.get(aspect_ref, [])
        aspect_omissions = omissions_by_aspect.get(aspect_ref, [])
        aspect_selection_refs = {item["selection_ref"] for item in aspect_selections}
        local_refs = _local_unresolved_refs(
            aspect=aspect,
            task_refs=task_ref_set,
            selection_refs=aspect_selection_refs,
            trace_by_task=grouped_trace,
            unresolved=unresolved_registry,
        )
        local_unresolved = [unresolved_registry[ref] for ref in local_refs]
        steps = [
            step
            for task_ref in task_refs
            for step in grouped_trace.get(task_ref, [])
        ]

        execution_status = _execution_status(aspect_ref, tasks, grouped_trace)
        evidence_status = _evidence_status(
            aspect_selections, steps, local_unresolved
        )
        authority_status = _authority_status(
            aspect_selections, local_unresolved
        )
        temporal_status = _temporal_status(
            plan=plan,
            selections=aspect_selections,
            local_unresolved=local_unresolved,
        )
        fact_status = _fact_status(aspect, fact_registry)
        synthesis_status = (
            "requires_facts"
            if fact_status in {"missing", "ambiguous"}
            else (
                "requires_interpretive_synthesis"
                if evidence_status == "context_ready"
                else "unsupported"
            )
        )
        closure = _support_closure(
            aspect=aspect,
            execution_status=execution_status,
            evidence_status=evidence_status,
            authority_status=authority_status,
            temporal_status=temporal_status,
            fact_status=fact_status,
            synthesis_status=synthesis_status,
            selections=aspect_selections,
            omissions=aspect_omissions,
            local_unresolved=local_unresolved,
            plan=plan,
        )
        limitations = _limitation_codes(
            aspect=aspect,
            execution_status=execution_status,
            evidence_status=evidence_status,
            authority_status=authority_status,
            fact_status=fact_status,
            plan=plan,
            local_unresolved=local_unresolved,
            omissions=aspect_omissions,
        )
        selection_refs_for_aspect = sorted(aspect_selection_refs)
        omission_refs_for_aspect = sorted(
            item["omission_ref"] for item in aspect_omissions
        )
        coverage_ref = _stable_ref(
            "coverage",
            plan["plan_ref"],
            research_context,
            aspect_ref,
            task_refs,
            selection_refs_for_aspect,
            omission_refs_for_aspect,
            local_refs,
            execution_status,
            evidence_status,
            authority_status,
            temporal_status,
            fact_status,
            synthesis_status,
            closure,
            limitations,
            COVERAGE_POLICY_VERSION,
        )
        coverage_items.append(
            {
                "kind": "aspect_coverage",
                "contract_version": CONTRACT_VERSION,
                "coverage_ref": coverage_ref,
                "aspect_ref": aspect_ref,
                "task_refs": task_refs,
                "selection_refs": selection_refs_for_aspect,
                "omission_refs": omission_refs_for_aspect,
                "unresolved_refs": local_refs,
                "execution_status": execution_status,
                "evidence_status": evidence_status,
                "authority_status": authority_status,
                "temporal_status": temporal_status,
                "fact_status": fact_status,
                "synthesis_status": synthesis_status,
                "support_closure": closure,
                "limitation_codes": limitations,
            }
        )

    all_authority_refs: set[str] = set()
    for step in trace_items:
        all_authority_refs.update(step["retrieved_authority_refs"])
        all_authority_refs.update(step["selected_authority_refs"])
    all_authority_refs.update(item["authority_ref"] for item in selections)

    global_integrity_failure = any(
        item.get("category") == "integrity_failure"
        for item in unresolved_registry.values()
    ) or any(item["reason"] == "integrity_failure" for item in omissions)

    required_aspects = [item for item in aspects.values() if item["required"]]
    coverage_by_aspect = {
        item["aspect_ref"]: item for item in coverage_items
    }
    complete = bool(required_aspects) and all(
        aspect["scope_status"] not in {"generic_limited", "unknown_unplanned"}
        and coverage_by_aspect[aspect["aspect_ref"]]["support_closure"] == "complete"
        for aspect in required_aspects
    ) and not any(item["required"] for item in omissions)

    if global_integrity_failure:
        status = "blocked"
    elif complete:
        status = "complete"
    else:
        status = "partial"

    result_ref = _stable_ref(
        "research",
        plan["plan_ref"],
        research_context,
        [item["trace_ref"] for item in trace_items],
        sorted(all_authority_refs),
        [item["selection_ref"] for item in selections],
        [item["coverage_ref"] for item in coverage_items],
        [item["omission_ref"] for item in omissions],
        sorted(unresolved_registry),
        status,
        COVERAGE_POLICY_VERSION,
        SUPPORT_SELECTION_VERSION,
    )
    result = {
        "kind": "research_result",
        "contract_version": CONTRACT_VERSION,
        "result_ref": result_ref,
        "plan_ref": plan["plan_ref"],
        "status": status,
        "trace": trace_items,
        "authority_refs": sorted(all_authority_refs),
        "evidence_selections": selections,
        "aspect_coverage": coverage_items,
        "omitted_work": omissions,
        "unresolved_refs": sorted(unresolved_registry),
        "research_context": deepcopy(research_context),
        "generated_at": generated_at or _utc_now(),
    }

    validate_research_result(
        plan,
        result,
        case_input=case_input,
        authorities=list(authority_registry.values()),
        evidence_spans=list(evidence_registry.values()),
        unresolved=list(unresolved_registry.values()),
        facts=list(fact_registry.values()),
    )
    return result
