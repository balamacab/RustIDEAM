#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from extract_document_temporality import extract_temporality
from temporal_candidate_model import ROLES


def raw_hash_registry(con: sqlite3.Connection) -> dict[str, object]:
    """Return a stable digest of registered immutable manifestation hashes."""
    rows = con.execute(
        "SELECT manifestation_id, sha256 FROM manifestations ORDER BY manifestation_id"
    ).fetchall()
    digest = hashlib.sha256()
    for manifestation_id, sha256 in rows:
        digest.update(f"{manifestation_id}:{sha256}\n".encode("utf-8"))
    return {"manifestation_count": len(rows), "sha256": digest.hexdigest()}


def select_extractions(
    con: sqlite3.Connection,
    *,
    document_ids: Iterable[str] | None = None,
    extraction_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[tuple[str, str, str]]:
    """Select one latest successful extraction for each canonical document.

    Reprocessing is document-scoped rather than manifestation-scoped so dry-run
    deltas remain directly comparable with apply even when a canonical document
    has multiple archived manifestations.
    """
    requested_documents = set(document_ids or ())
    requested_extractions = set(extraction_ids or ())
    rows = con.execute(
        """
        WITH ranked AS (
            SELECT
                te.extraction_id,
                m.document_id,
                m.manifestation_id,
                ROW_NUMBER() OVER (
                    PARTITION BY m.document_id
                    ORDER BY m.retrieved_at DESC, te.created_at DESC,
                             te.extraction_id DESC
                ) AS rn
            FROM text_extractions te
            JOIN manifestations m
              ON m.manifestation_id = te.manifestation_id
            WHERE te.status = 'success'
              AND m.document_id IS NOT NULL
        )
        SELECT extraction_id, document_id, manifestation_id
        FROM ranked
        WHERE rn = 1
        ORDER BY document_id
        """
    ).fetchall()
    if requested_documents:
        rows = [row for row in rows if row[1] in requested_documents]
    if requested_extractions:
        rows = [row for row in rows if row[0] in requested_extractions]
    if limit is not None:
        rows = rows[:limit]
    return rows


def reprocess(
    *,
    db_path: Path,
    apply: bool = False,
    document_ids: Iterable[str] | None = None,
    extraction_ids: Iterable[str] | None = None,
    limit: int | None = None,
    include_details: bool = False,
) -> dict[str, object]:
    """Preview or apply DEF-0004 temporal reprocessing.

    Preview is the default. Every selected document executes the same extractor
    mutation path as apply, but each operation is rolled back by the extractor.
    """
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        before_raw = raw_hash_registry(con)
        all_canonical_documents = {
            row[0]
            for row in con.execute(
                "SELECT DISTINCT document_id FROM manifestations "
                "WHERE document_id IS NOT NULL ORDER BY document_id"
            ).fetchall()
        }
        available = select_extractions(con)
        selected = select_extractions(
            con,
            document_ids=document_ids,
            extraction_ids=extraction_ids,
            limit=limit,
        )
    finally:
        con.close()

    role_status = {role: Counter() for role in ROLES}
    aggregate_delta: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    processed: list[dict[str, object]] = []

    for extraction_id, document_id, manifestation_id in selected:
        try:
            result = extract_temporality(
                extraction_id=extraction_id,
                db_path=db_path,
                dry_run=not apply,
            )
        except Exception as exc:
            errors.append(
                {
                    "document_id": document_id,
                    "manifestation_id": manifestation_id,
                    "extraction_id": extraction_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue

        for role in ROLES:
            role_status[role][result["roles"][role]["status"]] += 1
        aggregate_delta.update(result["delta"])
        processed.append(
            {
                "document_id": document_id,
                "manifestation_id": manifestation_id,
                "extraction_id": extraction_id,
                "roles": result["roles"],
                "issued_date": result["issued_date"],
                "publication_date": result["publication_date"],
                "effective_date": result["effective_date"],
            }
        )

    con = sqlite3.connect(db_path)
    try:
        after_raw = raw_hash_registry(con)
    finally:
        con.close()

    selected_document_ids = {row[1] for row in selected}
    available_document_ids = {row[1] for row in available}
    requested_documents = set(document_ids or ())
    requested_extractions = set(extraction_ids or ())
    if requested_documents:
        inventory_scope = all_canonical_documents & requested_documents
    elif requested_extractions:
        inventory_scope = selected_document_ids
    else:
        inventory_scope = all_canonical_documents
    skipped_no_successful_extraction = sorted(
        inventory_scope - available_document_ids
    )

    delta_dict = dict(sorted(aggregate_delta.items()))
    delta_summary = {
        "inserts": sum(
            delta_dict.get(key, 0)
            for key in (
                "evidence_inserted",
                "candidates_inserted",
                "resolutions_inserted",
                "review_items_inserted",
                "events_inserted",
                "event_evidence_links_inserted",
                "relationship_basis_inserted",
            )
        ),
        "updates": sum(
            delta_dict.get(key, 0)
            for key in (
                "review_items_resolved",
                "review_items_updated",
                "legacy_events_superseded",
                "relationship_dates_cleared",
                "relationship_dates_updated",
                "document_dates_updated",
            )
        ),
        "deletes": delta_dict.get("relationship_basis_deleted", 0),
        "rebindings": delta_dict.get("relationship_basis_inserted", 0),
    }

    return {
        "mode": "apply" if apply else "dry-run",
        "dry_run": not apply,
        "persistent_mutation": apply and bool(sum(aggregate_delta.values())),
        "canonical_documents_in_scope": len(inventory_scope),
        "selected_documents": len(selected),
        "processed_documents": len(processed),
        "skipped_count": len(skipped_no_successful_extraction),
        "skipped": {
            "no_successful_extraction": len(skipped_no_successful_extraction),
            "representative_document_ids": skipped_no_successful_extraction[:20],
        },
        "error_count": len(errors),
        "errors": errors,
        "role_status": {
            role: dict(sorted(counter.items()))
            for role, counter in role_status.items()
        },
        "delta": delta_dict,
        "delta_summary": delta_summary,
        "raw_hash_registry_before": before_raw,
        "raw_hash_registry_after": after_raw,
        "raw_hash_registry_unchanged": before_raw == after_raw,
        "documents": processed if include_details else [],
        "details_included": include_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply DEF-0004 temporal candidate reprocessing. "
            "Dry-run is the default."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the reprocessing result. Omit for a safe dry-run.",
    )
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--extraction-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Include per-document decisions in JSON output.",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")

    result = reprocess(
        db_path=Path(args.db),
        apply=args.apply,
        document_ids=args.document_id,
        extraction_ids=args.extraction_id,
        limit=args.limit,
        include_details=args.details,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
