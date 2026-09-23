#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from document_family_identity import SUPPORTED_FAMILIES
from promote_editorial_relationships import promote as promote_editorial
from promote_operational_relationships import promote as promote_operational
from register_dian_doctrine import register_doctrine
from register_document_identity import register_document_identity
from resolve_references import RESOLUTION_METHOD, resolve_references
from source_identity import DIAN_CONCEPTO, DIAN_OFICIO, classify_source_url


def _supported_rows(
    con: sqlite3.Connection,
    *,
    only_unidentified: bool,
) -> list[tuple[str, str, str, str | None, str]]:
    rows = con.execute(
        """
        SELECT
            s.source_url,
            m.manifestation_id,
            te.extraction_id,
            m.document_id,
            m.sha256
        FROM sources s
        JOIN manifestations m
          ON m.source_id = s.source_id
        JOIN text_extractions te
          ON te.manifestation_id = m.manifestation_id
        WHERE te.status = 'success'
          AND s.source_url LIKE
              'https://normograma.dian.gov.co/dian/compilacion/docs/%'
        ORDER BY s.source_url, te.created_at DESC, te.extraction_id
        """
    ).fetchall()

    selected: list[tuple[str, str, str, str | None, str]] = []
    seen_manifestations: set[str] = set()
    for row in rows:
        source_url, manifestation_id, extraction_id, document_id, sha256 = row
        if manifestation_id in seen_manifestations:
            continue
        if classify_source_url(source_url).family not in SUPPORTED_FAMILIES:
            continue
        if only_unidentified and document_id is not None:
            continue
        seen_manifestations.add(manifestation_id)
        selected.append(
            (source_url, manifestation_id, extraction_id, document_id, sha256)
        )
    return selected


def _sha_snapshot(
    rows: list[tuple[str, str, str, str | None, str]],
) -> dict[str, str]:
    return {manifestation_id: sha256 for _, manifestation_id, _, _, sha256 in rows}


def _aggregate_sha(snapshot: dict[str, str]) -> str:
    material = "\n".join(
        f"{manifestation_id}:{snapshot[manifestation_id]}"
        for manifestation_id in sorted(snapshot)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _state_counts(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "documents": "SELECT COUNT(*) FROM documents",
        "identifiers": "SELECT COUNT(*) FROM document_identifiers",
        "doctrine_metadata": "SELECT COUNT(*) FROM dian_doctrine_metadata",
        "doctrine_positions": "SELECT COUNT(*) FROM doctrine_positions",
        "relationships": "SELECT COUNT(*) FROM relationships",
    }
    return {
        name: int(con.execute(sql).fetchone()[0])
        for name, sql in queries.items()
    }


def _detection_runs(
    con: sqlite3.Connection,
    extraction_id: str,
) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            """
            SELECT detection_run_id
            FROM reference_detection_runs
            WHERE extraction_id = ?
            ORDER BY detection_run_id
            """,
            (extraction_id,),
        )
    ]


def _replay_relationships(
    *,
    db_path: Path,
    detection_run_ids: list[str],
) -> dict[str, int]:
    totals = {
        "detection_runs": len(detection_run_ids),
        "relationships_inserted": 0,
        "relationships_reused": 0,
        "promoters_skipped": 0,
    }
    for detection_run_id in detection_run_ids:
        resolve_references(
            detection_run_id=detection_run_id,
            db_path=db_path,
            relations_only=True,
        )
        for promoter in (promote_operational, promote_editorial):
            result = promoter(
                detection_run_id=detection_run_id,
                resolution_method=RESOLUTION_METHOD,
                db_path=db_path,
            )
            if result.get("status") == "skipped":
                totals["promoters_skipped"] += 1
                continue
            totals["relationships_inserted"] += int(
                result.get("relationships_inserted", 0)
            )
            totals["relationships_reused"] += int(
                result.get("relationships_reused", 0)
            )
    return totals


