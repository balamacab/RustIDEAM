#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path


RESOLVER_NAME = "canonical_reference_resolver"
RESOLVER_VERSION = "2"
RESOLUTION_METHOD = f"{RESOLVER_NAME}:{RESOLVER_VERSION}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def resolve_one(
    con: sqlite3.Connection,
    *,
    mention_id: str,
    mention_type: str,
    target_document_key: str,
    target_issuer: str | None,
    article_designation: str | None,
) -> dict[str, object]:
    docs = con.execute(
        """
        SELECT DISTINCT d.document_id
        FROM documents d
        JOIN document_identifiers di
          ON di.document_id = d.document_id
        WHERE di.identifier_type = 'canonical_key'
          AND di.identifier_value = ?
          AND (? IS NULL OR di.issuer = ?)
        ORDER BY d.document_id
        """,
        (target_document_key, target_issuer, target_issuer),
    ).fetchall()

    if not docs:
        return {
            "status": "unresolved",
            "target_document_id": None,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "TARGET_DOCUMENT_NOT_FOUND",
        }

    if len(docs) > 1:
        return {
            "status": "ambiguous",
            "target_document_id": None,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "AMBIGUOUS_DOCUMENT_ID",
        }

    document_id = docs[0][0]

    if mention_type == "document":
        return {
            "status": "resolved",
            "target_document_id": document_id,
            "target_provision_id": None,
            "confidence": 1.0,
            "requires_human_review": 0,
            "reason_code": None,
        }

    if mention_type != "article" or not article_designation:
        return {
            "status": "unresolved",
            "target_document_id": document_id,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "TARGET_PROVISION_NOT_FOUND",
        }

    conflict = con.execute(
        """
        SELECT conflict_id
        FROM provision_designation_conflicts
        WHERE document_id = ?
          AND normalized_designation = ?
          AND status = 'open'
        ORDER BY conflict_id
        LIMIT 1
        """,
        (document_id, article_designation),
    ).fetchone()

    if conflict is not None:
        return {
            "status": "ambiguous",
            "target_document_id": document_id,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "AMBIGUOUS_PROVISION_DESIGNATION",
        }

    provisions = con.execute(
        """
        SELECT provision_id
        FROM provisions
        WHERE document_id = ?
          AND normalized_designation = ?
        ORDER BY provision_id
        """,
        (document_id, article_designation),
    ).fetchall()

    if not provisions:
        return {
            "status": "unresolved",
            "target_document_id": document_id,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "TARGET_PROVISION_NOT_FOUND",
        }

    if len(provisions) > 1:
        return {
            "status": "ambiguous",
            "target_document_id": document_id,
            "target_provision_id": None,
            "confidence": 0.0,
            "requires_human_review": 1,
            "reason_code": "AMBIGUOUS_PROVISION_DESIGNATION",
        }

    return {
        "status": "resolved",
        "target_document_id": document_id,
        "target_provision_id": provisions[0][0],
        "confidence": 1.0,
        "requires_human_review": 0,
        "reason_code": None,
    }


