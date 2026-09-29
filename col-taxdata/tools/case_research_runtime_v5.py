"""Executable CASE v5 research orchestration over existing canonical primitives.\n\nThis module composes intake, planning, bounded retrieval/context, support\nselection, coverage and publication without becoming a new legal-authority layer.\n"""\n\nfrom __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from case_application import (
    CaseAnalysisIntegrityError,
    V5BundlePublicationOutcome,
    _app_ref,
    _structure_case,
    canonical_case_input_json,
    publish_v5_legal_research_bundle,
)
from case_contract_dispatch import V5_CONTRACT_VERSION, validate_case_input
from case_contract_validation_v5 import validate_legal_research_bundle
from case_evidence_graph import (
    EvidenceGraphIntegrityError,
    materialize_citable_context_spans,
    materialize_official_sources,
    materialize_retrieval_hit_span,
    materialize_selected_relationship_support,
)
from case_relationship_selection_v5 import (
    GRAPH_SELECTION_VERSION,
    RelationshipSelectionError,
    select_research_relationships_v5,
)
from case_research import (
    RETRIEVAL_VERSION,
    _corpus_snapshot_sha256,
    _explicit_conflict_unresolved_items,
    _intake_blockers,
    _schema_migration_fingerprint,
    retrieval_config_sha256,
)
from case_research_coverage_v5 import (
    CoverageBuildError,
    build_research_result_v5,
    research_context_for_coverage_v5,
)
from case_research_planning_v5 import ResearchPlanningError, build_research_plan_v5
from case_retrieval import CorpusRetrievalService, RetrievalHit, RetrievalIntegrityError
from legal_authority_classification import (
    AuthorityClassificationError,
    classify_canonical_authority,
)
from llm_client import CaseStructuringService


@dataclass(frozen=True)
class V5AnalysisOutcome:
    """One fully validated CASE v5 runtime result and publication receipt."""

    case_ref: str
    intake_draft: dict[str, Any]
    research_plan: dict[str, Any]
    research_result: dict[str, Any]
    bundle: dict[str, Any]
    publication: V5BundlePublicationOutcome


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_ref(namespace: str, *parts: object) -> str:
    material = _compact_json(parts).encode("utf-8")
    return f"{namespace}:{hashlib.sha256(material).hexdigest()[:32]}"


def _typed_value(ref: str, namespace: str) -> str:
    prefix = namespace + ":"
    if not isinstance(ref, str) or not ref.startswith(prefix) or len(ref) == len(prefix):
        raise CaseAnalysisIntegrityError(f"invalid {namespace} reference {ref!r}")
    return ref[len(prefix):]


def _project_shared_object_to_v5(value: Any) -> Any:
    """Project semantically unchanged shared v4 graph objects onto v5 copies.

    CASE v5 changes research decomposition/coverage, not canonical source,
    authority, evidence, relationship or unresolved semantics.  Only explicit
    version declarations are changed; canonical refs, hashes and provenance are
    preserved byte-for-byte as values.
    """

    copied = deepcopy(value)

    def rewrite(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"contract_version", "schema_version"} and child == "4.0.0":
                    node[key] = V5_CONTRACT_VERSION
                else:
                    rewrite(child)
        elif isinstance(node, list):
            for child in node:
                rewrite(child)

    rewrite(copied)
    return copied


def _unresolved(
    *,
    category: str,
    description: str,
    task: dict[str, Any] | None = None,
    authority_ref: str | None = None,
    evidence_ref: str | None = None,
    next_action: str,
    material: object,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "unresolved_item",
        "contract_version": V5_CONTRACT_VERSION,
        "unresolved_ref": _stable_ref("unresolved", "runtime-v5-1", category, material),
        "stage": "research",
        "category": category,
        "description": description,
        "next_action": next_action,
    }
    if task is not None:
        item["related_question_refs"] = [task["question_ref"]]
        item["related_aspect_refs"] = [task["aspect_ref"]]
        item["related_task_refs"] = [task["task_ref"]]
    if authority_ref is not None:
        item["related_authority_refs"] = [authority_ref]
    if evidence_ref is not None:
        item["related_evidence_refs"] = [evidence_ref]
    return item


