#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import urllib.parse

from crawl_page_classification import (
    AMBIGUOUS,
    CONFIRMED_INDEX,
    LEGAL_EXTRACTION_FAILURE,
    classify_heading_failure,
)


DOC_PREFIX = "/dian/compilacion/docs/"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_document_route(url: str) -> bool:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    return path.startswith(DOC_PREFIX) and path.endswith((".htm", ".html"))


def _candidate_rows(
    con: sqlite3.Connection,
    *,
    url: str | None,
) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    sql = """
        SELECT q.url, q.item_type, q.status, q.scope, q.attempts,
               q.manifestation_id, q.extraction_id, q.classification_state,
               q.classification_json, q.last_error, q.completed_at,
               q.next_attempt_at, m.local_path, m.sha256
        FROM dian_crawl_queue q
        LEFT JOIN manifestations m
          ON m.manifestation_id = q.manifestation_id
        WHERE q.item_type = 'index'
          AND q.status = 'done'
          AND q.extraction_id IS NULL
          AND q.classification_state != 'confirmed_index'
    """
    params: list[object] = []
    if url is not None:
        sql += " AND q.url = ?"
        params.append(url)
    sql += " ORDER BY q.url"
    return list(con.execute(sql, params))


def plan_reclassifications(
    con: sqlite3.Connection,
    *,
    data_root: Path,
    url: str | None = None,
    planned_at: str | None = None,
) -> dict[str, object]:
    """Build a non-mutating deterministic queue reclassification plan."""

    planned_at = planned_at or utc_now()
    items: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []

    for row in _candidate_rows(con, url=url):
        source_url = str(row["url"])
        if not _is_document_route(source_url):
            continue

        local_path = row["local_path"]
        if not local_path:
            conflicts.append(
                {
                    "url": source_url,
                    "reason": "MISSING_MANIFESTATION_OR_RAW_PATH",
                }
            )
            continue

        raw_path = data_root / str(local_path)
        if not raw_path.exists():
            conflicts.append(
                {
                    "url": source_url,
                    "reason": "RAW_FILE_NOT_FOUND",
                    "local_path": str(local_path),
                }
            )
            continue

        html = raw_path.read_text(encoding="utf-8", errors="replace")
        decision = classify_heading_failure(
            source_url=source_url,
            html=html,
        )
        classification = decision.as_dict()

        before = {
            "item_type": row["item_type"],
            "status": row["status"],
            "classification_state": row["classification_state"],
            "last_error": row["last_error"],
            "completed_at": row["completed_at"],
            "next_attempt_at": row["next_attempt_at"],
        }

        if decision.state == CONFIRMED_INDEX:
            after = {
                **before,
                "classification_state": CONFIRMED_INDEX,
                "last_error": None,
            }
        else:
            after = {
                **before,
                "item_type": "document",
                "status": "error",
                "classification_state": decision.state,
                "last_error": (
                    "classification review required: "
                    + decision.reason_code
                ),
                "completed_at": None,
                "next_attempt_at": planned_at,
            }

        items.append(
            {
                "url": source_url,
                "manifestation_id": row["manifestation_id"],
                "raw_sha256": row["sha256"],
                "classification": classification,
                "before": before,
                "after": after,
            }
        )

    counts = {
        "candidates": len(items),
        "confirmed_index": sum(
            item["classification"]["state"] == CONFIRMED_INDEX
            for item in items
        ),
        "legal_extraction_failure": sum(
            item["classification"]["state"] == LEGAL_EXTRACTION_FAILURE
            for item in items
        ),
        "ambiguous": sum(
            item["classification"]["state"] == AMBIGUOUS
            for item in items
        ),
        "conflicts": len(conflicts),
    }
    return {
        "planned_at": planned_at,
        "counts": counts,
        "items": items,
        "conflicts": conflicts,
    }


def apply_reclassifications(
    con: sqlite3.Connection,
    *,
    plan: dict[str, object],
) -> int:
    """Apply exactly a previously built plan; raw evidence is read-only."""

    changed = 0
    with con:
        for item in plan["items"]:
            after = item["after"]
            classification = item["classification"]
            cur = con.execute(
                """
                UPDATE dian_crawl_queue
                SET item_type = ?,
                    status = ?,
                    classification_state = ?,
                    classification_json = ?,
                    last_error = ?,
                    completed_at = ?,
                    next_attempt_at = ?
                WHERE url = ?
                  AND item_type = ?
                  AND status = ?
                  AND classification_state = ?
                """,
                (
                    after["item_type"],
                    after["status"],
                    after["classification_state"],
                    json.dumps(classification, ensure_ascii=False),
                    after["last_error"],
                    after["completed_at"],
                    after["next_attempt_at"],
                    item["url"],
                    item["before"]["item_type"],
                    item["before"]["status"],
                    item["before"]["classification_state"],
                ),
            )
            changed += cur.rowcount
    return changed


def reclassify(
    *,
    db_path: Path,
    data_root: Path,
    apply: bool,
    url: str | None = None,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    try:
        plan = plan_reclassifications(
            con,
            data_root=data_root,
            url=url,
        )
        changed = 0
        if apply:
            changed = apply_reclassifications(con, plan=plan)
        return {
            "mode": "apply" if apply else "preview",
            "mutated": bool(apply and changed),
            "changed_rows": changed,
            **plan,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply deterministic repair of legacy index/done "
            "crawler rows whose URL still routes as a document."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--url")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the exact plan. Omit for the non-mutating preview.",
    )
    args = parser.parse_args()

    result = reclassify(
        db_path=Path(args.db),
        data_root=Path(args.data_root),
        apply=args.apply,
        url=args.url,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
