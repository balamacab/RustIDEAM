#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from source_identity import (
    ISSUER_SCOPED_TYPES,
    IdentityAssessment,
    IdentitySignal,
    assess_generic_normative_identity,
    canonical_identifier_values,
    persist_assessment,
)


MIGRATION_REASON = "DEF-0002_ISSUER_COLLISION_SPLIT"
ISSUER_BACKFILL_REASON = "DEF-0002_ISSUER_KEY_BACKFILL"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, material).hex}"


@dataclass(frozen=True)
class ManifestationMove:
    legacy_document_id: str
    legacy_canonical_key: str
    manifestation_id: str
    extraction_id: str
    source_url: str
    heading: str
    issuer_key: str
    new_document_id: str
    new_canonical_key: str
    signal: IdentitySignal
    assessment: IdentityAssessment


@dataclass(frozen=True)
class IssuerBackfill:
    document_id: str
    legacy_canonical_key: str
    new_canonical_key: str
    issuer_key: str
    moves: tuple[ManifestationMove, ...]


def primary_canonical_key(con: sqlite3.Connection, document_id: str) -> str | None:
    row = con.execute(
        """
        SELECT identifier_value
        FROM document_identifiers
        WHERE document_id = ?
          AND identifier_type = 'canonical_key'
        ORDER BY is_primary DESC, identifier_id
        LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    return row[0] if row else None


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT
            m.manifestation_id,
            m.document_id,
            s.source_url,
            te.extraction_id,
            (
                SELECT es.text
                FROM extracted_segments es
                WHERE es.extraction_id = te.extraction_id
                  AND es.segment_type = 'document_heading'
                ORDER BY es.sequence_no
                LIMIT 1
            ) AS heading
        FROM manifestations m
        JOIN sources s ON s.source_id = m.source_id
        JOIN text_extractions te
          ON te.extraction_id = (
              SELECT te2.extraction_id
              FROM text_extractions te2
              WHERE te2.manifestation_id = m.manifestation_id
                AND te2.status = 'success'
              ORDER BY te2.created_at DESC, te2.extraction_id DESC
              LIMIT 1
          )
        WHERE m.document_id IS NOT NULL
          AND s.source_url LIKE
              'https://normograma.dian.gov.co/dian/compilacion/docs/%'
        ORDER BY m.document_id, m.manifestation_id
        """
    ).fetchall()


