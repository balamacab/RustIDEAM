#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sqlite3
import uuid
from pathlib import Path


PROMOTER_NAME = "editorial_relationship_promoter"
PROMOTER_VERSION = "1"

SOURCE_ARTICLE_RE = re.compile(
    r"^ART[IÍ]CULO\s+(?P<designation>\d+(?:\.\d+){2,})\b",
    re.IGNORECASE,
)

EDITORIAL_RELATION_TYPES = {
    "modified_by",
    "added_by",
    "repealed_by",
    "substituted_by",
}


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
            SELECT
                rdr.extraction_id,
                te.manifestation_id,
                m.document_id,
                m.sha256,
                m.retrieved_at,
                s.source_url
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
            # An unresolved source identity is a valid conservative outcome.
            # Relationship promotion must not turn that state into an
            # operational failure or invent a source document.
            return {
                "promoter_name": PROMOTER_NAME,
                "promoter_version": PROMOTER_VERSION,
                "detection_run_id": detection_run_id,
                "resolution_method": resolution_method,
                "extraction_id": extraction_id,
                "source_document_id": None,
                "status": "skipped",
                "reason_code": "SOURCE_DOCUMENT_ID_UNRESOLVED",
                "relationships_inserted": 0,
                "relationships_reused": 0,
            }

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
                rr.status,
                rr.requires_human_review,
                es.sequence_no,
                es.char_start,
                es.char_end,
                es.section_path,
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
              AND erm.relation_type IN (
                  'modified_by',
                  'added_by',
                  'repealed_by',
                  'substituted_by'
              )
            ORDER BY es.sequence_no, erm.relation_mention_id
            """,
            (detection_run_id, resolution_method),
        ).fetchall()

        now = utc_now()
        eligible = 0
        promoted = 0
        reused = 0
        evidence_inserted = 0
        provenance_inserted = 0
        reviews_inserted = 0
        source_unmapped = []
        target_unresolved = []

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
                resolution_status,
                resolution_review,
                sequence_no,
                seg_char_start,
                seg_char_end,
                section_path,
                segment_text,
            ) in rows:
                if (
                    resolution_status != "resolved"
                    or resolution_review != 0
                    or target_provision_id is None
                ):
                    target_unresolved.append(sequence_no)
                    continue

                match = SOURCE_ARTICLE_RE.match(section_path or "")
                source_provision_id = None
                source_designation = None

                if match is not None:
                    source_designation = match.group("designation")
                    provision = con.execute(
                        """
                        SELECT provision_id
                        FROM provisions
                        WHERE document_id = ?
                          AND normalized_designation = ?
                        """,
                        (
                            source_document_id,
                            source_designation,
                        ),
                    ).fetchone()
                    if provision is not None:
                        source_provision_id = provision[0]

                if source_provision_id is None:
                    review_id = deterministic_id(
                        "REV",
                        (
                            f"{relation_mention_id}:"
                            f"{PROMOTER_NAME}:{PROMOTER_VERSION}:"
                            "EDITORIAL_RELATION_SOURCE_PROVISION_UNRESOLVED"
                        ),
                    )
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO review_queue(
                            review_id,
                            entity_type,
                            entity_id,
                            reason_code,
                            severity,
                            created_at
                        )
                        VALUES (
                            ?,
                            'explicit_relation_mention',
                            ?,
                            'EDITORIAL_RELATION_SOURCE_PROVISION_UNRESOLVED',
                            'medium',
                            ?
                        )
                        """,
                        (
                            review_id,
                            relation_mention_id,
                            now,
                        ),
                    )
                    reviews_inserted += int(bool(cur.rowcount))
                    con.execute(
                        """
                        UPDATE explicit_relation_mentions
                        SET requires_human_review = 1,
                            status = 'candidate'
                        WHERE relation_mention_id = ?
                        """,
                        (relation_mention_id,),
                    )
                    source_unmapped.append(
                        {
                            "sequence_no": sequence_no,
                            "section_path": section_path,
                        }
                    )
                    continue

                eligible += 1

                evidence_id = deterministic_id(
                    "EVD",
                    (
                        f"{relation_mention_id}:"
                        f"{reference_resolution_id}:"
                        f"{PROMOTER_NAME}:{PROMOTER_VERSION}"
                    ),
                )
                cur = con.execute(
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
                            f"resolution={reference_resolution_id};"
                            f"source_designation={source_designation}"
                        ),
                        PROMOTER_VERSION,
                        min(
                            float(relation_confidence),
                            float(resolution_confidence),
                        ),
                        extracted_segment_id,
                    ),
                )
                evidence_inserted += int(bool(cur.rowcount))

                relationship_id = deterministic_id(
                    "REL",
                    (
                        f"{source_provision_id}:{relation_type}:"
                        f"{target_provision_id}:"
                        f"{relation_mention_id}:"
                        f"{PROMOTER_NAME}:{PROMOTER_VERSION}"
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
                        ?, 'provision', ?, ?, 'provision', ?,
                        'explicit_editorial_note',
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
                        source_provision_id,
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
                    promoted += 1
                else:
                    reused += 1

                cur = con.execute(
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
                provenance_inserted += int(bool(cur.rowcount))

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
            "editorial_relations_seen": len(rows),
            "eligible_relations": eligible,
            "relationships_inserted": promoted,
            "relationships_reused": reused,
            "evidence_inserted": evidence_inserted,
            "provenance_inserted": provenance_inserted,
            "review_items_inserted": reviews_inserted,
            "source_unmapped_count": len(source_unmapped),
            "source_unmapped": source_unmapped,
            "target_unresolved_count": len(target_unresolved),
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote resolved inverse editorial notes as canonical "
            "provision-to-provision relationships."
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
