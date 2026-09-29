from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from case_contract_validation import CaseContractError, validate_schema_object
from case_contract_validation_v4 import (
    _validate_registered_rule_fragment,
    validate_intake_draft as validate_v4_intake_draft,
)


CONTRACT_VERSION = "5.0.0"
V4_CONTRACT_VERSION = "4.0.0"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "application"
    / "schemas"
    / "case-contracts-v5.schema.json"
)

INVALID_CASE_INPUT = "INVALID_CASE_INPUT"
INVALID_INTAKE_DRAFT = "INVALID_INTAKE_DRAFT"
INVALID_RESEARCH_PLAN = "INVALID_RESEARCH_PLAN"
INVALID_RESEARCH_RESULT = "INVALID_RESEARCH_RESULT"
INVALID_LEGAL_RESEARCH_BUNDLE = "INVALID_LEGAL_RESEARCH_BUNDLE"
INVALID_RESEARCH_CONTINUATION_REQUEST = "INVALID_RESEARCH_CONTINUATION_REQUEST"

V5_REF_ASPECT_001 = "V5-REF-ASPECT-001"
V5_REF_SELECTION_002 = "V5-REF-SELECTION-002"
V5_REF_COVERAGE_003 = "V5-REF-COVERAGE-003"
V5_COMPLETE_001 = "V5-COMPLETE-001"
V5_OMISSION_001 = "V5-OMISSION-001"
V5_CONTEXT_001 = "V5-CONTEXT-001"
V5_TEMPORAL_001 = "V5-TEMPORAL-001"
V5_FACT_001 = "V5-FACT-001"
V5_EVALUATOR_001 = "V5-EVALUATOR-001"
V5_SCOPE_001 = "V5-SCOPE-001"
V5_CONSUMER_001 = "V5-CONSUMER-001"
V5_ID_001 = "V5-ID-001"

_KIND_TO_DEFINITION = {
    "case_input": "CaseInput",
    "intake_draft": "IntakeDraft",
    "research_aspect": "ResearchAspect",
    "research_task": "ResearchTask",
    "research_plan": "ResearchPlan",
    "research_trace_step": "ResearchTraceStep",
    "research_result": "ResearchResult",
    "evidence_selection": "EvidenceSelection",
    "aspect_coverage": "AspectCoverage",
    "omitted_work": "OmittedWork",
    "official_source": "OfficialSource",
    "canonical_authority": "CanonicalAuthority",
    "evidence_span": "EvidenceSpan",
    "normative_relationship": "NormativeRelationship",
    "rule_fragment": "RuleFragment",
    "deterministic_evaluation": "DeterministicEvaluation",
    "calculation_trace": "CalculationTrace",
    "unresolved_item": "UnresolvedItem",
    "legal_research_bundle": "LegalResearchBundle",
    "research_continuation_request": "ResearchContinuationRequest",
}

# v5 keeps the intake model intake-only. These new namespaces are platform or
# consumer owned and therefore may not be injected through model-authored intake
# labels/questions/search vocabulary. Frozen v4 validation already rejects the
# pre-v5 platform namespaces.
_NEW_V5_PLATFORM_REF_IN_MODEL_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9._-])"
    r"(?:aspect|selection|coverage|omission|continuation):[A-Za-z0-9._-]+"
    r"(?:$|[^A-Za-z0-9._-])"
)

_FINGERPRINT_OPTIONAL_FIELDS = frozenset(
    {
        "corpus_snapshot_sha256",
        "schema_migration_fingerprint",
        "retrieval_config_sha256",
        "as_of_date",
    }
)

_BLOCKING_UNRESOLVED_CATEGORIES = frozenset(
    {"integrity_failure", "context_incomplete", "conflicting_authority"}
)


def _fail(code: str, path: str, detail: str) -> None:
    raise CaseContractError(code, f"{path}: {detail}")


def _validate_schema(value: dict[str, Any], definition: str, code: str) -> None:
    validate_schema_object(value, definition, code, schema_path=SCHEMA_PATH)


def validate_contract_object(value: dict[str, Any]) -> None:
    """Validate the serialized shape of one named v5 contract primitive."""
    if not isinstance(value, dict):
        _fail(INVALID_LEGAL_RESEARCH_BUNDLE, "$", "expected object")
    if value.get("contract_version") != CONTRACT_VERSION:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$.contract_version",
            f"expected {CONTRACT_VERSION!r}",
        )
    kind = value.get("kind")
    definition = _KIND_TO_DEFINITION.get(kind)
    if definition is None:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$.kind",
            f"unsupported v5 contract kind {kind!r}",
        )
    _validate_schema(value, definition, INVALID_LEGAL_RESEARCH_BUNDLE)


def _registry(
    items: list[dict[str, Any]],
    key: str,
    *,
    code: str,
    owner: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        ref = item[key]
        if ref in result:
            _fail(code, owner, f"duplicate declared ref {ref!r}")
        result[ref] = item
    return result


def _require_refs(
    refs: list[str],
    registry: dict[str, dict[str, Any]],
    *,
    code: str,
    path: str,
) -> None:
    for ref in refs:
        if ref not in registry:
            _fail(code, path, f"dangling or wrong-type ref {ref!r}")


def _as_frozen_v4_copy(value: Any) -> Any:
    """Map unchanged v5 intake families onto frozen v4 semantics defensively.

    #279 intentionally preserved CaseInput/IntakeDraft semantics while changing
    the research graph. Reusing the mature v4 intake validator on a copy avoids
    duplicating its exact-quote/fact fidelity logic. No v5 research object ever
    passes through this compatibility helper.
    """
    copied = deepcopy(value)

    def rewrite(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if (
                    key in {"contract_version", "schema_version"}
                    and child == CONTRACT_VERSION
                ):
                    node[key] = V4_CONTRACT_VERSION
                else:
                    rewrite(child)
        elif isinstance(node, list):
            for child in node:
                rewrite(child)

    rewrite(copied)
    return copied


def validate_case_input(case_input: dict[str, Any]) -> None:
    """Validate one caller-owned v5 CaseInput without adding defaults."""
    _validate_schema(case_input, "CaseInput", INVALID_CASE_INPUT)


def _reject_new_v5_model_ref_injection(draft: dict[str, Any]) -> None:
    for index, fact in enumerate(draft["facts"]):
        for name in ("label", "value", "needed_information"):
            value = fact.get(name)
            if (
                isinstance(value, str)
                and _NEW_V5_PLATFORM_REF_IN_MODEL_TEXT.search(value)
            ):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.facts[{index}].{name}",
                    "model-authored intake content attempted to inject a v5 platform-owned identifier",
                )

    for index, question in enumerate(draft["questions"]):
        if _NEW_V5_PLATFORM_REF_IN_MODEL_TEXT.search(question["text"]):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.questions[{index}].text",
                "model-authored question attempted to inject a v5 platform-owned identifier",
            )

    for index, hint in enumerate(draft["search_hints"]):
        for term_index, term in enumerate(hint["terms"]):
            if _NEW_V5_PLATFORM_REF_IN_MODEL_TEXT.search(term):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.search_hints[{index}].terms[{term_index}]",
                    "model search vocabulary attempted to inject a v5 typed application identifier",
                )


