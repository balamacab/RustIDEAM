from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
import uuid

from temporal_candidate_model import ROLES, RoleResolution, Segment, TemporalCandidate


@dataclass
class Delta:
    evidence_inserted: int = 0
    candidates_inserted: int = 0
    resolutions_inserted: int = 0
    review_items_inserted: int = 0
    review_items_resolved: int = 0
    review_items_updated: int = 0
    events_inserted: int = 0
    event_evidence_links_inserted: int = 0
    legacy_events_superseded: int = 0
    relationship_basis_deleted: int = 0
    relationship_basis_inserted: int = 0
    relationship_dates_cleared: int = 0
    relationship_dates_updated: int = 0
    document_dates_updated: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, material).hex}"


def load_subject(
    con: sqlite3.Connection,
    extraction_id: str,
) -> tuple[str, str, str, str, str, str, list[Segment]]:
    row = con.execute(
        """
        SELECT te.manifestation_id, m.document_id, m.sha256, m.retrieved_at,
               s.source_url, te.extractor_version
        FROM text_extractions te
        JOIN manifestations m ON m.manifestation_id=te.manifestation_id
        JOIN sources s ON s.source_id=m.source_id
        WHERE te.extraction_id=?
        """,
        (extraction_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"extraction not found: {extraction_id}")
    manifestation_id, document_id, raw_sha, retrieved_at, source_url, extractor_version = row
    if document_id is None:
        raise RuntimeError("manifestation has no canonical document identity")
    segments = [
        Segment(*segment)
        for segment in con.execute(
            """
            SELECT extracted_segment_id, sequence_no, segment_type, section_path,
                   char_start, char_end, text
            FROM extracted_segments
            WHERE extraction_id=?
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()
    ]
    return (
        manifestation_id,
        document_id,
        raw_sha,
        retrieved_at,
        source_url,
        extractor_version,
        segments,
    )


def persist_candidate_evidence(
    con: sqlite3.Connection,
    *,
    candidate: TemporalCandidate,
    manifestation_id: str,
    source_url: str,
    source_sha256: str,
    retrieved_at: str,
    processor_name: str,
    processor_version: str,
    review_status: str,
    delta: Delta,
) -> str:
    evidence_id = deterministic_id("EVD", f"temporal-candidate:{candidate.candidate_id}")
    existing = con.execute(
        "SELECT exact_quote, char_start, char_end, source_sha256 FROM evidence WHERE evidence_id=?",
        (evidence_id,),
    ).fetchone()
    expected = (
        candidate.exact_quote,
        candidate.char_start,
        candidate.char_end,
        source_sha256,
    )
    if existing is not None:
        if existing != expected:
            raise RuntimeError("same temporal evidence id produced different evidence")
        return evidence_id
    con.execute(
        """
        INSERT INTO evidence(
            evidence_id, claim_id, manifestation_id, segment_id, page_number,
            char_start, char_end, exact_quote, source_url, source_sha256,
            retrieved_at, extraction_method, extractor_version, confidence,
            review_status, extracted_segment_id
        ) VALUES (?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            manifestation_id,
            candidate.char_start,
            candidate.char_end,
            candidate.exact_quote,
            source_url,
            source_sha256,
            retrieved_at,
            f"{processor_name}:{processor_version}:candidate:{candidate.role}:{candidate.context_type}",
            processor_version,
            1.0 if candidate.trusted_structure else None,
            review_status,
            candidate.segment.segment_id,
        ),
    )
    delta.evidence_inserted += 1
    return evidence_id


def persist_candidate(
    con: sqlite3.Connection,
    *,
    candidate: TemporalCandidate,
    evidence_id: str,
    extraction_id: str,
    manifestation_id: str,
    document_id: str,
    processor_name: str,
    processor_version: str,
    now: str,
    delta: Delta,
) -> None:
    expected = (
        candidate.candidate_date,
        candidate.context_type,
        int(candidate.trusted_structure),
        candidate.char_start,
        candidate.char_end,
        candidate.exact_quote,
        evidence_id,
    )
    existing = con.execute(
        """
        SELECT candidate_date, context_type, is_trusted_structure, char_start,
               char_end, exact_quote, evidence_id
        FROM temporal_candidates WHERE temporal_candidate_id=?
        """,
        (candidate.candidate_id,),
    ).fetchone()
    if existing is not None:
        if existing != expected:
            raise RuntimeError("same temporal candidate id produced different data")
        return
    con.execute(
        """
        INSERT INTO temporal_candidates(
            temporal_candidate_id, extraction_id, manifestation_id, document_id,
            extracted_segment_id, role, candidate_date, context_type,
            is_trusted_structure, char_start, char_end, exact_quote, evidence_id,
            processor_name, processor_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate.candidate_id,
            extraction_id,
            manifestation_id,
            document_id,
            candidate.segment.segment_id,
            candidate.role,
            candidate.candidate_date,
            candidate.context_type,
            int(candidate.trusted_structure),
            candidate.char_start,
            candidate.char_end,
            candidate.exact_quote,
            evidence_id,
            processor_name,
            processor_version,
            now,
        ),
    )
    delta.candidates_inserted += 1


def persist_resolution(
    con: sqlite3.Connection,
    *,
    extraction_id: str,
    document_id: str,
    resolution: RoleResolution,
    processor_name: str,
    processor_version: str,
    now: str,
    delta: Delta,
) -> str:
    resolution_id = deterministic_id(
        "TRS",
        f"{extraction_id}:{resolution.role}:{processor_name}:{processor_version}",
    )
    promoted_id = resolution.promoted.candidate_id if resolution.promoted else None
    expected = (
        resolution.status,
        len(resolution.candidates),
        len(resolution.trusted_candidates),
        promoted_id,
    )
    existing = con.execute(
        """
        SELECT status, candidate_count, trusted_candidate_count, promoted_candidate_id
        FROM temporal_role_resolutions WHERE temporal_resolution_id=?
        """,
        (resolution_id,),
    ).fetchone()
    if existing is not None:
        if existing != expected:
            raise RuntimeError("same temporal resolution id produced different decision")
        return resolution_id
    con.execute(
        """
        INSERT INTO temporal_role_resolutions(
            temporal_resolution_id, extraction_id, document_id, role, status,
            candidate_count, trusted_candidate_count, promoted_candidate_id,
            processor_name, processor_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolution_id,
            extraction_id,
            document_id,
            resolution.role,
            resolution.status,
            len(resolution.candidates),
            len(resolution.trusted_candidates),
            promoted_id,
            processor_name,
            processor_version,
            now,
            now,
        ),
    )
    delta.resolutions_inserted += 1
    return resolution_id


def sync_review_state(
    con: sqlite3.Connection,
    *,
    resolution_id: str,
    resolution: RoleResolution,
    now: str,
    delta: Delta,
) -> None:
    review_id = deterministic_id("REV", f"temporal-resolution:{resolution_id}")
    existing = con.execute(
        "SELECT reason_code, resolved_at FROM review_queue WHERE review_id=?",
        (review_id,),
    ).fetchone()
    if resolution.status == "resolved":
        if existing is not None and existing[1] is None:
            con.execute(
                """
                UPDATE review_queue
                SET resolved_at=?, resolution='resolved_by_unique_trusted_structure'
                WHERE review_id=?
                """,
                (now, review_id),
            )
            delta.review_items_resolved += 1
        return
    reason = (
        "TEMPORAL_ROLE_AMBIGUOUS"
        if resolution.status == "ambiguous"
        else "TEMPORAL_ROLE_UNRESOLVED"
    )
    if existing is None:
        con.execute(
            """
            INSERT INTO review_queue(
                review_id, entity_type, entity_id, reason_code, severity,
                created_at, resolved_at, resolution, reviewer
            ) VALUES (?, 'temporal_role_resolution', ?, ?, 'medium', ?, NULL, NULL, NULL)
            """,
            (review_id, resolution_id, reason, now),
        )
        delta.review_items_inserted += 1
    elif existing[0] != reason or existing[1] is not None:
        con.execute(
            """
            UPDATE review_queue
            SET reason_code=?, resolved_at=NULL, resolution=NULL, reviewer=NULL
            WHERE review_id=?
            """,
            (reason, review_id),
        )
        delta.review_items_updated += 1


def persist_candidate_state(
    con: sqlite3.Connection,
    *,
    extraction_id: str,
    manifestation_id: str,
    document_id: str,
    source_url: str,
    source_sha256: str,
    retrieved_at: str,
    resolutions: dict[str, RoleResolution],
    processor_name: str,
    processor_version: str,
    now: str,
    delta: Delta,
) -> dict[str, str]:
    """Persist all evidence candidates and the explicit per-role decision."""
    evidence_by_candidate: dict[str, str] = {}
    for role in ROLES:
        resolution = resolutions[role]
        for candidate in resolution.candidates:
            promoted = (
                resolution.promoted is not None
                and candidate.candidate_id == resolution.promoted.candidate_id
            )
            review_status = (
                "machine_validated"
                if promoted
                else ("ambiguous" if resolution.status == "ambiguous" else "unresolved")
            )
            evidence_id = persist_candidate_evidence(
                con,
                candidate=candidate,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                processor_name=processor_name,
                processor_version=processor_version,
                review_status=review_status,
                delta=delta,
            )
            evidence_by_candidate[candidate.candidate_id] = evidence_id
            persist_candidate(
                con,
                candidate=candidate,
                evidence_id=evidence_id,
                extraction_id=extraction_id,
                manifestation_id=manifestation_id,
                document_id=document_id,
                processor_name=processor_name,
                processor_version=processor_version,
                now=now,
                delta=delta,
            )
        resolution_id = persist_resolution(
            con,
            extraction_id=extraction_id,
            document_id=document_id,
            resolution=resolution,
            processor_name=processor_name,
            processor_version=processor_version,
            now=now,
            delta=delta,
        )
        sync_review_state(
            con,
            resolution_id=resolution_id,
            resolution=resolution,
            now=now,
            delta=delta,
        )
    return evidence_by_candidate