def build_plan(con: sqlite3.Connection) -> dict[str, object]:
    """Build a mutation-free collision split plan from trusted identity signals."""
    grouped: dict[str, list[ManifestationMove]] = defaultdict(list)
    skipped_unresolved: list[dict[str, str]] = []

    for row in candidate_rows(con):
        manifestation_id, old_document_id, source_url, extraction_id, heading = row
        assessment = assess_generic_normative_identity(source_url, heading or "")
        if not assessment.accepted or assessment.content is None:
            continue
        signal = assessment.content
        if signal.document_type not in ISSUER_SCOPED_TYPES:
            continue
        if signal.issuer_key is None or signal.canonical_key is None:
            skipped_unresolved.append(
                {
                    "manifestation_id": manifestation_id,
                    "source_url": source_url,
                    "reason": "ISSUER_IDENTITY_UNRESOLVED",
                }
            )
            continue
        new_document_id = deterministic_id("DOC", signal.canonical_key)
        if new_document_id == old_document_id:
            continue
        legacy_key = primary_canonical_key(con, old_document_id)
        if legacy_key is None:
            skipped_unresolved.append(
                {
                    "manifestation_id": manifestation_id,
                    "source_url": source_url,
                    "reason": "LEGACY_CANONICAL_KEY_MISSING",
                }
            )
            continue
        grouped[old_document_id].append(
            ManifestationMove(
                legacy_document_id=old_document_id,
                legacy_canonical_key=legacy_key,
                manifestation_id=manifestation_id,
                extraction_id=extraction_id,
                source_url=source_url,
                heading=heading or "",
                issuer_key=signal.issuer_key,
                new_document_id=new_document_id,
                new_canonical_key=signal.canonical_key,
                signal=signal,
                assessment=assessment,
            )
        )

    collision_groups: list[dict[str, object]] = []
    issuer_backfills: list[IssuerBackfill] = []
    conflicts: list[dict[str, object]] = []
    all_moves: list[ManifestationMove] = []

    for legacy_document_id, moves in sorted(grouped.items()):
        issuers = sorted({item.issuer_key for item in moves})

        total_linked = con.execute(
            "SELECT COUNT(*) FROM manifestations WHERE document_id = ?",
            (legacy_document_id,),
        ).fetchone()[0]
        planned_manifestations = {item.manifestation_id for item in moves}
        if total_linked != len(planned_manifestations):
            conflicts.append(
                {
                    "legacy_document_id": legacy_document_id,
                    "reason": "UNCLASSIFIED_LINKED_MANIFESTATIONS",
                    "linked": total_linked,
                    "planned": len(planned_manifestations),
                }
            )
            continue

        if len(issuers) == 1:
            new_keys = {item.new_canonical_key for item in moves}
            if len(new_keys) != 1:
                conflicts.append(
                    {
                        "legacy_document_id": legacy_document_id,
                        "reason": "INCONSISTENT_ISSUER_AWARE_KEYS",
                        "keys": sorted(new_keys),
                    }
                )
                continue
            # A five-part primary key is already issuer-aware. This keeps
            # repeated execution idempotent even when an older stable document
            # ID intentionally differs from a freshly generated deterministic ID.
            if len(moves[0].legacy_canonical_key.split(":")) == 5:
                continue
            issuer_backfills.append(
                IssuerBackfill(
                    document_id=legacy_document_id,
                    legacy_canonical_key=moves[0].legacy_canonical_key,
                    new_canonical_key=next(iter(new_keys)),
                    issuer_key=issuers[0],
                    moves=tuple(moves),
                )
            )
            continue

        old_provisions = [
            row[0]
            for row in con.execute(
                "SELECT provision_id FROM provisions WHERE document_id = ?",
                (legacy_document_id,),
            ).fetchall()
        ]
        if old_provisions:
            p1 = ",".join("?" for _ in old_provisions)
            p2 = ",".join("?" for _ in planned_manifestations)
            unmapped = con.execute(
                f"""
                SELECT COUNT(*)
                FROM provision_observations po
                JOIN text_extractions te ON te.extraction_id = po.extraction_id
                WHERE po.provision_id IN ({p1})
                  AND te.manifestation_id NOT IN ({p2})
                """,
                (*old_provisions, *sorted(planned_manifestations)),
            ).fetchone()[0]
            if unmapped:
                conflicts.append(
                    {
                        "legacy_document_id": legacy_document_id,
                        "reason": "UNMAPPED_PROVISION_OBSERVATIONS",
                        "count": unmapped,
                    }
                )
                continue

        collision_groups.append(
            {
                "legacy_document_id": legacy_document_id,
                "legacy_canonical_key": moves[0].legacy_canonical_key,
                "issuers": issuers,
                "manifestations": len(planned_manifestations),
                "new_documents": sorted({item.new_document_id for item in moves}),
            }
        )
        all_moves.extend(moves)

    affected_old_docs = sorted({m.legacy_document_id for m in all_moves})
    affected_manifestations = sorted(
        {m.manifestation_id for m in all_moves}
        | {
            move.manifestation_id
            for backfill in issuer_backfills
            for move in backfill.moves
        }
    )
    old_provision_ids: list[str] = []
    if affected_old_docs:
        q = ",".join("?" for _ in affected_old_docs)
        old_provision_ids = [
            row[0]
            for row in con.execute(
                f"SELECT provision_id FROM provisions WHERE document_id IN ({q})",
                affected_old_docs,
            ).fetchall()
        ]

    relationship_count = 0
    resolution_count = 0
    ids = affected_old_docs + old_provision_ids
    if ids:
        q = ",".join("?" for _ in ids)
        relationship_count = con.execute(
            f"""
            SELECT COUNT(*) FROM relationships
            WHERE source_id IN ({q}) OR target_id IN ({q})
            """,
            (*ids, *ids),
        ).fetchone()[0]
    if affected_old_docs or old_provision_ids:
        doc_q = ",".join("?" for _ in affected_old_docs) or "''"
        prov_q = ",".join("?" for _ in old_provision_ids) or "''"
        resolution_count = con.execute(
            f"""
            SELECT COUNT(*) FROM reference_resolutions
            WHERE target_document_id IN ({doc_q})
               OR target_provision_id IN ({prov_q})
            """,
            (*affected_old_docs, *old_provision_ids),
        ).fetchone()[0]

    return {
        "collision_groups": collision_groups,
        "issuer_backfill_groups": [
            {
                "document_id": item.document_id,
                "legacy_canonical_key": item.legacy_canonical_key,
                "new_canonical_key": item.new_canonical_key,
                "issuer_key": item.issuer_key,
                "manifestations": len(item.moves),
            }
            for item in issuer_backfills
        ],
        "moves": all_moves,
        "backfills": issuer_backfills,
        "conflicts": conflicts,
        "skipped_unresolved": skipped_unresolved,
        "metrics": {
            "collision_group_count": len(collision_groups),
            "issuer_backfill_documents": len(issuer_backfills),
            "affected_manifestations": len(affected_manifestations),
            "new_documents": len({m.new_document_id for m in all_moves}),
            "legacy_documents_to_delete": len(affected_old_docs),
            "relationships_to_rebuild": relationship_count,
            "reference_resolutions_to_rebuild": resolution_count,
        },
    }


