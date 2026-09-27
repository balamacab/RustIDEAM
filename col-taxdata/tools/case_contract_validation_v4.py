from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Callable

from case_contract_validation import (
    CaseContractError,
    validate_schema_object,
)


CONTRACT_VERSION = "4.0.0"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "application"
    / "schemas"
    / "case-contracts-v4.schema.json"
)

INVALID_CASE_INPUT = "INVALID_CASE_INPUT"
INVALID_INTAKE_DRAFT = "INVALID_INTAKE_DRAFT"
INVALID_RESEARCH_PLAN = "INVALID_RESEARCH_PLAN"
INVALID_RESEARCH_RESULT = "INVALID_RESEARCH_RESULT"
INVALID_LEGAL_RESEARCH_BUNDLE = "INVALID_LEGAL_RESEARCH_BUNDLE"

# SearchHint is model-owned vocabulary. Typed application references are not
# vocabulary and would let model output select platform-owned identities.
_TYPED_REF_IN_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9._-])"
    r"(?:intake|fact|question|hint|plan|task|research|trace|authority|source|"
    r"document|provision|evidence|span|relationship|rule|evaluation|calculation|"
    r"unresolved|provenance|bundle):[A-Za-z0-9._-]+"
    r"(?:$|[^A-Za-z0-9._-])"
)

# Intake refs (fact/question/hint/intake) are legitimate model-owned graph keys.
# Platform-owned namespaces are not legitimate content in model-authored labels,
# normalized values, questions, or search vocabulary.
_PLATFORM_REF_IN_MODEL_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9._-])"
    r"(?:plan|task|research|trace|authority|source|document|provision|evidence|"
    r"span|relationship|rule|evaluation|calculation|unresolved|provenance|bundle)"
    r":[A-Za-z0-9._-]+(?:$|[^A-Za-z0-9._-])"
)

_FINGERPRINT_OPTIONAL_FIELDS = frozenset(
    {
        "corpus_snapshot_sha256",
        "schema_migration_fingerprint",
        "retrieval_config_sha256",
        "as_of_date",
    }
)

_KIND_TO_DEFINITION = {
    "case_input": "CaseInput",
    "intake_fact": "IntakeFact",
    "case_question": "CaseQuestion",
    "search_hint": "SearchHint",
    "intake_draft": "IntakeDraft",
    "research_task": "ResearchTask",
    "research_plan": "ResearchPlan",
    "research_trace_step": "ResearchTraceStep",
    "research_result": "ResearchResult",
    "official_source": "OfficialSource",
    "canonical_authority": "CanonicalAuthority",
    "evidence_span": "EvidenceSpan",
    "normative_relationship": "NormativeRelationship",
    "rule_fragment": "RuleFragment",
    "deterministic_evaluation": "DeterministicEvaluation",
    "calculation_trace": "CalculationTrace",
    "unresolved_item": "UnresolvedItem",
    "legal_research_bundle": "LegalResearchBundle",
}

# #138 owns the first concrete RuleFragment schemas. The registry intentionally
# starts empty so unknown rule families cannot pass semantic validation merely
# because their generic transport envelope is structurally valid.
_RULE_FRAGMENT_VALIDATORS: dict[
    tuple[str, str],
    Callable[[dict[str, Any]], None],
] = {}


def _fail(code: str, path: str, detail: str) -> None:
    raise CaseContractError(code, f"{path}: {detail}")


def _validate_schema(
    value: dict[str, Any],
    definition: str,
    code: str,
) -> None:
    validate_schema_object(
        value,
        definition,
        code,
        schema_path=SCHEMA_PATH,
    )


def validate_contract_object(value: dict[str, Any]) -> None:
    """Validate the serialized shape of one named v4 contract primitive."""
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
            f"unsupported v4 contract kind {kind!r}",
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


def _singleton_registry(
    item: dict[str, Any],
    key: str,
) -> dict[str, dict[str, Any]]:
    return {item[key]: item}


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


