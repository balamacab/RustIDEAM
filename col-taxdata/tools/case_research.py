from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable
import unicodedata

from case_contract_validation_v4 import (
    CONTRACT_VERSION,
    validate_research_plan,
    validate_research_result,
)
from case_retrieval import CorpusRetrievalService, RetrievalHit
from legal_authority_classification import classify_canonical_authority


PLANNER_VERSION = "1"
RETRIEVAL_VERSION = "2"

DEFAULT_BOUNDS: dict[str, int] = {
    "max_rounds": 3,
    "max_queries_per_question": 6,
    "max_hits_per_query": 24,
    "max_reference_depth": 2,
    "max_total_authorities": 64,
}

# The vocabulary is intentionally about research topics, not legal outcomes or
# canonical IDs. It exists so a domain-specific client word does not have to
# occur verbatim in a general controlling rule.
_RESEARCH_VOCABULARY_VERSION = "1"
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_FILING_ACTION_TERMS = frozenset(
    {"declarar", "declaracion", "presentar", "obligacion", "obligado", "obligados"}
)
_PENALTY_TERMS = frozenset({"sancion", "sanciones", "extemporanea", "extemporaneidad"})
_FOREIGN_ASSET_TERMS = frozenset({"exterior", "extranjero", "extranjera", "extranjera"})

_RETRIEVAL_CONFIG = {
    "planner_version": PLANNER_VERSION,
    "retrieval_version": RETRIEVAL_VERSION,
    "research_vocabulary_version": _RESEARCH_VOCABULARY_VERSION,
    "default_bounds": DEFAULT_BOUNDS,
    "query_policy": "question+confirmed-facts+deterministic-tax-vocabulary",
    "hint_policy": "secondary-only",
    "dedupe": "task_ref+extracted_segment_id; authority_ref",
    "reference_policy": "resolved-explicit-only",
}


class ResearchPlanningError(RuntimeError):
    """The platform cannot create a contract-valid deterministic research plan."""


@dataclass(frozen=True)
class ResearchExecution:
    """In-memory #137 output before #138/#140 evidence/bundle materialization.

    ResearchResult is the serialized v4 research contract. The additional
    collections are internal, read-only candidate material needed by later
    evidence stages; they deliberately are not called EvidenceSpan objects.
    """

    plan: dict[str, Any]
    result: dict[str, Any]
    evidence_candidates: tuple[dict[str, Any], ...]
    authorities: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    unresolved: tuple[dict[str, Any], ...]


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