def hash_snapshot(
    con: sqlite3.Connection,
    manifestation_ids: set[str],
) -> list[tuple[str, str, str, str]]:
    if not manifestation_ids:
        return []
    q = ",".join("?" for _ in manifestation_ids)
    return con.execute(
        f"""
        SELECT m.manifestation_id, m.sha256,
               te.extraction_id, te.normalized_sha256
        FROM manifestations m
        JOIN text_extractions te ON te.manifestation_id = m.manifestation_id
        WHERE m.manifestation_id IN ({q})
        ORDER BY m.manifestation_id, te.extraction_id
        """,
        sorted(manifestation_ids),
    ).fetchall()


def create_identifiers_and_provenance(
    con: sqlite3.Connection,
    move: ManifestationMove,
    now: str,
) -> tuple[int, int]:
    inserted_identifiers = 0
    evidence_links = 0
    for value, is_primary in canonical_identifier_values(move.signal):
        identifier_id = deterministic_id(
            "ID", f"{move.new_document_id}:canonical:{value}"
        )
        existed = con.execute(
            "SELECT 1 FROM document_identifiers WHERE identifier_id = ?",
            (identifier_id,),
        ).fetchone()
        con.execute(
            """
            INSERT INTO document_identifiers(
                identifier_id, document_id, identifier_type,
                identifier_value, issuer, is_primary
            )
            VALUES (?, ?, 'canonical_key', ?, ?, ?)
            ON CONFLICT(document_id, identifier_type, identifier_value)
            DO UPDATE SET issuer=excluded.issuer, is_primary=excluded.is_primary
            """,
            (
                identifier_id,
                move.new_document_id,
                value,
                move.issuer_key,
                is_primary,
            ),
        )
        inserted_identifiers += int(existed is None)

        evidence_rows = con.execute(
            """
            SELECT DISTINCT die.evidence_id, die.evidence_role
            FROM document_identifier_evidence die
            JOIN document_identifiers old_di
              ON old_di.identifier_id = die.identifier_id
            JOIN evidence e ON e.evidence_id = die.evidence_id
            WHERE old_di.document_id = ?
              AND e.manifestation_id = ?
            """,
            (move.legacy_document_id, move.manifestation_id),
        ).fetchall()
        for evidence_id, evidence_role in evidence_rows:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO document_identifier_evidence(
                    identifier_id, evidence_id, evidence_role, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (identifier_id, evidence_id, evidence_role, now),
            )
            evidence_links += int(bool(cur.rowcount))
    return inserted_identifiers, evidence_links