def _merge_by_ref(
    registry: dict[str, dict[str, Any]],
    values: Iterable[dict[str, Any]],
    ref_field: str,
) -> None:
    for raw in values:
        item = deepcopy(raw)
        ref = item[ref_field]
        prior = registry.get(ref)
        if prior is not None and prior != item:
            raise CaseAnalysisIntegrityError(
                f"conflicting duplicate {ref_field} {ref!r}"
            )
        registry[ref] = item


def _selection_temporal_status(
    authority: dict[str, Any],
    *,
    as_of_date: str | None,
) -> str:
    if as_of_date is None:
        return "unassessed"
    effective = authority["temporal_state"].get("effective")
    if effective is True:
        return "effective_as_of"
    if effective is False:
        return "not_effective_as_of"
    return "ambiguous"


def _selection_authority_status(authority: dict[str, Any]) -> str:
    state = authority.get("classification_state")
    if state == "resolved":
        return "resolved"
    if state == "ambiguous":
        return "ambiguous"
    return "unassessed"


def _candidate_hits(
    retrieval: CorpusRetrievalService,
    task: dict[str, Any],
    *,
    limit: int,
) -> list[RetrievalHit]:
    target = task["target"]
    kind = target["kind"]
    if kind == "query":
        return list(retrieval.search_detailed(target["query_text"], limit=limit).hits)
    if kind == "document":
        lookup = retrieval.lookup_canonical_target(
            _typed_value(target["document_ref"], "document"),
            limit=limit,
        )
        return list(lookup.hits)
    if kind == "provision":
        lookup = retrieval.lookup_canonical_target(
            _typed_value(target["document_ref"], "document"),
            target_provision_id=_typed_value(target["provision_ref"], "provision"),
            limit=limit,
        )
        return list(lookup.hits)
    raise CaseAnalysisIntegrityError(
        f"v5 runtime cannot execute research target kind {kind!r}"
    )


def _bundle_ref(
    *,
    case_input: dict[str, Any],
    result: dict[str, Any],
    sources: Iterable[dict[str, Any]],
    authorities: Iterable[dict[str, Any]],
    evidence_spans: Iterable[dict[str, Any]],
    relationships: Iterable[dict[str, Any]],
    unresolved: Iterable[dict[str, Any]],
) -> str:
    return _stable_ref(
        "bundle",
        "case-v5-runtime-1",
        case_input,
        result["result_ref"],
        sorted(item["source_ref"] for item in sources),
        sorted(item["authority_ref"] for item in authorities),
        sorted(item["evidence_ref"] for item in evidence_spans),
        sorted(item["relationship_ref"] for item in relationships),
        sorted(item["unresolved_ref"] for item in unresolved),
    )


