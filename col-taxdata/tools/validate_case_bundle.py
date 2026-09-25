#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from case_claim_review import case_claim_requires_human_review
from materialize_case_report import render_report
from materialize_case_sources import render_source_manifest


def load_manifest(case_dir: Path) -> dict:
    path = case_dir / "sources" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_case(
    *,
    con: sqlite3.Connection,
    case_id: str,
    case_dir: Path,
) -> dict[str, object]:
    case = con.execute(
        """
        SELECT case_id, status, as_of_date
        FROM cases
        WHERE case_id = ?
        """,
        (case_id,),
    ).fetchone()
    if case is None:
        raise RuntimeError(f"case not found: {case_id}")

    claims = con.execute(
        """
        SELECT c.claim_id, c.status, c.requires_human_review
        FROM claims c
        JOIN case_items ci
          ON ci.item_type = 'claim'
         AND ci.item_id = c.claim_id
        WHERE ci.case_id = ?
        ORDER BY c.claim_id
        """,
        (case_id,),
    ).fetchall()

    claim_ids = {row[0] for row in claims}

    bundle = json.loads(
        (case_dir / "evidence.json").read_text(encoding="utf-8")
    )
    bundle_claims = {
        item["id"]: item
        for item in bundle.get("claims", [])
    }
    claim_review_state_mismatches = []
    for claim_id, status, requires_human_review in claims:
        bundle_claim = bundle_claims.get(claim_id)
        if bundle_claim is None:
            continue
        try:
            expected = case_claim_requires_human_review(
                bundle_claim,
                persisted_status=status,
            )
        except ValueError as exc:
            claim_review_state_mismatches.append(
                {
                    "claim_id": claim_id,
                    "status": status,
                    "persisted_requires_human_review": bool(
                        requires_human_review
                    ),
                    "expected_requires_human_review": None,
                    "reason": str(exc),
                }
            )
            continue

        actual = bool(requires_human_review)
        if actual != expected:
            claim_review_state_mismatches.append(
                {
                    "claim_id": claim_id,
                    "status": status,
                    "persisted_requires_human_review": actual,
                    "expected_requires_human_review": expected,
                }
            )

    unsupported_validated_claims = []
    for claim_id, status, _requires_human_review in claims:
        if status not in {"validated", "human_verified"}:
            continue

        evidence_count = con.execute(
            """
            SELECT COUNT(*)
            FROM evidence
            WHERE claim_id = ?
            """,
            (claim_id,),
        ).fetchone()[0]

        relationship_count = con.execute(
            """
            SELECT COUNT(*)
            FROM case_items ci
            JOIN relationships r
              ON r.relationship_id = ci.item_id
            WHERE ci.case_id = ?
              AND ci.item_type = 'relationship'
              AND r.relationship_id IN (
                  SELECT rp.relationship_id
                  FROM relationship_provenance rp
              )
              AND (
                  r.evidence_id IN (
                      SELECT evidence_id
                      FROM evidence
                      WHERE claim_id = ?
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM evidence e
                      WHERE e.claim_id = ?
                        AND e.manifestation_id = (
                            SELECT manifestation_id
                            FROM evidence re
                            WHERE re.evidence_id = r.evidence_id
                        )
                  )
              )
            """,
            (case_id, claim_id, claim_id),
        ).fetchone()[0]

        if evidence_count == 0 and relationship_count == 0:
            unsupported_validated_claims.append(claim_id)

    db_sources = {
        row[0]
        for row in con.execute(
            """
            SELECT item_id
            FROM case_items
            WHERE case_id = ?
              AND item_type = 'source'
            """,
            (case_id,),
        )
    }

    manifest = load_manifest(case_dir)
    manifest_sources = {
        item["id"]
        for item in manifest.get("sources", [])
    }
    stored_source_manifest = (
        case_dir / "sources" / "manifest.json"
    ).read_text(encoding="utf-8")
    generated_source_manifest = render_source_manifest(
        con,
        case_id=case_id,
    )
    source_manifest_matches_materializer = (
        stored_source_manifest == generated_source_manifest
    )

    orphan_case_items = con.execute(
        """
        SELECT item_type, item_id
        FROM case_items ci
        WHERE ci.case_id = ?
          AND (
            (ci.item_type = 'claim' AND NOT EXISTS (
                SELECT 1
                FROM claims c
                WHERE c.claim_id = ci.item_id
            ))
            OR
            (ci.item_type = 'evidence' AND NOT EXISTS (
                SELECT 1
                FROM evidence e
                WHERE e.evidence_id = ci.item_id
            ))
            OR
            (ci.item_type = 'relationship' AND NOT EXISTS (
                SELECT 1
                FROM relationships r
                WHERE r.relationship_id = ci.item_id
            ))
            OR
            (ci.item_type = 'source' AND NOT EXISTS (
                SELECT 1
                FROM sources s
                WHERE s.source_id = ci.item_id
            ))
            OR
            (ci.item_type = 'document' AND NOT EXISTS (
                SELECT 1
                FROM documents d
                WHERE d.document_id = ci.item_id
            ))
            OR
            (ci.item_type = 'extracted_segment' AND NOT EXISTS (
                SELECT 1
                FROM extracted_segments es
                WHERE es.extracted_segment_id = ci.item_id
            ))
          )
        ORDER BY item_type, item_id
        """,
        (case_id,),
    ).fetchall()

    evidence_count = con.execute(
        """
        SELECT COUNT(*)
        FROM evidence
        WHERE claim_id IN (
            SELECT item_id
            FROM case_items
            WHERE case_id = ?
              AND item_type = 'claim'
        )
        """,
        (case_id,),
    ).fetchone()[0]

    relationship_count = con.execute(
        """
        SELECT COUNT(*)
        FROM case_items
        WHERE case_id = ?
          AND item_type = 'relationship'
        """,
        (case_id,),
    ).fetchone()[0]

    duplicate_claim_evidence = con.execute(
        """
        SELECT
            claim_id,
            manifestation_id,
            COALESCE(extracted_segment_id, ''),
            exact_quote,
            source_sha256,
            COUNT(*) AS n
        FROM evidence
        WHERE claim_id IN (
            SELECT item_id
            FROM case_items
            WHERE case_id = ?
              AND item_type = 'claim'
        )
        GROUP BY
            claim_id,
            manifestation_id,
            COALESCE(extracted_segment_id, ''),
            exact_quote,
            source_sha256
        HAVING COUNT(*) > 1
        ORDER BY claim_id
        """,
        (case_id,),
    ).fetchall()

    manifest_matches_sqlite = manifest_sources == db_sources
    all_claims_validated = bool(claims) and all(
        status in {"validated", "human_verified"}
        for _, status, _requires_human_review in claims
    )

    report_path = case_dir / "report.md"
    if report_path.exists():
        stored_report = report_path.read_text(encoding="utf-8")
        generated_report = render_report(
            con=con,
            case_id=case_id,
            case_dir=case_dir,
        )
        report_matches_materializer = stored_report == generated_report
    else:
        report_matches_materializer = False

    errors = []

    if manifest.get("case_id") != case_id:
        errors.append("manifest_case_id_mismatch")
    if not manifest_matches_sqlite:
        errors.append("manifest_sources_do_not_match_sqlite")
    if not source_manifest_matches_materializer:
        errors.append(
            "source_manifest_not_materialized_from_canonical_state"
        )
    if orphan_case_items:
        errors.append("orphan_case_items")
    if unsupported_validated_claims:
        errors.append("validated_claim_without_canonical_support")
    if duplicate_claim_evidence:
        errors.append("duplicate_claim_evidence")
    if claim_review_state_mismatches:
        errors.append("claim_review_state_mismatch")
    if not report_matches_materializer:
        errors.append("report_not_materialized_from_canonical_state")

    return {
        "case_id": case_id,
        "case_status": case[1],
        "as_of_date": case[2],
        "claims_total": len(claims),
        "claims_validated_or_human_verified": sum(
            status in {"validated", "human_verified"}
            for _, status, _requires_human_review in claims
        ),
        "all_claims_validated_or_human_verified":
            all_claims_validated,
        "claim_ids": sorted(claim_ids),
        "evidence_count": evidence_count,
        "relationship_count": relationship_count,
        "sqlite_sources": sorted(db_sources),
        "manifest_sources": sorted(manifest_sources),
        "manifest_matches_sqlite": manifest_matches_sqlite,
        "source_manifest_matches_materializer":
            source_manifest_matches_materializer,
        "report_matches_materializer": report_matches_materializer,
        "orphan_case_items": [
            {"item_type": row[0], "item_id": row[1]}
            for row in orphan_case_items
        ],
        "unsupported_validated_claims":
            unsupported_validated_claims,
        "claim_review_state_mismatches":
            claim_review_state_mismatches,
        "duplicate_claim_evidence": [
            {
                "claim_id": row[0],
                "manifestation_id": row[1],
                "extracted_segment_id": row[2] or None,
                "source_sha256": row[4],
                "count": row[5],
            }
            for row in duplicate_claim_evidence
        ],
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate structural consistency of a registered case bundle."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    try:
        result = validate_case(
            con=con,
            case_id=args.case_id,
            case_dir=Path(args.case_dir),
        )
    finally:
        con.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