def rebind_provisions(
    con: sqlite3.Connection,
    old_document_id: str,
    manifestation_targets: dict[str, str],
    now: str,
) -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    mapping: dict[tuple[str, str], str] = {}
    counts = {"new_provisions": 0, "provision_observations_rebound": 0}
    provisions = con.execute(
        """
        SELECT provision_id, provision_type, designation,
               normalized_designation, title, created_at, updated_at
        FROM provisions
        WHERE document_id = ?
        ORDER BY provision_id
        """,
        (old_document_id,),
    ).fetchall()

    for row in provisions:
        old_provision_id = row[0]
        observation_targets = con.execute(
            """
            SELECT DISTINCT te.manifestation_id
            FROM provision_observations po
            JOIN text_extractions te ON te.extraction_id = po.extraction_id
            WHERE po.provision_id = ?
            ORDER BY te.manifestation_id
            """,
            (old_provision_id,),
        ).fetchall()
        for (manifestation_id,) in observation_targets:
            target_document_id = manifestation_targets[manifestation_id]
            new_provision_id = deterministic_id(
                "PROV",
                f"{target_document_id}:{row[1].upper()}:{row[3]}",
            )
            mapping[(old_provision_id, target_document_id)] = new_provision_id
            existed = con.execute(
                "SELECT 1 FROM provisions WHERE provision_id = ?",
                (new_provision_id,),
            ).fetchone()
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, normalized_designation) DO UPDATE SET
                    title = COALESCE(provisions.title, excluded.title),
                    updated_at = excluded.updated_at
                """,
                (
                    new_provision_id,
                    target_document_id,
                    row[1], row[2], row[3], row[4],
                    row[5] or now, now,
                ),
            )
            counts["new_provisions"] += int(existed is None)
            cur = con.execute(
                """
                UPDATE provision_observations
                SET provision_id = ?
                WHERE provision_id = ?
                  AND extraction_id IN (
                      SELECT extraction_id FROM text_extractions
                      WHERE manifestation_id = ?
                  )
                """,
                (new_provision_id, old_provision_id, manifestation_id),
            )
            counts["provision_observations_rebound"] += cur.rowcount

    conflict_rows = con.execute(
        """
        SELECT conflict_id, extraction_id
        FROM provision_designation_conflicts
        WHERE document_id = ?
        """,
        (old_document_id,),
    ).fetchall()
    for conflict_id, extraction_id in conflict_rows:
        manifestation = con.execute(
            "SELECT manifestation_id FROM text_extractions WHERE extraction_id = ?",
            (extraction_id,),
        ).fetchone()
        if manifestation and manifestation[0] in manifestation_targets:
            con.execute(
                "UPDATE provision_designation_conflicts SET document_id = ? WHERE conflict_id = ?",
                (manifestation_targets[manifestation[0]], conflict_id),
            )
    return mapping, counts


def rebind_temporal_events(
    con: sqlite3.Connection,
    old_document_id: str,
    old_provision_ids: set[str],
    manifestation_targets: dict[str, str],
    provision_mapping: dict[tuple[str, str], str],
) -> int:
    events = con.execute(
        """
        SELECT temporal_event_id, entity_type, entity_id
        FROM temporal_events
        WHERE (entity_type='document' AND entity_id = ?)
           OR (entity_type='provision' AND entity_id IN (
               SELECT provision_id FROM provisions WHERE document_id = ?
           ))
        ORDER BY temporal_event_id
        """,
        (old_document_id, old_document_id),
    ).fetchall()
    rebound = 0
    for event_id, entity_type, entity_id in events:
        manifestations = {
            row[0]
            for row in con.execute(
                """
                SELECT DISTINCT e.manifestation_id
                FROM temporal_event_evidence tee
                JOIN evidence e ON e.evidence_id = tee.evidence_id
                WHERE tee.temporal_event_id = ?
                """,
                (event_id,),
            ).fetchall()
            if row[0] in manifestation_targets
        }
        if len(manifestations) != 1:
            raise RuntimeError(
                f"temporal event {event_id} cannot be deterministically rebound"
            )
        manifestation_id = next(iter(manifestations))
        target_document_id = manifestation_targets[manifestation_id]
        if entity_type == "document":
            new_entity_id = target_document_id
        elif entity_type == "provision" and entity_id in old_provision_ids:
            new_entity_id = provision_mapping[(entity_id, target_document_id)]
        else:
            continue
        con.execute(
            "UPDATE temporal_events SET entity_id = ? WHERE temporal_event_id = ?",
            (new_entity_id, event_id),
        )
        rebound += 1
    return rebound


def apply_issuer_backfills(
    con: sqlite3.Connection,
    backfills: list[IssuerBackfill],
    now: str,
) -> dict[str, int]:
    counts = {
        "documents_backfilled": 0,
        "backfill_identifiers_inserted": 0,
        "backfill_identifier_evidence_links": 0,
        "backfill_provenance_inserted": 0,
    }
    for backfill in backfills:
        for move in backfill.moves:
            persist_assessment(
                con,
                manifestation_id=move.manifestation_id,
                extraction_id=move.extraction_id,
                assessment=move.assessment,
            )

        old_identifier_ids = [
            row[0]
            for row in con.execute(
                """
                SELECT identifier_id
                FROM document_identifiers
                WHERE document_id = ? AND identifier_type = 'canonical_key'
                """,
                (backfill.document_id,),
            ).fetchall()
        ]
        con.execute(
            """
            UPDATE document_identifiers
            SET issuer = ?, is_primary = 0
            WHERE document_id = ? AND identifier_type = 'canonical_key'
            """,
            (backfill.issuer_key, backfill.document_id),
        )
        con.execute(
            "UPDATE documents SET entity = ?, updated_at = ? WHERE document_id = ?",
            (backfill.issuer_key, now, backfill.document_id),
        )
        identifier_id = deterministic_id(
            "ID",
            (
                f"{backfill.document_id}:canonical:"
                f"{backfill.new_canonical_key}"
            ),
        )
        existed = con.execute(
            "SELECT 1 FROM document_identifiers WHERE identifier_id = ?",
            (identifier_id,),
        ).fetchone()
        con.execute(
            """
            INSERT INTO document_identifiers(
                identifier_id, document_id, identifier_type,
                identifier_value, issuer, is_primary
            )
            VALUES (?, ?, 'canonical_key', ?, ?, 1)
            ON CONFLICT(document_id, identifier_type, identifier_value)
            DO UPDATE SET issuer=excluded.issuer, is_primary=1
            """,
            (
                identifier_id,
                backfill.document_id,
                backfill.new_canonical_key,
                backfill.issuer_key,
            ),
        )
        counts["backfill_identifiers_inserted"] += int(existed is None)

        if old_identifier_ids:
            q = ",".join("?" for _ in old_identifier_ids)
            evidence_rows = con.execute(
                f"""
                SELECT DISTINCT evidence_id, evidence_role
                FROM document_identifier_evidence
                WHERE identifier_id IN ({q})
                """,
                old_identifier_ids,
            ).fetchall()
            for evidence_id, evidence_role in evidence_rows:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO document_identifier_evidence(
                        identifier_id, evidence_id, evidence_role, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (identifier_id, evidence_id, evidence_role, now),
                )
                counts["backfill_identifier_evidence_links"] += int(
                    bool(cur.rowcount)
                )

        for move in backfill.moves:
            migration_id = deterministic_id(
                "IDMIG",
                (
                    f"{move.manifestation_id}:{backfill.document_id}:"
                    f"{backfill.new_canonical_key}"
                ),
            )
            cur = con.execute(
                """
                INSERT OR IGNORE INTO document_identity_migrations(
                    migration_id, manifestation_id, legacy_document_id,
                    new_document_id, legacy_canonical_key, new_canonical_key,
                    issuer_key, reason_code, migrated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    migration_id,
                    move.manifestation_id,
                    backfill.document_id,
                    backfill.document_id,
                    backfill.legacy_canonical_key,
                    backfill.new_canonical_key,
                    backfill.issuer_key,
                    ISSUER_BACKFILL_REASON,
                    now,
                ),
            )
            counts["backfill_provenance_inserted"] += int(bool(cur.rowcount))
        counts["documents_backfilled"] += 1
    return counts


