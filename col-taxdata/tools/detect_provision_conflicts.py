#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path


DETECTOR_NAME = "provision_designation_conflict_detector"
DETECTOR_VERSION = "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def detect_conflicts(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        extraction = con.execute(
            """
            SELECT te.manifestation_id, m.document_id
            FROM text_extractions te
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            WHERE te.extraction_id = ?
            """,
            (extraction_id,),
        ).fetchone()

        if extraction is None:
            raise RuntimeError(f"extraction not found: {extraction_id}")

        manifestation_id, document_id = extraction
        if document_id is None:
            raise RuntimeError(
                "manifestation is not linked to a canonical document"
            )

        rows = con.execute(
            """
            SELECT
                p.normalized_designation,
                COUNT(po.provision_observation_id) AS observation_count,
                COUNT(DISTINCT po.normative_text_sha256)
                    AS distinct_normative_text_count
            FROM provisions p
            JOIN provision_observations po
              ON po.provision_id = p.provision_id
            WHERE p.document_id = ?
              AND po.extraction_id = ?
            GROUP BY p.normalized_designation
            HAVING COUNT(po.provision_observation_id) > 1
               AND COUNT(DISTINCT po.normative_text_sha256) > 1
            ORDER BY p.normalized_designation
            """,
            (document_id, extraction_id),
        ).fetchall()

        now = utc_now()
        inserted = 0
        reviews_inserted = 0
        conflicts: list[dict[str, object]] = []

        with con:
            for (
                designation,
                observation_count,
                distinct_text_count,
            ) in rows:
                material = (
                    f"{document_id}:{extraction_id}:"
                    f"{designation}:{DETECTOR_VERSION}"
                )
                conflict_id = deterministic_id("PCON", material)

                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO provision_designation_conflicts(
                        conflict_id,
                        document_id,
                        extraction_id,
                        normalized_designation,
                        observation_count,
                        distinct_normative_text_count,
                        reason_code,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?,
                            'DUPLICATE_DESIGNATION_IN_SOURCE',
                            'open', ?)
                    """,
                    (
                        conflict_id,
                        document_id,
                        extraction_id,
                        designation,
                        observation_count,
                        distinct_text_count,
                        now,
                    ),
                )
                if cur.rowcount:
                    inserted += 1

                review_id = deterministic_id(
                    "REV",
                    f"{conflict_id}:DUPLICATE_DESIGNATION_IN_SOURCE",
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
                    VALUES (
                        ?,
                        'provision_designation_conflict',
                        ?,
                        'DUPLICATE_DESIGNATION_IN_SOURCE',
                        'high',
                        ?
                    )
                    """,
                    (review_id, conflict_id, now),
                )
                if review.rowcount:
                    reviews_inserted += 1

                conflicts.append(
                    {
                        "conflict_id": conflict_id,
                        "designation": designation,
                        "observation_count": observation_count,
                        "distinct_normative_text_count": distinct_text_count,
                    }
                )

        return {
            "detector_name": DETECTOR_NAME,
            "detector_version": DETECTOR_VERSION,
            "manifestation_id": manifestation_id,
            "document_id": document_id,
            "extraction_id": extraction_id,
            "conflict_count": len(conflicts),
            "conflicts_inserted": inserted,
            "review_items_inserted": reviews_inserted,
            "conflicts": conflicts,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect incompatible observations sharing one canonical "
            "provision designation."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = detect_conflicts(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
