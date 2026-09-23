from __future__ import annotations

import sqlite3

from temporal_candidate_model import (
    ROLE_COMMENCEMENT,
    ROLE_ISSUED,
    ROLE_PUBLICATION,
    RoleResolution,
    TemporalCandidate,
)
from temporal_candidate_storage import Delta, deterministic_id


def find_legacy_events(
    con: sqlite3.Connection,
    *,
    document_id: str,
    processor_name: str,
    legacy_processor_version: str,
) -> list[tuple[str, str, str | None]]:
    return con.execute(
        """
        SELECT DISTINCT te.temporal_event_id, te.event_type, te.event_date
        FROM temporal_events te
        JOIN temporal_event_evidence tee
          ON tee.temporal_event_id=te.temporal_event_id
        JOIN evidence e ON e.evidence_id=tee.evidence_id
        WHERE te.entity_type='document'
          AND te.entity_id=?
          AND te.status != 'superseded'
          AND e.extraction_method LIKE ?
        ORDER BY te.temporal_event_id
        """,
        (document_id, f"{processor_name}:{legacy_processor_version}:%"),
    ).fetchall()


def supersede_legacy_events(
    con: sqlite3.Connection,
    *,
    legacy_events: list[tuple[str, str, str | None]],
    delta: Delta,
) -> None:
    """Supersede v2 derived state without deleting its evidence provenance."""
    if not legacy_events:
        return
    event_ids = [row[0] for row in legacy_events]
    placeholders = ",".join("?" for _ in event_ids)
    basis_rows = con.execute(
        f"""
        SELECT relationship_id, basis_role
        FROM relationship_temporal_basis
        WHERE temporal_event_id IN ({placeholders})
        ORDER BY relationship_id, basis_role
        """,
        event_ids,
    ).fetchall()
    for relationship_id, basis_role in basis_rows:
        if basis_role not in {"asserted_date", "effective_date", "end_date"}:
            raise RuntimeError(f"unsupported relationship basis role: {basis_role}")
        cur = con.execute(
            f"UPDATE relationships SET {basis_role}=NULL "
            f"WHERE relationship_id=? AND {basis_role} IS NOT NULL",
            (relationship_id,),
        )
        delta.relationship_dates_cleared += cur.rowcount
    cur = con.execute(
        f"DELETE FROM relationship_temporal_basis "
        f"WHERE temporal_event_id IN ({placeholders})",
        event_ids,
    )
    delta.relationship_basis_deleted += cur.rowcount
    cur = con.execute(
        f"""
        UPDATE temporal_events
        SET status='superseded', requires_human_review=1
        WHERE temporal_event_id IN ({placeholders})
          AND status != 'superseded'
        """,
        event_ids,
    )
    delta.legacy_events_superseded += cur.rowcount


def resolved_dates(
    resolutions: dict[str, RoleResolution],
) -> tuple[
    TemporalCandidate | None,
    TemporalCandidate | None,
    TemporalCandidate | None,
    str | None,
    str | None,
    str | None,
]:
    publication = resolutions[ROLE_PUBLICATION].promoted
    issued = resolutions[ROLE_ISSUED].promoted
    commencement = resolutions[ROLE_COMMENCEMENT].promoted
    publication_date = publication.candidate_date if publication else None
    issued_date = issued.candidate_date if issued else None
    # Publication is not effectiveness evidence by itself. The linkage is only
    # legal when the source also has one uniquely supported explicit rule.
    effective_date = publication_date if publication and commencement else None
    return (
        publication,
        issued,
        commencement,
        publication_date,
        issued_date,
        effective_date,
    )


def update_document_dates(
    con: sqlite3.Connection,
    *,
    document_id: str,
    issued_date: str | None,
    publication_date: str | None,
    legacy_events: list[tuple[str, str, str | None]],
    now: str,
    delta: Delta,
) -> None:
    current = con.execute(
        "SELECT issued_date, publication_date FROM documents WHERE document_id=?",
        (document_id,),
    ).fetchone()
    if current is None:
        raise RuntimeError(f"document not found: {document_id}")
    legacy_issued = {value for _, typ, value in legacy_events if typ == "issued"}
    legacy_publication = {value for _, typ, value in legacy_events if typ == "published"}
    desired_issued = issued_date
    desired_publication = publication_date
    if desired_issued is None and current[0] not in legacy_issued:
        desired_issued = current[0]
    if desired_publication is None and current[1] not in legacy_publication:
        desired_publication = current[1]
    if current != (desired_issued, desired_publication):
        con.execute(
            "UPDATE documents SET issued_date=?, publication_date=?, updated_at=? "
            "WHERE document_id=?",
            (desired_issued, desired_publication, now, document_id),
        )
        delta.document_dates_updated += 1


def create_event(
    con: sqlite3.Connection,
    *,
    document_id: str,
    event_type: str,
    event_date: str,
    effective_from: str | None,
    primary_evidence_id: str,
    evidence_roles: list[tuple[str, str]],
    processor_version: str,
    now: str,
    delta: Delta,
) -> str:
    event_id = deterministic_id(
        "TEV",
        f"{document_id}:{event_type}:{event_date}:{effective_from or ''}:{processor_version}",
    )
    expected = (event_date, effective_from, "validated", primary_evidence_id)
    existing = con.execute(
        """
        SELECT event_date, effective_from, status, evidence_id
        FROM temporal_events WHERE temporal_event_id=?
        """,
        (event_id,),
    ).fetchone()
    if existing is None:
        con.execute(
            """
            INSERT INTO temporal_events(
                temporal_event_id, entity_type, entity_id, event_type, event_date,
                effective_from, effective_to, caused_by_type, caused_by_id, scope,
                status, evidence_id, confidence, requires_human_review
            ) VALUES (?, 'document', ?, ?, ?, ?, NULL, NULL, NULL, 'document',
                      'validated', ?, 1.0, 0)
            """,
            (
                event_id,
                document_id,
                event_type,
                event_date,
                effective_from,
                primary_evidence_id,
            ),
        )
        delta.events_inserted += 1
    elif existing != expected:
        raise RuntimeError("same temporal event id produced different data")
    for evidence_id, evidence_role in evidence_roles:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO temporal_event_evidence(
                temporal_event_id, evidence_id, evidence_role, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (event_id, evidence_id, evidence_role, now),
        )
        delta.event_evidence_links_inserted += cur.rowcount
    return event_id