def _scalar_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _dedupe_phrases(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.split()).strip()
        if not value:
            continue
        key = _fold_text(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _deterministic_vocabulary(seed_text: str) -> list[str]:
    """Expand only neutral legal/tax research vocabulary.

    The rules intentionally never name a controlling document, article, rate,
    outcome, or canonical identifier. They broaden ordinary question language
    into the general legal vocabulary used by the corpus.
    """
    tokens = _tokens(seed_text)
    phrases: list[str] = []

    if "renta" in tokens and tokens.intersection(_FILING_ACTION_TERMS):
        phrases.extend(
            [
                "personas naturales",
                "declaración de renta",
                "obligados a declarar",
                "ingresos brutos",
                "patrimonio",
                "UVT",
            ]
        )

    if tokens.intersection(_PENALTY_TERMS):
        phrases.extend(
            [
                "sanción tributaria",
                "extemporaneidad",
                "reducción de sanciones",
                "favorabilidad",
            ]
        )

    if (
        tokens.intersection({"activo", "activos", "patrimonio"})
        and tokens.intersection(_FOREIGN_ASSET_TERMS)
    ):
        phrases.extend(
            [
                "activos en el exterior",
                "declaración anual",
                "patrimonio",
            ]
        )

    if "retencion" in tokens:
        phrases.extend(["retención en la fuente", "agente retenedor"])

    if tokens.intersection({"iva", "ventas"}):
        phrases.extend(["impuesto sobre las ventas", "responsable IVA"])

    return _dedupe_phrases(phrases)


def _confirmed_fact_texts(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
) -> tuple[list[str], list[str]]:
    facts = {fact["fact_ref"]: fact for fact in intake_draft["facts"]}
    requested = list(question.get("depends_on_fact_refs", []))
    if requested:
        candidates = [facts[ref] for ref in requested if ref in facts]
    else:
        candidates = list(facts.values())

    refs: list[str] = []
    text_parts: list[str] = []
    for fact in candidates:
        # Missing/ambiguous facts must never be smuggled into a platform query as
        # if they were established client facts.
        if fact["state"] != "user_provided":
            continue
        refs.append(fact["fact_ref"])
        text_parts.append(fact["label"])
        scalar = _scalar_text(fact.get("value"))
        if scalar:
            text_parts.append(scalar)
    return refs, text_parts


def _platform_query(
    intake_draft: dict[str, Any],
    question: dict[str, Any],
) -> tuple[str, list[str]]:
    fact_refs, fact_text = _confirmed_fact_texts(intake_draft, question)
    seed_parts = [question["text"], *fact_text]
    vocabulary = _deterministic_vocabulary(" ".join(seed_parts))
    query = " ".join(_dedupe_phrases([*seed_parts, *vocabulary]))
    if not query.strip():
        raise ResearchPlanningError(
            f"open legal question has no deterministic query material: {question['question_ref']}"
        )
    return query, fact_refs


def _task(
    *,
    question_ref: str,
    origin: str,
    purpose: str,
    query_text: str,
    depth: int,
    generated_from_fact_refs: Iterable[str] = (),
    hint_refs: Iterable[str] = (),
) -> dict[str, Any]:
    facts = sorted(set(generated_from_fact_refs))
    hints = sorted(set(hint_refs))
    task_ref = _stable_ref(
        "task",
        question_ref,
        origin,
        purpose,
        query_text,
        depth,
        facts,
        hints,
        PLANNER_VERSION,
    )
    item: dict[str, Any] = {
        "kind": "research_task",
        "contract_version": CONTRACT_VERSION,
        "task_ref": task_ref,
        "question_ref": question_ref,
        "origin": origin,
        "purpose": purpose,
        "query_text": query_text,
        "depth": depth,
    }
    if facts:
        item["generated_from_fact_refs"] = facts
    if hints:
        item["hint_refs"] = hints
    return item


def build_research_plan(
    case_input: dict[str, Any],
    intake_draft: dict[str, Any],
    *,
    bounds: dict[str, int] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic platform-owned v4 research plan.

    Every open legal question receives a platform-required task before optional
    model hints are considered. Hint tasks can add recall but can neither
    replace nor suppress the platform task.
    """
    effective_bounds = dict(DEFAULT_BOUNDS)
    if bounds is not None:
        effective_bounds.update(bounds)

    tasks: list[dict[str, Any]] = []
    hints_by_question: dict[str, list[dict[str, Any]]] = {}
    for hint in intake_draft["search_hints"]:
        for question_ref in hint["related_question_refs"]:
            hints_by_question.setdefault(question_ref, []).append(hint)

    for question in intake_draft["questions"]:
        if question["category"] != "legal" or question["status"] != "open":
            continue
        query, fact_refs = _platform_query(intake_draft, question)
        tasks.append(
            _task(
                question_ref=question["question_ref"],
                origin="platform_required",
                purpose="primary_research",
                query_text=query,
                depth=0,
                generated_from_fact_refs=fact_refs,
            )
        )

        for hint in sorted(
            hints_by_question.get(question["question_ref"], []),
            key=lambda item: item["hint_ref"],
        ):
            hint_query = " ".join(_dedupe_phrases(hint["terms"]))
            if not hint_query:
                continue
            tasks.append(
                _task(
                    question_ref=question["question_ref"],
                    origin="intake_hint_expansion",
                    purpose="primary_research",
                    query_text=hint_query,
                    depth=0,
                    hint_refs=[hint["hint_ref"]],
                )
            )

    plan = {
        "kind": "research_plan",
        "contract_version": CONTRACT_VERSION,
        "plan_ref": _stable_ref(
            "plan",
            intake_draft["intake_ref"],
            case_input.get("as_of_date"),
            PLANNER_VERSION,
        ),
        "intake_ref": intake_draft["intake_ref"],
        "tasks": tasks,
        "bounds": effective_bounds,
        "stop_conditions": [
            "questions_satisfied",
            "bounds_exhausted",
            "no_new_canonical_authorities",
            "blocked_by_missing_facts",
            "integrity_failure",
        ],
        "planner_version": PLANNER_VERSION,
        "generated_at": generated_at or _utc_now(),
    }
    if "as_of_date" in case_input:
        plan["as_of_date"] = case_input["as_of_date"]

    validate_research_plan(intake_draft, plan, case_input=case_input)
    return plan


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _corpus_snapshot_sha256(db_path: Path) -> str | None:
    """Fingerprint a stable SQLite snapshot without pretending a live WAL is one.

    A non-empty WAL means the main database file alone is not a complete byte
    identity. In that case the field is explicitly unavailable rather than
    emitting a misleading fingerprint.
    """
    if not db_path.is_file():
        return None
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        return None
    return _sha256_file(db_path)


def _schema_migration_fingerprint(con: sqlite3.Connection) -> str | None:
    exists = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_metadata'
        """
    ).fetchone()
    if exists is None:
        return None
    rows = con.execute(
        """
        SELECT schema_name, schema_sha256
        FROM schema_metadata
        ORDER BY schema_name
        """
    ).fetchall()
    if not rows:
        return None
    material = "\n".join(f"{row[0]}:{row[1]}" for row in rows)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def retrieval_config_sha256() -> str:
    return hashlib.sha256(_compact_json(_RETRIEVAL_CONFIG).encode("utf-8")).hexdigest()


def research_context_fingerprint(
    *,
    db_path: Path,
    con: sqlite3.Connection,
    plan: dict[str, Any],
) -> dict[str, Any]:
    corpus = _corpus_snapshot_sha256(db_path)
    schema = _schema_migration_fingerprint(con)
    as_of = plan.get("as_of_date")
    unavailable: list[str] = []
    if corpus is None:
        unavailable.append("corpus_snapshot_sha256")
    if schema is None:
        unavailable.append("schema_migration_fingerprint")
    if as_of is None:
        unavailable.append("as_of_date")

    return {
        "corpus_snapshot_sha256": corpus,
        "schema_migration_fingerprint": schema,
        "retrieval_config_sha256": retrieval_config_sha256(),
        "planner_version": PLANNER_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "as_of_date": as_of,
        "unavailable_fields": unavailable,
    }


def _unresolved(
    *,
    category: str,
    description: str,
    question_ref: str | None = None,
    fact_ref: str | None = None,
    authority_ref: str | None = None,
    next_action: str,
    material: object,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "unresolved_item",
        "contract_version": CONTRACT_VERSION,
        "unresolved_ref": _stable_ref("unresolved", category, material),
        "stage": "research",
        "category": category,
        "description": description,
        "next_action": next_action,
    }
    if question_ref is not None:
        item["related_question_refs"] = [question_ref]
    if fact_ref is not None:
        item["related_fact_refs"] = [fact_ref]
    if authority_ref is not None:
        item["related_authority_refs"] = [authority_ref]
    return item


def _intake_blockers(intake_draft: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    facts = {fact["fact_ref"]: fact for fact in intake_draft["facts"]}
    for question in intake_draft["questions"]:
        if question["status"] != "blocked":
            continue
        related = [
            facts[ref]
            for ref in question.get("depends_on_fact_refs", [])
            if ref in facts and facts[ref]["state"] in {"missing", "ambiguous"}
        ]
        if related:
            for fact in related:
                category = "missing_fact" if fact["state"] == "missing" else "ambiguous_fact"
                blockers.append(
                    _unresolved(
                        category=category,
                        description=fact["needed_information"],
                        question_ref=question["question_ref"],
                        fact_ref=fact["fact_ref"],
                        next_action="ask_client",
                        material=(question["question_ref"], fact["fact_ref"], fact["state"]),
                    )
                )
        else:
            blockers.append(
                _unresolved(
                    category="other",
                    description="Research question is blocked by unresolved intake state.",
                    question_ref=question["question_ref"],
                    next_action="ask_client",
                    material=question["question_ref"],
                )
            )
    return blockers


def _candidate_from_hit(
    task: dict[str, Any],
    hit: RetrievalHit,
    provision: dict[str, Any] | None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "research_evidence_candidate",
        "task_ref": task["task_ref"],
        "question_ref": task["question_ref"],
        "query_text": task["query_text"],
        "extracted_segment_id": hit.extracted_segment_id,
        "extraction_id": hit.extraction_id,
        "sequence_no": hit.sequence_no,
        "text": hit.text,
        "text_sha256": hit.text_sha256,
        "manifestation_id": hit.manifestation_id,
        "manifestation_sha256": hit.manifestation_sha256,
        "source_ref": f"source:{hit.source_id}",
        "source_url": hit.source_url,
        "retrieved_at": hit.retrieved_at,
        "rank": hit.rank,
    }
    if hit.document_id is not None:
        item["document_ref"] = f"document:{hit.document_id}"
        item["authority_ref"] = f"authority:{hit.document_id}"
    if provision is not None:
        item["provision_ref"] = f"provision:{provision['provision_id']}"
    return item


def _merge_unresolved(
    target: dict[str, dict[str, Any]],
    items: Iterable[dict[str, Any]],
) -> None:
    for item in items:
        target[item["unresolved_ref"]] = deepcopy(item)


class PlatformResearchService:
    """Bounded deterministic research over the canonical corpus.

    No model call occurs here. The service is read-only and never creates CASE
    claims, EvidenceSpan objects, canonical identities, or persisted research
    state. Those boundaries remain owned by later issues.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        bounds: dict[str, int] | None = None,
    ):
        self.db_path = Path(db_path)
        self.bounds = dict(DEFAULT_BOUNDS)
        if bounds is not None:
            self.bounds.update(bounds)

    def research(
        self,
        *,
        case_input: dict[str, Any],
        intake_draft: dict[str, Any],
        generated_at: str | None = None,
    ) -> ResearchExecution:
        plan = build_research_plan(
            case_input,
            intake_draft,
            bounds=self.bounds,
            generated_at=generated_at,
        )
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            retrieval = CorpusRetrievalService(con)
            return self._execute(
                con=con,
                retrieval=retrieval,
                case_input=case_input,
                intake_draft=intake_draft,
                plan=plan,
                generated_at=generated_at,
            )
        finally:
            con.close()

    def _execute(
        self,
        *,
        con: sqlite3.Connection,
        retrieval: CorpusRetrievalService,
        case_input: dict[str, Any],
        intake_draft: dict[str, Any],
        plan: dict[str, Any],
        generated_at: str | None,
    ) -> ResearchExecution:
        del case_input
        queue = list(plan["tasks"])
        scheduled = {
            (task["question_ref"], _fold_text(task["query_text"]))
            for task in queue
        }
        queries_by_question: dict[str, int] = {}
        trace: list[dict[str, Any]] = []
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        authorities: dict[str, dict[str, Any]] = {}
        relationships: dict[str, dict[str, Any]] = {}
        unresolved: dict[str, dict[str, Any]] = {}
        _merge_unresolved(unresolved, _intake_blockers(intake_draft))
        authority_cache: dict[str, dict[str, Any]] = {}
        question_authorities: dict[str, set[str]] = {}
        bounds_exhausted = False

        while queue:
            task = queue.pop(0)
            question_ref = task["question_ref"]
            count = queries_by_question.get(question_ref, 0)
            if count >= plan["bounds"]["max_queries_per_question"]:
                bounds_exhausted = True
                continue
            if task["depth"] + 1 > plan["bounds"]["max_rounds"]:
                bounds_exhausted = True
                continue
            queries_by_question[question_ref] = count + 1

            hits = retrieval.search(
                task["query_text"],
                limit=plan["bounds"]["max_hits_per_query"],
            )
            unique_hits: list[RetrievalHit] = []
            seen_segments: set[str] = set()
            for hit in hits:
                if hit.extracted_segment_id in seen_segments:
                    continue
                seen_segments.add(hit.extracted_segment_id)
                unique_hits.append(hit)

            step_authorities: set[str] = set()
            step_unresolved: set[str] = set()
            expansion_queries: list[str] = []

            if not unique_hits:
                item = _unresolved(
                    category="no_relevant_corpus_evidence",
                    description=(
                        "No relevant canonical corpus segment was retrieved for "
                        "this bounded research query."
                    ),
                    question_ref=question_ref,
                    next_action="expand_research",
                    material=(task["task_ref"], task["query_text"]),
                )
                unresolved[item["unresolved_ref"]] = item
                step_unresolved.add(item["unresolved_ref"])

            for hit in unique_hits:
                provision = retrieval.provision_for_segment(hit.extracted_segment_id)
                candidate = _candidate_from_hit(task, hit, provision)
                candidates[(task["task_ref"], hit.extracted_segment_id)] = candidate

                if hit.document_id is None:
                    item = _unresolved(
                        category="unresolved_identity",
                        description=(
                            "Retrieved text has provenance but is not bound to one "
                            "resolved canonical document identity."
                        ),
                        question_ref=question_ref,
                        next_action="human_review",
                        material=(task["task_ref"], hit.extracted_segment_id),
                    )
                    unresolved[item["unresolved_ref"]] = item
                    step_unresolved.add(item["unresolved_ref"])
                    continue

                if hit.document_id not in authority_cache:
                    authority_cache[hit.document_id] = classify_canonical_authority(
                        document_id=hit.document_id,
                        db_path=self.db_path,
                        as_of_date=plan.get("as_of_date"),
                    )
                classified = authority_cache[hit.document_id]
                authority = classified["authority"]
                authority_ref = str(authority["authority_ref"])
                authorities[authority_ref] = deepcopy(authority)
                step_authorities.add(authority_ref)
                question_authorities.setdefault(question_ref, set()).add(authority_ref)

                for source in classified["sources"]:
                    # OfficialSource objects are intentionally not duplicated in
                    # ResearchResult; #138/#140 materialize them into the bundle.
                    del source

                for relation in classified["relationships"]:
                    relationships[str(relation["relationship_ref"])] = deepcopy(relation)
                    other_ref = (
                        relation["target_authority_ref"]
                        if relation["source_authority_ref"] == authority_ref
                        else relation["source_authority_ref"]
                    )
                    if isinstance(other_ref, str) and other_ref.startswith("authority:"):
                        other_document_id = other_ref.split(":", 1)[1]
                        label = retrieval.query_for_document(other_document_id)
                        if label:
                            expansion_queries.append(label)

                _merge_unresolved(unresolved, classified["unresolved"])
                step_unresolved.update(
                    item["unresolved_ref"] for item in classified["unresolved"]
                )

                for reference in retrieval.resolved_references_for_segment(
                    hit.extracted_segment_id
                ):
                    expansion_queries.append(reference["query_text"])

            can_expand = (
                task["depth"] < plan["bounds"]["max_reference_depth"]
                and task["depth"] + 1 < plan["bounds"]["max_rounds"]
            )
            if can_expand:
                for query_text in _dedupe_phrases(expansion_queries):
                    if len(authorities) >= plan["bounds"]["max_total_authorities"]:
                        bounds_exhausted = True
                        break
                    key = (question_ref, _fold_text(query_text))
                    if key in scheduled:
                        continue
                    if (
                        queries_by_question.get(question_ref, 0)
                        + sum(1 for queued in queue if queued["question_ref"] == question_ref)
                        >= plan["bounds"]["max_queries_per_question"]
                    ):
                        bounds_exhausted = True
                        break
                    expanded = _task(
                        question_ref=question_ref,
                        origin="reference_expansion",
                        purpose="reference_expansion",
                        query_text=query_text,
                        depth=task["depth"] + 1,
                    )
                    plan["tasks"].append(expanded)
                    queue.append(expanded)
                    scheduled.add(key)
            elif expansion_queries:
                bounds_exhausted = True

            trace.append(
                {
                    "kind": "research_trace_step",
                    "contract_version": CONTRACT_VERSION,
                    "trace_ref": _stable_ref(
                        "trace",
                        task["task_ref"],
                        queries_by_question[question_ref],
                        task["query_text"],
                    ),
                    "task_ref": task["task_ref"],
                    "round": task["depth"] + 1,
                    "query_text": task["query_text"],
                    "outcome": "hits" if unique_hits else "no_hits",
                    "hit_count": len(unique_hits),
                    "authority_refs": sorted(step_authorities),
                    "unresolved_refs": sorted(step_unresolved),
                }
            )

            if len(authorities) >= plan["bounds"]["max_total_authorities"]:
                bounds_exhausted = True
                break

        validate_research_plan(intake_draft, plan)

        open_legal_questions = {
            question["question_ref"]
            for question in intake_draft["questions"]
            if question["category"] == "legal" and question["status"] == "open"
        }
        covered_questions = {
            ref for ref, values in question_authorities.items() if values
        }
        blocked_questions = {
            question["question_ref"]
            for question in intake_draft["questions"]
            if question["status"] == "blocked"
        }

        if trace:
            if bounds_exhausted:
                stop_reason = "bounds_exhausted"
            elif open_legal_questions and open_legal_questions <= covered_questions:
                stop_reason = "questions_satisfied"
            elif blocked_questions and not open_legal_questions:
                stop_reason = "blocked_by_missing_facts"
            else:
                stop_reason = "no_new_canonical_authorities"
            trace[-1]["stop_reason"] = stop_reason

        if blocked_questions and not open_legal_questions:
            status = "blocked"
        elif open_legal_questions <= covered_questions and not unresolved:
            status = "complete"
        else:
            status = "partial"

        context = research_context_fingerprint(
            db_path=self.db_path,
            con=con,
            plan=plan,
        )
        result = {
            "kind": "research_result",
            "contract_version": CONTRACT_VERSION,
            "result_ref": _stable_ref(
                "research",
                plan["plan_ref"],
                context,
                sorted(authorities),
                sorted(unresolved),
            ),
            "plan_ref": plan["plan_ref"],
            "status": status,
            "trace": trace,
            "authority_refs": sorted(authorities),
            "unresolved_refs": sorted(unresolved),
            "research_context": context,
            "generated_at": generated_at or _utc_now(),
        }
        validate_research_result(plan, result)

        return ResearchExecution(
            plan=deepcopy(plan),
            result=result,
            evidence_candidates=tuple(
                deepcopy(candidates[key]) for key in sorted(candidates)
            ),
            authorities=tuple(
                deepcopy(authorities[key]) for key in sorted(authorities)
            ),
            relationships=tuple(
                deepcopy(relationships[key]) for key in sorted(relationships)
            ),
            unresolved=tuple(
                deepcopy(unresolved[key]) for key in sorted(unresolved)
            ),
        )
