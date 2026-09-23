#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from document_family_identity import (
    FamilyIdentityResult,
    SegmentIdentityInput,
    assess_supported_family_identity,
    default_family_title,
)
from source_identity import (
    IdentityAssessment,
    IdentitySignal,
    assess_generic_normative_identity,
    canonical_identifier_values,
    equivalent_existing_canonical_key,
    persist_assessment,
)


IDENTITY_REVIEW_REASONS = {
    "SOURCE_IDENTITY_CONFLICT",
    "SOURCE_IDENTITY_UNRESOLVED",
    "FAMILY_IDENTITY_AMBIGUOUS",
    "ISSUER_IDENTITY_UNRESOLVED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def _load_identity_input(
    con: sqlite3.Connection,
    extraction_id: str,
) -> tuple[str, str | None, str, list[SegmentIdentityInput]]:
    base = con.execute(
        """
        SELECT te.manifestation_id, m.document_id, s.source_url
        FROM text_extractions te
        JOIN manifestations m
          ON m.manifestation_id = te.manifestation_id
        JOIN sources s
          ON s.source_id = m.source_id
        WHERE te.extraction_id = ?
        """,
        (extraction_id,),
    ).fetchone()
    if base is None:
        raise RuntimeError(f"extraction not found: {extraction_id}")

    rows = con.execute(
        """
        SELECT sequence_no, segment_type, text
        FROM extracted_segments
        WHERE extraction_id = ?
        ORDER BY sequence_no
        """,
        (extraction_id,),
    ).fetchall()
    segments = [
        SegmentIdentityInput(int(sequence_no), segment_type, text)
        for sequence_no, segment_type, text in rows
    ]
    return base[0], base[1], base[2], segments


def _first_document_heading(
    segments: list[SegmentIdentityInput],
) -> str | None:
    for segment in segments:
        if segment.segment_type == "document_heading":
            return segment.text
    return None


def _assess_identity(
    *,
    source_url: str,
    segments: list[SegmentIdentityInput],
) -> tuple[IdentityAssessment, IdentitySignal | None, str | None, FamilyIdentityResult | None]:
    family_result = assess_supported_family_identity(source_url, segments)
    if family_result is not None:
        title = (
            family_result.title
            if family_result.title is not None
            else (
                default_family_title(family_result.identity)
                if family_result.identity is not None
                else None
            )
        )
        return (
            family_result.assessment,
            family_result.identity,
            title,
            family_result,
        )

    heading = _first_document_heading(segments)
    if heading is None:
        raise RuntimeError("document heading not found")
    assessment = assess_generic_normative_identity(source_url, heading)
    return assessment, assessment.content, heading, None


def _mark_identity_reviews_resolved(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    resolution: str,
    now: str,
) -> int:
    placeholders = ",".join("?" for _ in IDENTITY_REVIEW_REASONS)
    return con.execute(
        f"""
        UPDATE review_queue
        SET resolved_at = ?,
            resolution = ?,
            reviewer = 'system'
        WHERE entity_type = 'manifestation'
          AND entity_id = ?
          AND resolved_at IS NULL
          AND reason_code IN ({placeholders})
        """,
        (
            now,
            resolution,
            manifestation_id,
            *sorted(IDENTITY_REVIEW_REASONS),
        ),
    ).rowcount


def _unresolved_result(
    *,
    assessment: IdentityAssessment,
    review_id: str | None,
    source_url: str,
    title: str | None,
    manifestation_id: str,
    extraction_id: str,
) -> dict[str, object]:
    return {
        "status": "unresolved",
        "reason_code": assessment.reason_code,
        "review_id": review_id,
        "source_family": assessment.source.family,
        "source_url": source_url,
        "heading": title,
        "manifestation_id": manifestation_id,
        "extraction_id": extraction_id,
        "document_id": None,
    }