def promote_resolved_events(
    con: sqlite3.Connection,
    *,
    document_id: str,
    publication: TemporalCandidate | None,
    issued: TemporalCandidate | None,
    commencement: TemporalCandidate | None,
    publication_date: str | None,
    issued_date: str | None,
    effective_date: str | None,
    evidence_by_candidate: dict[str, str],
    processor_version: str,
    now: str,
    delta: Delta,
) -> tuple[str | None, str | None, str | None]:
    issued_event = None
    if issued and issued_date:
        evidence_id = evidence_by_candidate[issued.candidate_id]
        issued_event = create_event(
            con,
            document_id=document_id,
            event_type="issued",
            event_date=issued_date,
            effective_from=None,
            primary_evidence_id=evidence_id,
            evidence_roles=[(evidence_id, "issued_date_source")],
            processor_version=processor_version,
            now=now,
            delta=delta,
        )
    publication_event = None
    if publication and publication_date:
        evidence_id = evidence_by_candidate[publication.candidate_id]
        publication_event = create_event(
            con,
            document_id=document_id,
            event_type="published",
            event_date=publication_date,
            effective_from=None,
            primary_evidence_id=evidence_id,
            evidence_roles=[(evidence_id, "publication_date_source")],
            processor_version=processor_version,
            now=now,
            delta=delta,
        )
    effective_event = None
    if publication and commencement and effective_date:
        publication_evidence = evidence_by_candidate[publication.candidate_id]
        commencement_evidence = evidence_by_candidate[commencement.candidate_id]
        effective_event = create_event(
            con,
            document_id=document_id,
            event_type="enters_into_force",
            event_date=effective_date,
            effective_from=effective_date,
            primary_evidence_id=commencement_evidence,
            evidence_roles=[
                (commencement_evidence, "commencement_rule"),
                (publication_evidence, "publication_date_basis"),
            ],
            processor_version=processor_version,
            now=now,
            delta=delta,
        )
    return issued_event, publication_event, effective_event


def relationship_sets(
    con: sqlite3.Connection,
    document_id: str,
) -> tuple[list[str], list[str]]:
    source = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT r.relationship_id
            FROM relationships r
            LEFT JOIN provisions sp
              ON r.source_type='provision' AND sp.provision_id=r.source_id
            WHERE r.status='validated'
              AND r.relation_type IN
                  ('substitutes','modifies','adds','repeals','partially_repeals')
              AND ((r.source_type='document' AND r.source_id=?)
                   OR (r.source_type='provision' AND sp.document_id=?))
            ORDER BY r.relationship_id
            """,
            (document_id, document_id),
        ).fetchall()
    ]
    inverse = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT r.relationship_id
            FROM relationships r
            JOIN provisions tp
              ON r.target_type='provision' AND tp.provision_id=r.target_id
            WHERE r.status='validated'
              AND tp.document_id=?
              AND r.relation_type IN
                  ('modified_by','added_by','repealed_by','substituted_by')
            ORDER BY r.relationship_id
            """,
            (document_id,),
        ).fetchall()
    ]
    return source, inverse


def bind_relationship_date(
    con: sqlite3.Connection,
    *,
    relationship_ids: list[str],
    column: str,
    date_value: str,
    event_id: str,
    now: str,
    delta: Delta,
) -> None:
    if column not in {"asserted_date", "effective_date", "end_date"}:
        raise RuntimeError(f"unsupported relationship temporal column: {column}")
    for relationship_id in relationship_ids:
        current = con.execute(
            f"SELECT {column} FROM relationships WHERE relationship_id=?",
            (relationship_id,),
        ).fetchone()[0]
        if current != date_value:
            con.execute(
                f"UPDATE relationships SET {column}=? WHERE relationship_id=?",
                (date_value, relationship_id),
            )
            delta.relationship_dates_updated += 1
        cur = con.execute(
            """
            INSERT OR IGNORE INTO relationship_temporal_basis(
                relationship_id, temporal_event_id, basis_role, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (relationship_id, event_id, column, now),
        )
        delta.relationship_basis_inserted += cur.rowcount


def rebind_relationship_temporality(
    con: sqlite3.Connection,
    *,
    document_id: str,
    issued_event_id: str | None,
    effective_event_id: str | None,
    issued_date: str | None,
    effective_date: str | None,
    now: str,
    delta: Delta,
) -> tuple[int, int]:
    source, inverse = relationship_sets(con, document_id)
    if issued_event_id and issued_date:
        bind_relationship_date(
            con,
            relationship_ids=source,
            column="asserted_date",
            date_value=issued_date,
            event_id=issued_event_id,
            now=now,
            delta=delta,
        )
    if effective_event_id and effective_date:
        bind_relationship_date(
            con,
            relationship_ids=source + inverse,
            column="effective_date",
            date_value=effective_date,
            event_id=effective_event_id,
            now=now,
            delta=delta,
        )
    return len(source), len(inverse)
