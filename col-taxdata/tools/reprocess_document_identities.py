#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import urllib.parse

from source_identity import (
    NORMATIVE_ACT,
    normalize_document_number,
    assess_generic_normative_identity,
    classify_source_url,
    persist_assessment,
)


GENERIC_TYPES = {"LEY", "DECRETO", "RESOLUCION", "CIRCULAR"}
COMPILED_EXEMPT = {"estatuto_tributario.htm"}


def canonical_identifier(con: sqlite3.Connection, document_id: str) -> str | None:
    row = con.execute(
        """
        SELECT identifier_value
        FROM document_identifiers
        WHERE document_id = ? AND identifier_type = 'canonical_key'
        ORDER BY is_primary DESC, identifier_id
        LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    return row[0] if row else None


def is_incompatible(
    con: sqlite3.Connection,
    *,
    source_url: str,
    document_id: str,
    document_type: str,
) -> bool:
    name = Path(urllib.parse.urlparse(source_url).path).name.lower()
    if name in COMPILED_EXEMPT:
        return False

    source = classify_source_url(source_url)
    if source.family != NORMATIVE_ACT:
        return document_type in GENERIC_TYPES

    if document_type != source.document_type:
        return True
    if source.number is None or source.year is None:
        return False
    identifier = canonical_identifier(con, document_id)
    if identifier is None:
        return True
    parts = identifier.split(":")
    if len(parts) != 4:
        return True
    _, identifier_type, identifier_number, identifier_year = parts
    try:
        identifier_year_int = int(identifier_year)
    except ValueError:
        return True
    return (
        identifier_type != source.document_type
        or normalize_document_number(identifier_number) != source.number
        or identifier_year_int != source.year
    )


def cleanup_false_derivations(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    extraction_id: str,
    old_document_id: str,
) -> dict[str, int]:
    relationship_ids = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT rp.relationship_id
            FROM relationship_provenance rp
            JOIN explicit_relation_mentions erm
              ON erm.relation_mention_id = rp.relation_mention_id
            WHERE erm.extraction_id = ?
            """,
            (extraction_id,),
        )
    ]
    relationships_deleted = 0
    for relationship_id in relationship_ids:
        relationships_deleted += con.execute(
            "DELETE FROM relationships WHERE relationship_id = ?",
            (relationship_id,),
        ).rowcount

    observations_deleted = con.execute(
        "DELETE FROM provision_observations WHERE extraction_id = ?",
        (extraction_id,),
    ).rowcount

    identifier_evidence_deleted = con.execute(
        """
        DELETE FROM document_identifier_evidence
        WHERE identifier_id IN (
            SELECT identifier_id FROM document_identifiers WHERE document_id = ?
        )
          AND evidence_id IN (
            SELECT evidence_id FROM evidence WHERE manifestation_id = ?
        )
        """,
        (old_document_id, manifestation_id),
    ).rowcount

    temporal_ids = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT tee.temporal_event_id
            FROM temporal_event_evidence tee
            JOIN evidence e ON e.evidence_id = tee.evidence_id
            JOIN temporal_events te ON te.temporal_event_id = tee.temporal_event_id
            WHERE e.manifestation_id = ?
              AND te.entity_type = 'document'
              AND te.entity_id = ?
            """,
            (manifestation_id, old_document_id),
        )
    ]
    temporal_evidence_deleted = con.execute(
        """
        DELETE FROM temporal_event_evidence
        WHERE evidence_id IN (
            SELECT evidence_id FROM evidence WHERE manifestation_id = ?
        )
          AND temporal_event_id IN (
            SELECT temporal_event_id FROM temporal_events
            WHERE entity_type = 'document' AND entity_id = ?
        )
        """,
        (manifestation_id, old_document_id),
    ).rowcount

    temporal_events_deleted = 0
    for temporal_id in temporal_ids:
        remaining = con.execute(
            "SELECT 1 FROM temporal_event_evidence WHERE temporal_event_id = ? LIMIT 1",
            (temporal_id,),
        ).fetchone()
        if remaining is None:
            temporal_events_deleted += con.execute(
                "DELETE FROM temporal_events WHERE temporal_event_id = ?",
                (temporal_id,),
            ).rowcount

    # Remove only provisions that became completely unsupported after deleting
    # observations from this extraction. Shared/legitimate observations survive.
    provisions_deleted = con.execute(
        """
        DELETE FROM provisions
        WHERE document_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM provision_observations po
              WHERE po.provision_id = provisions.provision_id
          )
        """,
        (old_document_id,),
    ).rowcount

    return {
        "relationships_deleted": relationships_deleted,
        "provision_observations_deleted": observations_deleted,
        "provisions_deleted": provisions_deleted,
        "identifier_evidence_deleted": identifier_evidence_deleted,
        "temporal_evidence_deleted": temporal_evidence_deleted,
        "temporal_events_deleted": temporal_events_deleted,
    }


def reprocess(*, db_path: Path, apply: bool) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        rows = con.execute(
            """
            SELECT
                s.source_url,
                m.manifestation_id,
                m.document_id,
                d.document_type,
                te.extraction_id,
                (
                    SELECT es.text
                    FROM extracted_segments es
                    WHERE es.extraction_id = te.extraction_id
                      AND es.segment_type = 'document_heading'
                    ORDER BY es.sequence_no
                    LIMIT 1
                ) AS heading
            FROM sources s
            JOIN manifestations m ON m.source_id = s.source_id
            JOIN documents d ON d.document_id = m.document_id
            JOIN text_extractions te ON te.manifestation_id = m.manifestation_id
            WHERE s.source_url LIKE
                'https://normograma.dian.gov.co/dian/compilacion/docs/%'
              AND te.status = 'success'
            ORDER BY s.source_url
            """
        ).fetchall()

        incompatible = []
        totals = {
            "relationships_deleted": 0,
            "provision_observations_deleted": 0,
            "provisions_deleted": 0,
            "identifier_evidence_deleted": 0,
            "temporal_evidence_deleted": 0,
            "temporal_events_deleted": 0,
        }

        for source_url, manifestation_id, document_id, document_type, extraction_id, heading in rows:
            if not is_incompatible(
                con,
                source_url=source_url,
                document_id=document_id,
                document_type=document_type,
            ):
                continue

            assessment = assess_generic_normative_identity(source_url, heading or "")
            item = {
                "source_url": source_url,
                "manifestation_id": manifestation_id,
                "extraction_id": extraction_id,
                "old_document_id": document_id,
                "old_document_type": document_type,
                "source_family": assessment.source.family,
                "reason_code": assessment.reason_code or "SOURCE_IDENTITY_CONFLICT",
            }
            incompatible.append(item)

            if not apply:
                continue

            with con:
                persist_assessment(
                    con,
                    manifestation_id=manifestation_id,
                    extraction_id=extraction_id,
                    assessment=assessment,
                )
                cleanup = cleanup_false_derivations(
                    con,
                    manifestation_id=manifestation_id,
                    extraction_id=extraction_id,
                    old_document_id=document_id,
                )
                for key, value in cleanup.items():
                    totals[key] += value
                con.execute(
                    "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                    (manifestation_id,),
                )

        return {
            "mode": "apply" if apply else "dry-run",
            "scanned_linked_manifestations": len(rows),
            "incompatible_count": len(incompatible),
            "incompatible": incompatible,
            **totals,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reprocess derived Normograma document identity links made unsafe by "
            "generic normative-heading inference. Raw evidence is never changed."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply derived-state cleanup. Default is read-only dry-run.",
    )
    args = parser.parse_args()
    print(json.dumps(reprocess(db_path=Path(args.db), apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())