def validate_intake_draft(case_input: dict[str, Any], draft: dict[str, Any]) -> None:
    """Validate the unchanged intake-only boundary under declared v5 identity."""
    validate_case_input(case_input)
    _validate_schema(draft, "IntakeDraft", INVALID_INTAKE_DRAFT)

    # CaseInput and IntakeDraft are intentionally semantically unchanged from
    # v4. Validate their mature fidelity/typed-intake invariants on copies, then
    # add the v5-only namespace ownership guard.
    validate_v4_intake_draft(
        _as_frozen_v4_copy(case_input),
        _as_frozen_v4_copy(draft),
    )
    _reject_new_v5_model_ref_injection(draft)


def _validate_case_as_of_date(
    case_input: dict[str, Any],
    plan: dict[str, Any],
    *,
    code: str,
) -> None:
    if "as_of_date" in case_input:
        if plan.get("as_of_date") != case_input["as_of_date"]:
            _fail(
                code,
                "$.as_of_date",
                "plan does not preserve CaseInput.as_of_date",
            )
    elif "as_of_date" in plan:
        _fail(
            code,
            "$.as_of_date",
            "plan invented an absent CaseInput.as_of_date",
        )


def validate_research_plan(
    intake_draft: dict[str, Any],
    plan: dict[str, Any],
    *,
    case_input: dict[str, Any] | None = None,
) -> None:
    """Validate v5 question -> aspect -> task ownership and plan bounds."""
    _validate_schema(plan, "ResearchPlan", INVALID_RESEARCH_PLAN)
    _validate_schema(intake_draft, "IntakeDraft", INVALID_RESEARCH_PLAN)

    if plan["intake_ref"] != intake_draft["intake_ref"]:
        _fail(
            INVALID_RESEARCH_PLAN,
            "$.intake_ref",
            "does not resolve to the accepted IntakeDraft",
        )
    if case_input is not None:
        _validate_case_as_of_date(case_input, plan, code=V5_TEMPORAL_001)

    facts = _registry(
        intake_draft["facts"],
        "fact_ref",
        code=V5_REF_ASPECT_001,
        owner="$.intake_draft.facts",
    )
    questions = _registry(
        intake_draft["questions"],
        "question_ref",
        code=V5_REF_ASPECT_001,
        owner="$.intake_draft.questions",
    )
    hints = _registry(
        intake_draft["search_hints"],
        "hint_ref",
        code=V5_REF_ASPECT_001,
        owner="$.intake_draft.search_hints",
    )
    aspects = _registry(
        plan["aspects"],
        "aspect_ref",
        code=V5_REF_ASPECT_001,
        owner="$.aspects",
    )
    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=V5_REF_ASPECT_001,
        owner="$.tasks",
    )

    aspects_by_question: dict[str, list[dict[str, Any]]] = {}
    for index, aspect in enumerate(plan["aspects"]):
        _require_refs(
            [aspect["question_ref"]],
            questions,
            code=V5_REF_ASPECT_001,
            path=f"$.aspects[{index}].question_ref",
        )
        _require_refs(
            aspect["fact_refs"],
            facts,
            code=V5_REF_ASPECT_001,
            path=f"$.aspects[{index}].fact_refs",
        )
        aspects_by_question.setdefault(aspect["question_ref"], []).append(aspect)

        profile_fields = ("profile_id", "profile_version")
        if aspect["origin"] == "profile":
            if any(name not in aspect for name in profile_fields):
                _fail(
                    INVALID_RESEARCH_PLAN,
                    f"$.aspects[{index}]",
                    "profile-origin aspect requires profile_id and profile_version",
                )
        elif any(name in aspect for name in profile_fields):
            _fail(
                INVALID_RESEARCH_PLAN,
                f"$.aspects[{index}]",
                "profile metadata is only valid for profile-origin aspects",
            )

        if (
            aspect["origin"] == "generic_fallback"
            and aspect["scope_status"]
            not in {"generic_limited", "unknown_unplanned"}
        ):
            _fail(
                V5_SCOPE_001,
                f"$.aspects[{index}].scope_status",
                "generic_fallback cannot claim finite scope",
            )

    for index, task in enumerate(plan["tasks"]):
        _require_refs(
            [task["question_ref"]],
            questions,
            code=V5_REF_ASPECT_001,
            path=f"$.tasks[{index}].question_ref",
        )
        _require_refs(
            [task["aspect_ref"]],
            aspects,
            code=V5_REF_ASPECT_001,
            path=f"$.tasks[{index}].aspect_ref",
        )
        aspect = aspects[task["aspect_ref"]]
        if task["question_ref"] != aspect["question_ref"]:
            _fail(
                V5_REF_ASPECT_001,
                f"$.tasks[{index}].question_ref",
                "task question_ref does not match owning ResearchAspect",
            )
        _require_refs(
            task.get("generated_from_fact_refs", []),
            facts,
            code=V5_REF_ASPECT_001,
            path=f"$.tasks[{index}].generated_from_fact_refs",
        )
        _require_refs(
            task.get("hint_refs", []),
            hints,
            code=V5_REF_ASPECT_001,
            path=f"$.tasks[{index}].hint_refs",
        )

    for question in intake_draft["questions"]:
        if question["category"] == "legal" and question["status"] == "open":
            if not aspects_by_question.get(question["question_ref"]):
                _fail(
                    V5_REF_ASPECT_001,
                    "$.aspects",
                    f"open legal question has no ResearchAspect: {question['question_ref']!r}",
                )

    for aspect in plan["aspects"]:
        if not aspect["required"]:
            continue
        has_required_task = any(
            task["aspect_ref"] == aspect["aspect_ref"]
            and task["origin"] == "platform_required"
            and task["required"]
            for task in tasks.values()
        )
        if not has_required_task:
            _fail(
                V5_REF_ASPECT_001,
                "$.tasks",
                f"required aspect lacks required platform task: {aspect['aspect_ref']!r}",
            )

    research_budget = plan["budgets"]["research"]
    if len(tasks) > research_budget["max_tasks"]:
        _fail(
            INVALID_RESEARCH_PLAN,
            "$.tasks",
            "task count exceeds research max_tasks",
        )
    for index, task in enumerate(plan["tasks"]):
        if task["depth"] > research_budget["max_reference_depth"]:
            _fail(
                INVALID_RESEARCH_PLAN,
                f"$.tasks[{index}].depth",
                "task depth exceeds max_reference_depth",
            )