def _require_optional_field_preserved(
    source: dict[str, Any],
    target: dict[str, Any],
    name: str,
    *,
    code: str,
) -> None:
    source_has = name in source
    target_has = name in target
    if source_has != target_has:
        _fail(
            code,
            f"$.{name}",
            "client field presence/absence was not preserved",
        )
    if source_has and target[name] != source[name]:
        _fail(code, f"$.{name}", "client field value was modified")


def validate_case_input(case_input: dict[str, Any]) -> None:
    """Validate a v4 caller-owned CaseInput."""
    _validate_schema(case_input, "CaseInput", INVALID_CASE_INPUT)


def validate_intake_draft(
    case_input: dict[str, Any],
    draft: dict[str, Any],
) -> None:
    """Validate the complete model-owned v4 intake boundary.

    This function deliberately validates only intake structure. It does not
    accept platform research/evidence/authority objects and never upgrades
    model prose into a legal conclusion.
    """
    validate_case_input(case_input)
    _validate_schema(draft, "IntakeDraft", INVALID_INTAKE_DRAFT)

    if draft["problem_text"] != case_input["problem_text"]:
        _fail(
            INVALID_INTAKE_DRAFT,
            "$.problem_text",
            "client problem_text was modified",
        )

    for name in ("as_of_date", "client_reference", "caller_metadata"):
        _require_optional_field_preserved(
            case_input,
            draft,
            name,
            code=INVALID_INTAKE_DRAFT,
        )

    facts = _registry(
        draft["facts"],
        "fact_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.facts",
    )
    questions = _registry(
        draft["questions"],
        "question_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.questions",
    )
    hints = _registry(
        draft["search_hints"],
        "hint_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.search_hints",
    )
    del hints

    for index, fact in enumerate(draft["facts"]):
        if fact["state"] in {"user_provided", "llm_normalized"}:
            quote = fact["source_quote"]
            if quote not in case_input["problem_text"]:
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.facts[{index}].source_quote",
                    "source quote is not present verbatim in CaseInput.problem_text",
                )
        for name in ("label", "value", "needed_information"):
            value = fact.get(name)
            if isinstance(value, str) and _PLATFORM_REF_IN_MODEL_TEXT.search(value):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.facts[{index}].{name}",
                    "model-authored intake content attempted to inject a platform-owned identifier",
                )

    for index, question in enumerate(draft["questions"]):
        if _PLATFORM_REF_IN_MODEL_TEXT.search(question["text"]):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.questions[{index}].text",
                "model-authored question attempted to inject a platform-owned identifier",
            )
        _require_refs(
            question.get("depends_on_fact_refs", []),
            facts,
            code=INVALID_INTAKE_DRAFT,
            path=f"$.questions[{index}].depends_on_fact_refs",
        )

    for index, hint in enumerate(draft["search_hints"]):
        _require_refs(
            hint["related_question_refs"],
            questions,
            code=INVALID_INTAKE_DRAFT,
            path=f"$.search_hints[{index}].related_question_refs",
        )
        for term_index, term in enumerate(hint["terms"]):
            if _TYPED_REF_IN_TEXT.search(term):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.search_hints[{index}].terms[{term_index}]",
                    "model search vocabulary attempted to inject a typed application identifier",
                )


def _validate_case_as_of_date(
    case_input: dict[str, Any],
    plan: dict[str, Any],
    *,
    code: str,
) -> None:
    """Prevent a platform plan from inventing or losing caller as-of context."""
    if "as_of_date" in case_input:
        if plan.get("as_of_date") != case_input["as_of_date"]:
            _fail(code, "$.as_of_date", "plan does not preserve CaseInput.as_of_date")
    elif "as_of_date" in plan:
        _fail(code, "$.as_of_date", "plan invented an absent CaseInput.as_of_date")


