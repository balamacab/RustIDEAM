#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from extract_document_temporality import PROCESSOR_NAME as TEMPORAL_PROCESSOR_NAME
from extract_document_temporality import PROCESSOR_VERSION as TEMPORAL_PROCESSOR_VERSION
from register_document_identity import IDENTITY_REVIEW_REASONS
from source_identity import (
    CORTE_CONSTITUCIONAL_SENTENCIA_C,
    DIAN_CONCEPTO,
    DIAN_OFICIO,
    JURISPRUDENCIA,
    UNKNOWN,
    classify_source_url,
)


CONTRACT_VERSION = "4.0.0"
CLASSIFIER_NAME = "canonical_legal_authority_classifier"
CLASSIFIER_VERSION = "1"

_NORMATIVE_TYPES = frozenset(
    {
        "CONSTITUCION_POLITICA",
        "LEY",
        "DECRETO",
        "RESOLUCION",
    }
)
_JURISPRUDENTIAL_TYPES = frozenset(
    {
        "SENTENCIA",
        "SENTENCIA_C",
        "AUTO",
    }
)
_ADMINISTRATIVE_INTERPRETATION_TYPES = frozenset({"CONCEPTO", "OFICIO"})
_GUIDANCE_TYPES = frozenset({"CIRCULAR", "TRAMITE_OFICIAL"})
_OTHER_TYPES = frozenset({"CONPES"})

_FAMILY_FUNCTION = {
    CORTE_CONSTITUCIONAL_SENTENCIA_C: "jurisprudential",
    JURISPRUDENCIA: "jurisprudential",
    DIAN_CONCEPTO: "administrative_interpretation",
    DIAN_OFICIO: "administrative_interpretation",
}

_TERMINATING_EVENT_TYPES = frozenset(
    {
        "repealed",
        "annulled",
        "suspended",
        "expired",
        "ceases_effect",
    }
)


class AuthorityClassificationError(RuntimeError):
    """Raised when a requested canonical authority cannot be materialized safely."""


def _ref(namespace: str, value: str) -> str:
    return f"{namespace}:{value}"


