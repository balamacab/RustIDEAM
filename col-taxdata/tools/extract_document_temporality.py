#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from temporal_candidate_model import ROLES, collect_candidates, resolve_role
from temporal_candidate_storage import (
    Delta,
    deterministic_id,
    load_subject,
    persist_candidate_state,
    utc_now,
)
from temporal_event_promotion import (
    find_legacy_events,
    promote_resolved_events,
    rebind_relationship_temporality,
    resolved_dates,
    supersede_legacy_events,
    update_document_dates,
)

PROCESSOR_NAME = "document_temporality_regex"
PROCESSOR_VERSION = "3"
LEGACY_PROCESSOR_VERSION = "2"


def process_temporality(
    con: sqlite3.Connection,
    *,
    extraction_id: str,
) -> dict[str, object]:
    """Resolve document temporality without converting ambiguity into fact."""
    (
        manifestation_id,
        document_id,
        source_sha256,
        retrieved_at,
        source_url,
        source_extractor_version,
        segments,
    ) = load_subject(con, extraction_id)
    candidates = collect_candidates(
        deterministic_id=deterministic_id,
        extraction_id=extraction_id,
        segments=segments,
        processor_name=PROCESSOR_NAME,
        processor_version=PROCESSOR_VERSION,
    )
    resolutions = {
        role: resolve_role(role, candidates[role])
        for role in ROLES
    }
    now = utc_now()
    delta = Delta()
    evidence_by_candidate = persist_candidate_state(
        con,
        extraction_id=extraction_id,
        manifestation_id=manifestation_id,
        document_id=document_id,
        source_url=source_url,
        source_sha256=source_sha256,
        retrieved_at=retrieved_at,
        resolutions=resolutions,
        processor_name=PROCESSOR_NAME,
        processor_version=PROCESSOR_VERSION,
        now=now,
        delta=delta,
    )

    legacy_events = find_legacy_events(
        con,
        document_id=document_id,
        processor_name=PROCESSOR_NAME,
        legacy_processor_version=LEGACY_PROCESSOR_VERSION,
    )
    supersede_legacy_events(con, legacy_events=legacy_events, delta=delta)
    (
        publication,
        issued,
        commencement,
        publication_date,
        issued_date,
        effective_date,
    ) = resolved_dates(resolutions)
    update_document_dates(
        con,
        document_id=document_id,
        issued_date=issued_date,
        publication_date=publication_date,
        legacy_events=legacy_events,
        now=now,
        delta=delta,
    )
    issued_event_id, _, effective_event_id = promote_resolved_events(
        con,
        document_id=document_id,
        publication=publication,
        issued=issued,
        commencement=commencement,
        publication_date=publication_date,
        issued_date=issued_date,
        effective_date=effective_date,
        evidence_by_candidate=evidence_by_candidate,
        processor_version=PROCESSOR_VERSION,
        now=now,
        delta=delta,
    )
    source_count, inverse_count = rebind_relationship_temporality(
        con,
        document_id=document_id,
        issued_event_id=issued_event_id,
        effective_event_id=effective_event_id,
        issued_date=issued_date,
        effective_date=effective_date,
        now=now,
        delta=delta,
    )

    return {
        "processor_name": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "source_extractor_version": source_extractor_version,
        "status": "completed",
        "document_id": document_id,
        "manifestation_id": manifestation_id,
        "extraction_id": extraction_id,
        "roles": {
            role: {
                "status": resolutions[role].status,
                "candidate_count": len(resolutions[role].candidates),
                "trusted_candidate_count": len(resolutions[role].trusted_candidates),
                "promoted_candidate_id": (
                    resolutions[role].promoted.candidate_id
                    if resolutions[role].promoted
                    else None
                ),
            }
            for role in ROLES
        },
        "issued_date": issued_date,
        "publication_date": publication_date,
        "effective_date": effective_date,
        "source_relationships_considered": source_count,
        "inverse_relationships_considered": inverse_count,
        "delta": delta.as_dict(),
    }


def extract_temporality(
    *,
    extraction_id: str,
    db_path: Path,
    dry_run: bool = False,
) -> dict[str, object]:
    """Run the same decision path for preview and apply.

    Dry-run performs every SQL mutation inside a savepoint and then rolls the
    savepoint back, which makes its reported delta directly comparable to apply.
    """
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.execute("SAVEPOINT def0004_temporality")
        try:
            result = process_temporality(con, extraction_id=extraction_id)
            if dry_run:
                con.execute("ROLLBACK TO def0004_temporality")
            con.execute("RELEASE def0004_temporality")
            if not dry_run:
                con.commit()
        except Exception:
            con.execute("ROLLBACK TO def0004_temporality")
            con.execute("RELEASE def0004_temporality")
            raise
        result["dry_run"] = dry_run
        result["persistent_mutation"] = (
            not dry_run and any(result["delta"].values())
        )
        return result
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract evidence-backed temporal candidates and promote only "
            "uniquely supported document-level temporal state."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = extract_temporality(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