def validate_research_plan(
    intake_draft: dict[str, Any],
    plan: dict[str, Any],
    *,
    case_input: dict[str, Any] | None = None,
) -> None:
    """Validate platform-owned v4 research intent and its typed intake graph."""
    _validate_schema(plan, "ResearchPlan", INVALID_RESEARCH_PLAN)

    if plan["intake_ref"] != intake_draft["intake_ref"]:
        _fail(
            INVALID_RESEARCH_PLAN,
            "$.intake_ref",
            "does not resolve to the accepted IntakeDraft",
        )
    if case_input is not None:
        _validate_case_as_of_date(
            case_input,
            plan,
            code=INVALID_RESEARCH_PLAN,
        )

    facts = _registry(
        intake_draft["facts"],
        "fact_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.facts",
    )
    questions = _registry(
        intake_draft["questions"],
        "question_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.questions",
    )
    hints = _registry(
        intake_draft["search_hints"],
        "hint_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.search_hints",
    )
    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.tasks",
    )
    del tasks

    platform_required_questions: set[str] = set()
    for index, task in enumerate(plan["tasks"]):
        _require_refs(
            [task["question_ref"]],
            questions,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].question_ref",
        )
        _require_refs(
            task.get("generated_from_fact_refs", []),
            facts,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].generated_from_fact_refs",
        )
        _require_refs(
            task.get("hint_refs", []),
            hints,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].hint_refs",
        )
        if task["origin"] == "platform_required":
            platform_required_questions.add(task["question_ref"])

    for question in intake_draft["questions"]:
        if (
            question["category"] == "legal"
            and question["status"] == "open"
            and question["question_ref"] not in platform_required_questions
        ):
            _fail(
                INVALID_RESEARCH_PLAN,
                "$.tasks",
                (
                    "every open legal question requires at least one "
                    f"platform_required task; missing {question['question_ref']!r}"
                ),
            )


def _validate_research_context(
    context: dict[str, Any],
    plan: dict[str, Any],
    *,
    code: str,
    path: str,
) -> None:
    unavailable = set(context["unavailable_fields"])
    for name in _FINGERPRINT_OPTIONAL_FIELDS:
        is_null = context[name] is None
        is_unavailable = name in unavailable
        if is_null != is_unavailable:
            _fail(
                code,
                f"{path}.{name}",
                "null availability must match unavailable_fields exactly",
            )

    if context["planner_version"] != plan["planner_version"]:
        _fail(
            code,
            f"{path}.planner_version",
            "does not match ResearchPlan.planner_version",
        )

    expected_as_of = plan.get("as_of_date")
    if context["as_of_date"] != expected_as_of:
        _fail(
            code,
            f"{path}.as_of_date",
            "does not match ResearchPlan.as_of_date",
        )


