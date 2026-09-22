#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from case_support_graph import canonical_case_source_records


def canonical_case_sources(
    con: sqlite3.Connection,
    *,
    case_id: str,
) -> list[dict[str, object]]:
    records, _document_ids = canonical_case_source_records(
        con,
        case_id=case_id,
    )

    result = []
    for record in records:
        manifestations = list(record["manifestations"])
        result.append(
            {
                "id": record["source_id"],
                "authority": record["authority"],
                "type": record["source_kind"],
                "url": record["source_url"],
                "status": (
                    "fetched_registered"
                    if manifestations
                    else "registered_without_case_document"
                ),
                "document_ids": record["document_ids"],
                "manifestations": manifestations,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the canonical source manifest for a registered case "
            "from SQLite support/evidence/relationship provenance."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--output")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    try:
        case = con.execute(
            """
            SELECT case_id, as_of_date
            FROM cases
            WHERE case_id = ?
            """,
            (args.case_id,),
        ).fetchone()
        if case is None:
            raise RuntimeError(f"case not found: {args.case_id}")

        payload = {
            "case_id": case[0],
            "as_of_date": case[1],
            "materialized_from": "sqlite_canonical_case_support_graph",
            "sources": canonical_case_sources(
                con,
                case_id=args.case_id,
            ),
        }
    finally:
        con.close()

    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    if args.output:
        Path(args.output).write_text(
            rendered,
            encoding="utf-8",
        )
    else:
        print(rendered, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
