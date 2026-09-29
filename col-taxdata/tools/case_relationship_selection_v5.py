from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable
import unicodedata


GRAPH_SELECTION_VERSION = "v5-graph-selection-1"

# These are dependency classes, not a legal hierarchy or relevance score.  They
# identify relationship types whose context can remain mandatory even when the
# endpoint text itself has little or no query-term similarity.
_DEPENDENCY_TYPES = {
    "modification": "amendment",
    "modification_of": "amendment",
    "modifies": "amendment",
    "modified_by": "amendment",
    "amends": "amendment",
    "amended_by": "amendment",
    "replaces": "amendment",
    "replaced_by": "amendment",
    "repeal": "repeal",
    "repeal_of": "repeal",
    "repeals": "repeal",
    "repealed_by": "repeal",
    "revokes": "repeal",
    "revoked_by": "repeal",
    "supersession": "supersession",
    "supersession_of": "supersession",
    "supersedes": "supersession",
    "superseded_by": "supersession",
    "exception": "exception",
    "exception_to": "exception",
    "excepts": "exception",
    "excepted_by": "exception",
    "definition": "definition",
    "defines": "definition",
    "defined_by": "definition",
    "definition_for": "definition",
    "conflict": "conflict",
    "conflict_with": "conflict",
    "conflicts": "conflict",
    "conflicts_with": "conflict",
    "contradicts": "conflict",
    "inconsistent_with": "conflict",
    "incompatible_with": "conflict",
    "suspends": "temporal",
    "suspended_by": "temporal",
    "extends": "temporal",
    "extended_by": "temporal",
    "effective_from": "temporal",
    "expires": "temporal",
}


class RelationshipSelectionError(RuntimeError):
    """The v5 case-specific relationship graph cannot be selected safely."""


@dataclass(frozen=True)
class RelationshipSelectionRecord:
    """One deterministic aspect/relationship selection decision."""

    aspect_ref: str
    relationship_ref: str
    selected: bool
    required: bool
    scope_state: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipSelectionResult:
    """Read-only v5 relationship-selection output before support closure."""

    selected_relationships: tuple[dict[str, Any], ...]
    records: tuple[RelationshipSelectionRecord, ...]
    omitted_work_inputs: tuple[dict[str, Any], ...]
    metrics: dict[str, int | str]


@dataclass(frozen=True)
class _Endpoint:
    authority_ref: str
    provision_ref: str | None


@dataclass(frozen=True)
class _RelationshipRow:
    relationship_ref: str
    relationship_type: str
    source: _Endpoint
    target: _Endpoint
    evidence_ref: str


def _typed_value(ref: str, namespace: str) -> str:
    prefix = namespace + ":"
    if not isinstance(ref, str) or not ref.startswith(prefix) or len(ref) == len(prefix):
        raise RelationshipSelectionError(f"invalid {namespace} reference: {ref!r}")
    return ref[len(prefix):]