def validate_research_result(
    plan: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Validate one platform-owned research execution record."""
    _validate_schema(result, "ResearchResult", INVALID_RESEARCH_RESULT)

    if result["plan_ref"] != plan["plan_ref"]:
        _fail(
            INVALID_RESEARCH_RESULT,
            "$.plan_ref",
            "does not resolve to the ResearchPlan",
        )

    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=INVALID_RESEARCH_RESULT,
        owner="$.research_plan.tasks",
    )
    _registry(
        result["trace"],
        "trace_ref",
        code=INVALID_RESEARCH_RESULT,
        owner="$.trace",
    )
    for index, step in enumerate(result["trace"]):
        _require_refs(
            [step["task_ref"]],
            tasks,
            code=INVALID_RESEARCH_RESULT,
            path=f"$.trace[{index}].task_ref",
        )

    _validate_research_context(
        result["research_context"],
        plan,
        code=INVALID_RESEARCH_RESULT,
        path="$.research_context",
    )


def _validate_registered_rule_fragment(
    fragment: dict[str, Any],
    *,
    code: str,
    path: str,
) -> None:
    key = (fragment["rule_type"], fragment["rule_schema_version"])
    validator = _RULE_FRAGMENT_VALIDATORS.get(key)
    if validator is None:
        _fail(
            code,
            path,
            (
                "unregistered RuleFragment type/schema version "
                f"{key[0]!r}/{key[1]!r}; unknown rule semantics fail closed"
            ),
        )
    try:
        validator(fragment["structured_data"])
    except CaseContractError:
        raise
    except (TypeError, ValueError) as exc:
        _fail(code, path, f"registered RuleFragment validation failed: {exc}")


def _validate_bundle_graph(bundle: dict[str, Any]) -> None:
    code = INVALID_LEGAL_RESEARCH_BUNDLE

    intake = bundle["intake_draft"]
    plan = bundle["research_plan"]
    result = bundle["research_result"]

    facts = _registry(intake["facts"], "fact_ref", code=code, owner="$.intake_draft.facts")
    questions = _registry(
        intake["questions"],
        "question_ref",
        code=code,
        owner="$.intake_draft.questions",
    )
    hints = _registry(
        intake["search_hints"],
        "hint_ref",
        code=code,
        owner="$.intake_draft.search_hints",
    )
    tasks = _registry(plan["tasks"], "task_ref", code=code, owner="$.research_plan.tasks")
    traces = _registry(
        result["trace"],
        "trace_ref",
        code=code,
        owner="$.research_result.trace",
    )
    del hints, traces

    sources = _registry(bundle["sources"], "source_ref", code=code, owner="$.sources")
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
    span_refs = _registry(
        bundle["evidence_spans"],
        "span_ref",
        code=code,
        owner="$.evidence_spans",
    )
    del span_refs
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
    evaluations = _registry(
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
    unresolved = _registry(
        bundle["unresolved"],
        "unresolved_ref",
        code=code,
        owner="$.unresolved",
    )

    for index, step in enumerate(result["trace"]):
        _require_refs(
            [step["task_ref"]],
            tasks,
            code=code,
            path=f"$.research_result.trace[{index}].task_ref",
        )
        _require_refs(
            step["authority_refs"],
            authorities,
            code=code,
            path=f"$.research_result.trace[{index}].authority_refs",
        )
        _require_refs(
            step["unresolved_refs"],
            unresolved,
            code=code,
            path=f"$.research_result.trace[{index}].unresolved_refs",
        )

    _require_refs(
        result["authority_refs"],
        authorities,
        code=code,
        path="$.research_result.authority_refs",
    )
    _require_refs(
        result["unresolved_refs"],
        unresolved,
        code=code,
        path="$.research_result.unresolved_refs",
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
                "does not match the owning CanonicalAuthority document_ref",
            )
        if (
            "provision_ref" in item
            and item["provision_ref"] not in authority["provision_refs"]
        ):
            _fail(
                code,
                f"$.evidence_spans[{index}].provision_ref",
                "does not belong to the owning CanonicalAuthority",
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
        _require_refs(
            evaluation["unresolved_refs"],
            unresolved,
            code=code,
            path=f"$.deterministic_evaluations[{index}].unresolved_refs",
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

    for index, item in enumerate(bundle["unresolved"]):
        references = (
            ("related_fact_refs", facts),
            ("related_question_refs", questions),
            ("related_authority_refs", authorities),
            ("related_evidence_refs", evidence),
            ("related_rule_refs", rules),
            ("related_evaluation_refs", evaluations),
            ("related_calculation_refs", calculations),
        )
        for name, registry in references:
            _require_refs(
                item.get(name, []),
                registry,
                code=code,
                path=f"$.unresolved[{index}].{name}",
            )


def validate_legal_research_bundle(bundle: dict[str, Any]) -> None:
    """Validate the complete v4 platform-owned integration object.

    Validation is read-only. It checks serialized shape, the accepted intake
    fidelity boundary, research ownership, fingerprint availability, and every
    cross-object typed reference required by the v4 contract.
    """
    _validate_schema(
        bundle,
        "LegalResearchBundle",
        INVALID_LEGAL_RESEARCH_BUNDLE,
    )

    case_input = bundle["case_input"]
    intake = bundle["intake_draft"]
    plan = bundle["research_plan"]
    result = bundle["research_result"]

    try:
        validate_intake_draft(case_input, intake)
        validate_research_plan(intake, plan, case_input=case_input)
        validate_research_result(plan, result)
    except CaseContractError as exc:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$",
            f"embedded v4 contract invalid: {exc.code}: {exc.detail}",
        )

    _validate_bundle_graph(bundle)


def validated_copy(value: dict[str, Any]) -> dict[str, Any]:
    """Return a defensive copy after shape validation without mutating input."""
    validate_contract_object(value)
    return deepcopy(value)