def register_document_identity(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    """Register canonical identity using the source-family-specific contract.

    DEF-0003 families are dispatched before the generic normative parser. This
    prevents quoted normative acts from becoming identities while allowing a
    complete trusted source identity to stand without a synthetic heading.
    """

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        (
            manifestation_id,
            existing_document_id,
            source_url,
            segments,
        ) = _load_identity_input(con, extraction_id)
        assessment, identity, title, family_result = _assess_identity(
            source_url=source_url,
            segments=segments,
        )

        with con:
            review_id = persist_assessment(
                con,
                manifestation_id=manifestation_id,
                extraction_id=extraction_id,
                assessment=assessment,
            )

            if not assessment.accepted or identity is None:
                if existing_document_id is not None:
                    con.execute(
                        "UPDATE manifestations SET document_id = NULL "
                        "WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                return _unresolved_result(
                    assessment=assessment,
                    review_id=review_id,
                    source_url=source_url,
                    title=title,
                    manifestation_id=manifestation_id,
                    extraction_id=extraction_id,
                )

            doc_type = identity.document_type
            number = identity.number
            year = identity.year
            issuer_key = identity.issuer_key
            canonical_key = identity.canonical_key
            assert doc_type and number and year and issuer_key and canonical_key
            document_id = deterministic_id("DOC", canonical_key)
            now = utc_now()

            if (
                existing_document_id is not None
                and existing_document_id != document_id
            ):
                equivalent_key = equivalent_existing_canonical_key(
                    con,
                    document_id=existing_document_id,
                    signal=identity,
                    allow_unqualified_scoped=family_result is not None,
                )
                if equivalent_key is not None:
                    document_id = existing_document_id
                    # Generic normative registrars preserve an existing
                    # equivalent key (including historic zero padding). DEF-0003
                    # families upgrade to the issuer-aware primary key while
                    # retaining the old key as a non-primary alias.
                    if family_result is None:
                        canonical_key = equivalent_key
                else:
                    conflict = IdentityAssessment(
                        "unresolved",
                        assessment.source,
                        assessment.content,
                        "SOURCE_IDENTITY_CONFLICT",
                    )
                    review_id = persist_assessment(
                        con,
                        manifestation_id=manifestation_id,
                        extraction_id=extraction_id,
                        assessment=conflict,
                    )
                    con.execute(
                        "UPDATE manifestations SET document_id = NULL "
                        "WHERE manifestation_id = ?",
                        (manifestation_id,),
                    )
                    return _unresolved_result(
                        assessment=conflict,
                        review_id=review_id,
                        source_url=source_url,
                        title=title,
                        manifestation_id=manifestation_id,
                        extraction_id=extraction_id,
                    )

            con.execute(
                """
                INSERT INTO documents(
                    document_id,
                    jurisdiction,
                    entity,
                    document_type,
                    title,
                    issued_date,
                    publication_date,
                    created_at,
                    updated_at
                )
                VALUES (?, 'CO', ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    entity = excluded.entity,
                    document_type = excluded.document_type,
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    issuer_key,
                    doc_type,
                    title,
                    now,
                    now,
                ),
            )

            for identifier_value, is_primary in canonical_identifier_values(identity):
                identifier_id = deterministic_id(
                    "ID",
                    f"{document_id}:canonical:{identifier_value}",
                )
                con.execute(
                    """
                    INSERT INTO document_identifiers(
                        identifier_id,
                        document_id,
                        identifier_type,
                        identifier_value,
                        issuer,
                        is_primary
                    )
                    VALUES (?, ?, 'canonical_key', ?, ?, ?)
                    ON CONFLICT(document_id, identifier_type, identifier_value)
                    DO UPDATE SET
                        issuer = excluded.issuer,
                        is_primary = excluded.is_primary
                    """,
                    (
                        identifier_id,
                        document_id,
                        identifier_value,
                        issuer_key,
                        is_primary,
                    ),
                )

            con.execute(
                "UPDATE manifestations SET document_id = ? "
                "WHERE manifestation_id = ?",
                (document_id, manifestation_id),
            )
            reviews_resolved = _mark_identity_reviews_resolved(
                con,
                manifestation_id=manifestation_id,
                resolution=f"Resolved by family-safe identity registration: {canonical_key}",
                now=now,
            )

        return {
            "status": "registered",
            "document_id": document_id,
            "canonical_key": canonical_key,
            "issuer_key": issuer_key,
            "document_type": doc_type,
            "number": number,
            "year": year,
            "heading": title,
            "source_family": assessment.source.family,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "reused": existing_document_id == document_id,
            "identity_reviews_resolved": reviews_resolved,
            "family_metadata": (
                family_result.metadata if family_result is not None else {}
            ),
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register the canonical identity of a legal document using a "
            "source-family-specific parser before any generic fallback."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_document_identity(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
