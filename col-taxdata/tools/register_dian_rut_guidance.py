#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


PARSER_NAME = "dian_rut_guidance_registry"
PARSER_VERSION = "1"
EXPECTED_EXTRACTOR = "dian_rut_cancellation_html"
MIN_EXTRACTOR_VERSION = 2

CANONICAL_KEY = "CO:DIAN:TRAMITE:RUT_CANCELACION"
CANONICAL_SLUG = "rut_cancelacion"
TITLE = "Cancelación de la inscripción en el Registro Único Tributario (RUT)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def create_evidence(
    con: sqlite3.Connection,
    *,
    manifestation_id: str,
    source_url: str,
    source_sha256: str,
    retrieved_at: str,
    segment_id: str,
    char_start: int,
    char_end: int,
    text: str,
    role: str,
) -> tuple[str, bool]:
    evidence_id = deterministic_id(
        "EVD",
        f"{segment_id}:{PARSER_NAME}:{PARSER_VERSION}:{role}",
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
            ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?,
            ?, ?, 1.0, 'machine_validated', ?
        )
        """,
        (
            evidence_id,
            manifestation_id,
            char_start,
            char_end,
            text,
            source_url,
            source_sha256,
            retrieved_at,
            f"{PARSER_NAME}:{PARSER_VERSION}:{role}",
            PARSER_VERSION,
            segment_id,
        ),
    )
    return evidence_id, bool(cur.rowcount)


def register_guidance(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        base = con.execute(
            """
            SELECT
                te.manifestation_id,
                te.extractor_name,
                te.extractor_version,
                m.document_id,
                m.sha256,
                m.retrieved_at,
                s.source_url
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

        (
            manifestation_id,
            extractor_name,
            extractor_version,
            existing_document_id,
            source_sha256,
            retrieved_at,
            source_url,
        ) = base

        if extractor_name != EXPECTED_EXTRACTOR:
            raise RuntimeError(
                f"unsupported extractor: {extractor_name}"
            )

        try:
            extractor_version_num = int(extractor_version)
        except ValueError as exc:
            raise RuntimeError(
                f"non-numeric extractor version: {extractor_version}"
            ) from exc

        if extractor_version_num < MIN_EXTRACTOR_VERSION:
            raise RuntimeError(
                "RUT guidance registration requires extractor version "
                f">= {MIN_EXTRACTOR_VERSION}"
            )

        segments = con.execute(
            """
            SELECT
                extracted_segment_id,
                sequence_no,
                segment_type,
                char_start,
                char_end,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        if not segments:
            raise RuntimeError("extraction has no segments")

        first = segments[0]
        if first[2] != "section_heading" or first[5].strip() != TITLE:
            raise RuntimeError(
                f"unexpected RUT cancellation heading: {first[5]!r}"
            )

        questions: list[dict[str, object]] = []
        current: dict[str, object] | None = None

        for row in segments:
            segment_id, sequence_no, segment_type, char_start, char_end, text = row

            if segment_type == "question":
                current = {
                    "question": row,
                    "answers": [],
                }
                questions.append(current)
                continue

            if segment_type == "section_heading":
                current = None
                continue

            if segment_type == "answer" and current is not None:
                current["answers"].append(row)

        if len(questions) != 13:
            raise RuntimeError(
                "expected exactly 13 RUT cancellation questions; "
                f"found {len(questions)}"
            )

        empty = [
            idx
            for idx, item in enumerate(questions, start=1)
            if not item["answers"]
        ]
        if empty:
            raise RuntimeError(
                f"questions without answer segments: {empty}"
            )

        document_id = deterministic_id("DOC", CANONICAL_KEY)
        if (
            existing_document_id is not None
            and existing_document_id != document_id
        ):
            raise RuntimeError(
                "manifestation already linked to another document: "
                f"{existing_document_id}"
            )

        now = utc_now()

        questions_inserted = 0
        answer_segments_inserted = 0
        evidence_inserted = 0
        evidence_links_inserted = 0
        identifiers_inserted = 0
        identifier_evidence_inserted = 0

        with con:
            title_evidence, inserted = create_evidence(
                con,
                manifestation_id=manifestation_id,
                source_url=source_url,
                source_sha256=source_sha256,
                retrieved_at=retrieved_at,
                segment_id=first[0],
                char_start=first[3],
                char_end=first[4],
                text=first[5],
                role="document_identity",
            )
            evidence_inserted += int(inserted)

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
                VALUES (
                    ?, 'CO', 'DIAN', 'TRAMITE_OFICIAL',
                    ?, NULL, NULL, ?, ?
                )
                ON CONFLICT(document_id) DO UPDATE SET
                    entity = excluded.entity,
                    document_type = excluded.document_type,
                    title = excluded.title,
                    issued_date = NULL,
                    publication_date = NULL,
                    updated_at = excluded.updated_at
                """,
                (document_id, TITLE, now, now),
            )

            identifier_id = deterministic_id(
                "ID",
                f"{document_id}:canonical_key:{CANONICAL_KEY}",
            )
            cur = con.execute(
                """
                INSERT OR IGNORE INTO document_identifiers(
                    identifier_id,
                    document_id,
                    identifier_type,
                    identifier_value,
                    issuer,
                    is_primary
                )
                VALUES (?, ?, 'canonical_key', ?, 'DIAN', 1)
                """,
                (identifier_id, document_id, CANONICAL_KEY),
            )
            identifiers_inserted += int(bool(cur.rowcount))

            cur = con.execute(
                """
                INSERT OR IGNORE INTO document_identifier_evidence(
                    identifier_id,
                    evidence_id,
                    evidence_role,
                    created_at
                )
                VALUES (?, ?, 'page_heading', ?)
                """,
                (identifier_id, title_evidence, now),
            )
            identifier_evidence_inserted += int(bool(cur.rowcount))

            con.execute(
                """
                UPDATE manifestations
                SET document_id = ?
                WHERE manifestation_id = ?
                """,
                (document_id, manifestation_id),
            )

            con.execute(
                """
                INSERT INTO official_guidance_metadata(
                    document_id,
                    guidance_kind,
                    canonical_slug,
                    created_at,
                    updated_at
                )
                VALUES (?, 'rut_cancellation', ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    guidance_kind = excluded.guidance_kind,
                    canonical_slug = excluded.canonical_slug,
                    updated_at = excluded.updated_at
                """,
                (document_id, CANONICAL_SLUG, now, now),
            )

            for ordinal, item in enumerate(questions, start=1):
                question = item["question"]
                answers = item["answers"]

                question_id = deterministic_id(
                    "GQ",
                    f"{document_id}:{ordinal}:{question[0]}",
                )

                existed = con.execute(
                    """
                    SELECT 1
                    FROM guidance_questions
                    WHERE guidance_question_id = ?
                    """,
                    (question_id,),
                ).fetchone()

                con.execute(
                    """
                    INSERT INTO guidance_questions(
                        guidance_question_id,
                        document_id,
                        extraction_id,
                        ordinal,
                        question_segment_id,
                        question_text,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, 'validated', ?, ?
                    )
                    ON CONFLICT(guidance_question_id) DO UPDATE SET
                        extraction_id = excluded.extraction_id,
                        question_segment_id = excluded.question_segment_id,
                        question_text = excluded.question_text,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        question_id,
                        document_id,
                        extraction_id,
                        ordinal,
                        question[0],
                        question[5],
                        now,
                        now,
                    ),
                )
                questions_inserted += int(existed is None)

                question_evidence, inserted = create_evidence(
                    con,
                    manifestation_id=manifestation_id,
                    source_url=source_url,
                    source_sha256=source_sha256,
                    retrieved_at=retrieved_at,
                    segment_id=question[0],
                    char_start=question[3],
                    char_end=question[4],
                    text=question[5],
                    role=f"question_{ordinal}",
                )
                evidence_inserted += int(inserted)

                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO guidance_question_evidence(
                        guidance_question_id,
                        evidence_role,
                        evidence_order,
                        evidence_id,
                        created_at
                    )
                    VALUES (?, 'question', 0, ?, ?)
                    """,
                    (question_id, question_evidence, now),
                )
                evidence_links_inserted += int(bool(cur.rowcount))

                for answer_order, answer in enumerate(answers, start=1):
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO guidance_answer_segments(
                            guidance_question_id,
                            answer_order,
                            extracted_segment_id,
                            answer_text,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            question_id,
                            answer_order,
                            answer[0],
                            answer[5],
                            now,
                        ),
                    )
                    answer_segments_inserted += int(bool(cur.rowcount))

                    answer_evidence, inserted = create_evidence(
                        con,
                        manifestation_id=manifestation_id,
                        source_url=source_url,
                        source_sha256=source_sha256,
                        retrieved_at=retrieved_at,
                        segment_id=answer[0],
                        char_start=answer[3],
                        char_end=answer[4],
                        text=answer[5],
                        role=f"question_{ordinal}_answer_{answer_order}",
                    )
                    evidence_inserted += int(inserted)

                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO guidance_question_evidence(
                            guidance_question_id,
                            evidence_role,
                            evidence_order,
                            evidence_id,
                            created_at
                        )
                        VALUES (?, 'answer', ?, ?, ?)
                        """,
                        (
                            question_id,
                            answer_order,
                            answer_evidence,
                            now,
                        ),
                    )
                    evidence_links_inserted += int(bool(cur.rowcount))

        total_answer_segments = sum(
            len(item["answers"]) for item in questions
        )

        return {
            "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            "document_id": document_id,
            "canonical_key": CANONICAL_KEY,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "document_type": "TRAMITE_OFICIAL",
            "entity": "DIAN",
            "issued_date": None,
            "publication_date": None,
            "question_count": len(questions),
            "answer_segment_count": total_answer_segments,
            "questions_inserted": questions_inserted,
            "answer_segments_inserted": answer_segments_inserted,
            "evidence_inserted": evidence_inserted,
            "evidence_links_inserted": evidence_links_inserted,
            "identifiers_inserted": identifiers_inserted,
            "identifier_evidence_inserted":
                identifier_evidence_inserted,
            "reused": existing_document_id == document_id,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register the official DIAN RUT cancellation guidance page "
            "with structured question/answer evidence."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = register_guidance(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
