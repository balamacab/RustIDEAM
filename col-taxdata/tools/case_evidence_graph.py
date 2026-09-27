from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from case_contract_validation_v4 import (
    CONTRACT_VERSION,
    validate_contract_object,
    validate_legal_research_bundle,
)
from case_evaluators import evaluate_supported_rules
from case_research import ResearchExecution
from case_retrieval import exact_unambiguous_substring_offset
from legal_authority_classification import (
    AuthorityClassificationError,
    classify_canonical_authority,
)


ANCHOR_VERSION = "canonical-legal-span-v1"
CANONICAL_EVIDENCE_SPAN_REF_VERSION = "1"
RULE_DERIVATION_VERSION = "1"
RULE_SCHEMA_VERSION = "1"
CANONICAL_SOURCE_STATEMENT_RULE = "canonical_source_statement"
RESOLVED_PROVISION_REFERENCE_RULE = "resolved_provision_reference"


class EvidenceGraphIntegrityError(RuntimeError):
    """Canonical research cannot be converted into a safe evidence graph."""


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_ref(namespace: str, *parts: object) -> str:
    digest = hashlib.sha256(_json(parts).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest[:32]}"


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise EvidenceGraphIntegrityError(f"database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _typed_value(ref: str, namespace: str) -> str:
    prefix = namespace + ":"
    if not ref.startswith(prefix) or len(ref) == len(prefix):
        raise EvidenceGraphIntegrityError(
            f"invalid {namespace} reference: {ref!r}"
        )
    return ref[len(prefix):]


def _official_source(
    con: sqlite3.Connection,
    source_ref: str,
) -> dict[str, Any]:
    source_id = _typed_value(source_ref, "source")
    row = con.execute(
        """
        SELECT source_url, authority, source_kind
        FROM sources
        WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        raise EvidenceGraphIntegrityError(
            f"canonical source not found: {source_ref}"
        )
    source: dict[str, Any] = {
        "kind": "official_source",
        "contract_version": CONTRACT_VERSION,
        "source_ref": source_ref,
        "authority": row["authority"],
        "source_uri": row["source_url"],
    }
    if row["source_kind"]:
        source["source_kind"] = row["source_kind"]
    validate_contract_object(source)
    return source


def _close_relationship_endpoints(
    *,
    db_path: Path,
    authorities: dict[str, dict[str, Any]],
    relationships: dict[str, dict[str, Any]],
    unresolved: dict[str, dict[str, Any]],
    as_of_date: str | None,
) -> None:
    """Include relationship endpoint authority metadata without recursive research."""
    included_relationships = set(relationships)
    endpoint_refs = sorted(
        {
            ref
            for relation in relationships.values()
            for ref in (
                relation["source_authority_ref"],
                relation["target_authority_ref"],
            )
        }
    )
    for authority_ref in endpoint_refs:
        if authority_ref in authorities:
            continue
        document_id = _typed_value(authority_ref, "authority")
        try:
            classified = classify_canonical_authority(
                document_id=document_id,
                db_path=db_path,
                as_of_date=as_of_date,
            )
        except AuthorityClassificationError as exc:
            raise EvidenceGraphIntegrityError(
                "relationship endpoint authority cannot be materialized: "
                f"{authority_ref}: {exc}"
            ) from exc
        authority = deepcopy(classified["authority"])
        if authority["authority_ref"] != authority_ref:
            raise EvidenceGraphIntegrityError(
                "authority classifier returned a different endpoint identity"
            )
        # #138 closes only the already-researched relationship graph. Pulling
        # every relationship of a newly included endpoint would silently turn
        # graph materialization into another unbounded research stage.
        authority["relationship_refs"] = sorted(
            set(authority["relationship_refs"]).intersection(
                included_relationships
            )
        )
        authorities[authority_ref] = authority
        for item in classified["unresolved"]:
            unresolved[item["unresolved_ref"]] = deepcopy(item)

    for authority in authorities.values():
        authority["relationship_refs"] = sorted(
            set(authority["relationship_refs"]).intersection(
                included_relationships
            )
        )


def _verified_candidate_row(
    con: sqlite3.Connection,
    candidate: dict[str, Any],
) -> sqlite3.Row:
    row = con.execute(
        """
        SELECT
            es.extracted_segment_id,
            es.extraction_id,
            es.sequence_no,
            es.char_start,
            es.char_end,
            es.text,
            es.text_sha256,
            m.manifestation_id,
            m.sha256 AS manifestation_sha256,
            m.retrieved_at,
            m.document_id,
            s.source_id,
            s.source_url
        FROM extracted_segments es
        JOIN text_extractions te
          ON te.extraction_id = es.extraction_id
         AND te.status = 'success'
        JOIN manifestations m
          ON m.manifestation_id = te.manifestation_id
        JOIN sources s
          ON s.source_id = m.source_id
        WHERE es.extracted_segment_id = ?
        """,
        (candidate["extracted_segment_id"],),
    ).fetchone()
    if row is None:
        raise EvidenceGraphIntegrityError(
            "research candidate points to a missing extracted segment"
        )
    if _text_sha(row["text"]) != row["text_sha256"]:
        raise EvidenceGraphIntegrityError(
            "canonical extracted segment text fingerprint mismatch"
        )

    expected = {
        "extraction_id": row["extraction_id"],
        "sequence_no": int(row["sequence_no"]),
        "text": row["text"],
        "text_sha256": row["text_sha256"],
        "manifestation_id": row["manifestation_id"],
        "manifestation_sha256": row["manifestation_sha256"],
        "source_ref": f"source:{row['source_id']}",
        "source_url": row["source_url"],
    }
    for name, value in expected.items():
        if candidate.get(name) != value:
            raise EvidenceGraphIntegrityError(
                f"research candidate {name} does not match canonical provenance"
            )

    if row["document_id"] is None:
        if "document_ref" in candidate or "authority_ref" in candidate:
            raise EvidenceGraphIntegrityError(
                "candidate invented identity for an unbound manifestation"
            )
    else:
        if candidate.get("document_ref") != f"document:{row['document_id']}":
            raise EvidenceGraphIntegrityError(
                "candidate document_ref does not match manifestation identity"
            )
        if candidate.get("authority_ref") != f"authority:{row['document_id']}":
            raise EvidenceGraphIntegrityError(
                "candidate authority_ref does not match manifestation identity"
            )
    return row


def _provision_observation(
    con: sqlite3.Connection,
    *,
    provision_ref: str,
    extracted_segment_id: str,
) -> sqlite3.Row:
    provision_id = _typed_value(provision_ref, "provision")
    rows = con.execute(
        """
        SELECT
            po.provision_observation_id,
            po.extraction_id,
            po.observed_text,
            po.normative_text,
            po.observed_text_sha256,
            po.normative_text_sha256,
            po.parser_name,
            po.parser_version,
            p.document_id,
            p.provision_type,
            p.designation
        FROM provision_observations po
        JOIN provisions p ON p.provision_id = po.provision_id
        WHERE po.provision_id = ?
          AND po.extracted_segment_id = ?
        ORDER BY po.provision_observation_id
        """,
        (provision_id, extracted_segment_id),
    ).fetchall()
    if len(rows) != 1:
        raise EvidenceGraphIntegrityError(
            "provision_ref does not resolve to exactly one observation"
        )
    return rows[0]


def _candidate_span(
    con: sqlite3.Connection,
    candidate: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Create exact source evidence; unresolved identity stays unresolved."""
    row = _verified_candidate_row(con, candidate)
    if row["document_id"] is None:
        return None, None

    authority_ref = f"authority:{row['document_id']}"
    document_ref = f"document:{row['document_id']}"
    exact_text = row["text"]
    exact_sha = row["text_sha256"]
    anchor_start = int(row["char_start"])
    anchor_end = int(row["char_end"])
    provision_meta: dict[str, Any] | None = None
    provenance_parts: tuple[object, ...]

    requested_provision_ref = candidate.get("provision_ref")
    provision_ref: str | None = None
    if requested_provision_ref is not None:
        observation = _provision_observation(
            con,
            provision_ref=requested_provision_ref,
            extracted_segment_id=row["extracted_segment_id"],
        )
        if observation["document_id"] != row["document_id"]:
            raise EvidenceGraphIntegrityError(
                "provision observation belongs to a different document"
            )
        if observation["extraction_id"] != row["extraction_id"]:
            raise EvidenceGraphIntegrityError(
                "provision observation belongs to a different extraction"
            )
        if (
            _text_sha(observation["observed_text"])
            != observation["observed_text_sha256"]
        ):
            raise EvidenceGraphIntegrityError(
                "provision observed-text fingerprint mismatch"
            )
        if (
            _text_sha(observation["normative_text"])
            != observation["normative_text_sha256"]
        ):
            raise EvidenceGraphIntegrityError(
                "provision normative-text fingerprint mismatch"
            )

        offset = exact_unambiguous_substring_offset(
            row["text"],
            observation["normative_text"],
        )
        if offset is not None:
            provision_ref = requested_provision_ref
            exact_text = observation["normative_text"]
            exact_sha = observation["normative_text_sha256"]
            anchor_start = int(row["char_start"]) + offset
            anchor_end = anchor_start + len(exact_text)
            provision_meta = {
                "provision_ref": provision_ref,
                "provision_type": observation["provision_type"],
                "designation": observation["designation"],
            }
            provenance_parts = (
                "provision_observation",
                observation["provision_observation_id"],
                observation["parser_name"],
                observation["parser_version"],
            )

    if provision_ref is None:
        # A provision identity can be canonical while its observation is not
        # citable at one exact span. Preserve the verified segment as evidence
        # instead of guessing an empty/ambiguous provision anchor.
        provenance_parts = (
            "research_segment",
            row["extracted_segment_id"],
            row["extraction_id"],
        )

    evidence_ref = _stable_ref(
        "evidence",
        "research",
        row["manifestation_id"],
        row["extracted_segment_id"],
        provision_ref,
        exact_sha,
        ANCHOR_VERSION,
    )
    span: dict[str, Any] = {
        "kind": "evidence_span",
        "contract_version": CONTRACT_VERSION,
        "evidence_ref": evidence_ref,
        "span_ref": _stable_ref(
            "span",
            ANCHOR_VERSION,
            row["manifestation_id"],
            row["extracted_segment_id"],
            anchor_start,
            anchor_end,
            exact_sha,
        ),
        "authority_ref": authority_ref,
        "document_ref": document_ref,
        "exact_text": exact_text,
        "source_ref": f"source:{row['source_id']}",
        "source_sha256": row["manifestation_sha256"],
        "text_sha256": exact_sha,
        "provenance_ref": _stable_ref(
            "provenance",
            *provenance_parts,
            row["manifestation_id"],
            row["extracted_segment_id"],
            exact_sha,
        ),
        "anchor_version": ANCHOR_VERSION,
        "retrieved_at": row["retrieved_at"],
    }
    if provision_ref is not None:
        span["provision_ref"] = provision_ref
    validate_contract_object(span)
    return span, {
        "candidate_segment_id": row["extracted_segment_id"],
        "authority_ref": authority_ref,
        "document_ref": document_ref,
        "evidence_ref": evidence_ref,
        "provision": provision_meta,
    }


def _canonical_evidence_span(
    con: sqlite3.Connection,
    *,
    evidence_ref: str,
    authorities: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Materialize an existing canonical evidence row without changing its ID."""
    evidence_id = _typed_value(evidence_ref, "evidence")
    row = con.execute(
        """
        SELECT
            e.manifestation_id,
            e.segment_id,
            e.extracted_segment_id,
            e.page_number,
            e.char_start,
            e.char_end,
            e.exact_quote,
            e.source_url,
            e.source_sha256,
            e.retrieved_at,
            m.document_id,
            m.source_id,
            m.sha256 AS manifestation_sha256,
            s.source_url AS canonical_source_url
        FROM evidence e
        JOIN manifestations m ON m.manifestation_id = e.manifestation_id
        JOIN sources s ON s.source_id = m.source_id
        WHERE e.evidence_id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise EvidenceGraphIntegrityError(
            f"canonical metadata references missing evidence {evidence_ref}"
        )
    if row["document_id"] is None:
        raise EvidenceGraphIntegrityError(
            f"canonical evidence has unresolved document identity {evidence_ref}"
        )
    authority_ref = f"authority:{row['document_id']}"
    if authority_ref not in authorities:
        raise EvidenceGraphIntegrityError(
            "canonical evidence owner is absent from the authority graph"
        )
    if row["source_sha256"] != row["manifestation_sha256"]:
        raise EvidenceGraphIntegrityError(
            f"source SHA mismatch for canonical evidence {evidence_ref}"
        )
    if row["source_url"] != row["canonical_source_url"]:
        raise EvidenceGraphIntegrityError(
            f"source URL mismatch for canonical evidence {evidence_ref}"
        )
    if not row["exact_quote"]:
        raise EvidenceGraphIntegrityError(
            f"empty exact quote for canonical evidence {evidence_ref}"
        )

    provision_ref: str | None = None
    if row["extracted_segment_id"]:
        segment = con.execute(
            """
            SELECT es.text, es.text_sha256, te.manifestation_id
            FROM extracted_segments es
            JOIN text_extractions te ON te.extraction_id = es.extraction_id
            WHERE es.extracted_segment_id = ?
            """,
            (row["extracted_segment_id"],),
        ).fetchone()
        if (
            segment is None
            or segment["manifestation_id"] != row["manifestation_id"]
            or _text_sha(segment["text"]) != segment["text_sha256"]
        ):
            raise EvidenceGraphIntegrityError(
                f"invalid extracted-segment anchor for {evidence_ref}"
            )
        if row["exact_quote"] not in segment["text"]:
            raise EvidenceGraphIntegrityError(
                f"exact quote is absent from its linked segment for {evidence_ref}"
            )
        provisions = con.execute(
            """
            SELECT DISTINCT p.provision_id
            FROM provision_observations po
            JOIN provisions p ON p.provision_id = po.provision_id
            WHERE po.extracted_segment_id = ?
              AND p.document_id = ?
            ORDER BY p.provision_id
            """,
            (row["extracted_segment_id"], row["document_id"]),
        ).fetchall()
        if len(provisions) == 1:
            provision_ref = f"provision:{provisions[0][0]}"

    text_sha = _text_sha(row["exact_quote"])
    anchor = (
        ANCHOR_VERSION,
        row["manifestation_id"],
        row["extracted_segment_id"],
        row["segment_id"],
        row["page_number"],
        row["char_start"],
        row["char_end"],
        text_sha,
    )
    span: dict[str, Any] = {
        "kind": "evidence_span",
        "contract_version": CONTRACT_VERSION,
        "evidence_ref": evidence_ref,
        "span_ref": _stable_ref(
            "span",
            "canonical_evidence",
            CANONICAL_EVIDENCE_SPAN_REF_VERSION,
            evidence_id,
            *anchor,
        ),
        "authority_ref": authority_ref,
        "document_ref": f"document:{row['document_id']}",
        "exact_text": row["exact_quote"],
        "source_ref": f"source:{row['source_id']}",
        "source_sha256": row["manifestation_sha256"],
        "text_sha256": text_sha,
        "provenance_ref": _stable_ref(
            "provenance",
            "canonical_evidence",
            evidence_id,
            *anchor,
        ),
        "anchor_version": ANCHOR_VERSION,
        "retrieved_at": row["retrieved_at"],
    }
    if provision_ref is not None:
        span["provision_ref"] = provision_ref
    validate_contract_object(span)
    return span


def _required_evidence_refs(
    authorities: Iterable[dict[str, Any]],
    relationships: Iterable[dict[str, Any]],
    unresolved: Iterable[dict[str, Any]],
) -> list[str]:
    refs: set[str] = set()
    for authority in authorities:
        refs.update(authority["evidence_refs"])
        refs.update(authority["temporal_state"]["basis_evidence_refs"])
        refs.update(authority["publication_metadata"]["evidence_refs"])
    for relation in relationships:
        refs.update(relation["evidence_refs"])
    for item in unresolved:
        refs.update(item.get("related_evidence_refs", []))
    return sorted(refs)


def _statement_rule(
    *,
    span: dict[str, Any],
    provision: dict[str, Any],
    authority: dict[str, Any],
    as_of_date: str | None,
) -> dict[str, Any]:
    """Derive a rule only from one canonical provision observation.

    A verified document segment is still valid citable evidence, but retrieval
    relevance by itself never upgrades document-level text into rule semantics.
    """
    structured: dict[str, Any] = {
        "statement_scope": "canonical_provision",
        "document_ref": span["document_ref"],
        "authority_ref": span["authority_ref"],
        "evidence_refs": [span["evidence_ref"]],
    }
    structured.update(provision)

    fragment: dict[str, Any] = {
        "kind": "rule_fragment",
        "contract_version": CONTRACT_VERSION,
        "rule_ref": _stable_ref(
            "rule",
            CANONICAL_SOURCE_STATEMENT_RULE,
            RULE_SCHEMA_VERSION,
            structured,
        ),
        "rule_type": CANONICAL_SOURCE_STATEMENT_RULE,
        "rule_schema_version": RULE_SCHEMA_VERSION,
        "structured_data": structured,
        "derivation": {
            "method": "extractive_normalization",
            "version": RULE_DERIVATION_VERSION,
        },
        "authority_refs": [span["authority_ref"]],
        "evidence_refs": [span["evidence_ref"]],
    }
    temporal = authority["temporal_state"]
    if (
        as_of_date is not None
        and temporal.get("resolution_state") == "resolved"
        and temporal.get("effective") is True
    ):
        fragment["as_of_date"] = as_of_date
    return fragment


def _provision_index(
    statements: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in statements:
        provision = item.get("provision")
        if provision is None:
            continue
        ref = provision["provision_ref"]
        entry = grouped.setdefault(
            ref,
            {
                "authority_ref": item["authority_ref"],
                "document_ref": item["document_ref"],
                "evidence_refs": set(),
            },
        )
        if (
            entry["authority_ref"] != item["authority_ref"]
            or entry["document_ref"] != item["document_ref"]
        ):
            raise EvidenceGraphIntegrityError(
                f"provision {ref} has conflicting canonical identity"
            )
        entry["evidence_refs"].add(item["evidence_ref"])
    for entry in grouped.values():
        entry["evidence_refs"] = sorted(entry["evidence_refs"])
    return grouped


def _reference_rules(
    con: sqlite3.Connection,
    *,
    statements: list[dict[str, Any]],
    authorities: dict[str, dict[str, Any]],
    as_of_date: str | None,
) -> list[dict[str, Any]]:
    """Compose only provision references already resolved by canonical corpus logic."""
    provisions = _provision_index(statements)
    segment_sources = {
        item["candidate_segment_id"]: item["provision"]["provision_ref"]
        for item in statements
        if item.get("provision") is not None
    }
    if not segment_sources:
        return []

    placeholders = ",".join("?" for _ in segment_sources)
    rows = con.execute(
        f"""
        SELECT
            rm.extracted_segment_id,
            rr.target_provision_id,
            rr.resolution_method
        FROM reference_mentions rm
        JOIN reference_resolutions rr
          ON rr.reference_mention_id = rm.reference_mention_id
        WHERE rm.extracted_segment_id IN ({placeholders})
          AND rr.status = 'resolved'
          AND rr.requires_human_review = 0
          AND rr.target_provision_id IS NOT NULL
        ORDER BY
            rm.extracted_segment_id,
            rr.target_provision_id,
            rr.resolution_method
        """,
        sorted(segment_sources),
    ).fetchall()

    fragments: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_ref = segment_sources[row["extracted_segment_id"]]
        target_ref = f"provision:{row['target_provision_id']}"
        if source_ref not in provisions or target_ref not in provisions:
            # Resolved identity alone is not exact source evidence for a target.
            continue
        source = provisions[source_ref]
        target = provisions[target_ref]
        structured = {
            "source": {
                "provision_ref": source_ref,
                "authority_ref": source["authority_ref"],
                "evidence_refs": source["evidence_refs"],
            },
            "target": {
                "provision_ref": target_ref,
                "authority_ref": target["authority_ref"],
                "evidence_refs": target["evidence_refs"],
            },
            "resolution_method": row["resolution_method"],
        }
        structured["resolution_fingerprint_sha256"] = hashlib.sha256(
            _json(structured).encode("utf-8")
        ).hexdigest()
        authority_refs = sorted(
            {source["authority_ref"], target["authority_ref"]}
        )
        evidence_refs = sorted(
            set(source["evidence_refs"]) | set(target["evidence_refs"])
        )
        fragment: dict[str, Any] = {
            "kind": "rule_fragment",
            "contract_version": CONTRACT_VERSION,
            "rule_ref": _stable_ref(
                "rule",
                RESOLVED_PROVISION_REFERENCE_RULE,
                RULE_SCHEMA_VERSION,
                structured,
            ),
            "rule_type": RESOLVED_PROVISION_REFERENCE_RULE,
            "rule_schema_version": RULE_SCHEMA_VERSION,
            "structured_data": structured,
            "derivation": {
                "method": "deterministic_composition",
                "version": RULE_DERIVATION_VERSION,
            },
            "authority_refs": authority_refs,
            "evidence_refs": evidence_refs,
        }
        if as_of_date is not None and all(
            authorities[ref]["temporal_state"].get("resolution_state")
            == "resolved"
            and authorities[ref]["temporal_state"].get("effective") is True
            for ref in authority_refs
        ):
            fragment["as_of_date"] = as_of_date
        fragments[fragment["rule_ref"]] = fragment
    return [fragments[key] for key in sorted(fragments)]


def _status(
    research_status: str,
    research_unresolved: set[str],
    graph_unresolved: dict[str, dict[str, Any]],
) -> str:
    if research_status == "blocked":
        return "blocked"
    if research_status == "partial":
        return "partial"

    # An external-synthesis handoff is an intentional completed platform
    # boundary, not failed research. Other newly introduced uncertainty still
    # makes the bundle partial.
    for ref in set(graph_unresolved) - research_unresolved:
        if graph_unresolved[ref]["category"] != "requires_interpretive_synthesis":
            return "partial"
    return "complete"


def build_legal_research_bundle(
    *,
    case_input: dict[str, Any],
    intake_draft: dict[str, Any],
    research: ResearchExecution,
    db_path: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic read-only v4 evidence/rule/evaluation graph.

    Model-authored case/intake prose is copied only into contract-owned bundle
    objects. Rule semantics come from canonical evidence; #139 evaluators accept
    only explicitly supported structured facts and rules and never use model
    legal prose as authority.
    """
    db_path = Path(db_path)
    authorities = {
        item["authority_ref"]: deepcopy(item)
        for item in research.authorities
    }
    relationships = {
        item["relationship_ref"]: deepcopy(item)
        for item in research.relationships
    }
    unresolved = {
        item["unresolved_ref"]: deepcopy(item)
        for item in research.unresolved
    }
    _close_relationship_endpoints(
        db_path=db_path,
        authorities=authorities,
        relationships=relationships,
        unresolved=unresolved,
        as_of_date=case_input.get("as_of_date"),
    )

    con = _readonly(db_path)
    try:
        spans: dict[str, dict[str, Any]] = {}
        statements: list[dict[str, Any]] = []

        for evidence_ref in _required_evidence_refs(
            authorities.values(),
            relationships.values(),
            unresolved.values(),
        ):
            spans[evidence_ref] = _canonical_evidence_span(
                con,
                evidence_ref=evidence_ref,
                authorities=authorities,
            )

        for candidate in research.evidence_candidates:
            span, statement = _candidate_span(con, candidate)
            if span is None or statement is None:
                continue
            prior = spans.get(span["evidence_ref"])
            if prior is not None and prior != span:
                raise EvidenceGraphIntegrityError(
                    f"deterministic evidence-ref collision {span['evidence_ref']}"
                )
            spans[span["evidence_ref"]] = span
            statements.append(statement)

        source_refs = {
            ref
            for authority in authorities.values()
            for ref in authority["source_refs"]
        }
        source_refs.update(span["source_ref"] for span in spans.values())
        sources = {
            ref: _official_source(con, ref)
            for ref in sorted(source_refs)
        }

        rules: dict[str, dict[str, Any]] = {}
        for statement in statements:
            authority = authorities.get(statement["authority_ref"])
            if authority is None:
                raise EvidenceGraphIntegrityError(
                    "resolved research evidence has no authority object"
                )
            provision = statement.get("provision")
            if provision is None:
                # Exact canonical text remains citable EvidenceSpan material.
                # Search relevance alone is not legal-rule semantics.
                continue
            span = spans[statement["evidence_ref"]]
            rule = _statement_rule(
                span=span,
                provision=provision,
                authority=authority,
                as_of_date=case_input.get("as_of_date"),
            )
            rules[rule["rule_ref"]] = rule

        for rule in _reference_rules(
            con,
            statements=statements,
            authorities=authorities,
            as_of_date=case_input.get("as_of_date"),
        ):
            rules[rule["rule_ref"]] = rule
    finally:
        con.close()

    evaluation_outcome = evaluate_supported_rules(
        case_input=case_input,
        intake_draft=intake_draft,
        authorities=authorities.values(),
        evidence_spans=spans.values(),
        rule_fragments=rules.values(),
        generated_at=generated_at or research.result["generated_at"],
    )
    evaluations = {
        item["evaluation_ref"]: deepcopy(item)
        for item in evaluation_outcome.evaluations
    }
    calculations = {
        item["calculation_ref"]: deepcopy(item)
        for item in evaluation_outcome.calculations
    }
    for item in evaluation_outcome.unresolved:
        unresolved[item["unresolved_ref"]] = deepcopy(item)

    for collection in (
        sources.values(),
        authorities.values(),
        spans.values(),
        relationships.values(),
        rules.values(),
        evaluations.values(),
        calculations.values(),
        unresolved.values(),
    ):
        for item in collection:
            validate_contract_object(item)

    bundle = {
        "kind": "legal_research_bundle",
        "contract_version": CONTRACT_VERSION,
        "bundle_ref": _stable_ref(
            "bundle",
            research.result["result_ref"],
            sorted(sources),
            sorted(authorities),
            sorted(spans),
            sorted(relationships),
            sorted(rules),
            sorted(evaluations),
            sorted(calculations),
            sorted(unresolved),
            ANCHOR_VERSION,
            CANONICAL_EVIDENCE_SPAN_REF_VERSION,
            RULE_DERIVATION_VERSION,
        ),
        "status": _status(
            research.result["status"],
            set(research.result["unresolved_refs"]),
            unresolved,
        ),
        "case_input": deepcopy(case_input),
        "intake_draft": deepcopy(intake_draft),
        "research_plan": deepcopy(research.plan),
        "research_result": deepcopy(research.result),
        "sources": [deepcopy(sources[key]) for key in sorted(sources)],
        "authorities": [
            deepcopy(authorities[key]) for key in sorted(authorities)
        ],
        "evidence_spans": [
            deepcopy(spans[key]) for key in sorted(spans)
        ],
        "normative_relationships": [
            deepcopy(relationships[key]) for key in sorted(relationships)
        ],
        "rule_fragments": [
            deepcopy(rules[key]) for key in sorted(rules)
        ],
        "deterministic_evaluations": [
            deepcopy(evaluations[key]) for key in sorted(evaluations)
        ],
        "calculation_traces": [
            deepcopy(calculations[key]) for key in sorted(calculations)
        ],
        "unresolved": [
            deepcopy(unresolved[key]) for key in sorted(unresolved)
        ],
        "generated_at": generated_at or research.result["generated_at"],
    }
    validate_legal_research_bundle(bundle)
    return bundle