def _sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise AuthorityClassificationError(f"database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _document_row(con: sqlite3.Connection, document_id: str) -> sqlite3.Row:
    row = con.execute(
        """
        SELECT
            document_id,
            jurisdiction,
            entity,
            document_type,
            title,
            issued_date,
            publication_date
        FROM documents
        WHERE document_id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise AuthorityClassificationError(
            f"canonical document not found: {document_id}"
        )
    return row


def _source_rows(
    con: sqlite3.Connection,
    document_id: str,
) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT DISTINCT
            s.source_id,
            s.source_url,
            s.authority,
            s.source_kind
        FROM manifestations m
        JOIN sources s ON s.source_id = m.source_id
        WHERE m.document_id = ?
        ORDER BY s.source_id
        """,
        (document_id,),
    ).fetchall()


def _official_sources(source_rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    return [
        {
            "kind": "official_source",
            "contract_version": CONTRACT_VERSION,
            "source_ref": _ref("source", row["source_id"]),
            "authority": row["authority"],
            "source_uri": row["source_url"],
            "source_kind": row["source_kind"],
        }
        for row in source_rows
    ]


def _source_families(
    con: sqlite3.Connection,
    document_id: str,
    source_rows: list[sqlite3.Row],
) -> list[str]:
    values = {
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT dis.source_family
            FROM document_identity_signals dis
            JOIN manifestations m
              ON m.manifestation_id = dis.manifestation_id
            WHERE m.document_id = ?
              AND dis.source_family IS NOT NULL
              AND dis.source_family != ?
            """,
            (document_id, UNKNOWN),
        ).fetchall()
    }

    # Reuse the canonical source-family parser rather than inventing a second
    # URL taxonomy for the authority layer. Persisted identity signals win no
    # special precedence here: disagreement is retained as ambiguity below.
    for row in source_rows:
        family = classify_source_url(row["source_url"]).family
        if family != UNKNOWN:
            values.add(family)

    return sorted(values)


def _issuer_resolution(
    con: sqlite3.Connection,
    document: sqlite3.Row,
) -> tuple[str | None, bool]:
    candidates: set[str] = set()

    entity = (document["entity"] or "").strip()
    if entity and entity.upper() != "UNKNOWN":
        candidates.add(entity)

    candidates.update(
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT issuer
            FROM document_identifiers
            WHERE document_id = ?
              AND issuer IS NOT NULL
              AND TRIM(issuer) != ''
            """,
            (document["document_id"],),
        ).fetchall()
    )

    if len(candidates) == 1:
        return next(iter(candidates)), False
    return None, len(candidates) > 1


def _metadata_flag(
    con: sqlite3.Connection,
    table: str,
    document_id: str,
) -> bool:
    if table not in {"dian_doctrine_metadata", "official_guidance_metadata"}:
        raise ValueError(f"unsupported metadata table: {table}")
    return (
        con.execute(
            f"SELECT 1 FROM {table} WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
        is not None
    )


def _document_type_function(document_type: str) -> str | None:
    if document_type in _NORMATIVE_TYPES:
        return "normative"
    if (
        document_type in _JURISPRUDENTIAL_TYPES
        or document_type.startswith("SENTENCIA_")
    ):
        return "jurisprudential"
    if document_type in _ADMINISTRATIVE_INTERPRETATION_TYPES:
        return "administrative_interpretation"
    if document_type in _GUIDANCE_TYPES:
        return "guidance"
    if document_type in _OTHER_TYPES:
        return "other"
    return None


def _legal_function(
    *,
    document_type: str,
    source_families: list[str],
    has_doctrine_metadata: bool,
    has_guidance_metadata: bool,
) -> tuple[str, bool]:
    candidates: set[str] = set()

    type_function = _document_type_function(document_type)
    if type_function is not None:
        candidates.add(type_function)

    if has_doctrine_metadata:
        candidates.add("administrative_interpretation")
    if has_guidance_metadata:
        candidates.add("guidance")

    for family in source_families:
        mapped = _FAMILY_FUNCTION.get(family)
        if mapped is not None:
            candidates.add(mapped)

    if len(candidates) == 1:
        return next(iter(candidates)), False
    if len(candidates) > 1:
        return "unknown", True
    return "unknown", False


def _identity_review_reasons(
    con: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    placeholders = ",".join("?" for _ in IDENTITY_REVIEW_REASONS)
    rows = con.execute(
        f"""
        SELECT DISTINCT rq.reason_code
        FROM review_queue rq
        LEFT JOIN manifestations m
          ON rq.entity_type = 'manifestation'
         AND rq.entity_id = m.manifestation_id
        WHERE rq.resolved_at IS NULL
          AND (
                (rq.entity_type = 'document' AND rq.entity_id = ?)
                OR m.document_id = ?
              )
          AND rq.reason_code IN ({placeholders})
        ORDER BY rq.reason_code
        """,
        [document_id, document_id, *sorted(IDENTITY_REVIEW_REASONS)],
    ).fetchall()
    return [row[0] for row in rows]


def _provision_refs(
    con: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    return [
        _ref("provision", row[0])
        for row in con.execute(
            """
            SELECT provision_id
            FROM provisions
            WHERE document_id = ?
            ORDER BY provision_id
            """,
            (document_id,),
        ).fetchall()
    ]


def _identity_evidence_refs(
    con: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    return [
        _ref("evidence", row[0])
        for row in con.execute(
            """
            SELECT DISTINCT die.evidence_id
            FROM document_identifiers di
            JOIN document_identifier_evidence die
              ON die.identifier_id = di.identifier_id
            WHERE di.document_id = ?
            ORDER BY die.evidence_id
            """,
            (document_id,),
        ).fetchall()
    ]


def _current_role_rows(
    con: sqlite3.Connection,
    document_id: str,
    role: str,
) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT
            tr.status,
            tc.candidate_date,
            tc.evidence_id
        FROM temporal_role_resolutions tr
        LEFT JOIN temporal_candidates tc
          ON tc.temporal_candidate_id = tr.promoted_candidate_id
        WHERE tr.document_id = ?
          AND tr.role = ?
          AND tr.processor_name = ?
          AND tr.processor_version = ?
        ORDER BY tr.extraction_id
        """,
        (
            document_id,
            role,
            TEMPORAL_PROCESSOR_NAME,
            TEMPORAL_PROCESSOR_VERSION,
        ),
    ).fetchall()


def _event_evidence_refs(
    con: sqlite3.Connection,
    event_id: str,
    primary_evidence_id: str | None,
) -> list[str]:
    values: set[str] = set()
    if primary_evidence_id:
        values.add(primary_evidence_id)
    values.update(
        row[0]
        for row in con.execute(
            """
            SELECT evidence_id
            FROM temporal_event_evidence
            WHERE temporal_event_id = ?
            ORDER BY evidence_id
            """,
            (event_id,),
        ).fetchall()
    )
    return [_ref("evidence", value) for value in sorted(values)]


def _publication_metadata(
    con: sqlite3.Connection,
    document: sqlite3.Row,
) -> dict[str, object]:
    dates: set[str] = set()
    evidence_refs: set[str] = set()
    role_rows = _current_role_rows(
        con,
        document["document_id"],
        "publication_date",
    )
    role_statuses = {row["status"] for row in role_rows}

    for row in role_rows:
        if row["status"] != "resolved":
            continue
        if row["candidate_date"]:
            dates.add(row["candidate_date"])
        if row["evidence_id"]:
            evidence_refs.add(_ref("evidence", row["evidence_id"]))

    for row in con.execute(
        """
        SELECT temporal_event_id, event_date, evidence_id
        FROM temporal_events
        WHERE entity_type = 'document'
          AND entity_id = ?
          AND event_type = 'published'
          AND status = 'validated'
          AND requires_human_review = 0
        ORDER BY temporal_event_id
        """,
        (document["document_id"],),
    ).fetchall():
        if row["event_date"]:
            dates.add(row["event_date"])
        evidence_refs.update(
            _event_evidence_refs(
                con,
                row["temporal_event_id"],
                row["evidence_id"],
            )
        )

    # The document-level field is retained as current derived state. If it has
    # no accompanying evidence in the current temporal model, expose it only as
    # partial metadata rather than pretending it has evidentiary resolution.
    document_publication = document["publication_date"]
    if document_publication:
        dates.add(document_publication)

    if "ambiguous" in role_statuses or len(dates) > 1:
        state = "ambiguous"
    elif dates and "unresolved" in role_statuses:
        state = "partial"
    elif dates and evidence_refs:
        state = "resolved"
    elif dates:
        state = "partial"
    else:
        state = "unknown"

    return {
        "state": state,
        "publication_dates": sorted(dates),
        # The current corpus has issuance and publication semantics but no
        # dedicated promulgation fact. Do not relabel issued_date as promulgation.
        "promulgation_dates": [],
        "evidence_refs": sorted(evidence_refs),
    }


def _temporal_event_rows(
    con: sqlite3.Connection,
    document_id: str,
) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT
            temporal_event_id,
            event_type,
            event_date,
            effective_from,
            effective_to,
            evidence_id
        FROM temporal_events
        WHERE entity_type = 'document'
          AND entity_id = ?
          AND status = 'validated'
          AND requires_human_review = 0
        ORDER BY temporal_event_id
        """,
        (document_id,),
    ).fetchall()


def _event_date(row: sqlite3.Row) -> str | None:
    return row["effective_from"] or row["event_date"]


def _parse_iso_date(value: str, *, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AuthorityClassificationError(
            f"{field} must be an ISO date (YYYY-MM-DD): {value!r}"
        ) from exc


def _unresolved_item(
    document_id: str,
    *,
    suffix: str,
    category: str,
    description: str,
    evidence_refs: Iterable[str] = (),
) -> dict[str, object]:
    item: dict[str, object] = {
        "kind": "unresolved_item",
        "contract_version": CONTRACT_VERSION,
        "unresolved_ref": _ref(
            "unresolved",
            f"{document_id}.{suffix.lower()}",
        ),
        "stage": "authority",
        "category": category,
        "description": description,
        "related_authority_refs": [_ref("authority", document_id)],
        "next_action": "human_review",
    }
    evidence = _sorted_unique(evidence_refs)
    if evidence:
        item["related_evidence_refs"] = evidence
    return item


def _temporal_state(
    con: sqlite3.Connection,
    document_id: str,
    as_of_date: str | None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if as_of_date is None:
        return (
            {
                "resolution_state": "not_applicable",
                "effective": None,
                "basis_evidence_refs": [],
            },
            [],
        )

    as_of = _parse_iso_date(as_of_date, field="as_of_date")
    role_rows = _current_role_rows(con, document_id, "commencement_rule")
    role_statuses = {row["status"] for row in role_rows}

    events = _temporal_event_rows(con, document_id)
    evidence_refs: set[str] = set()
    for row in events:
        if (
            row["event_type"] == "enters_into_force"
            or row["event_type"] in _TERMINATING_EVENT_TYPES
        ):
            evidence_refs.update(
                _event_evidence_refs(
                    con,
                    row["temporal_event_id"],
                    row["evidence_id"],
                )
            )
    for row in role_rows:
        if row["evidence_id"]:
            evidence_refs.add(_ref("evidence", row["evidence_id"]))

    if "ambiguous" in role_statuses:
        item = _unresolved_item(
            document_id,
            suffix="temporal-ambiguous",
            category="temporal_uncertainty",
            description=(
                "Current commencement evidence is ambiguous; no as-of legal "
                "effect is guessed."
            ),
            evidence_refs=evidence_refs,
        )
        return (
            {
                "as_of_date": as_of_date,
                "resolution_state": "ambiguous",
                "effective": None,
                "basis_evidence_refs": sorted(evidence_refs),
            },
            [item],
        )

    terminating: list[tuple[date, sqlite3.Row]] = []
    commencement: list[tuple[date, sqlite3.Row]] = []
    for row in events:
        raw_date = _event_date(row)
        if not raw_date:
            continue
        parsed = _parse_iso_date(raw_date, field="temporal_event date")
        if row["event_type"] in _TERMINATING_EVENT_TYPES:
            terminating.append((parsed, row))
        elif row["event_type"] == "enters_into_force":
            commencement.append((parsed, row))

    # An explicit terminating event is sufficient to support non-effect from
    # that point forward. Relationship absence is deliberately not treated as
    # proof that a document remains effective.
    applicable_terminations = [item for item in terminating if item[0] <= as_of]
    if applicable_terminations:
        return (
            {
                "as_of_date": as_of_date,
                "resolution_state": "resolved",
                "effective": False,
                "basis_evidence_refs": sorted(evidence_refs),
            },
            [],
        )

    distinct_starts = sorted({item[0] for item in commencement})
    if len(distinct_starts) > 1:
        item = _unresolved_item(
            document_id,
            suffix="temporal-conflict",
            category="temporal_uncertainty",
            description=(
                "Multiple validated commencement dates are present; no as-of "
                "legal effect is guessed."
            ),
            evidence_refs=evidence_refs,
        )
        return (
            {
                "as_of_date": as_of_date,
                "resolution_state": "ambiguous",
                "effective": None,
                "basis_evidence_refs": sorted(evidence_refs),
            },
            [item],
        )

    if len(distinct_starts) == 1:
        start = distinct_starts[0]
        if as_of < start:
            return (
                {
                    "as_of_date": as_of_date,
                    "resolution_state": "resolved",
                    "effective": False,
                    "basis_evidence_refs": sorted(evidence_refs),
                },
                [],
            )

        # True effect requires a supported interval, not merely the absence of
        # repeal evidence. This preserves the project's no-inferred-legal-truth
        # invariant while still exposing exact as-of state where supported.
        relevant_rows = [
            row for parsed, row in commencement if parsed == start
        ]
        explicit_ends = {
            _parse_iso_date(row["effective_to"], field="effective_to")
            for row in relevant_rows
            if row["effective_to"]
        }
        if len(explicit_ends) == 1:
            end = next(iter(explicit_ends))
            return (
                {
                    "as_of_date": as_of_date,
                    "resolution_state": "resolved",
                    "effective": as_of <= end,
                    "basis_evidence_refs": sorted(evidence_refs),
                },
                [],
            )
        if len(explicit_ends) > 1:
            item = _unresolved_item(
                document_id,
                suffix="temporal-end-conflict",
                category="temporal_uncertainty",
                description=(
                    "Conflicting supported effective-to dates are present; "
                    "no as-of legal effect is guessed."
                ),
                evidence_refs=evidence_refs,
            )
            return (
                {
                    "as_of_date": as_of_date,
                    "resolution_state": "ambiguous",
                    "effective": None,
                    "basis_evidence_refs": sorted(evidence_refs),
                },
                [item],
            )

    item = _unresolved_item(
        document_id,
        suffix="temporal-unresolved",
        category="temporal_uncertainty",
        description=(
            "The corpus does not contain sufficient positive temporal evidence "
            "to determine legal effect for the requested as-of date."
        ),
        evidence_refs=evidence_refs,
    )
    return (
        {
            "as_of_date": as_of_date,
            "resolution_state": "unresolved",
            "effective": None,
            "basis_evidence_refs": sorted(evidence_refs),
        },
        [item],
    )


def _endpoint_document_id(
    con: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
) -> str | None:
    if entity_type == "document":
        row = con.execute(
            "SELECT document_id FROM documents WHERE document_id = ?",
            (entity_id,),
        ).fetchone()
        return row[0] if row else None
    if entity_type == "provision":
        row = con.execute(
            "SELECT document_id FROM provisions WHERE provision_id = ?",
            (entity_id,),
        ).fetchone()
        return row[0] if row else None
    return None


def _normative_relationships(
    con: sqlite3.Connection,
    document_id: str,
) -> list[dict[str, object]]:
    provision_ids = {
        row[0]
        for row in con.execute(
            "SELECT provision_id FROM provisions WHERE document_id = ?",
            (document_id,),
        ).fetchall()
    }

    rows = con.execute(
        """
        SELECT
            relationship_id,
            source_type,
            source_id,
            relation_type,
            target_type,
            target_id,
            evidence_id
        FROM relationships
        WHERE status = 'validated'
          AND requires_human_review = 0
          AND evidence_id IS NOT NULL
        ORDER BY relationship_id
        """
    ).fetchall()

    output: list[dict[str, object]] = []
    for row in rows:
        touches_document = (
            (
                row["source_type"] == "document"
                and row["source_id"] == document_id
            )
            or (
                row["source_type"] == "provision"
                and row["source_id"] in provision_ids
            )
            or (
                row["target_type"] == "document"
                and row["target_id"] == document_id
            )
            or (
                row["target_type"] == "provision"
                and row["target_id"] in provision_ids
            )
        )
        if not touches_document:
            continue

        source_document = _endpoint_document_id(
            con,
            row["source_type"],
            row["source_id"],
        )
        target_document = _endpoint_document_id(
            con,
            row["target_type"],
            row["target_id"],
        )
        if source_document is None or target_document is None:
            # The canonical relationship contract currently owns document /
            # provision endpoints. Unsupported polymorphic endpoints are not
            # silently coerced into document authority.
            continue

        output.append(
            {
                "kind": "normative_relationship",
                "contract_version": CONTRACT_VERSION,
                "relationship_ref": _ref(
                    "relationship",
                    row["relationship_id"],
                ),
                "relationship_type": row["relation_type"],
                "source_authority_ref": _ref(
                    "authority",
                    source_document,
                ),
                "target_authority_ref": _ref(
                    "authority",
                    target_document,
                ),
                "evidence_refs": [
                    _ref("evidence", row["evidence_id"])
                ],
                "provenance_ref": _ref(
                    "provenance",
                    row["relationship_id"],
                ),
                "status": "resolved",
            }
        )

    return output


def _display_name(
    con: sqlite3.Connection,
    document: sqlite3.Row,
) -> str:
    if document["title"] and document["title"].strip():
        return document["title"].strip()
    primary = con.execute(
        """
        SELECT identifier_value
        FROM document_identifiers
        WHERE document_id = ?
          AND is_primary = 1
        ORDER BY identifier_value
        LIMIT 1
        """,
        (document["document_id"],),
    ).fetchone()
    if primary:
        return primary[0]
    return f"{document['document_type']} {document['document_id']}"


def classify_canonical_authority(
    *,
    document_id: str,
    db_path: Path,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Materialize deterministic v4 authority metadata from canonical corpus state.

    The classifier is intentionally read-only. It reuses canonical identity,
    issuer, source-family, temporal and relationship state and never creates a
    parallel legal identity or infers legal truth from missing evidence.

    The returned mapping contains one CanonicalAuthority, its OfficialSource
    views, supported NormativeRelationship views and explicit UnresolvedItems.
    EvidenceSpan materialization remains owned by issue #138.
    """
    con = _readonly_connection(db_path)
    try:
        document = _document_row(con, document_id)
        source_rows = _source_rows(con, document_id)
        sources = _official_sources(source_rows)
        source_families = _source_families(
            con,
            document_id,
            source_rows,
        )
        issuer, issuer_conflict = _issuer_resolution(con, document)
        identity_review_reasons = _identity_review_reasons(
            con,
            document_id,
        )

        has_doctrine = _metadata_flag(
            con,
            "dian_doctrine_metadata",
            document_id,
        )
        has_guidance = _metadata_flag(
            con,
            "official_guidance_metadata",
            document_id,
        )
        legal_function, function_conflict = _legal_function(
            document_type=document["document_type"],
            source_families=source_families,
            has_doctrine_metadata=has_doctrine,
            has_guidance_metadata=has_guidance,
        )

        unresolved: list[dict[str, object]] = []
        classification_ambiguous = (
            issuer_conflict
            or len(source_families) > 1
            or function_conflict
            or bool(identity_review_reasons)
        )

        authority_ref = _ref("authority", document_id)
        if classification_ambiguous:
            description_parts = []
            if issuer_conflict:
                description_parts.append("issuer signals conflict")
            if len(source_families) > 1:
                description_parts.append(
                    "multiple source families are attached to the canonical "
                    "document"
                )
            if function_conflict:
                description_parts.append("legal-function signals conflict")
            if identity_review_reasons:
                description_parts.append(
                    "open identity review: "
                    + ", ".join(identity_review_reasons)
                )
            unresolved.append(
                _unresolved_item(
                    document_id,
                    suffix="classification-ambiguous",
                    category="conflicting_authority",
                    description="; ".join(description_parts) + ".",
                )
            )
            classification_state = "ambiguous"
        elif legal_function == "unknown":
            classification_state = "unknown"
            unresolved.append(
                _unresolved_item(
                    document_id,
                    suffix="classification-unknown",
                    category="other",
                    description=(
                        "Existing canonical corpus semantics do not support a "
                        "legal-function classification for this document."
                    ),
                )
            )
        else:
            missing = []
            if issuer is None:
                missing.append("issuer")
            if not (document["jurisdiction"] or "").strip():
                missing.append("jurisdiction")
            if not source_families:
                missing.append("source family")
            if not sources:
                missing.append("official source")
            classification_state = "partial" if missing else "resolved"
            if missing:
                unresolved.append(
                    _unresolved_item(
                        document_id,
                        suffix="classification-partial",
                        category="other",
                        description=(
                            "Authority classification is supported, but the "
                            "following metadata is not resolved: "
                            + ", ".join(missing)
                            + "."
                        ),
                    )
                )

        publication_metadata = _publication_metadata(con, document)
        temporal_state, temporal_unresolved = _temporal_state(
            con,
            document_id,
            as_of_date,
        )
        unresolved.extend(temporal_unresolved)

        relationships = _normative_relationships(con, document_id)
        relationship_refs = [
            item["relationship_ref"]
            for item in relationships
        ]

        evidence_refs = set(_identity_evidence_refs(con, document_id))
        evidence_refs.update(publication_metadata["evidence_refs"])
        evidence_refs.update(temporal_state["basis_evidence_refs"])
        for relationship in relationships:
            evidence_refs.update(relationship["evidence_refs"])

        authority: dict[str, object] = {
            "kind": "canonical_authority",
            "contract_version": CONTRACT_VERSION,
            "authority_ref": authority_ref,
            "document_ref": _ref("document", document_id),
            "provision_refs": _provision_refs(con, document_id),
            "display_name": _display_name(con, document),
            "document_type": document["document_type"],
            "legal_function": legal_function,
            "classification_state": classification_state,
            "temporal_state": temporal_state,
            "evidence_refs": sorted(evidence_refs),
            "relationship_refs": sorted(relationship_refs),
            "source_refs": [
                source["source_ref"]
                for source in sources
            ],
            "publication_metadata": publication_metadata,
        }
        if issuer is not None:
            authority["issuer"] = issuer
        if document["jurisdiction"] and document["jurisdiction"].strip():
            authority["jurisdiction_scope"] = document[
                "jurisdiction"
            ].strip()
        if len(source_families) == 1:
            authority["source_family"] = source_families[0]

        return {
            "classifier": {
                "name": CLASSIFIER_NAME,
                "version": CLASSIFIER_VERSION,
            },
            "authority": authority,
            "sources": sources,
            "relationships": relationships,
            "unresolved": sorted(
                unresolved,
                key=lambda item: item["unresolved_ref"],
            ),
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize deterministic v4 legal-authority metadata from "
            "canonical col-taxdata state without mutating the database."
        )
    )
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--as-of-date")
    args = parser.parse_args()

    result = classify_canonical_authority(
        document_id=args.document_id,
        db_path=Path(args.db),
        as_of_date=args.as_of_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