def apply_plan(con: sqlite3.Connection, plan: dict[str, object]) -> dict[str, object]:
    moves: list[ManifestationMove] = list(plan["moves"])
    backfills: list[IssuerBackfill] = list(plan["backfills"])
    if plan["conflicts"]:
        raise RuntimeError("collision plan contains conflicts; refusing mutation")
    if not moves and not backfills:
        return {
            "documents_backfilled": 0,
            "backfill_identifiers_inserted": 0,
            "backfill_identifier_evidence_links": 0,
            "backfill_provenance_inserted": 0,
            "documents_inserted": 0,
            "identifiers_inserted": 0,
            "identifier_evidence_links": 0,
            "manifestations_rebound": 0,
            "new_provisions": 0,
            "provision_observations_rebound": 0,
            "temporal_events_rebound": 0,
            "relationships_deleted": 0,
            "reference_resolutions_deleted": 0,
            "legacy_documents_deleted": 0,
            "migration_provenance_inserted": 0,
            "detection_runs_to_reresolve": [],
        }

    now = utc_now()
    manifestation_targets = {m.manifestation_id: m.new_document_id for m in moves}
    affected_old_docs = sorted({m.legacy_document_id for m in moves})
    legacy_keys = sorted({m.legacy_canonical_key for m in moves})
    counts: defaultdict[str, int] = defaultdict(int)
    detection_runs: set[str] = set()

    if moves:
        qkeys = ",".join("?" for _ in legacy_keys)
        detection_runs.update(
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT detection_run_id FROM reference_mentions WHERE target_document_key IN ({qkeys})",
                legacy_keys,
            ).fetchall()
        )
        qman = ",".join("?" for _ in manifestation_targets)
        detection_runs.update(
            row[0]
            for row in con.execute(
                f"""
                SELECT DISTINCT rdr.detection_run_id
                FROM reference_detection_runs rdr
                JOIN text_extractions te ON te.extraction_id = rdr.extraction_id
                WHERE te.manifestation_id IN ({qman})
                """,
                sorted(manifestation_targets),
            ).fetchall()
        )

    old_provisions_by_doc: dict[str, set[str]] = {}
    provision_mapping: dict[tuple[str, str], str] = {}

    with con:
        backfill_counts = apply_issuer_backfills(con, backfills, now)
        for key, value in backfill_counts.items():
            counts[key] += value

        for old_document_id in affected_old_docs:
            old_provisions_by_doc[old_document_id] = {
                row[0]
                for row in con.execute(
                    "SELECT provision_id FROM provisions WHERE document_id = ?",
                    (old_document_id,),
                ).fetchall()
            }

        endpoint_ids = set(affected_old_docs)
        for values in old_provisions_by_doc.values():
            endpoint_ids.update(values)
        if endpoint_ids:
            q = ",".join("?" for _ in endpoint_ids)
            relationship_ids = [
                row[0]
                for row in con.execute(
                    f"SELECT relationship_id FROM relationships WHERE source_id IN ({q}) OR target_id IN ({q})",
                    (*sorted(endpoint_ids), *sorted(endpoint_ids)),
                ).fetchall()
            ]
            for relationship_id in relationship_ids:
                counts["relationships_deleted"] += con.execute(
                    "DELETE FROM relationships WHERE relationship_id = ?",
                    (relationship_id,),
                ).rowcount

            provision_ids = sorted(endpoint_ids - set(affected_old_docs))
            doc_q = ",".join("?" for _ in affected_old_docs)
            prov_q = ",".join("?" for _ in provision_ids) or "''"
            resolution_rows = con.execute(
                f"""
                SELECT reference_resolution_id, reference_mention_id
                FROM reference_resolutions
                WHERE target_document_id IN ({doc_q})
                   OR target_provision_id IN ({prov_q})
                """,
                (*affected_old_docs, *provision_ids),
            ).fetchall()
            for resolution_id, mention_id in resolution_rows:
                counts["reference_resolutions_deleted"] += con.execute(
                    "DELETE FROM reference_resolutions WHERE reference_resolution_id = ?",
                    (resolution_id,),
                ).rowcount
                con.execute(
                    "UPDATE reference_mentions SET status='candidate', requires_human_review=1 WHERE reference_mention_id = ?",
                    (mention_id,),
                )

        seen_new_docs: set[str] = set()
        for move in moves:
            persist_assessment(
                con,
                manifestation_id=move.manifestation_id,
                extraction_id=move.extraction_id,
                assessment=move.assessment,
            )
            if move.new_document_id not in seen_new_docs:
                old = con.execute(
                    "SELECT jurisdiction, document_type, title FROM documents WHERE document_id = ?",
                    (move.legacy_document_id,),
                ).fetchone()
                con.execute(
                    """
                    INSERT INTO documents(
                        document_id, jurisdiction, entity, document_type, title,
                        issued_date, publication_date, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        entity=excluded.entity,
                        document_type=excluded.document_type,
                        title=excluded.title,
                        updated_at=excluded.updated_at
                    """,
                    (
                        move.new_document_id,
                        old[0], move.issuer_key, old[1], old[2], now, now,
                    ),
                )
                counts["documents_inserted"] += 1
                seen_new_docs.add(move.new_document_id)
            added_ids, added_links = create_identifiers_and_provenance(
                con, move, now
            )
            counts["identifiers_inserted"] += added_ids
            counts["identifier_evidence_links"] += added_links

        for old_document_id in affected_old_docs:
            local_targets = {
                m.manifestation_id: m.new_document_id
                for m in moves
                if m.legacy_document_id == old_document_id
            }
            local_mapping, local_counts = rebind_provisions(
                con, old_document_id, local_targets, now
            )
            provision_mapping.update(local_mapping)
            for key, value in local_counts.items():
                counts[key] += value

            counts["temporal_events_rebound"] += rebind_temporal_events(
                con,
                old_document_id,
                old_provisions_by_doc[old_document_id],
                local_targets,
                provision_mapping,
            )

        for move in moves:
            con.execute(
                "UPDATE manifestations SET document_id = ? WHERE manifestation_id = ?",
                (move.new_document_id, move.manifestation_id),
            )
            counts["manifestations_rebound"] += 1
            migration_id = deterministic_id(
                "IDMIG",
                f"{move.manifestation_id}:{move.legacy_document_id}:{move.new_document_id}",
            )
            cur = con.execute(
                """
                INSERT OR IGNORE INTO document_identity_migrations(
                    migration_id, manifestation_id, legacy_document_id,
                    new_document_id, legacy_canonical_key, new_canonical_key,
                    issuer_key, reason_code, migrated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    migration_id, move.manifestation_id,
                    move.legacy_document_id, move.new_document_id,
                    move.legacy_canonical_key, move.new_canonical_key,
                    move.issuer_key, MIGRATION_REASON, now,
                ),
            )
            counts["migration_provenance_inserted"] += int(bool(cur.rowcount))

        for old_document_id in affected_old_docs:
            counts["legacy_documents_deleted"] += con.execute(
                "DELETE FROM documents WHERE document_id = ?",
                (old_document_id,),
            ).rowcount

    result: dict[str, object] = dict(counts)
    result["detection_runs_to_reresolve"] = sorted(detection_runs)
    return result


def reprocess(*, db_path: Path, apply: bool) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    try:
        plan = build_plan(con)
        moves: list[ManifestationMove] = list(plan["moves"])
        backfills: list[IssuerBackfill] = list(plan["backfills"])
        affected = {m.manifestation_id for m in moves} | {
            move.manifestation_id
            for backfill in backfills
            for move in backfill.moves
        }
        before_hashes = hash_snapshot(con, affected)
        summary = {
            "mode": "apply" if apply else "dry-run",
            **plan["metrics"],
            "collision_groups": plan["collision_groups"],
            "issuer_backfill_groups": plan["issuer_backfill_groups"],
            "conflicts": plan["conflicts"],
            "skipped_unresolved": plan["skipped_unresolved"],
            "persistent_mutation": False,
        }
        if not apply:
            return summary
        if plan["conflicts"]:
            raise RuntimeError("dry-run plan contains conflicts; refusing apply")

        changes = apply_plan(con, plan)
        after_hashes = hash_snapshot(con, affected)
        if before_hashes != after_hashes:
            raise RuntimeError(
                "raw/normalized SHA-256 values changed during migration"
            )
        summary.update(changes)
        summary["persistent_mutation"] = bool(moves or backfills)
        summary["hashes_unchanged"] = True
        return summary
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Split confirmed issuer collisions into issuer-aware canonical "
            "identities. Default mode is a mutation-free dry-run."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the previously previewed deterministic split.",
    )
    args = parser.parse_args()
    try:
        result = reprocess(db_path=Path(args.db), apply=args.apply)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