def _run_apply_logic(
    *,
    db_path: Path,
    only_unidentified: bool,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        rows = _supported_rows(con, only_unidentified=only_unidentified)
        before_hashes = _sha_snapshot(rows)
        before_counts = _state_counts(con)
        before_bindings = {
            manifestation_id: document_id
            for _, manifestation_id, _, document_id, _ in rows
        }
    finally:
        con.close()

    registered: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    relationship_totals = {
        "detection_runs": 0,
        "relationships_inserted": 0,
        "relationships_reused": 0,
        "promoters_skipped": 0,
    }

    for source_url, manifestation_id, extraction_id, _, _ in rows:
        family = classify_source_url(source_url).family
        if family in {DIAN_CONCEPTO, DIAN_OFICIO}:
            result = register_doctrine(
                extraction_id=extraction_id,
                db_path=db_path,
            )
        else:
            result = register_document_identity(
                extraction_id=extraction_id,
                db_path=db_path,
            )

        summary = {
            "source_url": source_url,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "source_family": family,
            "status": result.get("status"),
            "document_id": result.get("document_id"),
            "canonical_key": result.get("canonical_key"),
            "reason_code": result.get("reason_code"),
        }
        if result.get("status") != "registered":
            unresolved.append(summary)
            if result.get("reason_code") in {
                "SOURCE_IDENTITY_CONFLICT",
                "FAMILY_IDENTITY_AMBIGUOUS",
            }:
                conflicts.append(summary)
            continue

        registered.append(summary)

        replay_con = sqlite3.connect(db_path)
        try:
            run_ids = _detection_runs(replay_con, extraction_id)
        finally:
            replay_con.close()
        if not run_ids:
            skipped.append(
                {
                    **summary,
                    "skip_reason": "NO_REFERENCE_DETECTION_RUN",
                }
            )
            continue
        replay = _replay_relationships(
            db_path=db_path,
            detection_run_ids=run_ids,
        )
        for key in relationship_totals:
            relationship_totals[key] += replay[key]

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        after_rows = _supported_rows(con, only_unidentified=False)
        current_sha = {
            manifestation_id: sha256
            for _, manifestation_id, _, _, sha256 in after_rows
            if manifestation_id in before_hashes
        }
        after_counts = _state_counts(con)
        after_bindings = {
            manifestation_id: document_id
            for _, manifestation_id, _, document_id, _ in after_rows
            if manifestation_id in before_bindings
        }
    finally:
        con.close()

    rebindings = sum(
        before_bindings[manifestation_id] != after_bindings.get(manifestation_id)
        for manifestation_id in before_bindings
    )
    hashes_unchanged = before_hashes == current_sha
    if not hashes_unchanged:
        raise RuntimeError(
            "raw manifestation SHA-256 values changed during family reprocessing"
        )

    delta = {
        "documents_inserted": after_counts["documents"] - before_counts["documents"],
        "identifiers_inserted": (
            after_counts["identifiers"] - before_counts["identifiers"]
        ),
        "doctrine_metadata_inserted": (
            after_counts["doctrine_metadata"] - before_counts["doctrine_metadata"]
        ),
        "doctrine_positions_inserted": (
            after_counts["doctrine_positions"] - before_counts["doctrine_positions"]
        ),
        "relationships_inserted_net": (
            after_counts["relationships"] - before_counts["relationships"]
        ),
        "manifestation_rebindings": rebindings,
        "documents_deleted": 0,
    }

    return {
        "scope": "unidentified" if only_unidentified else "all_supported",
        "scanned_manifestations": len(rows),
        "registered_count": len(registered),
        "unresolved_count": len(unresolved),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "unchanged_bindings": len(rows) - rebindings,
        "delta": delta,
        "relationship_replay": relationship_totals,
        "registered": registered,
        "unresolved": unresolved,
        "conflicts": conflicts,
        "skipped": skipped,
        "raw_sha256_aggregate_before": _aggregate_sha(before_hashes),
        "raw_sha256_aggregate_after": _aggregate_sha(current_sha),
        "hashes_unchanged": hashes_unchanged,
    }


def _backup_database(source: Path, destination: Path) -> None:
    source_con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_con = sqlite3.connect(destination)
    try:
        source_con.backup(destination_con)
    finally:
        destination_con.close()
        source_con.close()


def reprocess(
    *,
    db_path: Path,
    apply: bool,
    only_unidentified: bool = False,
) -> dict[str, object]:
    """Replay supported-family identity safely.

    Dry-run uses SQLite's backup API and executes the exact apply path against
    the temporary copy. The production/original database is never mutated by
    preview mode.
    """

    if apply:
        result = _run_apply_logic(
            db_path=db_path,
            only_unidentified=only_unidentified,
        )
        return {
            "mode": "apply",
            "persistent_mutation": True,
            **result,
        }

    with tempfile.TemporaryDirectory(prefix="def0003-dry-run-") as tmp:
        preview_db = Path(tmp) / "preview.sqlite"
        _backup_database(db_path, preview_db)
        result = _run_apply_logic(
            db_path=preview_db,
            only_unidentified=only_unidentified,
        )
    return {
        "mode": "dry-run",
        "persistent_mutation": False,
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay DEF-0003 supported document-family identity. Default mode "
            "is a non-mutating SQLite-copy dry-run."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply to the selected database. Default is safe dry-run.",
    )
    parser.add_argument(
        "--only-unidentified",
        action="store_true",
        help=(
            "Scope replay to supported-family manifestations whose current "
            "document_id is NULL. Use this first before all-family replay."
        ),
    )
    args = parser.parse_args()
    result = reprocess(
        db_path=Path(args.db),
        apply=args.apply,
        only_unidentified=args.only_unidentified,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