def _execute_research(
    *,
    case_input: dict[str, Any],
    intake_draft: dict[str, Any],
    db_path: Path,
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    plan = build_research_plan_v5(
        case_input,
        intake_draft,
        generated_at=generated_at,
    )
    research_budget = plan["budgets"]["research"]
    support_budget = plan["budgets"]["support"]

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    retrieval = CorpusRetrievalService(con)

    authorities_v4: dict[str, dict[str, Any]] = {}
    relationships_v4: dict[str, dict[str, Any]] = {}
    evidence_v5: dict[str, dict[str, Any]] = {}
    unresolved_v5: dict[str, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = []
    selection_inputs: list[dict[str, Any]] = []
    selected_evidence_by_aspect: dict[str, set[str]] = {}
    context_expansions_by_aspect: dict[str, int] = {}

    _merge_by_ref(
        unresolved_v5,
        (_project_shared_object_to_v5(item) for item in _intake_blockers(intake_draft)),
        "unresolved_ref",
    )

    try:
        for task in plan["tasks"]:
            task_unresolved: set[str] = set()
            retrieved_authorities: set[str] = set()
            selected_authorities: set[str] = set()
            selected_evidence: set[str] = set()
            outcome = "hits"

            if task["depth"] + 1 > research_budget["max_rounds"]:
                outcome = "budget_exhausted"
                item = _unresolved(
                    category="budget_exhausted",
                    description="Research task exceeds the declared max_rounds budget.",
                    task=task,
                    next_action="expand_research",
                    material=(task["task_ref"], "max_rounds"),
                )
                unresolved_v5[item["unresolved_ref"]] = item
                task_unresolved.add(item["unresolved_ref"])
                hits: list[RetrievalHit] = []
            else:
                max_hits = research_budget["max_hits_per_query"]
                fetched = _candidate_hits(retrieval, task, limit=max_hits + 1)
                overflow = len(fetched) > max_hits
                hits = fetched[:max_hits]
                if overflow:
                    outcome = "budget_exhausted"
                    item = _unresolved(
                        category="budget_exhausted",
                        description=(
                            "Additional retrieval hits existed beyond the declared "
                            "max_hits_per_query budget."
                        ),
                        task=task,
                        next_action="expand_research",
                        material=(task["task_ref"], "max_hits_per_query", max_hits),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])

            if not hits and outcome != "budget_exhausted":
                outcome = "no_hits"
                item = _unresolved(
                    category="no_relevant_corpus_evidence",
                    description="No relevant canonical corpus segment was retrieved.",
                    task=task,
                    next_action="expand_research",
                    material=(task["task_ref"], task["target"]),
                )
                unresolved_v5[item["unresolved_ref"]] = item
                task_unresolved.add(item["unresolved_ref"])

            for hit in hits:
                if hit.document_id is None:
                    item = _unresolved(
                        category="unresolved_identity",
                        description=(
                            "Retrieved text has provenance but no resolved canonical "
                            "document identity."
                        ),
                        task=task,
                        next_action="human_review",
                        material=(task["task_ref"], hit.extracted_segment_id),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])
                    continue

                authority_ref = f"authority:{hit.document_id}"
                if (
                    authority_ref not in authorities_v4
                    and len(authorities_v4) >= research_budget["max_total_authorities"]
                ):
                    outcome = "budget_exhausted"
                    item = _unresolved(
                        category="budget_exhausted",
                        description=(
                            "A new canonical authority could not be admitted within "
                            "max_total_authorities."
                        ),
                        task=task,
                        authority_ref=authority_ref,
                        next_action="expand_research",
                        material=(task["task_ref"], authority_ref, "authority_budget"),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])
                    continue

                if authority_ref not in authorities_v4:
                    classified = classify_canonical_authority(
                        document_id=hit.document_id,
                        db_path=db_path,
                        as_of_date=case_input.get("as_of_date"),
                    )
                    authorities_v4[authority_ref] = deepcopy(classified["authority"])
                    _merge_by_ref(
                        relationships_v4,
                        classified["relationships"],
                        "relationship_ref",
                    )
                    _merge_by_ref(
                        unresolved_v5,
                        (
                            _project_shared_object_to_v5(item)
                            for item in classified["unresolved"]
                        ),
                        "unresolved_ref",
                    )
                authority = authorities_v4[authority_ref]
                retrieved_authorities.add(authority_ref)

                provision = retrieval.provision_for_segment(hit.extracted_segment_id)
                provision_ref = (
                    f"provision:{provision['provision_id']}"
                    if provision is not None and provision["document_id"] == hit.document_id
                    else None
                )
                span_v4 = materialize_retrieval_hit_span(
                    con,
                    hit,
                    provision_ref=provision_ref,
                )
                if span_v4 is None:
                    item = _unresolved(
                        category="unresolved_identity",
                        description=(
                            "Retrieved material could not be materialized as exact "
                            "canonical evidence."
                        ),
                        task=task,
                        authority_ref=authority_ref,
                        next_action="human_review",
                        material=(task["task_ref"], hit.extracted_segment_id, "span"),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])
                    continue

                base_span = _project_shared_object_to_v5(span_v4)
                aspect_ref = task["aspect_ref"]
                aspect_selected = selected_evidence_by_aspect.setdefault(
                    aspect_ref, set()
                )
                remaining = (
                    support_budget["max_selected_evidence_per_aspect"]
                    - len(aspect_selected)
                )
                total_remaining = (
                    support_budget["max_total_evidence_spans"] - len(evidence_v5)
                )
                if remaining <= 0 or total_remaining <= 0:
                    outcome = "budget_exhausted"
                    item = _unresolved(
                        category="budget_exhausted",
                        description=(
                            "Selected exact evidence exceeded the declared support "
                            "evidence budget."
                        ),
                        task=task,
                        authority_ref=authority_ref,
                        next_action="expand_research",
                        material=(task["task_ref"], "evidence_budget"),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])
                    continue

                selection_spans = [base_span]
                context_status = "exact_sufficient"
                reference_states = retrieval.reference_resolution_states_for_segment(
                    hit.extracted_segment_id
                )
                if reference_states:
                    context_used = context_expansions_by_aspect.get(aspect_ref, 0)
                    context_remaining = max(
                        0,
                        support_budget["max_context_expansions_per_aspect"]
                        - context_used,
                    )
                    evidence_remaining = max(0, min(remaining, total_remaining) - 1)
                    context_limit = min(context_remaining, evidence_remaining)
                    context = retrieval.retrieve_citable_context(
                        hit.extracted_segment_id,
                        provision_id=(
                            provision["provision_id"] if provision is not None else None
                        ),
                        max_context_hits=context_limit,
                        include_resolved_references=True,
                    )
                    context_spans = [
                        _project_shared_object_to_v5(item)
                        for item in materialize_citable_context_spans(con, context)
                    ]
                    selection_spans.extend(context_spans)
                    context_expansions_by_aspect[aspect_ref] = (
                        context_used + len(context_spans)
                    )
                    context_status = context.context_status
                    if context_status != "expanded_verified":
                        context_status = "incomplete"
                        category = (
                            "budget_exhausted"
                            if context.budget_exhausted
                            else "context_incomplete"
                        )
                        item = _unresolved(
                            category=category,
                            description=(
                                "Selected evidence requires context that could not be "
                                "completed from verified bounded corpus structure."
                            ),
                            task=task,
                            authority_ref=authority_ref,
                            evidence_ref=base_span["evidence_ref"],
                            next_action="expand_research",
                            material=(
                                task["task_ref"],
                                base_span["evidence_ref"],
                                tuple(gap.reason for gap in context.gaps),
                                context.budget_exhausted,
                            ),
                        )
                        unresolved_v5[item["unresolved_ref"]] = item
                        task_unresolved.add(item["unresolved_ref"])

                refs = [span["evidence_ref"] for span in selection_spans]
                if len(aspect_selected | set(refs)) > support_budget[
                    "max_selected_evidence_per_aspect"
                ] or len(set(evidence_v5) | set(refs)) > support_budget[
                    "max_total_evidence_spans"
                ]:
                    outcome = "budget_exhausted"
                    item = _unresolved(
                        category="budget_exhausted",
                        description="Context support exceeds the declared evidence budget.",
                        task=task,
                        authority_ref=authority_ref,
                        next_action="expand_research",
                        material=(task["task_ref"], "context_evidence_budget"),
                    )
                    unresolved_v5[item["unresolved_ref"]] = item
                    task_unresolved.add(item["unresolved_ref"])
                    continue

                for span in selection_spans:
                    _merge_by_ref(evidence_v5, [span], "evidence_ref")
                    aspect_selected.add(span["evidence_ref"])
                    selected_evidence.add(span["evidence_ref"])
                selected_authorities.add(authority_ref)

                basis = (
                    "exact_target"
                    if task["target"]["kind"] in {"document", "provision"}
                    else "thematic_relevance"
                )
                selection_inputs.append(
                    {
                        "aspect_ref": aspect_ref,
                        "task_ref": task["task_ref"],
                        "authority_ref": authority_ref,
                        "evidence_refs": sorted(refs),
                        "basis": basis,
                        "context_status": context_status,
                        "authority_status": _selection_authority_status(authority),
                        "temporal_status": _selection_temporal_status(
                            authority,
                            as_of_date=case_input.get("as_of_date"),
                        ),
                    }
                )

            trace.append(
                {
                    "kind": "research_trace_step",
                    "contract_version": V5_CONTRACT_VERSION,
                    "trace_ref": _stable_ref(
                        "trace",
                        "case-v5-runtime-1",
                        task["task_ref"],
                        task["target"],
                        sorted(retrieved_authorities),
                        sorted(selected_evidence),
                        sorted(task_unresolved),
                        outcome,
                    ),
                    "task_ref": task["task_ref"],
                    "aspect_ref": task["aspect_ref"],
                    "round": task["depth"] + 1,
                    "executed_target": deepcopy(task["target"]),
                    "outcome": outcome,
                    "hit_count": len(hits),
                    "retrieved_authority_refs": sorted(retrieved_authorities),
                    "selected_authority_refs": sorted(selected_authorities),
                    "selected_evidence_refs": sorted(selected_evidence),
                    "unresolved_refs": sorted(task_unresolved),
                }
            )

        _merge_by_ref(
            unresolved_v5,
            (
                _project_shared_object_to_v5(item)
                for item in _explicit_conflict_unresolved_items(
                    relationships_v4.values(),
                    authorities_v4.keys(),
                )
            ),
            "unresolved_ref",
        )

        context = research_context_for_coverage_v5(
            plan,
            corpus_snapshot_sha256=_corpus_snapshot_sha256(db_path),
            schema_migration_fingerprint=_schema_migration_fingerprint(con),
            retrieval_config_sha256=retrieval_config_sha256(),
            retrieval_version=RETRIEVAL_VERSION,
            graph_selection_version=GRAPH_SELECTION_VERSION,
        )

        provisional = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=trace,
            selection_inputs=selection_inputs,
            authorities=[
                _project_shared_object_to_v5(item)
                for item in authorities_v4.values()
            ],
            evidence_spans=evidence_v5.values(),
            unresolved=unresolved_v5.values(),
            facts=intake_draft["facts"],
            research_context=context,
            generated_at=generated_at,
        )

        selector = select_research_relationships_v5(
            plan=plan,
            evidence_selections=provisional["evidence_selections"],
            evidence_spans=evidence_v5.values(),
            relationships=relationships_v4.values(),
            db_path=db_path,
        )
        support = materialize_selected_relationship_support(
            authorities=authorities_v4.values(),
            relationships=selector.selected_relationships,
            unresolved=(
                _project_shared_object_to_v5(item)
                for item in []
            ),
            db_path=db_path,
            as_of_date=case_input.get("as_of_date"),
        )

        support_authorities_v5 = [
            _project_shared_object_to_v5(item) for item in support["authorities"]
        ]
        support_relationships_v5 = [
            _project_shared_object_to_v5(item)
            for item in support["normative_relationships"]
        ]
        support_evidence_v5 = [
            _project_shared_object_to_v5(item) for item in support["evidence_spans"]
        ]
        support_unresolved_v5 = [
            _project_shared_object_to_v5(item) for item in support["unresolved"]
        ]
        _merge_by_ref(evidence_v5, support_evidence_v5, "evidence_ref")
        _merge_by_ref(unresolved_v5, support_unresolved_v5, "unresolved_ref")

        final_result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=trace,
            selection_inputs=selection_inputs,
            authorities=support_authorities_v5,
            evidence_spans=evidence_v5.values(),
            unresolved=unresolved_v5.values(),
            facts=intake_draft["facts"],
            research_context=context,
            omitted_work_inputs=selector.omitted_work_inputs,
            generated_at=generated_at,
        )

        source_refs = {
            ref
            for authority in support_authorities_v5
            for ref in authority["source_refs"]
        }
        source_refs.update(
            span["source_ref"] for span in evidence_v5.values()
        )
        sources_v5 = [
            _project_shared_object_to_v5(item)
            for item in materialize_official_sources(con, source_refs)
        ]

        graph = {
            "sources": sources_v5,
            "authorities": sorted(
                support_authorities_v5,
                key=lambda item: item["authority_ref"],
            ),
            "evidence_spans": [
                deepcopy(evidence_v5[ref]) for ref in sorted(evidence_v5)
            ],
            "normative_relationships": sorted(
                support_relationships_v5,
                key=lambda item: item["relationship_ref"],
            ),
            "unresolved": [
                deepcopy(unresolved_v5[ref]) for ref in sorted(unresolved_v5)
            ],
        }
        return plan, final_result, graph
    finally:
        con.close()