def _validate_research_context(
    context: dict[str, Any],
    plan: dict[str, Any],
    *,
    path: str,
) -> None:
    unavailable = set(context["unavailable_fields"])
    for name in _FINGERPRINT_OPTIONAL_FIELDS:
        is_null = context[name] is None
        is_unavailable = name in unavailable
        if is_null != is_unavailable:
            code = V5_TEMPORAL_001 if name == "as_of_date" else V5_ID_001
            _fail(
                code,
                f"{path}.{name}",
                "null availability must match unavailable_fields exactly",
            )

    expected = {
        "planner_version": plan["planner_version"],
        "profile_set_version": plan["profile_set_version"],
        "profile_set_sha256": plan["profile_set_sha256"],
    }
    for name, expected_value in expected.items():
        if context[name] != expected_value:
            _fail(
                V5_ID_001,
                f"{path}.{name}",
                f"does not match ResearchPlan.{name}",
            )

    if context["as_of_date"] != plan.get("as_of_date"):
        _fail(
            V5_TEMPORAL_001,
            f"{path}.as_of_date",
            "does not match ResearchPlan.as_of_date",
        )


def _validate_limitation_codes(
    aspect: dict[str, Any],
    coverage: dict[str, Any],
    *,
    path: str,
) -> None:
    codes = set(coverage["limitation_codes"])
    required: set[str] = set()
    if aspect["scope_status"] == "generic_limited":
        required.add("generic_scope")
    elif aspect["scope_status"] == "unknown_unplanned":
        required.add("unplanned_scope")
    if coverage["fact_status"] in {"missing", "ambiguous"}:
        required.add("missing_facts")
    # Other limitation codes describe evidence/authority/execution reasons but
    # are not a one-to-one encoding of status enums. The accepted #279 vectors
    # intentionally use, for example, unsupported_topic instead of forcing a
    # synthetic no_evidence reason. Do not invent a stricter mapping here.
    missing = sorted(required - codes)
    if missing:
        _fail(
            V5_COMPLETE_001,
            f"{path}.limitation_codes",
            "status limitations missing required reason code(s): "
            + ", ".join(missing),
        )


def _validate_fact_locality(
    aspect: dict[str, Any],
    coverage: dict[str, Any],
    *,
    facts: dict[str, dict[str, Any]] | None,
    path: str,
) -> None:
    if coverage["fact_status"] not in {"missing", "ambiguous"}:
        return
    if coverage["synthesis_status"] != "requires_facts":
        _fail(
            V5_FACT_001,
            f"{path}.synthesis_status",
            "missing/ambiguous fact status requires requires_facts synthesis status",
        )
    if facts is None:
        return
    linked = [facts[ref] for ref in aspect["fact_refs"] if ref in facts]
    wanted = "missing" if coverage["fact_status"] == "missing" else "ambiguous"
    if not any(item["state"] == wanted for item in linked):
        _fail(
            V5_FACT_001,
            f"{path}.fact_status",
            "coverage fact blocker is not linked to an owning aspect fact",
        )


def _validate_complete_coverage(
    *,
    aspect: dict[str, Any],
    coverage: dict[str, Any],
    selections: dict[str, dict[str, Any]],
    omissions: dict[str, dict[str, Any]],
    unresolved: dict[str, dict[str, Any]] | None,
    facts: dict[str, dict[str, Any]] | None,
    case_as_of_date: str | None,
    path: str,
) -> None:
    if coverage["support_closure"] != "complete":
        return
    if aspect["scope_status"] in {"generic_limited", "unknown_unplanned"}:
        _fail(
            V5_SCOPE_001,
            f"{path}.support_closure",
            "limited/unplanned scope cannot close complete",
        )
    if coverage["execution_status"] != "complete":
        _fail(
            V5_COMPLETE_001,
            f"{path}.execution_status",
            "complete support requires complete execution",
        )
    if coverage["evidence_status"] != "context_ready":
        _fail(
            V5_COMPLETE_001,
            f"{path}.evidence_status",
            "complete support requires context_ready evidence",
        )
    if coverage["authority_status"] != "resolved":
        _fail(
            V5_COMPLETE_001,
            f"{path}.authority_status",
            "complete support requires resolved authority",
        )
    if coverage["synthesis_status"] == "unsupported":
        _fail(
            V5_COMPLETE_001,
            f"{path}.synthesis_status",
            "unsupported synthesis cannot close support",
        )

    required_omissions = [
        omissions[ref]
        for ref in coverage["omission_refs"]
        if ref in omissions and omissions[ref]["required"]
    ]
    if required_omissions:
        _fail(
            V5_OMISSION_001,
            f"{path}.omission_refs",
            "required omitted work prevents complete support",
        )

    selected = [
        selections[ref]
        for ref in coverage["selection_refs"]
        if ref in selections
    ]
    if not selected:
        _fail(
            V5_COMPLETE_001,
            f"{path}.selection_refs",
            "complete support requires at least one selected evidence record",
        )
    if any(item["context_status"] == "incomplete" for item in selected):
        _fail(
            V5_CONTEXT_001,
            f"{path}.selection_refs",
            "context-incomplete selection cannot close support",
        )

    if case_as_of_date is None:
        if (
            coverage["temporal_status"] != "unassessed"
            or "temporal_unassessed" not in coverage["limitation_codes"]
        ):
            _fail(
                V5_TEMPORAL_001,
                f"{path}.temporal_status",
                "absent caller as_of_date requires unassessed temporal status and temporal_unassessed limitation",
            )
    elif coverage["temporal_status"] != "assessed":
        _fail(
            V5_TEMPORAL_001,
            f"{path}.temporal_status",
            "complete support with caller as_of_date requires assessed temporal status",
        )

    if unresolved is not None:
        for ref in coverage["unresolved_refs"]:
            item = unresolved.get(ref)
            if item is None:
                continue
            if item["category"] in _BLOCKING_UNRESOLVED_CATEGORIES:
                _fail(
                    V5_COMPLETE_001,
                    f"{path}.unresolved_refs",
                    f"blocking unresolved category {item['category']!r} prevents complete support",
                )
            if (
                case_as_of_date is not None
                and item["category"] == "temporal_uncertainty"
            ):
                _fail(
                    V5_TEMPORAL_001,
                    f"{path}.unresolved_refs",
                    "temporal uncertainty prevents complete assessed support",
                )

    _validate_fact_locality(aspect, coverage, facts=facts, path=path)


