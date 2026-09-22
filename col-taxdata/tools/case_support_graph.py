from __future__ import annotations

import sqlite3


def endpoint_document_id(
    con: sqlite3.Connection,
    *,
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
            """
            SELECT document_id
            FROM provisions
            WHERE provision_id = ?
            """,
            (entity_id,),
        ).fetchone()
        return row[0] if row else None

    return None


def source_records_for_documents(
    con: sqlite3.Connection,
    document_ids: set[str],
) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}

    for document_id in sorted(document_ids):
        rows = con.execute(
            """
            SELECT
                s.source_id,
                s.source_url,
                s.authority,
                s.source_kind,
                m.manifestation_id,
                m.sha256,
                m.retrieved_at,
                m.content_type,
                m.byte_size,
                m.local_path
            FROM manifestations m
            JOIN sources s
              ON s.source_id = m.source_id
            WHERE m.document_id = ?
            ORDER BY m.retrieved_at, m.manifestation_id
            """,
            (document_id,),
        ).fetchall()

        for row in rows:
            source_id = row[0]
            record = records.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "source_url": row[1],
                    "authority": row[2],
                    "source_kind": row[3],
                    "document_ids": set(),
                    "manifestations": [],
                },
            )
            record["document_ids"].add(document_id)
            record["manifestations"].append(
                {
                    "manifestation_id": row[4],
                    "sha256": row[5],
                    "retrieved_at": row[6],
                    "content_type": row[7],
                    "byte_size": row[8],
                    "local_path": row[9],
                }
            )

    return records


def canonical_case_source_records(
    con: sqlite3.Connection,
    *,
    case_id: str,
) -> tuple[list[dict[str, object]], set[str]]:
    document_ids: set[str] = set()
    direct_source_ids: set[str] = set()

    for document_id, source_id in con.execute(
        """
        SELECT DISTINCT
            m.document_id,
            m.source_id
        FROM evidence e
        JOIN manifestations m
          ON m.manifestation_id = e.manifestation_id
        WHERE e.claim_id IN (
            SELECT item_id
            FROM case_items
            WHERE case_id = ?
              AND item_type = 'claim'
        )
        """,
        (case_id,),
    ):
        direct_source_ids.add(source_id)
        if document_id:
            document_ids.add(document_id)

    relationship_rows = con.execute(
        """
        SELECT
            r.source_type,
            r.source_id,
            r.target_type,
            r.target_id,
            m.document_id,
            m.source_id
        FROM relationships r
        JOIN case_items ci
          ON ci.item_type = 'relationship'
         AND ci.item_id = r.relationship_id
        LEFT JOIN evidence e
          ON e.evidence_id = r.evidence_id
        LEFT JOIN manifestations m
          ON m.manifestation_id = e.manifestation_id
        WHERE ci.case_id = ?
        """,
        (case_id,),
    ).fetchall()

    for (
        source_type,
        source_id,
        target_type,
        target_id,
        evidence_document_id,
        evidence_source_id,
    ) in relationship_rows:
        if evidence_source_id:
            direct_source_ids.add(evidence_source_id)
        if evidence_document_id:
            document_ids.add(evidence_document_id)

        for entity_type, entity_id in (
            (source_type, source_id),
            (target_type, target_id),
        ):
            document_id = endpoint_document_id(
                con,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            if document_id:
                document_ids.add(document_id)

    records = source_records_for_documents(con, document_ids)

    for source_id in direct_source_ids:
        if source_id in records:
            continue
        row = con.execute(
            """
            SELECT source_url, authority, source_kind
            FROM sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        if row:
            records[source_id] = {
                "source_id": source_id,
                "source_url": row[0],
                "authority": row[1],
                "source_kind": row[2],
                "document_ids": set(),
                "manifestations": [],
            }

    result = []
    for source_id in sorted(records):
        record = records[source_id]
        result.append(
            {
                "source_id": record["source_id"],
                "source_url": record["source_url"],
                "authority": record["authority"],
                "source_kind": record["source_kind"],
                "document_ids": sorted(record["document_ids"]),
                "manifestations": record["manifestations"],
            }
        )

    return result, document_ids
