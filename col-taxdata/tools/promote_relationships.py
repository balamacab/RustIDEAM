#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path


PROMOTER_NAME = "canonical_relationship_promoter"
PROMOTER_VERSION = "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def promote(
    *,
    detection_run_id: str,
    resolution_method: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        run = con.execute(
            """
            SELECT rdr.extraction_id, te.manifestation_id, m.document_id,
                   m.sha256, m.retrieved_at, s.source_url
            FROM reference_detection_runs rdr
            JOIN text_extractions te
              ON te.extraction_id = rdr.extraction_id
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            JOIN sources s
              ON s.source_id = m.source_id
            WHERE rdr.detection_run_id = ?
            """,
            (detection_run_id,),
        ).fetchone()

        if run is None:
            raise RuntimeError(
                f"detection run not found: {detection_run_id}"
            )

        (
            extraction_id,
            manifestation_id,
            source_document_id,
            source_sha256,
            retrieved_at,
            source_url,
        ) = run

        if source_document_id is None:
            raise RuntimeError(
                "source manifestation has no canonical document_id"
            )

        rows = con.execute(
            """
            SELECT
                erm.relation_mention_id,
                erm.relation_type,
                erm.extracted_segment_id,
                erm.confidence,
                rm.reference_mention_id,
                rr.reference_resolution_id,
                rr.target_document_id,
                rr.target_provision_id,
                rr.confidence,
                es.char_start,
                es.char_end,
                es.text
            FROM explicit_relation_mentions erm
            JOIN reference_mentions rm
              ON rm.reference_mention_id =
                 erm.target_reference_mention_id
            JOIN reference_resolutions rr
              ON rr.reference_mention_id =
                 rm.reference_mention_id
            JOIN extracted_segments es
              ON es.extracted_segment_id =
                 erm.extracted_segment_id
            WHERE erm.detection_run_id = ?
              AND rr.resolution_method = ?
              AND rr.status = 'resolved'
              AND rr.requires_human_review = 0
              AND rr.target_provision_id IS NOT NULL
            ORDER BY erm.relation_mention_id
            """,
            (detection_run_id, resolution_method),
        ).fetchall()

        total_explicit = con.execute(
            """
            SELECT COUNT(*)
            FROM explicit_relation_mentions
            WHERE detection_run_id = ?
            """,
            (detection_run_id,),
        ).fetchone()[0]

        if len(rows) != total_explicit:
            raise RuntimeError(
                "refusing partial promotion: "
                f"{len(rows)} of {total_explicit} explicit relations "
                "have an unambiguous resolved target"
            )

        now = utc_now()
        relationships_inserted = 0
        relationships_reused = 0
        evidence_inserted = 0
        provenance_inserted = 0

        with con:
            for (
                relation_mention_id,
                relation_type,
                extracted_segment_id,
                relation_confidence,
                reference_mention_id,
                reference_resolution_id,
                target_document_id,
                target_provision_id,
                resolution_confidence,
                seg_char_start,
                seg_char_end,
                segment_text,
            ) in rows:
                evidence_id = deterministic_id(
                    "EVD",
                    (
                        f"{relation_mention_id}:"
                        f"{reference_resolution_id}:"
                        f"{PROMOTER_NAME}:{PROMOTER_VERSION}"
                    ),
                )

                evidence_cur = con.execute(
                    """
                    INSERT OR IGNORE INTO evidence(
                        evidence_id,
                        claim_id,
                        manifestation_id,
                        segment_id,
                        page_number,
                        char_start,
                        char_end,
                        exact_quote,
                        source_url,
                        source_sha256,
                        retrieved_at,
                        extraction_method,
                        extractor_version,
                        confidence,
                        review_status,
                        extracted_segment_id
                    )
                    VALUES (
                        ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, 'machine_validated', ?
                    )
                    """,
                    (
                        evidence_id,
                        manifestation_id,
                        seg_char_start,
                        seg_char_end,
                        segment_text,
                        source_url,
                        source_sha256,
                        retrieved_at,
                        (
                            f"{PROMOTER_NAME}:{PROMOTER_VERSION};"
                            f"relation_mention={relation_mention_id};"
                            f"resolution={reference_resolution_id}"
                        ),
                        PROMOTER_VERSION,
                        min(
                            float(relation_confidence),
                            float(resolution_confidence),
                        ),
                        extracted_segment_id,
                    ),
                )
                if evidence_cur.rowcount:
                    evidence_inserted += 1

                relationship_id = deterministic_id(
                    "REL",
                    (
                        f"{source_document_id}:{relation_type}:"
                        f"{target_provision_id}:"
                        f"{relation_mention_id}:"
                        f"{PROMOTER_VERSION}"
                    ),
                )

                existing = con.execute(
                    """
                    SELECT 1
                    FROM relationships
                    WHERE relationship_id = ?
                    """,
                    (relationship_id,),
                ).fetchone()

                con.execute(
                    """
                    INSERT INTO relationships(
                        relationship_id,
                        source_type,
                        source_id,
                        relation_type,
                        target_type,
                        target_id,
                        scope,
                        asserted_date,
                        effective_date,
                        end_date,
                        status,
                        evidence_id,
                        confidence,
                        requires_human_review
                    )
                    VALUES (
                        ?, 'document', ?, ?, 'provision', ?,
                        'explicit_operational_text',
                        NULL, NULL, NULL,
                        'validated', ?, ?, 0
                    )
                    ON CONFLICT(relationship_id) DO UPDATE SET
                        evidence_id = excluded.evidence_id,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        requires_human_review =
                            excluded.requires_human_review
                    """,
                    (
                        relationship_id,
                        source_document_id,
                        relation_type,
                        target_provision_id,
                        evidence_id,
                        min(
                            float(relation_confidence),
                            float(resolution_confidence),
                        ),
                    ),
                )

                if existing is None:
                    relationships_inserted += 1
                else:
                    relationships_reused += 1

                prov_cur = con.execute(
                    """
                    INSERT OR IGNORE INTO relationship_provenance(
                        relationship_id,
                        relation_mention_id,
                        reference_resolution_id,
                        promoter_name,
                        promoter_version,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relationship_id,
                        relation_mention_id,
                        reference_resolution_id,
                        PROMOTER_NAME,
                        PROMOTER_VERSION,
                        now,
                    ),
                )
                if prov_cur.rowcount:
                    provenance_inserted += 1

                con.execute(
                    """
                    UPDATE explicit_relation_mentions
                    SET status = 'validated',
                        requires_human_review = 0
                    WHERE relation_mention_id = ?
                    """,
                    (relation_mention_id,),
                )

        return {
            "promoter_name": PROMOTER_NAME,
            "promoter_version": PROMOTER_VERSION,
            "detection_run_id": detection_run_id,
            "resolution_method": resolution_method,
            "extraction_id": extraction_id,
            "source_document_id": source_document_id,
            "target_document_ids": sorted(
                {row[6] for row in rows if row[6] is not None}
            ),
            "explicit_relations": total_explicit,
            "eligible_relations": len(rows),
            "relationships_inserted": relationships_inserted,
            "relationships_reused": relationships_reused,
            "evidence_inserted": evidence_inserted,
            "provenance_inserted": provenance_inserted,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote fully resolved explicit relation mentions into "
            "canonical relationships with evidence and provenance."
        )
    )
    parser.add_argument("--detection-run-id", required=True)
    parser.add_argument(
        "--resolution-method",
        default="canonical_reference_resolver:2",
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = promote(
        detection_run_id=args.detection_run_id,
        resolution_method=args.resolution_method,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