def _normalize_relation_type(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def _unique_registry(
    items: Iterable[dict[str, Any]],
    ref_field: str,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = deepcopy(raw)
        ref = item.get(ref_field)
        if not isinstance(ref, str) or not ref:
            raise RelationshipSelectionError(f"{label} is missing {ref_field}")
        prior = registry.get(ref)
        if prior is not None and prior != item:
            raise RelationshipSelectionError(f"conflicting duplicate {label}: {ref}")
        registry[ref] = item
    return registry


def _support_limit(plan: dict[str, Any]) -> int:
    try:
        value = plan["budgets"]["support"]["max_relationships_per_aspect"]
    except (KeyError, TypeError) as exc:
        raise RelationshipSelectionError(
            "research plan is missing support.max_relationships_per_aspect"
        ) from exc
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RelationshipSelectionError(
            "max_relationships_per_aspect must be a non-negative integer"
        )
    return value


def _selected_scope(
    *,
    plan: dict[str, Any],
    evidence_selections: Iterable[dict[str, Any]],
    evidence_spans: Iterable[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, set[str]],
    dict[str, dict[str, set[str]]],
]:
    aspects = _unique_registry(plan.get("aspects", ()), "aspect_ref", label="aspect")
    evidence = _unique_registry(evidence_spans, "evidence_ref", label="evidence span")
    selected_authorities: dict[str, set[str]] = {
        ref: set() for ref in aspects
    }
    selected_provisions: dict[str, dict[str, set[str]]] = {
        ref: {} for ref in aspects
    }

    for selection in evidence_selections:
        aspect_ref = selection.get("aspect_ref")
        authority_ref = selection.get("authority_ref")
        if aspect_ref not in aspects:
            raise RelationshipSelectionError(
                f"evidence selection references unknown aspect: {aspect_ref!r}"
            )
        _typed_value(str(authority_ref), "authority")
        refs = selection.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise RelationshipSelectionError(
                f"evidence selection for {aspect_ref} has no evidence refs"
            )
        selected_authorities[aspect_ref].add(str(authority_ref))
        for evidence_ref in refs:
            span = evidence.get(evidence_ref)
            if span is None:
                raise RelationshipSelectionError(
                    f"selection references unavailable evidence: {evidence_ref}"
                )
            if span.get("authority_ref") != authority_ref:
                raise RelationshipSelectionError(
                    f"evidence {evidence_ref} belongs to a different authority"
                )
            provision_ref = span.get("provision_ref")
            if provision_ref is None:
                continue
            _typed_value(provision_ref, "provision")
            selected_provisions[aspect_ref].setdefault(
                str(authority_ref), set()
            ).add(provision_ref)

    return aspects, selected_authorities, selected_provisions


def _load_relationship_rows(
    con: sqlite3.Connection,
    relationships: dict[str, dict[str, Any]],
) -> dict[str, _RelationshipRow]:
    if not relationships:
        return {}

    relationship_ids = {
        ref: _typed_value(ref, "relationship") for ref in relationships
    }
    placeholders = ",".join("?" for _ in relationship_ids)
    rows = con.execute(
        f"""
        SELECT
            relationship_id,
            source_type,
            source_id,
            relation_type,
            target_type,
            target_id,
            status,
            evidence_id,
            requires_human_review
        FROM relationships
        WHERE relationship_id IN ({placeholders})
        ORDER BY relationship_id
        """,
        [relationship_ids[ref] for ref in sorted(relationship_ids)],
    ).fetchall()
    by_id = {row["relationship_id"]: row for row in rows}

    provision_ids = sorted(
        {
            row[column]
            for row in rows
            for type_column, column in (
                ("source_type", "source_id"),
                ("target_type", "target_id"),
            )
            if row[type_column] == "provision"
        }
    )
    provision_owners: dict[str, str] = {}
    if provision_ids:
        provision_placeholders = ",".join("?" for _ in provision_ids)
        provision_rows = con.execute(
            f"""
            SELECT provision_id, document_id
            FROM provisions
            WHERE provision_id IN ({provision_placeholders})
            """,
            provision_ids,
        ).fetchall()
        provision_owners = {
            row["provision_id"]: row["document_id"] for row in provision_rows
        }

    def endpoint(row: sqlite3.Row, side: str) -> _Endpoint:
        endpoint_type = row[f"{side}_type"]
        endpoint_id = row[f"{side}_id"]
        if endpoint_type == "document":
            return _Endpoint(
                authority_ref=f"authority:{endpoint_id}",
                provision_ref=None,
            )
        if endpoint_type == "provision":
            owner = provision_owners.get(endpoint_id)
            if owner is None:
                raise RelationshipSelectionError(
                    f"relationship endpoint provision is missing: {endpoint_id}"
                )
            return _Endpoint(
                authority_ref=f"authority:{owner}",
                provision_ref=f"provision:{endpoint_id}",
            )
        raise RelationshipSelectionError(
            "relationship uses unsupported canonical endpoint type: "
            f"{endpoint_type!r}"
        )

    output: dict[str, _RelationshipRow] = {}
    for relationship_ref, relationship_id in relationship_ids.items():
        row = by_id.get(relationship_id)
        if row is None:
            raise RelationshipSelectionError(
                f"candidate relationship is missing from canonical storage: {relationship_ref}"
            )
        if (
            row["status"] != "validated"
            or int(row["requires_human_review"]) != 0
            or row["evidence_id"] is None
        ):
            raise RelationshipSelectionError(
                f"candidate relationship is not validated for use: {relationship_ref}"
            )
        source = endpoint(row, "source")
        target = endpoint(row, "target")
        canonical = relationships[relationship_ref]
        expected_evidence = [f"evidence:{row['evidence_id']}"]
        if canonical.get("relationship_type") != row["relation_type"]:
            raise RelationshipSelectionError(
                f"relationship type drift for {relationship_ref}"
            )
        if canonical.get("source_authority_ref") != source.authority_ref:
            raise RelationshipSelectionError(
                f"relationship source drift for {relationship_ref}"
            )
        if canonical.get("target_authority_ref") != target.authority_ref:
            raise RelationshipSelectionError(
                f"relationship target drift for {relationship_ref}"
            )
        if sorted(set(canonical.get("evidence_refs", ()))) != expected_evidence:
            raise RelationshipSelectionError(
                f"relationship evidence drift for {relationship_ref}"
            )
        output[relationship_ref] = _RelationshipRow(
            relationship_ref=relationship_ref,
            relationship_type=str(row["relation_type"]),
            source=source,
            target=target,
            evidence_ref=expected_evidence[0],
        )
    return output


def _relevance(
    row: _RelationshipRow,
    *,
    selected_authorities: set[str],
    selected_provisions: dict[str, set[str]],
) -> tuple[str, tuple[str, ...]] | None:
    family = _DEPENDENCY_TYPES.get(_normalize_relation_type(row.relationship_type))
    endpoints = (row.source, row.target)

    exact_provision = any(
        endpoint.provision_ref is not None
        and endpoint.provision_ref
        in selected_provisions.get(endpoint.authority_ref, set())
        for endpoint in endpoints
    )
    if exact_provision:
        reasons = ["selected_provision_endpoint"]
        if family is not None:
            reasons.append(f"{family}_dependency")
        return "exact_provision", tuple(sorted(set(reasons)))

    if (
        row.source.authority_ref in selected_authorities
        and row.target.authority_ref in selected_authorities
    ):
        reasons = ["both_selected_authorities"]
        if family is not None:
            reasons.append(f"{family}_dependency")
        return "selected_authorities", tuple(sorted(set(reasons)))

    if family is None:
        return None

    conservative_scope: str | None = None
    for endpoint in endpoints:
        if endpoint.authority_ref not in selected_authorities:
            continue
        known_provisions = selected_provisions.get(endpoint.authority_ref, set())
        if endpoint.provision_ref is None:
            conservative_scope = "document_scope_conservative"
            break
        if not known_provisions:
            conservative_scope = "unspecified_provision_conservative"

    if conservative_scope is None:
        # The relationship is provision-scoped to a different provision of a
        # researched document. Treating that as relevant merely because the
        # document is high-degree would recreate the issue this selector fixes.
        return None

    return (
        conservative_scope,
        tuple(
            sorted(
                {
                    f"{family}_dependency",
                    "document_scope_uncertain",
                }
            )
        ),
    )


def select_research_relationships_v5(
    *,
    plan: dict[str, Any],
    evidence_selections: Iterable[dict[str, Any]],
    evidence_spans: Iterable[dict[str, Any]],
    relationships: Iterable[dict[str, Any]],
    db_path: Path,
) -> RelationshipSelectionResult:
    """Select a case-specific v5 relationship subgraph before support closure.

    Complete canonical classification remains upstream and unchanged.  This
    function uses only typed selected evidence, canonical relationship endpoint
    scope, dependency classes accepted by the v5 contract, and the support
    budget.  It does not inspect relationship endpoint text or compute a legal
    validity/ranking score.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise RelationshipSelectionError(f"database not found: {db_path}")

    aspects, authority_scope, provision_scope = _selected_scope(
        plan=plan,
        evidence_selections=evidence_selections,
        evidence_spans=evidence_spans,
    )
    relationship_registry = _unique_registry(
        relationships,
        "relationship_ref",
        label="relationship",
    )
    max_per_aspect = _support_limit(plan)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = _load_relationship_rows(con, relationship_registry)
    finally:
        con.close()

    records: list[RelationshipSelectionRecord] = []
    omitted_inputs: list[dict[str, Any]] = []
    selected_refs: set[str] = set()
    relevant_pairs = 0
    budget_omitted_pairs = 0
    aspects_with_selected: set[str] = set()

    for aspect_ref in sorted(aspects):
        relevant: list[tuple[str, str, tuple[str, ...]]] = []
        for relationship_ref in sorted(relationship_registry):
            decision = _relevance(
                rows[relationship_ref],
                selected_authorities=authority_scope[aspect_ref],
                selected_provisions=provision_scope[aspect_ref],
            )
            if decision is None:
                continue
            relevant_pairs += 1
            scope_state, reasons = decision
            relevant.append((relationship_ref, scope_state, reasons))

        admitted = relevant[:max_per_aspect]
        omitted = relevant[max_per_aspect:]
        required = bool(aspects[aspect_ref].get("required"))

        for relationship_ref, scope_state, reasons in admitted:
            selected_refs.add(relationship_ref)
            aspects_with_selected.add(aspect_ref)
            records.append(
                RelationshipSelectionRecord(
                    aspect_ref=aspect_ref,
                    relationship_ref=relationship_ref,
                    selected=True,
                    required=required,
                    scope_state=scope_state,
                    reasons=reasons,
                )
            )

        if omitted:
            budget_omitted_pairs += len(omitted)
            omitted_refs = [item[0] for item in omitted]
            for relationship_ref, scope_state, reasons in omitted:
                records.append(
                    RelationshipSelectionRecord(
                        aspect_ref=aspect_ref,
                        relationship_ref=relationship_ref,
                        selected=False,
                        required=required,
                        scope_state=scope_state,
                        reasons=tuple(
                            sorted(set(reasons) | {"support_budget_exhausted"})
                        ),
                    )
                )
            omitted_inputs.append(
                {
                    "aspect_ref": aspect_ref,
                    "class": "support",
                    "reason": "budget_exhausted",
                    "required": required,
                    "description": (
                        "Relationship support exceeded "
                        f"max_relationships_per_aspect={max_per_aspect}; "
                        "mandatory/relevant canonical relationships remain "
                        "unmaterialized for this aspect: "
                        + ", ".join(omitted_refs)
                    ),
                }
            )

    selected_relationships = tuple(
        deepcopy(relationship_registry[ref]) for ref in sorted(selected_refs)
    )
    selected_authority_values = {
        authority_ref
        for refs in authority_scope.values()
        for authority_ref in refs
    }
    selected_provision_values = {
        provision_ref
        for by_authority in provision_scope.values()
        for refs in by_authority.values()
        for provision_ref in refs
    }
    relevant_relationship_refs = {
        record.relationship_ref for record in records
    }
    metrics: dict[str, int | str] = {
        "graph_selection_version": GRAPH_SELECTION_VERSION,
        "candidate_relationship_count": len(relationship_registry),
        "canonical_relationship_rows_loaded": len(rows),
        "aspect_relationship_evaluations": len(aspects) * len(relationship_registry),
        "relevant_relationship_count": len(relevant_relationship_refs),
        "relevant_aspect_relationship_pairs": relevant_pairs,
        "selected_relationship_count": len(selected_refs),
        "budget_omitted_aspect_relationship_pairs": budget_omitted_pairs,
        "excluded_relationship_count": (
            len(relationship_registry) - len(relevant_relationship_refs)
        ),
        "aspects_with_selected_relationships": len(aspects_with_selected),
        "selected_authority_count": len(selected_authority_values),
        "selected_provision_count": len(selected_provision_values),
    }
    return RelationshipSelectionResult(
        selected_relationships=selected_relationships,
        records=tuple(
            sorted(
                records,
                key=lambda item: (
                    item.aspect_ref,
                    item.relationship_ref,
                    not item.selected,
                ),
            )
        ),
        omitted_work_inputs=tuple(omitted_inputs),
        metrics=metrics,
    )