def resolve_references(
    *,
    detection_run_id: str,
    db_path: Path,
    relations_only: bool,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        run = con.execute(
            """
            SELECT detection_run_id, extraction_id, detector_name, detector_version
            FROM reference_detection_runs
            WHERE detection_run_id = ?
            """,
            (detection_run_id,),
        ).fetchone()

        if run is None:
            raise RuntimeError(f"detection run not found: {detection_run_id}")

        if relations_only:
            rows = con.execute(
                """
                SELECT DISTINCT
                    rm.reference_mention_id,
                    rm.mention_type,
                    rm.target_document_key,
                    rm.target_issuer,
                    rm.article_designation
                FROM explicit_relation_mentions erm
                JOIN reference_mentions rm
                  ON rm.reference_mention_id = erm.target_reference_mention_id
                WHERE erm.detection_run_id = ?
                ORDER BY rm.reference_mention_id
                """,
                (detection_run_id,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT
                    reference_mention_id,
                    mention_type,
                    target_document_key,
                    target_issuer,
                    article_designation
                FROM reference_mentions
                WHERE detection_run_id = ?
                ORDER BY reference_mention_id
                """,
                (detection_run_id,),
            ).fetchall()

        now = utc_now()
        counts = {
            "resolved": 0,
            "unresolved": 0,
            "ambiguous": 0,
        }
        document_resolved = 0
        provision_resolved = 0
        review_items_inserted = 0
        review_items_closed = 0
        reason_counts: dict[str, int] = {}

        with con:
            for (
                mention_id,
                mention_type,
                target_document_key,
                target_issuer,
                article_designation,
            ) in rows:
                result = resolve_one(
                    con,
                    mention_id=mention_id,
                    mention_type=mention_type,
                    target_document_key=target_document_key,
                    target_issuer=target_issuer,
                    article_designation=article_designation,
                )

                status = str(result["status"])
                counts[status] += 1

                if status == "resolved":
                    if result["target_document_id"] is not None:
                        document_resolved += 1
                    if result["target_provision_id"] is not None:
                        provision_resolved += 1

                resolution_id = deterministic_id(
                    "RRES",
                    f"{mention_id}:{RESOLUTION_METHOD}",
                )

                con.execute(
                    """
                    INSERT INTO reference_resolutions(
                        reference_resolution_id,
                        reference_mention_id,
                        target_document_id,
                        target_provision_id,
                        resolution_method,
                        confidence,
                        status,
                        requires_human_review,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reference_mention_id, resolution_method)
                    DO UPDATE SET
                        target_document_id = excluded.target_document_id,
                        target_provision_id = excluded.target_provision_id,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        requires_human_review = excluded.requires_human_review
                    """,
                    (
                        resolution_id,
                        mention_id,
                        result["target_document_id"],
                        result["target_provision_id"],
                        RESOLUTION_METHOD,
                        result["confidence"],
                        status,
                        result["requires_human_review"],
                        now,
                    ),
                )

                con.execute(
                    """
                    UPDATE reference_mentions
                    SET status = ?,
                        requires_human_review = ?
                    WHERE reference_mention_id = ?
                    """,
                    (
                        status,
                        result["requires_human_review"],
                        mention_id,
                    ),
                )

                reason_code = result["reason_code"]
                review_prefix = f"{mention_id}:{RESOLUTION_METHOD}:"

                if reason_code is not None:
                    reason_code = str(reason_code)
                    reason_counts[reason_code] = (
                        reason_counts.get(reason_code, 0) + 1
                    )
                    review_id = deterministic_id(
                        "REV",
                        review_prefix + reason_code,
                    )
                    review = con.execute(
                        """
                        INSERT OR IGNORE INTO review_queue(
                            review_id,
                            entity_type,
                            entity_id,
                            reason_code,
                            severity,
                            created_at
                        )
                        VALUES (?, 'reference_mention', ?, ?, 'high', ?)
                        """,
                        (review_id, mention_id, reason_code, now),
                    )
                    if review.rowcount:
                        review_items_inserted += 1
                else:
                    open_reviews = con.execute(
                        """
                        SELECT review_id
                        FROM review_queue
                        WHERE entity_type = 'reference_mention'
                          AND entity_id = ?
                          AND resolved_at IS NULL
                          AND reason_code IN (
                              'TARGET_DOCUMENT_NOT_FOUND',
                              'AMBIGUOUS_DOCUMENT_ID',
                              'TARGET_PROVISION_NOT_FOUND',
                              'AMBIGUOUS_PROVISION_DESIGNATION'
                          )
                        """,
                        (mention_id,),
                    ).fetchall()
                    for (review_id,) in open_reviews:
                        con.execute(
                            """
                            UPDATE review_queue
                            SET resolved_at = ?,
                                resolution = ?
                            WHERE review_id = ?
                            """,
                            (
                                now,
                                f"Resolved by {RESOLUTION_METHOD}",
                                review_id,
                            ),
                        )
                        review_items_closed += 1

        return {
            "resolver_name": RESOLVER_NAME,
            "resolver_version": RESOLVER_VERSION,
            "resolution_method": RESOLUTION_METHOD,
            "detection_run_id": detection_run_id,
            "extraction_id": run[1],
            "relations_only": relations_only,
            "mentions_processed": len(rows),
            "resolved": counts["resolved"],
            "unresolved": counts["unresolved"],
            "ambiguous": counts["ambiguous"],
            "document_resolved": document_resolved,
            "provision_resolved": provision_resolved,
            "review_items_inserted": review_items_inserted,
            "review_items_closed": review_items_closed,
            "reason_counts": reason_counts,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve detected legal references against canonical documents "
            "and provisions without inferring missing identities."
        )
    )
    parser.add_argument("--detection-run-id", required=True)
    parser.add_argument(
        "--relations-only",
        action="store_true",
        help=(
            "Resolve only reference mentions targeted by explicit relation "
            "mentions from the selected detection run."
        ),
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = resolve_references(
        detection_run_id=args.detection_run_id,
        db_path=Path(args.db),
        relations_only=args.relations_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