def validate_research_result(
    plan: dict[str, Any],
    result: dict[str, Any],
    *,
    case_input: dict[str, Any] | None = None,
    authorities: list[dict[str, Any]] | None = None,
    evidence_spans: list[dict[str, Any]] | None = None,
    unresolved: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> None:
    """Validate v5 execution/selection/coverage refs and status semantics."""
    _validate_schema(result, "ResearchResult", INVALID_RESEARCH_RESULT)
    _validate_schema(plan, "ResearchPlan", INVALID_RESEARCH_RESULT)
    if result["plan_ref"] != plan["plan_ref"]:
        _fail(
            INVALID_RESEARCH_RESULT,
            "$.plan_ref",
            "does not resolve to ResearchPlan",
        )

    aspects = _registry(
        plan["aspects"],
        "aspect_ref",
        code=V5_REF_ASPECT_001,
        owner="$.research_plan.aspects",
    )
    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=V5_REF_ASPECT_001,
        owner="$.research_plan.tasks",
    )
    _registry(
        result["trace"],
        "trace_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.trace",
    )
    selections = _registry(
        result["evidence_selections"],
        "selection_ref",
        code=V5_REF_SELECTION_002,
        owner="$.evidence_selections",
    )
    omissions = _registry(
        result["omitted_work"],
        "omission_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.omitted_work",
    )
    _registry(
        result["aspect_coverage"],
        "coverage_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.aspect_coverage",
    )
    coverage_by_aspect: dict[str, dict[str, Any]] = {}
    for index, coverage in enumerate(result["aspect_coverage"]):
        if coverage["aspect_ref"] in coverage_by_aspect:
            _fail(
                V5_REF_COVERAGE_003,
                f"$.aspect_coverage[{index}].aspect_ref",
                f"duplicate coverage owner {coverage['aspect_ref']!r}",
            )
        coverage_by_aspect[coverage["aspect_ref"]] = coverage

    authority_registry = (
        _registry(
            authorities,
            "authority_ref",
            code=V5_REF_SELECTION_002,
            owner="$.authorities",
        )
        if authorities is not None
        else None
    )
    evidence_registry = (
        _registry(
            evidence_spans,
            "evidence_ref",
            code=V5_REF_SELECTION_002,
            owner="$.evidence_spans",
        )
        if evidence_spans is not None
        else None
    )
    unresolved_registry = (
        _registry(
            unresolved,
            "unresolved_ref",
            code=V5_REF_COVERAGE_003,
            owner="$.unresolved",
        )
        if unresolved is not None
        else None
    )
    fact_registry = (
        _registry(
            facts,
            "fact_ref",
            code=V5_FACT_001,
            owner="$.intake_draft.facts",
        )
        if facts is not None
        else None
    )

    result_authority_refs = set(result["authority_refs"])
    if (
        len(result_authority_refs)
        > plan["budgets"]["research"]["max_total_authorities"]
    ):
        _fail(
            INVALID_RESEARCH_RESULT,
            "$.authority_refs",
            "authority count exceeds max_total_authorities",
        )
    if authority_registry is not None:
        _require_refs(
            result["authority_refs"],
            authority_registry,
            code=V5_REF_SELECTION_002,
            path="$.authority_refs",
        )

    query_counts: dict[str, int] = {}
    result_unresolved = set(result["unresolved_refs"])
    for index, step in enumerate(result["trace"]):
        _require_refs(
            [step["task_ref"]],
            tasks,
            code=V5_REF_ASPECT_001,
            path=f"$.trace[{index}].task_ref",
        )
        _require_refs(
            [step["aspect_ref"]],
            aspects,
            code=V5_REF_ASPECT_001,
            path=f"$.trace[{index}].aspect_ref",
        )
        task = tasks[step["task_ref"]]
        if task["aspect_ref"] != step["aspect_ref"]:
            _fail(
                V5_REF_ASPECT_001,
                f"$.trace[{index}].aspect_ref",
                "trace aspect does not match owning task",
            )
        if step["executed_target"] != task["target"]:
            _fail(
                INVALID_RESEARCH_RESULT,
                f"$.trace[{index}].executed_target",
                "executed target does not match task target",
            )
        if step["round"] > plan["budgets"]["research"]["max_rounds"]:
            _fail(
                INVALID_RESEARCH_RESULT,
                f"$.trace[{index}].round",
                "trace round exceeds max_rounds",
            )
        if (
            step["hit_count"]
            > plan["budgets"]["research"]["max_hits_per_query"]
        ):
            _fail(
                INVALID_RESEARCH_RESULT,
                f"$.trace[{index}].hit_count",
                "hit count exceeds max_hits_per_query",
            )
        if task["target"]["kind"] == "query":
            aspect_ref = task["aspect_ref"]
            query_counts[aspect_ref] = query_counts.get(aspect_ref, 0) + 1
            if (
                query_counts[aspect_ref]
                > plan["budgets"]["research"]["max_queries_per_aspect"]
            ):
                _fail(
                    INVALID_RESEARCH_RESULT,
                    f"$.trace[{index}].task_ref",
                    "query count exceeds max_queries_per_aspect",
                )
        for name in ("retrieved_authority_refs", "selected_authority_refs"):
            for ref in step[name]:
                if ref not in result_authority_refs:
                    _fail(
                        V5_REF_SELECTION_002,
                        f"$.trace[{index}].{name}",
                        f"authority ref {ref!r} not admitted by ResearchResult",
                    )
            if authority_registry is not None:
                _require_refs(
                    step[name],
                    authority_registry,
                    code=V5_REF_SELECTION_002,
                    path=f"$.trace[{index}].{name}",
                )
        if evidence_registry is not None:
            _require_refs(
                step["selected_evidence_refs"],
                evidence_registry,
                code=V5_REF_SELECTION_002,
                path=f"$.trace[{index}].selected_evidence_refs",
            )
        if unresolved_registry is not None:
            _require_refs(
                step["unresolved_refs"],
                unresolved_registry,
                code=V5_REF_COVERAGE_003,
                path=f"$.trace[{index}].unresolved_refs",
            )
        elif any(ref not in result_unresolved for ref in step["unresolved_refs"]):
            _fail(
                V5_REF_COVERAGE_003,
                f"$.trace[{index}].unresolved_refs",
                "trace unresolved ref is not admitted by ResearchResult",
            )

    for index, selection in enumerate(result["evidence_selections"]):
        _require_refs(
            [selection["aspect_ref"]],
            aspects,
            code=V5_REF_SELECTION_002,
            path=f"$.evidence_selections[{index}].aspect_ref",
        )
        _require_refs(
            [selection["task_ref"]],
            tasks,
            code=V5_REF_SELECTION_002,
            path=f"$.evidence_selections[{index}].task_ref",
        )
        task = tasks[selection["task_ref"]]
        if task["aspect_ref"] != selection["aspect_ref"]:
            _fail(
                V5_REF_SELECTION_002,
                f"$.evidence_selections[{index}].aspect_ref",
                "selection aspect does not match owning task",
            )
        if selection["authority_ref"] not in result_authority_refs:
            _fail(
                V5_REF_SELECTION_002,
                f"$.evidence_selections[{index}].authority_ref",
                "selected authority is not admitted by ResearchResult",
            )
        if authority_registry is not None:
            _require_refs(
                [selection["authority_ref"]],
                authority_registry,
                code=V5_REF_SELECTION_002,
                path=f"$.evidence_selections[{index}].authority_ref",
            )
        if evidence_registry is not None:
            _require_refs(
                selection["evidence_refs"],
                evidence_registry,
                code=V5_REF_SELECTION_002,
                path=f"$.evidence_selections[{index}].evidence_refs",
            )
            for ref in selection["evidence_refs"]:
                if (
                    evidence_registry[ref]["authority_ref"]
                    != selection["authority_ref"]
                ):
                    _fail(
                        V5_REF_SELECTION_002,
                        f"$.evidence_selections[{index}].evidence_refs",
                        f"evidence {ref!r} belongs to a different authority",
                    )
        if (
            case_input is not None
            and "as_of_date" not in case_input
            and selection["temporal_status"] != "unassessed"
        ):
            _fail(
                V5_TEMPORAL_001,
                f"$.evidence_selections[{index}].temporal_status",
                "selection cannot assess temporal applicability without caller as_of_date",
            )

    for index, omission in enumerate(result["omitted_work"]):
        _require_refs(
            [omission["aspect_ref"]],
            aspects,
            code=V5_REF_COVERAGE_003,
            path=f"$.omitted_work[{index}].aspect_ref",
        )
        if "task_ref" in omission:
            _require_refs(
                [omission["task_ref"]],
                tasks,
                code=V5_REF_COVERAGE_003,
                path=f"$.omitted_work[{index}].task_ref",
            )
            if (
                tasks[omission["task_ref"]]["aspect_ref"]
                != omission["aspect_ref"]
            ):
                _fail(
                    V5_REF_COVERAGE_003,
                    f"$.omitted_work[{index}].task_ref",
                    "omitted task belongs to a different aspect",
                )
        if (
            omission["reason"] == "context_unavailable"
            and omission["class"] != "support"
        ):
            _fail(
                V5_OMISSION_001,
                f"$.omitted_work[{index}].class",
                "context_unavailable is support omitted work",
            )
        if (
            omission["reason"] in {"not_planned", "unsupported_scope"}
            and omission["class"] != "research"
        ):
            _fail(
                V5_OMISSION_001,
                f"$.omitted_work[{index}].class",
                "scope/not-planned omission is research work",
            )
        if (
            omission["reason"] == "blocked_by_facts"
            and fact_registry is not None
        ):
            aspect = aspects[omission["aspect_ref"]]
            linked = [
                fact_registry[ref]
                for ref in aspect["fact_refs"]
                if ref in fact_registry
            ]
            if not any(
                item["state"] in {"missing", "ambiguous"}
                for item in linked
            ):
                _fail(
                    V5_FACT_001,
                    f"$.omitted_work[{index}].reason",
                    "blocked_by_facts is not linked to a missing/ambiguous aspect fact",
                )

    selected_evidence_by_aspect: dict[str, set[str]] = {}
    for selection in selections.values():
        selected_evidence_by_aspect.setdefault(
            selection["aspect_ref"], set()
        ).update(selection["evidence_refs"])
    support_budget = plan["budgets"]["support"]
    for aspect_ref, refs in selected_evidence_by_aspect.items():
        if len(refs) > support_budget["max_selected_evidence_per_aspect"]:
            _fail(
                INVALID_RESEARCH_RESULT,
                "$.evidence_selections",
                f"selected evidence for {aspect_ref!r} exceeds max_selected_evidence_per_aspect",
            )
    all_selected_evidence = (
        set().union(*selected_evidence_by_aspect.values())
        if selected_evidence_by_aspect
        else set()
    )
    if len(all_selected_evidence) > support_budget["max_total_evidence_spans"]:
        _fail(
            INVALID_RESEARCH_RESULT,
            "$.evidence_selections",
            "selected evidence exceeds max_total_evidence_spans",
        )

    # ResearchPlan is the platform-owned carrier of caller temporal scope.
    # When CaseInput is available validate_research_plan has already proven that
    # the plan preserved it exactly; standalone result validation can therefore
    # use the plan without inventing a clock/default.
    case_as_of_date = plan.get("as_of_date")
    if unresolved_registry is not None:
        _require_refs(
            result["unresolved_refs"],
            unresolved_registry,
            code=V5_REF_COVERAGE_003,
            path="$.unresolved_refs",
        )

    for index, coverage in enumerate(result["aspect_coverage"]):
        path = f"$.aspect_coverage[{index}]"
        _require_refs(
            [coverage["aspect_ref"]],
            aspects,
            code=V5_REF_COVERAGE_003,
            path=f"{path}.aspect_ref",
        )
        aspect = aspects[coverage["aspect_ref"]]
        _require_refs(
            coverage["task_refs"],
            tasks,
            code=V5_REF_COVERAGE_003,
            path=f"{path}.task_refs",
        )
        _require_refs(
            coverage["selection_refs"],
            selections,
            code=V5_REF_COVERAGE_003,
            path=f"{path}.selection_refs",
        )
        _require_refs(
            coverage["omission_refs"],
            omissions,
            code=V5_REF_COVERAGE_003,
            path=f"{path}.omission_refs",
        )
        for ref in coverage["task_refs"]:
            if tasks[ref]["aspect_ref"] != coverage["aspect_ref"]:
                _fail(
                    V5_REF_COVERAGE_003,
                    f"{path}.task_refs",
                    f"task {ref!r} belongs to a different aspect",
                )
        for ref in coverage["selection_refs"]:
            if selections[ref]["aspect_ref"] != coverage["aspect_ref"]:
                _fail(
                    V5_REF_COVERAGE_003,
                    f"{path}.selection_refs",
                    f"selection {ref!r} belongs to a different aspect",
                )
        for ref in coverage["omission_refs"]:
            if omissions[ref]["aspect_ref"] != coverage["aspect_ref"]:
                _fail(
                    V5_REF_COVERAGE_003,
                    f"{path}.omission_refs",
                    f"omission {ref!r} belongs to a different aspect",
                )
        if unresolved_registry is not None:
            _require_refs(
                coverage["unresolved_refs"],
                unresolved_registry,
                code=V5_REF_COVERAGE_003,
                path=f"{path}.unresolved_refs",
            )
        elif any(
            ref not in result_unresolved
            for ref in coverage["unresolved_refs"]
        ):
            _fail(
                V5_REF_COVERAGE_003,
                f"{path}.unresolved_refs",
                "coverage unresolved ref is not admitted by ResearchResult",
            )

        _validate_limitation_codes(aspect, coverage, path=path)
        _validate_fact_locality(
            aspect,
            coverage,
            facts=fact_registry,
            path=path,
        )
        _validate_complete_coverage(
            aspect=aspect,
            coverage=coverage,
            selections=selections,
            omissions=omissions,
            unresolved=unresolved_registry,
            facts=fact_registry,
            case_as_of_date=case_as_of_date,
            path=path,
        )

    _validate_research_context(
        result["research_context"],
        plan,
        path="$.research_context",
    )

    if result["status"] == "complete":
        for aspect in aspects.values():
            if not aspect["required"]:
                continue
            if aspect["scope_status"] in {
                "generic_limited",
                "unknown_unplanned",
            }:
                _fail(
                    V5_SCOPE_001,
                    "$.status",
                    f"required limited-scope aspect prevents complete result: {aspect['aspect_ref']!r}",
                )
            coverage = coverage_by_aspect.get(aspect["aspect_ref"])
            if (
                coverage is None
                or coverage["support_closure"] != "complete"
            ):
                _fail(
                    V5_COMPLETE_001,
                    "$.status",
                    f"required aspect lacks complete support closure: {aspect['aspect_ref']!r}",
                )
        if any(item["required"] for item in omissions.values()):
            _fail(
                V5_OMISSION_001,
                "$.status",
                "required omitted work prevents complete result",
            )
        if unresolved_registry is not None and any(
            item["category"] == "integrity_failure"
            for item in unresolved_registry.values()
        ):
            _fail(
                V5_COMPLETE_001,
                "$.status",
                "integrity failure prevents complete result",
            )