def analyze_case_v5(
    *,
    case_input: dict[str, Any],
    db_path: Path,
    case_root: Path,
    structurer: CaseStructuringService,
    dry_run: bool = False,
    request_fingerprints: dict[str, str] | None = None,
) -> V5AnalysisOutcome:
    """Execute the complete product-owned CASE v5 research/publication path."""

    contract_version = validate_case_input(case_input)
    if contract_version != V5_CONTRACT_VERSION:
        raise CaseAnalysisIntegrityError(
            f"CASE v5 runtime received unsupported contract {contract_version!r}"
        )

    try:
        structuring = _structure_case(
            case_input=case_input,
            contract_version=contract_version,
            structurer=structurer,
            request_fingerprints=request_fingerprints,
        )
        generated_at = _utc_now()
        plan, result, graph = _execute_research(
            case_input=case_input,
            intake_draft=structuring.draft,
            db_path=Path(db_path),
            generated_at=generated_at,
        )

        bundle = {
            "kind": "legal_research_bundle",
            "contract_version": V5_CONTRACT_VERSION,
            "bundle_ref": _bundle_ref(
                case_input=case_input,
                result=result,
                sources=graph["sources"],
                authorities=graph["authorities"],
                evidence_spans=graph["evidence_spans"],
                relationships=graph["normative_relationships"],
                unresolved=graph["unresolved"],
            ),
            "status": result["status"],
            "case_input": deepcopy(case_input),
            "intake_draft": deepcopy(structuring.draft),
            "research_plan": deepcopy(plan),
            "research_result": deepcopy(result),
            "sources": graph["sources"],
            "authorities": graph["authorities"],
            "evidence_spans": graph["evidence_spans"],
            "normative_relationships": graph["normative_relationships"],
            "rule_fragments": [],
            "deterministic_evaluations": [],
            "calculation_traces": [],
            "unresolved": graph["unresolved"],
            "generated_at": generated_at,
        }
        validate_legal_research_bundle(bundle)

        case_ref = _app_ref(
            "case",
            "col-taxdata:case-input:v5:" + canonical_case_input_json(case_input),
        )
        publication = publish_v5_legal_research_bundle(
            case_ref=case_ref,
            bundle=bundle,
            db_path=Path(db_path),
            case_root=Path(case_root),
            dry_run=dry_run,
        )
    except (
        sqlite3.Error,
        ResearchPlanningError,
        CoverageBuildError,
        RelationshipSelectionError,
        RetrievalIntegrityError,
        EvidenceGraphIntegrityError,
        AuthorityClassificationError,
    ) as exc:
        raise CaseAnalysisIntegrityError(
            f"v5 corpus research/evidence orchestration failed safely: {exc}"
        ) from exc

    return V5AnalysisOutcome(
        case_ref=case_ref,
        intake_draft=deepcopy(structuring.draft),
        research_plan=deepcopy(plan),
        research_result=deepcopy(result),
        bundle=deepcopy(bundle),
        publication=publication,
    )
