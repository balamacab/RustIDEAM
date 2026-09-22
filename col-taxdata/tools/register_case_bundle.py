#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path

from case_support_graph import canonical_case_source_records


REGISTRAR_NAME = "case_bundle_registry"
REGISTRAR_VERSION = "4"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, material).hex}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def case_title(query_text: str, case_id: str) -> str:
    for line in query_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return case_id


def copy_claim_evidence(
    con: sqlite3.Connection,
    *,
    claim_id: str,
    source_evidence_id: str,
) -> tuple[str, bool]:
    row = con.execute(
        """
        SELECT
            manifestation_id,
            segment_id,
            page_number,
            char_start,
            char_end,
            exact_quote,
            source_url,
            source_sha256,
            retrieved_at,
            confidence,
            review_status,
            extracted_segment_id
        FROM evidence
        WHERE evidence_id = ?
        """,
        (source_evidence_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"source evidence not found: {source_evidence_id}"
        )

    existing = con.execute(
        """
        SELECT evidence_id
        FROM evidence
        WHERE claim_id = ?
          AND manifestation_id = ?
          AND COALESCE(extracted_segment_id, '') =
              COALESCE(?, '')
          AND exact_quote = ?
          AND source_sha256 = ?
        ORDER BY evidence_id
        LIMIT 1
        """,
        (
            claim_id,
            row[0],
            row[11],
            row[5],
            row[7],
        ),
    ).fetchone()
    if existing is not None:
        return existing[0], False

    evidence_id = deterministic_id(
        "EVD",
        (
            f"case-claim:{claim_id}:source-evidence:"
            f"{source_evidence_id}"
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
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?
        )
        """,
        (
            evidence_id,
            claim_id,
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            f"{REGISTRAR_NAME}:{REGISTRAR_VERSION}:claim_binding",
            REGISTRAR_VERSION,
            row[9],
            row[10],
            row[11],
        ),
    )
    return evidence_id, bool(cur.rowcount)


def create_claim_evidence_from_segment(
    con: sqlite3.Connection,
    *,
    claim_id: str,
    document_id: str,
    sequence_no: int,
) -> tuple[str, str, str, bool]:
    rows = con.execute(
        """
        SELECT
            es.extracted_segment_id,
            es.extraction_id,
            es.char_start,
            es.char_end,
            es.text,
            te.extractor_name,
            te.extractor_version,
            m.manifestation_id,
            m.sha256,
            m.retrieved_at,
            m.source_id,
            s.source_url,
            te.created_at
        FROM manifestations m
        JOIN sources s
          ON s.source_id = m.source_id
        JOIN text_extractions te
          ON te.manifestation_id = m.manifestation_id
        JOIN extracted_segments es
          ON es.extraction_id = te.extraction_id
        WHERE m.document_id = ?
          AND es.sequence_no = ?
          AND te.status = 'success'
        ORDER BY te.created_at DESC, te.extraction_id DESC
        """,
        (document_id, sequence_no),
    ).fetchall()

    if not rows:
        raise RuntimeError(
            "source segment not found: "
            f"document_id={document_id} sequence_no={sequence_no}"
        )

    newest = rows[0]
    newest_created_at = newest[12]
    same_latest = [row for row in rows if row[12] == newest_created_at]
    if len(same_latest) > 1:
        identities = {
            (row[0], row[1], row[4])
            for row in same_latest
        }
        if len(identities) > 1:
            raise RuntimeError(
                "ambiguous latest source segment: "
                f"document_id={document_id} sequence_no={sequence_no}"
            )

    (
        extracted_segment_id,
        extraction_id,
        char_start,
        char_end,
        exact_quote,
        extractor_name,
        extractor_version,
        manifestation_id,
        source_sha256,
        retrieved_at,
        source_id,
        source_url,
        _created_at,
    ) = newest

    existing = con.execute(
        """
        SELECT evidence_id
        FROM evidence
        WHERE claim_id = ?
          AND manifestation_id = ?
          AND extracted_segment_id = ?
          AND exact_quote = ?
          AND source_sha256 = ?
        ORDER BY evidence_id
        LIMIT 1
        """,
        (
            claim_id,
            manifestation_id,
            extracted_segment_id,
            exact_quote,
            source_sha256,
        ),
    ).fetchone()
    if existing is not None:
        return (
            existing[0],
            extracted_segment_id,
            source_id,
            False,
        )

    evidence_id = deterministic_id(
        "EVD",
        (
            f"case-claim:{claim_id}:extracted-segment:"
            f"{extracted_segment_id}"
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
            ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?,
            ?, ?, 1.0, 'validated', ?
        )
        """,
        (
            evidence_id,
            claim_id,
            manifestation_id,
            char_start,
            char_end,
            exact_quote,
            source_url,
            source_sha256,
            retrieved_at,
            (
                f"{REGISTRAR_NAME}:{REGISTRAR_VERSION}:"
                f"source_segment:{extractor_name}:{extraction_id}"
            ),
            extractor_version,
            extracted_segment_id,
        ),
    )
    return evidence_id, extracted_segment_id, source_id, bool(cur.rowcount)




def register_case(
    *,
    case_dir: Path,
    as_of_date: str,
    db_path: Path,
) -> dict[str, object]:
    query_path = case_dir / "query.md"
    evidence_path = case_dir / "evidence.json"
    manifest_path = case_dir / "sources" / "manifest.json"
    bindings_path = case_dir / "claim_bindings.json"

    query_text = query_path.read_text(encoding="utf-8")
    legacy = load_json(evidence_path)
    manifest = load_json(manifest_path)
    bindings = load_json(bindings_path) if bindings_path.exists() else {}

    case_id = legacy["case_id"]
    if manifest.get("case_id") != case_id:
        raise RuntimeError("case_id mismatch between evidence and manifest")

    now = utc_now()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    claims_inserted = 0
    claims_reused = 0
    claims_validated = 0
    case_items_inserted = 0
    evidence_inserted = 0
    declared_manifest_sources_present = []
    missing_sources = []
    linked_documents = set()
    linked_relationships = set()
    linked_evidence = set()

    try:
        with con:
            existing_case = con.execute(
                "SELECT 1 FROM cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            con.execute(
                """
                INSERT INTO cases(
                    case_id, title, query_text, as_of_date,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    title = excluded.title,
                    query_text = excluded.query_text,
                    as_of_date = excluded.as_of_date,
                    updated_at = excluded.updated_at
                """,
                (
                    case_id,
                    case_title(query_text, case_id),
                    query_text,
                    as_of_date,
                    now,
                    now,
                ),
            )

            for source in manifest.get("sources", []):
                source_id = source["id"]
                exists = con.execute(
                    "SELECT 1 FROM sources WHERE source_id = ?",
                    (source_id,),
                ).fetchone()
                if not exists:
                    missing_sources.append(source_id)
                    continue

                declared_manifest_sources_present.append(source_id)
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO case_items(
                        case_id, item_type, item_id, relevance, added_at
                    )
                    VALUES (?, 'source', ?, ?, ?)
                    """,
                    (
                        case_id,
                        source_id,
                        "official source referenced by case manifest",
                        now,
                    ),
                )
                case_items_inserted += int(bool(cur.rowcount))

                for (document_id,) in con.execute(
                    """
                    SELECT DISTINCT document_id
                    FROM manifestations
                    WHERE source_id = ?
                      AND document_id IS NOT NULL
                    """,
                    (source_id,),
                ):
                    linked_documents.add(document_id)
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO case_items(
                            case_id, item_type, item_id,
                            relevance, added_at
                        )
                        VALUES (?, 'document', ?, ?, ?)
                        """,
                        (
                            case_id,
                            document_id,
                            f"canonical document reached from {source_id}",
                            now,
                        ),
                    )
                    case_items_inserted += int(bool(cur.rowcount))

            for entry in legacy.get("claims", []):
                claim_id = entry["id"]
                binding = bindings.get(claim_id)
                desired_status = (
                    binding.get("status", "validated")
                    if binding
                    else "candidate"
                )
                if desired_status not in {
                    "candidate",
                    "validated",
                    "rejected",
                    "conflicting",
                    "unresolved",
                    "human_verified",
                }:
                    raise RuntimeError(
                        f"unsupported claim status for {claim_id}: "
                        f"{desired_status}"
                    )

                existing = con.execute(
                    """
                    SELECT status
                    FROM claims
                    WHERE claim_id = ?
                    """,
                    (claim_id,),
                ).fetchone()

                if existing is None:
                    con.execute(
                        """
                        INSERT INTO claims(
                            claim_id,
                            subject_type,
                            subject_id,
                            predicate,
                            object_type,
                            object_id,
                            object_literal,
                            claim_type,
                            status,
                            extraction_method,
                            confidence_extraction,
                            requires_human_review,
                            created_at
                        )
                        VALUES (
                            ?, 'case', ?, 'legal_conclusion',
                            NULL, NULL, ?, 'case_legal_conclusion',
                            ?, ?, 1.0, 0, ?
                        )
                        """,
                        (
                            claim_id,
                            case_id,
                            entry["claim"],
                            desired_status,
                            f"{REGISTRAR_NAME}:{REGISTRAR_VERSION}",
                            now,
                        ),
                    )
                    claims_inserted += 1
                else:
                    claims_reused += 1
                    if binding and existing[0] not in {
                        "validated", "human_verified"
                    }:
                        con.execute(
                            """
                            UPDATE claims
                            SET status = ?,
                                object_literal = ?,
                                extraction_method = ?,
                                confidence_extraction = 1.0,
                                requires_human_review = 0
                            WHERE claim_id = ?
                            """,
                            (
                                desired_status,
                                entry["claim"],
                                f"{REGISTRAR_NAME}:{REGISTRAR_VERSION}",
                                claim_id,
                            ),
                        )

                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO case_items(
                        case_id, item_type, item_id, relevance, added_at
                    )
                    VALUES (?, 'claim', ?, ?, ?)
                    """,
                    (
                        case_id,
                        claim_id,
                        (
                            "canonical claim; legacy JSON status="
                            f"{entry.get('status', 'unknown')}"
                        ),
                        now,
                    ),
                )
                case_items_inserted += int(bool(cur.rowcount))

                if not binding:
                    continue

                relationship_ids = binding.get("relationship_ids", [])
                evidence_ids = binding.get("evidence_ids", [])
                source_segments = binding.get("source_segments", [])

                if not (
                    relationship_ids
                    or evidence_ids
                    or source_segments
                ):
                    raise RuntimeError(
                        f"binding has no canonical support: {claim_id}"
                    )

                generated_evidence_ids = []

                if relationship_ids:
                    primary_relationship_id = binding.get(
                        "primary_relationship_id"
                    )
                    if primary_relationship_id not in relationship_ids:
                        raise RuntimeError(
                            "primary relationship is not bound: "
                            f"{claim_id}"
                        )

                    primary_evidence_id = None
                    for relationship_id in relationship_ids:
                        row = con.execute(
                            """
                            SELECT evidence_id, status
                            FROM relationships
                            WHERE relationship_id = ?
                            """,
                            (relationship_id,),
                        ).fetchone()
                        if row is None:
                            raise RuntimeError(
                                "relationship not found: "
                                f"{relationship_id}"
                            )
                        if row[1] != "validated":
                            raise RuntimeError(
                                "relationship not validated: "
                                f"{relationship_id}"
                            )
                        if row[0] is None:
                            raise RuntimeError(
                                "relationship has no evidence: "
                                f"{relationship_id}"
                            )

                        linked_relationships.add(relationship_id)
                        cur = con.execute(
                            """
                            INSERT OR IGNORE INTO case_items(
                                case_id, item_type, item_id,
                                relevance, added_at
                            )
                            VALUES (?, 'relationship', ?, ?, ?)
                            """,
                            (
                                case_id,
                                relationship_id,
                                binding.get(
                                    "relevance",
                                    (
                                        "canonical support for "
                                        f"{claim_id}"
                                    ),
                                ),
                                now,
                            ),
                        )
                        case_items_inserted += int(bool(cur.rowcount))

                        if relationship_id == primary_relationship_id:
                            primary_evidence_id = row[0]

                    if primary_evidence_id is None:
                        raise RuntimeError(
                            f"primary evidence unresolved: {claim_id}"
                        )

                    new_evidence_id, inserted = copy_claim_evidence(
                        con,
                        claim_id=claim_id,
                        source_evidence_id=primary_evidence_id,
                    )
                    evidence_inserted += int(inserted)
                    generated_evidence_ids.append(new_evidence_id)

                for source_evidence_id in evidence_ids:
                    row = con.execute(
                        """
                        SELECT 1
                        FROM evidence
                        WHERE evidence_id = ?
                        """,
                        (source_evidence_id,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError(
                            "bound evidence not found: "
                            f"{source_evidence_id}"
                        )
                    new_evidence_id, inserted = copy_claim_evidence(
                        con,
                        claim_id=claim_id,
                        source_evidence_id=source_evidence_id,
                    )
                    evidence_inserted += int(inserted)
                    generated_evidence_ids.append(new_evidence_id)

                for segment_binding in source_segments:
                    document_id = segment_binding["document_id"]
                    sequence_no = int(
                        segment_binding["sequence_no"]
                    )
                    new_evidence_id, extracted_segment_id, source_id, inserted = (
                        create_claim_evidence_from_segment(
                            con,
                            claim_id=claim_id,
                            document_id=document_id,
                            sequence_no=sequence_no,
                        )
                    )
                    evidence_inserted += int(inserted)
                    generated_evidence_ids.append(new_evidence_id)
                    linked_documents.add(document_id)

                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO case_items(
                            case_id, item_type, item_id,
                            relevance, added_at
                        )
                        VALUES (?, 'document', ?, ?, ?)
                        """,
                        (
                            case_id,
                            document_id,
                            (
                                f"canonical document supporting "
                                f"{claim_id}"
                            ),
                            now,
                        ),
                    )
                    case_items_inserted += int(bool(cur.rowcount))

                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO case_items(
                            case_id, item_type, item_id,
                            relevance, added_at
                        )
                        VALUES (
                            ?, 'extracted_segment', ?, ?, ?
                        )
                        """,
                        (
                            case_id,
                            extracted_segment_id,
                            (
                                f"source segment supporting "
                                f"{claim_id}"
                            ),
                            now,
                        ),
                    )
                    case_items_inserted += int(bool(cur.rowcount))

                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO case_items(
                            case_id, item_type, item_id,
                            relevance, added_at
                        )
                        VALUES (?, 'source', ?, ?, ?)
                        """,
                        (
                            case_id,
                            source_id,
                            (
                                f"official source supporting "
                                f"{claim_id}"
                            ),
                            now,
                        ),
                    )
                    case_items_inserted += int(bool(cur.rowcount))

                for new_evidence_id in generated_evidence_ids:
                    linked_evidence.add(new_evidence_id)
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO case_items(
                            case_id, item_type, item_id,
                            relevance, added_at
                        )
                        VALUES (?, 'evidence', ?, ?, ?)
                        """,
                        (
                            case_id,
                            new_evidence_id,
                            f"canonical evidence for {claim_id}",
                            now,
                        ),
                    )
                    case_items_inserted += int(bool(cur.rowcount))

                con.execute(
                    """
                    UPDATE claims
                    SET status = ?,
                        requires_human_review = 0
                    WHERE claim_id = ?
                    """,
                    (desired_status, claim_id),
                )
                if desired_status in {"validated", "human_verified"}:
                    claims_validated += 1

            canonical_sources, canonical_document_ids = (
                canonical_case_source_records(
                    con,
                    case_id=case_id,
                )
            )

            for document_id in canonical_document_ids:
                linked_documents.add(document_id)
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO case_items(
                        case_id, item_type, item_id,
                        relevance, added_at
                    )
                    VALUES (?, 'document', ?, ?, ?)
                    """,
                    (
                        case_id,
                        document_id,
                        "canonical document reached from case support graph",
                        now,
                    ),
                )
                case_items_inserted += int(bool(cur.rowcount))

            for source_record in canonical_sources:
                source_id = source_record["source_id"]
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO case_items(
                        case_id, item_type, item_id,
                        relevance, added_at
                    )
                    VALUES (?, 'source', ?, ?, ?)
                    """,
                    (
                        case_id,
                        source_id,
                        "canonical source reached from case support graph",
                        now,
                    ),
                )
                case_items_inserted += int(bool(cur.rowcount))

        return {
            "registrar_name": REGISTRAR_NAME,
            "registrar_version": REGISTRAR_VERSION,
            "case_id": case_id,
            "as_of_date": as_of_date,
            "case_reused": existing_case is not None,
            "claims_total": len(legacy.get("claims", [])),
            "claims_inserted": claims_inserted,
            "claims_reused": claims_reused,
            "claims_validated_from_canonical_bindings":
                claims_validated,
            "case_items_inserted": case_items_inserted,
            "evidence_inserted": evidence_inserted,
            "available_sources": [
                item["source_id"]
                for item in canonical_sources
            ],
            "canonical_sources": canonical_sources,
            "declared_manifest_sources_present":
                sorted(declared_manifest_sources_present),
            "missing_sources": sorted(missing_sources),
            "linked_documents": sorted(linked_documents),
            "linked_relationships": sorted(linked_relationships),
            "linked_evidence": sorted(linked_evidence),
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register a case bundle in SQLite and promote only claims "
            "with explicit canonical evidence bindings."
        )
    )
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_case(
        case_dir=Path(args.case_dir),
        as_of_date=args.as_of_date,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
