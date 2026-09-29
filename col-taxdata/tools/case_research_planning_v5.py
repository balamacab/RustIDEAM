from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import unicodedata

from case_contract_validation_v5 import (
    CONTRACT_VERSION,
    validate_intake_draft,
    validate_research_plan,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "config" / "case-research-profiles-v5.json"

PLANNER_VERSION = "v5-planner-1"
FAIRNESS_POLICY = {
    "policy": "required_aspects_round_robin",
    "max_consecutive_optional_tasks": 0,
}
DEFAULT_RESEARCH_BUDGET = {
    "max_rounds": 3,
    "max_tasks": 32,
    "max_queries_per_aspect": 3,
    "max_hits_per_query": 24,
    "max_reference_depth": 2,
    "max_total_authorities": 64,
}
DEFAULT_SUPPORT_BUDGET = {
    "max_selected_evidence_per_aspect": 8,
    "max_context_expansions_per_aspect": 4,
    "max_relationships_per_aspect": 4,
    "max_total_evidence_spans": 128,
}

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_FORBIDDEN_PROFILE_REF_RE = re.compile(
    r"(?i)(?:document|provision|authority|evidence|relationship):[A-Za-z0-9._-]+"
)
_FORBIDDEN_NORM_SHORTCUT_RE = re.compile(
    r"(?i)\b(?:ley|decreto|resoluci[oó]n|circular)\s+\d+(?:\s+de\s+\d{4})?\b"
)


class ResearchPlanningError(RuntimeError):
    """The platform cannot create a contract-valid deterministic v5 plan."""


@dataclass(frozen=True)
class PlannerProfileSet:
    """Validated planner configuration plus its canonical policy identity."""

    version: str
    sha256: str
    payload: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_ref(namespace: str, *parts: object) -> str:
    material = _compact_json(parts).encode("utf-8")
    return f"{namespace}:{hashlib.sha256(material).hexdigest()[:32]}"


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _tokens(value: str) -> set[str]:
    return {match.group(0) for match in _WORD_RE.finditer(_fold_text(value))}


def _dedupe_phrases(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw).split()).strip()
        if not value:
            continue
        key = _fold_text(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _validate_neutral_profile_text(value: str, *, path: str) -> None:
    if _FORBIDDEN_PROFILE_REF_RE.search(value):
        raise ResearchPlanningError(
            f"{path} contains a canonical typed ref; planner profiles may not hard-code legal targets"
        )
    if _FORBIDDEN_NORM_SHORTCUT_RE.search(value):
        raise ResearchPlanningError(
            f"{path} contains a hard-coded numbered norm; profiles must name neutral research dimensions"
        )


def planner_profile_set_from_data(payload: dict[str, Any]) -> PlannerProfileSet:
    """Validate and fingerprint one neutral planner profile set.

    The digest covers canonical JSON rather than file bytes so formatting-only
    changes do not create a different research-policy identity.
    """
    if set(payload) != {"profile_set_version", "profiles"}:
        raise ResearchPlanningError(
            "profile set must contain exactly profile_set_version and profiles"
        )
    version = payload["profile_set_version"]
    profiles = payload["profiles"]
    if not isinstance(version, str) or not version:
        raise ResearchPlanningError("profile_set_version must be a non-empty string")
    if not isinstance(profiles, list) or not profiles:
        raise ResearchPlanningError("profile set must declare at least one profile")

    profile_ids: set[str] = set()
    for profile_index, profile in enumerate(profiles):
        path = f"profiles[{profile_index}]"
        required_profile_keys = {
            "profile_id",
            "profile_version",
            "match",
            "dimensions",
        }
        if set(profile) != required_profile_keys:
            raise ResearchPlanningError(f"{path} has unsupported or missing keys")

        profile_id = profile["profile_id"]
        if not isinstance(profile_id, str) or not profile_id:
            raise ResearchPlanningError(f"{path}.profile_id must be non-empty")
        if profile_id in profile_ids:
            raise ResearchPlanningError(f"duplicate profile_id: {profile_id}")
        profile_ids.add(profile_id)

        profile_version = profile["profile_version"]
        if not isinstance(profile_version, str) or not profile_version:
            raise ResearchPlanningError(f"{path}.profile_version must be non-empty")

        match = profile["match"]
        if set(match) != {"any_phrases", "all_token_groups"}:
            raise ResearchPlanningError(f"{path}.match has unsupported or missing keys")
        if not isinstance(match["any_phrases"], list):
            raise ResearchPlanningError(f"{path}.match.any_phrases must be a list")
        if not isinstance(match["all_token_groups"], list):
            raise ResearchPlanningError(f"{path}.match.all_token_groups must be a list")
        for index, phrase in enumerate(match["any_phrases"]):
            if not isinstance(phrase, str) or not phrase.strip():
                raise ResearchPlanningError(
                    f"{path}.match.any_phrases[{index}] must be non-empty"
                )
            _validate_neutral_profile_text(
                phrase, path=f"{path}.match.any_phrases[{index}]"
            )
        for group_index, group in enumerate(match["all_token_groups"]):
            if not isinstance(group, list) or not group:
                raise ResearchPlanningError(
                    f"{path}.match.all_token_groups[{group_index}] must be non-empty"
                )
            for token_index, token in enumerate(group):
                if not isinstance(token, str) or not token.strip():
                    raise ResearchPlanningError(
                        f"{path}.match.all_token_groups[{group_index}][{token_index}] "
                        "must be non-empty"
                    )
                _validate_neutral_profile_text(
                    token,
                    path=(
                        f"{path}.match.all_token_groups[{group_index}]"
                        f"[{token_index}]"
                    ),
                )

        dimensions = profile["dimensions"]
        if not isinstance(dimensions, list) or not dimensions:
            raise ResearchPlanningError(f"{path}.dimensions must be non-empty")
        dimension_keys: set[str] = set()
        for dimension_index, dimension in enumerate(dimensions):
            dim_path = f"{path}.dimensions[{dimension_index}]"
            required_dimension_keys = {
                "dimension_key",
                "research_goal",
                "query_terms",
                "fact_semantic_keys",
                "uses_question_dependency_facts",
            }
            if set(dimension) != required_dimension_keys:
                raise ResearchPlanningError(
                    f"{dim_path} has unsupported or missing keys"
                )
            dimension_key = dimension["dimension_key"]
            if not isinstance(dimension_key, str) or not dimension_key:
                raise ResearchPlanningError(
                    f"{dim_path}.dimension_key must be non-empty"
                )
            if dimension_key in dimension_keys:
                raise ResearchPlanningError(
                    f"{path} contains duplicate dimension_key {dimension_key!r}"
                )
            dimension_keys.add(dimension_key)

            goal = dimension["research_goal"]
            if not isinstance(goal, str) or not goal.strip():
                raise ResearchPlanningError(
                    f"{dim_path}.research_goal must be non-empty"
                )
            _validate_neutral_profile_text(goal, path=f"{dim_path}.research_goal")

            query_terms = dimension["query_terms"]
            if not isinstance(query_terms, list) or not query_terms:
                raise ResearchPlanningError(
                    f"{dim_path}.query_terms must be non-empty"
                )
            for term_index, term in enumerate(query_terms):
                if not isinstance(term, str) or not term.strip():
                    raise ResearchPlanningError(
                        f"{dim_path}.query_terms[{term_index}] must be non-empty"
                    )
                _validate_neutral_profile_text(
                    term, path=f"{dim_path}.query_terms[{term_index}]"
                )

            semantic_keys = dimension["fact_semantic_keys"]
            if not isinstance(semantic_keys, list) or any(
                not isinstance(item, str) or not item for item in semantic_keys
            ):
                raise ResearchPlanningError(
                    f"{dim_path}.fact_semantic_keys must contain strings"
                )
            if not isinstance(dimension["uses_question_dependency_facts"], bool):
                raise ResearchPlanningError(
                    f"{dim_path}.uses_question_dependency_facts must be boolean"
                )

    copied = json.loads(json.dumps(payload, ensure_ascii=False))
    digest = hashlib.sha256(_compact_json(copied).encode("utf-8")).hexdigest()
    return PlannerProfileSet(version=version, sha256=digest, payload=copied)


def load_planner_profile_set(
    path: Path | str = PROFILE_PATH,
) -> PlannerProfileSet:
    """Load the default versioned planner profile catalog."""
    profile_path = Path(path)
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchPlanningError(
            f"cannot load planner profile set {profile_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ResearchPlanningError("planner profile root must be an object")
    return planner_profile_set_from_data(payload)


def _confirmed_fact_refs(
    intake_draft: dict[str, Any],
    fact_refs: Iterable[str],
) -> list[str]:
    facts = {fact["fact_ref"]: fact for fact in intake_draft["facts"]}
    return sorted(
        {
            ref
            for ref in fact_refs
            if ref in facts and facts[ref]["state"] == "user_provided"
        }
    )


def _confirmed_fact_parts(
    intake_draft: dict[str, Any],
    fact_refs: Iterable[str],
) -> list[str]:
    facts = {fact["fact_ref"]: fact for fact in intake_draft["facts"]}
    parts: list[str] = []
    for ref in fact_refs:
        fact = facts.get(ref)
        if fact is None or fact["state"] != "user_provided":
            continue
        parts.append(fact["label"])
        value = fact.get("value")
        if isinstance(value, bool):
            parts.append("sí" if value else "no")
        elif isinstance(value, (str, int, float)):
            parts.append(str(value))
    return parts


def _question_match_fact_refs(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
) -> list[str]:
    requested = list(question.get("depends_on_fact_refs", []))
    if requested:
        return requested
    return [
        fact["fact_ref"]
        for fact in intake_draft["facts"]
        if fact["state"] == "user_provided"
    ]


def _profile_matches(profile: dict[str, Any], seed_text: str) -> bool:
    folded = _fold_text(seed_text)
    seed_tokens = _tokens(seed_text)
    match = profile["match"]

    def alias_matches(phrase: str) -> bool:
        folded_phrase = _fold_text(phrase).strip()
        phrase_tokens = _tokens(phrase)
        if len(phrase_tokens) == 1 and " " not in folded_phrase:
            return next(iter(phrase_tokens)) in seed_tokens
        return folded_phrase in folded

    phrase_match = any(alias_matches(phrase) for phrase in match["any_phrases"])
    groups = match["all_token_groups"]
    group_match = bool(groups) and all(
        bool(seed_tokens.intersection(_tokens(" ".join(group))))
        for group in groups
    )
    return phrase_match or group_match


def _dimension_fact_refs(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
    dimension: dict[str, Any],
) -> list[str]:
    refs: set[str] = set()
    semantic_keys = set(dimension["fact_semantic_keys"])
    for fact in intake_draft["facts"]:
        if fact.get("semantic_key") in semantic_keys:
            refs.add(fact["fact_ref"])
    if dimension["uses_question_dependency_facts"]:
        refs.update(question.get("depends_on_fact_refs", []))
    return sorted(refs)


def _aspect_ref(
    *,
    intake_ref: str,
    question_ref: str,
    origin: str,
    dimension_key: str,
    profile_id: str | None,
    profile_version: str | None,
    profile_set: PlannerProfileSet,
) -> str:
    return _stable_ref(
        "aspect",
        intake_ref,
        question_ref,
        origin,
        profile_id,
        profile_version,
        dimension_key,
        PLANNER_VERSION,
        profile_set.version,
        profile_set.sha256,
    )


def _candidate_aspects(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
    profile_set: PlannerProfileSet,
) -> list[dict[str, Any]]:
    match_refs = _question_match_fact_refs(intake_draft, question)
    seed = " ".join(
        [
            question["text"],
            *_confirmed_fact_parts(intake_draft, match_refs),
        ]
    )
    matched_profiles = [
        profile
        for profile in profile_set.payload["profiles"]
        if _profile_matches(profile, seed)
    ]

    if not matched_profiles:
        fact_refs = sorted(set(question.get("depends_on_fact_refs", [])))
        if not fact_refs:
            fact_refs = [
                fact["fact_ref"]
                for fact in intake_draft["facts"]
                if fact["state"] == "user_provided"
            ]
        dimension_key = "generic_legal_research"
        return [
            {
                "kind": "research_aspect",
                "contract_version": CONTRACT_VERSION,
                "aspect_ref": _aspect_ref(
                    intake_ref=intake_draft["intake_ref"],
                    question_ref=question["question_ref"],
                    origin="generic_fallback",
                    dimension_key=dimension_key,
                    profile_id=None,
                    profile_version=None,
                    profile_set=profile_set,
                ),
                "question_ref": question["question_ref"],
                "origin": "generic_fallback",
                "scope_status": "generic_limited",
                "dimension_key": dimension_key,
                "research_goal": (
                    "Investigar evidencia jurídica general directamente relacionada "
                    "con la pregunta, manteniendo explícita la cobertura limitada."
                ),
                "required": True,
                "fact_refs": fact_refs,
                "decomposition_status": "uncertain",
            }
        ]

    decomposition_status = (
        "uncertain" if len(matched_profiles) > 1 else "certain"
    )
    result: list[dict[str, Any]] = []
    for profile in matched_profiles:
        for dimension in profile["dimensions"]:
            result.append(
                {
                    "kind": "research_aspect",
                    "contract_version": CONTRACT_VERSION,
                    "aspect_ref": _aspect_ref(
                        intake_ref=intake_draft["intake_ref"],
                        question_ref=question["question_ref"],
                        origin="profile",
                        dimension_key=dimension["dimension_key"],
                        profile_id=profile["profile_id"],
                        profile_version=profile["profile_version"],
                        profile_set=profile_set,
                    ),
                    "question_ref": question["question_ref"],
                    "origin": "profile",
                    "scope_status": "profiled_finite",
                    "dimension_key": dimension["dimension_key"],
                    "research_goal": dimension["research_goal"],
                    "required": True,
                    "fact_refs": _dimension_fact_refs(
                        intake_draft, question, dimension
                    ),
                    "decomposition_status": decomposition_status,
                    "profile_id": profile["profile_id"],
                    "profile_version": profile["profile_version"],
                }
            )
    return result


def _round_robin_aspects(
    questions: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    queues = {
        question["question_ref"]: list(candidates[question["question_ref"]])
        for question in questions
    }
    result: list[dict[str, Any]] = []
    while any(queues.values()):
        for question in questions:
            queue = queues[question["question_ref"]]
            if queue:
                result.append(queue.pop(0))
    return result


def _profile_dimension(
    profile_set: PlannerProfileSet,
    aspect: dict[str, Any],
) -> dict[str, Any] | None:
    profile_id = aspect.get("profile_id")
    if profile_id is None:
        return None
    for profile in profile_set.payload["profiles"]:
        if profile["profile_id"] != profile_id:
            continue
        for dimension in profile["dimensions"]:
            if dimension["dimension_key"] == aspect["dimension_key"]:
                return dimension
    raise ResearchPlanningError(
        f"profile dimension disappeared for {aspect['aspect_ref']}"
    )


def _task_ref(
    *,
    aspect: dict[str, Any],
    origin: str,
    required: bool,
    strategy: str,
    target: dict[str, Any],
    depth: int,
    fact_refs: Iterable[str],
    hint_refs: Iterable[str],
    profile_set: PlannerProfileSet,
) -> str:
    return _stable_ref(
        "task",
        aspect["question_ref"],
        aspect["aspect_ref"],
        origin,
        required,
        strategy,
        target,
        depth,
        sorted(set(fact_refs)),
        sorted(set(hint_refs)),
        PLANNER_VERSION,
        profile_set.version,
        profile_set.sha256,
    )


def _make_task(
    *,
    aspect: dict[str, Any],
    origin: str,
    required: bool,
    strategy: str,
    query_text: str,
    profile_set: PlannerProfileSet,
    depth: int = 0,
    fact_refs: Iterable[str] = (),
    hint_refs: Iterable[str] = (),
) -> dict[str, Any]:
    facts = sorted(set(fact_refs))
    hints = sorted(set(hint_refs))
    target = {"kind": "query", "query_text": query_text}
    item: dict[str, Any] = {
        "kind": "research_task",
        "contract_version": CONTRACT_VERSION,
        "task_ref": _task_ref(
            aspect=aspect,
            origin=origin,
            required=required,
            strategy=strategy,
            target=target,
            depth=depth,
            fact_refs=facts,
            hint_refs=hints,
            profile_set=profile_set,
        ),
        "question_ref": aspect["question_ref"],
        "aspect_ref": aspect["aspect_ref"],
        "required": required,
        "origin": origin,
        "purpose": "primary_research",
        "strategy": strategy,
        "target": target,
        "depth": depth,
    }
    if facts:
        item["generated_from_fact_refs"] = facts
    if hints:
        item["hint_refs"] = hints
    return item


def _task_lane(task: dict[str, Any]) -> int:
    if (
        task["required"]
        and task["origin"] == "platform_required"
        and task["depth"] == 0
    ):
        return 0
    if task["required"]:
        return 1
    if task["origin"] == "intake_hint_expansion":
        return 2
    if task["origin"] in {"reference_expansion", "context_expansion"}:
        return 3
    return 4


def _round_robin_task_lane(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    question_order: list[str] = []
    aspect_order: dict[str, list[str]] = {}
    queues: dict[tuple[str, str], list[dict[str, Any]]] = {}
    cursors: dict[str, int] = {}

    for task in tasks:
        question_ref = task["question_ref"]
        aspect_ref = task["aspect_ref"]
        if question_ref not in aspect_order:
            question_order.append(question_ref)
            aspect_order[question_ref] = []
            cursors[question_ref] = 0
        if aspect_ref not in aspect_order[question_ref]:
            aspect_order[question_ref].append(aspect_ref)
        queues.setdefault((question_ref, aspect_ref), []).append(task)

    result: list[dict[str, Any]] = []
    while any(queues.values()):
        progressed = False
        for question_ref in question_order:
            aspects = aspect_order[question_ref]
            if not aspects:
                continue
            for offset in range(len(aspects)):
                index = (cursors[question_ref] + offset) % len(aspects)
                aspect_ref = aspects[index]
                queue = queues[(question_ref, aspect_ref)]
                if not queue:
                    continue
                result.append(queue.pop(0))
                cursors[question_ref] = (index + 1) % len(aspects)
                progressed = True
                break
        if not progressed:
            break
    return result


def schedule_research_tasks(
    tasks: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Order tasks so required aspect progress wins over hints/expansion.

    The scheduler is reusable by later v5 execution work. It does not infer
    legal priority: it only enforces the accepted process-fairness policy.
    """
    copied = [deepcopy(task) for task in tasks]
    result: list[dict[str, Any]] = []
    for lane in range(5):
        lane_tasks = [task for task in copied if _task_lane(task) == lane]
        result.extend(_round_robin_task_lane(lane_tasks))
    return result


def _primary_query(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
    aspect: dict[str, Any],
    profile_set: PlannerProfileSet,
) -> str:
    dimension = _profile_dimension(profile_set, aspect)
    if dimension is None:
        phrases = [
            question["text"],
            *_confirmed_fact_parts(intake_draft, aspect["fact_refs"]),
        ]
    else:
        phrases = [
            *dimension["query_terms"],
            question["text"],
            *_confirmed_fact_parts(intake_draft, aspect["fact_refs"]),
        ]
    query = " ".join(_dedupe_phrases(phrases))
    if not query:
        raise ResearchPlanningError(
            f"required aspect has no deterministic query material: {aspect['aspect_ref']}"
        )
    return query


def _optional_hint_tasks(
    *,
    intake_draft: dict[str, Any],
    questions: list[dict[str, Any]],
    aspects: list[dict[str, Any]],
    profile_set: PlannerProfileSet,
    max_queries_per_aspect: int,
    remaining_task_slots: int,
) -> list[dict[str, Any]]:
    if remaining_task_slots <= 0 or max_queries_per_aspect <= 1:
        return []

    aspects_by_question: dict[str, list[dict[str, Any]]] = {}
    for aspect in aspects:
        aspects_by_question.setdefault(aspect["question_ref"], []).append(aspect)

    hints_by_question: dict[str, list[dict[str, Any]]] = {}
    for hint in intake_draft["search_hints"]:
        for question_ref in hint["related_question_refs"]:
            if question_ref in aspects_by_question:
                hints_by_question.setdefault(question_ref, []).append(hint)
    for values in hints_by_question.values():
        values.sort(key=lambda item: item["hint_ref"])

    used_queries = {aspect["aspect_ref"]: 1 for aspect in aspects}
    question_by_ref = {q["question_ref"]: q for q in questions}
    hint_positions = {q["question_ref"]: 0 for q in questions}
    result: list[dict[str, Any]] = []

    while len(result) < remaining_task_slots:
        progressed = False
        for question in questions:
            question_ref = question["question_ref"]
            hints = hints_by_question.get(question_ref, [])
            position = hint_positions[question_ref]
            if position >= len(hints):
                continue
            aspect_options = aspects_by_question[question_ref]
            hint = hints[position]
            hint_positions[question_ref] += 1
            progressed = True

            aspect = min(
                aspect_options,
                key=lambda item: (
                    used_queries[item["aspect_ref"]],
                    item["sequence"],
                ),
            )
            if used_queries[aspect["aspect_ref"]] >= max_queries_per_aspect:
                continue

            query = " ".join(
                _dedupe_phrases([question_by_ref[question_ref]["text"], *hint["terms"]])
            )
            if not query:
                continue
            result.append(
                _make_task(
                    aspect=aspect,
                    origin="intake_hint_expansion",
                    required=False,
                    strategy="thematic_search",
                    query_text=query,
                    profile_set=profile_set,
                    hint_refs=[hint["hint_ref"]],
                )
            )
            used_queries[aspect["aspect_ref"]] += 1
            if len(result) >= remaining_task_slots:
                break
        if not progressed:
            break
    return result


def build_research_plan_v5(
    case_input: dict[str, Any],
    intake_draft: dict[str, Any],
    *,
    research_budget: dict[str, int] | None = None,
    support_budget: dict[str, int] | None = None,
    profile_set: PlannerProfileSet | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the platform-owned v5 question -> aspect -> task plan.

    Profile selection is deterministic and uses only accepted question text and
    confirmed caller facts. Unknown topics stay explicit generic-limited scope.
    """
    validate_intake_draft(case_input, intake_draft)

    profiles = profile_set or load_planner_profile_set()
    research = dict(DEFAULT_RESEARCH_BUDGET)
    support = dict(DEFAULT_SUPPORT_BUDGET)
    if research_budget is not None:
        research.update(research_budget)
    if support_budget is not None:
        support.update(support_budget)

    open_questions = [
        question
        for question in intake_draft["questions"]
        if question["category"] == "legal" and question["status"] == "open"
    ]
    candidates = {
        question["question_ref"]: _candidate_aspects(
            intake_draft, question, profiles
        )
        for question in open_questions
    }
    aspects = _round_robin_aspects(open_questions, candidates)
    for sequence, aspect in enumerate(aspects):
        aspect["sequence"] = sequence

    required_tasks: list[dict[str, Any]] = []
    questions = {q["question_ref"]: q for q in open_questions}
    for aspect in aspects:
        question = questions[aspect["question_ref"]]
        strategy = (
            "generic_fallback"
            if aspect["origin"] == "generic_fallback"
            else "thematic_search"
        )
        required_tasks.append(
            _make_task(
                aspect=aspect,
                origin="platform_required",
                required=True,
                strategy=strategy,
                query_text=_primary_query(
                    intake_draft, question, aspect, profiles
                ),
                profile_set=profiles,
                fact_refs=_confirmed_fact_refs(
                    intake_draft, aspect["fact_refs"]
                ),
            )
        )

    max_tasks = research["max_tasks"]
    if len(required_tasks) > max_tasks:
        raise ResearchPlanningError(
            "research max_tasks cannot represent one required task for every "
            f"planned aspect: required={len(required_tasks)} max_tasks={max_tasks}"
        )

    hint_tasks = _optional_hint_tasks(
        intake_draft=intake_draft,
        questions=open_questions,
        aspects=aspects,
        profile_set=profiles,
        max_queries_per_aspect=research["max_queries_per_aspect"],
        remaining_task_slots=max_tasks - len(required_tasks),
    )
    tasks = schedule_research_tasks([*required_tasks, *hint_tasks])
    for sequence, task in enumerate(tasks):
        task["sequence"] = sequence

    budgets = {"research": research, "support": support}
    plan_ref = _stable_ref(
        "plan",
        intake_draft["intake_ref"],
        case_input.get("as_of_date"),
        PLANNER_VERSION,
        profiles.version,
        profiles.sha256,
        FAIRNESS_POLICY,
        budgets,
        [aspect["aspect_ref"] for aspect in aspects],
        [task["task_ref"] for task in tasks],
    )
    plan: dict[str, Any] = {
        "kind": "research_plan",
        "contract_version": CONTRACT_VERSION,
        "plan_ref": plan_ref,
        "intake_ref": intake_draft["intake_ref"],
        "aspects": aspects,
        "tasks": tasks,
        "budgets": budgets,
        "fairness_policy": deepcopy(FAIRNESS_POLICY),
        "stop_conditions": [
            "required_support_closure",
            "bounds_exhausted",
            "no_new_canonical_authorities",
            "blocked_by_required_facts",
            "unsupported_scope",
            "integrity_failure",
        ],
        "planner_version": PLANNER_VERSION,
        "profile_set_version": profiles.version,
        "profile_set_sha256": profiles.sha256,
        "generated_at": generated_at or _utc_now(),
    }
    if "as_of_date" in case_input:
        plan["as_of_date"] = case_input["as_of_date"]

    validate_research_plan(intake_draft, plan, case_input=case_input)
    return plan


def research_context_fingerprint_v5(
    plan: dict[str, Any],
    *,
    corpus_snapshot_sha256: str | None,
    schema_migration_fingerprint: str | None,
    retrieval_config_sha256: str | None,
    retrieval_version: str,
    coverage_policy_version: str,
    support_selection_version: str,
    graph_selection_version: str,
) -> dict[str, Any]:
    """Build the v5 context identity without claiming downstream policy ownership.

    Coverage/support/graph versions are explicit inputs owned by later v5
    stages. This planner only supplies and binds planner/profile identity.
    """
    unavailable: list[str] = []
    if corpus_snapshot_sha256 is None:
        unavailable.append("corpus_snapshot_sha256")
    if schema_migration_fingerprint is None:
        unavailable.append("schema_migration_fingerprint")
    if retrieval_config_sha256 is None:
        unavailable.append("retrieval_config_sha256")
    as_of_date = plan.get("as_of_date")
    if as_of_date is None:
        unavailable.append("as_of_date")

    return {
        "corpus_snapshot_sha256": corpus_snapshot_sha256,
        "schema_migration_fingerprint": schema_migration_fingerprint,
        "retrieval_config_sha256": retrieval_config_sha256,
        "planner_version": plan["planner_version"],
        "retrieval_version": retrieval_version,
        "profile_set_version": plan["profile_set_version"],
        "profile_set_sha256": plan["profile_set_sha256"],
        "coverage_policy_version": coverage_policy_version,
        "support_selection_version": support_selection_version,
        "graph_selection_version": graph_selection_version,
        "as_of_date": as_of_date,
        "unavailable_fields": unavailable,
    }