def _validate_common_bundle_graph(bundle: dict[str, Any]) -> None:
    code = INVALID_LEGAL_RESEARCH_BUNDLE
    facts = _registry(
        bundle["intake_draft"]["facts"],
        "fact_ref",
        code=code,
        owner="$.intake_draft.facts",
    )
    questions = _registry(
        bundle["intake_draft"]["questions"],
        "question_ref",
        code=code,
        owner="$.intake_draft.questions",
    )
    sources = _registry(
        bundle["sources"],
        "source_ref",
        code=code,
        owner="$.sources",
    )
    authorities = _registry(
        bundle["authorities"],
        "authority_ref",
        code=code,
        owner="$.authorities",
    )
    evidence = _registry(
        bundle["evidence_spans"],
        "evidence_ref",
        code=code,
        owner="$.evidence_spans",
    )
    _registry(
        bundle["evidence_spans"],
        "span_ref",
        code=code,
        owner="$.evidence_spans",
    )
    relationships = _registry(
        bundle["normative_relationships"],
        "relationship_ref",
        code=code,
        owner="$.normative_relationships",
    )
    rules = _registry(
        bundle["rule_fragments"],
        "rule_ref",
        code=code,
        owner="$.rule_fragments",
    )
    _registry(
        bundle["deterministic_evaluations"],
        "evaluation_ref",
        code=code,
        owner="$.deterministic_evaluations",
    )
    calculations = _registry(
        bundle["calculation_traces"],
        "calculation_ref",
        code=code,
        owner="$.calculation_traces",
    )

    for index, authority in enumerate(bundle["authorities"]):
        _require_refs(
            authority["source_refs"],
            sources,
            code=code,
            path=f"$.authorities[{index}].source_refs",
        )
        _require_refs(
            authority["evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].evidence_refs",
        )
        _require_refs(
            authority["relationship_refs"],
            relationships,
            code=code,
            path=f"$.authorities[{index}].relationship_refs",
        )
        _require_refs(
            authority["temporal_state"]["basis_evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].temporal_state.basis_evidence_refs",
        )
        _require_refs(
            authority["publication_metadata"]["evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].publication_metadata.evidence_refs",
        )

    for index, item in enumerate(bundle["evidence_spans"]):
        _require_refs(
            [item["source_ref"]],
            sources,
            code=code,
            path=f"$.evidence_spans[{index}].source_ref",
        )
        _require_refs(
            [item["authority_ref"]],
            authorities,
            code=code,
            path=f"$.evidence_spans[{index}].authority_ref",
        )
        authority = authorities[item["authority_ref"]]
        if item["document_ref"] != authority["document_ref"]:
            _fail(
                code,
                f"$.evidence_spans[{index}].document_ref",
                "does not match owning CanonicalAuthority document_ref",
            )
        if (
            "provision_ref" in item
            and item["provision_ref"] not in authority["provision_refs"]
        ):
            _fail(
                code,
                f"$.evidence_spans[{index}].provision_ref",
                "does not belong to owning CanonicalAuthority",
            )

    for index, relationship in enumerate(bundle["normative_relationships"]):
        _require_refs(
            [
                relationship["source_authority_ref"],
                relationship["target_authority_ref"],
            ],
            authorities,
            code=code,
            path=f"$.normative_relationships[{index}]",
        )
        _require_refs(
            relationship["evidence_refs"],
            evidence,
            code=code,
            path=f"$.normative_relationships[{index}].evidence_refs",
        )

    for index, fragment in enumerate(bundle["rule_fragments"]):
        _require_refs(
            fragment["authority_refs"],
            authorities,
            code=code,
            path=f"$.rule_fragments[{index}].authority_refs",
        )
        _require_refs(
            fragment["evidence_refs"],
            evidence,
            code=code,
            path=f"$.rule_fragments[{index}].evidence_refs",
        )
        _require_refs(
            fragment.get("relationship_refs", []),
            relationships,
            code=code,
            path=f"$.rule_fragments[{index}].relationship_refs",
        )
        _validate_registered_rule_fragment(
            fragment,
            code=code,
            path=f"$.rule_fragments[{index}]",
        )

    for index, evaluation in enumerate(bundle["deterministic_evaluations"]):
        _require_refs(
            evaluation["fact_refs"],
            facts,
            code=code,
            path=f"$.deterministic_evaluations[{index}].fact_refs",
        )
        _require_refs(
            evaluation["question_refs"],
            questions,
            code=code,
            path=f"$.deterministic_evaluations[{index}].question_refs",
        )
        _require_refs(
            evaluation["rule_refs"],
            rules,
            code=code,
            path=f"$.deterministic_evaluations[{index}].rule_refs",
        )
        _require_refs(
            evaluation["evidence_refs"],
            evidence,
            code=code,
            path=f"$.deterministic_evaluations[{index}].evidence_refs",
        )
        _require_refs(
            evaluation["calculation_trace_refs"],
            calculations,
            code=code,
            path=f"$.deterministic_evaluations[{index}].calculation_trace_refs",
        )

    for index, calculation in enumerate(bundle["calculation_traces"]):
        for input_index, calculation_input in enumerate(calculation["inputs"]):
            if "source_fact_ref" in calculation_input:
                _require_refs(
                    [calculation_input["source_fact_ref"]],
                    facts,
                    code=code,
                    path=(
                        f"$.calculation_traces[{index}].inputs"
                        f"[{input_index}].source_fact_ref"
                    ),
                )
            if "source_rule_ref" in calculation_input:
                _require_refs(
                    [calculation_input["source_rule_ref"]],
                    rules,
                    code=code,
                    path=(
                        f"$.calculation_traces[{index}].inputs"
                        f"[{input_index}].source_rule_ref"
                    ),
                )
        _require_refs(
            calculation["rule_refs"],
            rules,
            code=code,
            path=f"$.calculation_traces[{index}].rule_refs",
        )
        _require_refs(
            calculation["evidence_refs"],
            evidence,
            code=code,
            path=f"$.calculation_traces[{index}].evidence_refs",
        )


def validate_legal_research_bundle(bundle: dict[str, Any]) -> None:
    """Validate one complete v5 bundle without mutating or activating runtime state."""
    _validate_schema(
        bundle,
        "LegalResearchBundle",
        INVALID_LEGAL_RESEARCH_BUNDLE,
    )

    case_input = bundle["case_input"]
    intake = bundle["intake_draft"]
    plan = bundle["research_plan"]
    result = bundle["research_result"]

    validate_intake_draft(case_input, intake)
    validate_research_plan(intake, plan, case_input=case_input)
    validate_research_result(
        plan,
        result,
        case_input=case_input,
        authorities=bundle["authorities"],
        evidence_spans=bundle["evidence_spans"],
        unresolved=bundle["unresolved"],
        facts=intake["facts"],
    )

    _validate_common_bundle_graph(bundle)

    aspects = _registry(
        plan["aspects"],
        "aspect_ref",
        code=V5_REF_ASPECT_001,
        owner="$.research_plan.aspects",
    )
    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=V5_REF_ASPECT_001,
        owner="$.research_plan.tasks",
    )
    selections = _registry(
        result["evidence_selections"],
        "selection_ref",
        code=V5_REF_SELECTION_002,
        owner="$.research_result.evidence_selections",
    )
    omissions = _registry(
        result["omitted_work"],
        "omission_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.research_result.omitted_work",
    )
    coverages = _registry(
        result["aspect_coverage"],
        "coverage_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.research_result.aspect_coverage",
    )
    unresolved = _registry(
        bundle["unresolved"],
        "unresolved_ref",
        code=V5_REF_COVERAGE_003,
        owner="$.unresolved",
    )
    facts = _registry(
        intake["facts"],
        "fact_ref",
        code=V5_FACT_001,
        owner="$.intake_draft.facts",
    )
    questions = _registry(
        intake["questions"],
        "question_ref",
        code=V5_REF_ASPECT_001,
        owner="$.intake_draft.questions",
    )
    authorities = _registry(
        bundle["authorities"],
        "authority_ref",
        code=V5_REF_SELECTION_002,
        owner="$.authorities",
    )
    evidence = _registry(
        bundle["evidence_spans"],
        "evidence_ref",
        code=V5_REF_SELECTION_002,
        owner="$.evidence_spans",
    )
    rules = _registry(
        bundle["rule_fragments"],
        "rule_ref",
        code=INVALID_LEGAL_RESEARCH_BUNDLE,
        owner="$.rule_fragments",
    )
    evaluations = _registry(
        bundle["deterministic_evaluations"],
        "evaluation_ref",
        code=INVALID_LEGAL_RESEARCH_BUNDLE,
        owner="$.deterministic_evaluations",
    )
    calculations = _registry(
        bundle["calculation_traces"],
        "calculation_ref",
        code=INVALID_LEGAL_RESEARCH_BUNDLE,
        owner="$.calculation_traces",
    )

    for index, evaluation in enumerate(bundle["deterministic_evaluations"]):
        _require_refs(
            evaluation["unresolved_refs"],
            unresolved,
            code=INVALID_LEGAL_RESEARCH_BUNDLE,
            path=f"$.deterministic_evaluations[{index}].unresolved_refs",
        )

    for index, item in enumerate(bundle["unresolved"]):
        references = (
            ("related_fact_refs", facts, V5_FACT_001),
            ("related_question_refs", questions, V5_REF_ASPECT_001),
            ("related_authority_refs", authorities, V5_REF_SELECTION_002),
            ("related_evidence_refs", evidence, V5_REF_SELECTION_002),
            ("related_rule_refs", rules, INVALID_LEGAL_RESEARCH_BUNDLE),
            (
                "related_evaluation_refs",
                evaluations,
                INVALID_LEGAL_RESEARCH_BUNDLE,
            ),
            (
                "related_calculation_refs",
                calculations,
                INVALID_LEGAL_RESEARCH_BUNDLE,
            ),
            ("related_aspect_refs", aspects, V5_REF_COVERAGE_003),
            ("related_task_refs", tasks, V5_REF_COVERAGE_003),
            ("related_selection_refs", selections, V5_REF_COVERAGE_003),
            ("related_coverage_refs", coverages, V5_REF_COVERAGE_003),
            ("related_omission_refs", omissions, V5_REF_COVERAGE_003),
        )
        for name, registry, error_code in references:
            _require_refs(
                item.get(name, []),
                registry,
                code=error_code,
                path=f"$.unresolved[{index}].{name}",
            )

    if bundle["status"] == "complete" and result["status"] != "complete":
        _fail(
            V5_COMPLETE_001,
            "$.status",
            "complete bundle requires complete ResearchResult",
        )

    evaluations_by_question = {
        question_ref
        for evaluation in bundle["deterministic_evaluations"]
        for question_ref in evaluation["question_refs"]
    }
    for index, coverage in enumerate(result["aspect_coverage"]):
        if coverage["synthesis_status"] != "deterministic_completed":
            continue
        aspect = aspects[coverage["aspect_ref"]]
        if aspect["question_ref"] not in evaluations_by_question:
            _fail(
                V5_EVALUATOR_001,
                f"$.research_result.aspect_coverage[{index}].synthesis_status",
                "deterministic_completed requires a matching deterministic evaluation",
            )


def validate_research_continuation_request(
    request: dict[str, Any],
    *,
    bundle: dict[str, Any] | None = None,
) -> None:
    """Validate non-canonical consumer continuation metadata and known refs."""
    _validate_schema(
        request,
        "ResearchContinuationRequest",
        INVALID_RESEARCH_CONTINUATION_REQUEST,
    )
    if bundle is None:
        return
    validate_legal_research_bundle(bundle)
    if request["bundle_ref"] != bundle["bundle_ref"]:
        _fail(
            V5_CONSUMER_001,
            "$.bundle_ref",
            "continuation request targets a different bundle",
        )

    questions = _registry(
        bundle["intake_draft"]["questions"],
        "question_ref",
        code=V5_CONSUMER_001,
        owner="$.bundle.intake_draft.questions",
    )
    aspects = _registry(
        bundle["research_plan"]["aspects"],
        "aspect_ref",
        code=V5_CONSUMER_001,
        owner="$.bundle.research_plan.aspects",
    )
    authorities = _registry(
        bundle["authorities"],
        "authority_ref",
        code=V5_CONSUMER_001,
        owner="$.bundle.authorities",
    )
    evidence = _registry(
        bundle["evidence_spans"],
        "evidence_ref",
        code=V5_CONSUMER_001,
        owner="$.bundle.evidence_spans",
    )
    _require_refs(
        [request["question_ref"]],
        questions,
        code=V5_CONSUMER_001,
        path="$.question_ref",
    )
    if "aspect_ref" in request:
        _require_refs(
            [request["aspect_ref"]],
            aspects,
            code=V5_CONSUMER_001,
            path="$.aspect_ref",
        )
        if (
            aspects[request["aspect_ref"]]["question_ref"]
            != request["question_ref"]
        ):
            _fail(
                V5_CONSUMER_001,
                "$.aspect_ref",
                "continuation aspect belongs to a different question",
            )
    _require_refs(
        request["known_authority_refs"],
        authorities,
        code=V5_CONSUMER_001,
        path="$.known_authority_refs",
    )
    _require_refs(
        request["known_evidence_refs"],
        evidence,
        code=V5_CONSUMER_001,
        path="$.known_evidence_refs",
    )


def validated_copy(value: dict[str, Any]) -> dict[str, Any]:
    """Return a defensive copy after v5 shape validation without mutation."""
    validate_contract_object(value)
    return deepcopy(value)
