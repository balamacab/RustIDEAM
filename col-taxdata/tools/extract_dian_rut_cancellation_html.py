#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from extract_normograma_html import (
    RawBlock,
    VisibleBlockParser,
    normalize_key,
    normalize_space,
)


EXTRACTOR_NAME = "dian_rut_cancellation_html"
EXTRACTOR_VERSION = "2"

START_HEADING = (
    "Cancelación de la inscripción en el "
    "Registro Único Tributario (RUT)"
)
END_HEADING = (
    "Levantamiento de la suspensión de la inscripción en el "
    "Registro Único Tributario (RUT)"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256_file(path) != sha256_bytes(content):
            raise RuntimeError(f"immutable output path collision: {path}")
        return

    fd, tmp_name = tempfile.mkstemp(prefix="extract-", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_bytes(content)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def is_question(text: str) -> bool:
    stripped = text.strip()
    if "?" not in stripped:
        return False

    question_start = stripped.find("¿")
    if question_start < 0:
        return False

    # DIAN sometimes prefixes a condition before the interrogative,
    # e.g. "Si una sociedad ..., ¿puede cancelar el RUT?"
    # Keep this conservative: the block must end as a question.
    return stripped.endswith("?")


def classify(block: RawBlock, sequence_no: int) -> str:
    text = normalize_space(block.text)
    key = normalize_key(text)

    if sequence_no == 1:
        return "section_heading"
    if key == "PREGUNTAS FRECUENTES":
        return "section_heading"
    if key == "GLOSARIO":
        return "section_heading"
    if is_question(text):
        return "question"
    if key.startswith("CONOZCA TODO SOBRE EL TRAMITE"):
        return "portal_link"
    return "answer"


def find_section(blocks: list[RawBlock]) -> list[RawBlock]:
    start_key = normalize_key(START_HEADING)
    end_key = normalize_key(END_HEADING)

    starts = [
        i for i, block in enumerate(blocks)
        if normalize_key(block.text) == start_key
    ]
    ends = [
        i for i, block in enumerate(blocks)
        if normalize_key(block.text) == end_key
    ]

    if len(starts) != 1:
        raise RuntimeError(
            "expected exactly one RUT cancellation heading; "
            f"found {len(starts)}"
        )

    start = starts[0]
    following_ends = [i for i in ends if i > start]
    if len(following_ends) != 1:
        raise RuntimeError(
            "expected exactly one suspension heading after cancellation; "
            f"found {len(following_ends)}"
        )

    end = following_ends[0]
    section = blocks[start:end]

    if len(section) < 10:
        raise RuntimeError("RUT cancellation section is unexpectedly short")

    if normalize_key(section[0].text) != start_key:
        raise RuntimeError("section start invariant failed")

    return section


def build_segments(
    blocks: list[RawBlock],
) -> tuple[str, list[dict[str, object]]]:
    texts = [normalize_space(block.text) for block in blocks]
    normalized_text = "\n\n".join(texts) + "\n"

    segments: list[dict[str, object]] = []
    cursor = 0
    current_section = START_HEADING
    pending_question: str | None = None

    for sequence_no, block in enumerate(blocks, start=1):
        text = normalize_space(block.text)
        segment_type = classify(block, sequence_no)

        if segment_type == "section_heading":
            current_section = text[:500]
            pending_question = None
        elif segment_type == "question":
            pending_question = text[:500]
            current_section = pending_question
        elif segment_type == "answer" and pending_question:
            current_section = pending_question

        char_start = normalized_text.find(text, cursor)
        if char_start < 0:
            raise RuntimeError("segment offset calculation failed")
        char_end = char_start + len(text)
        cursor = char_end

        segments.append(
            {
                "sequence_no": sequence_no,
                "segment_type": segment_type,
                "section_path": current_section,
                "char_start": char_start,
                "char_end": char_end,
                "text": text,
                "text_sha256": sha256_bytes(text.encode("utf-8")),
            }
        )

    question_count = sum(
        1 for segment in segments
        if segment["segment_type"] == "question"
    )
    if question_count < 5:
        raise RuntimeError(
            "RUT cancellation section has unexpectedly few questions: "
            f"{question_count}"
        )

    return normalized_text, segments


def extract_manifestation(
    *,
    manifestation_id: str,
    db_path: Path,
    data_root: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        row = con.execute(
            """
            SELECT
                m.content_type,
                m.sha256,
                m.byte_size,
                m.local_path,
                s.source_url
            FROM manifestations m
            JOIN sources s
              ON s.source_id = m.source_id
            WHERE m.manifestation_id = ?
            """,
            (manifestation_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"manifestation not found: {manifestation_id}"
            )

        content_type, raw_sha256, raw_size, local_path, source_url = row
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        if mime not in {"text/html", "application/xhtml+xml"}:
            raise RuntimeError(f"unsupported content type: {content_type}")

        raw_path = data_root / local_path
        if not raw_path.is_file():
            raise RuntimeError(f"raw source missing: {raw_path}")
        if raw_path.stat().st_size != raw_size:
            raise RuntimeError("raw source size differs from database")
        if sha256_file(raw_path) != raw_sha256:
            raise RuntimeError("raw source SHA-256 differs from database")

        raw_bytes = raw_path.read_bytes()
        try:
            raw_html = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_html = raw_bytes.decode("latin-1")

        parser = VisibleBlockParser()
        parser.feed(raw_html)
        parser.close()

        section = find_section(parser.blocks)
        normalized_text, segments = build_segments(section)
        normalized_bytes = normalized_text.encode("utf-8")
        normalized_sha256 = sha256_bytes(normalized_bytes)

        extraction_id = deterministic_id(
            "EXT",
            (
                f"col-taxdata:{manifestation_id}:"
                f"{EXTRACTOR_NAME}:{EXTRACTOR_VERSION}"
            ),
        )

        output_relative = (
            Path("extracted")
            / "sha256"
            / normalized_sha256[:2]
            / f"{normalized_sha256}.txt"
        )
        output_path = data_root / output_relative
        write_atomic(output_path, normalized_bytes)

        counts = dict(
            sorted(
                Counter(
                    segment["segment_type"]
                    for segment in segments
                ).items()
            )
        )

        existing = con.execute(
            """
            SELECT normalized_sha256, local_path, segment_count
            FROM text_extractions
            WHERE extraction_id = ?
            """,
            (extraction_id,),
        ).fetchone()

        if existing is not None:
            if (
                existing[0] != normalized_sha256
                or existing[1] != str(output_relative)
                or existing[2] != len(segments)
            ):
                raise RuntimeError(
                    "same extractor version produced a different result"
                )
            return {
                "extraction_id": extraction_id,
                "manifestation_id": manifestation_id,
                "extractor_name": EXTRACTOR_NAME,
                "extractor_version": EXTRACTOR_VERSION,
                "source_url": source_url,
                "raw_sha256": raw_sha256,
                "normalized_sha256": normalized_sha256,
                "local_path": str(output_relative),
                "char_count": len(normalized_text),
                "segment_count": len(segments),
                "segment_types": counts,
                "reused": True,
            }

        created_at = utc_now()

        with con:
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id,
                    manifestation_id,
                    extractor_name,
                    extractor_version,
                    normalized_sha256,
                    byte_size,
                    char_count,
                    segment_count,
                    local_path,
                    created_at,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    EXTRACTOR_NAME,
                    EXTRACTOR_VERSION,
                    normalized_sha256,
                    len(normalized_bytes),
                    len(normalized_text),
                    len(segments),
                    str(output_relative),
                    created_at,
                ),
            )

            for segment in segments:
                segment_id = deterministic_id(
                    "SEG",
                    (
                        f"col-taxdata:{extraction_id}:"
                        f"{segment['sequence_no']}:"
                        f"{segment['text_sha256']}"
                    ),
                )
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id,
                        extraction_id,
                        sequence_no,
                        segment_type,
                        section_path,
                        char_start,
                        char_end,
                        text,
                        text_sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment_id,
                        extraction_id,
                        segment["sequence_no"],
                        segment["segment_type"],
                        segment["section_path"],
                        segment["char_start"],
                        segment["char_end"],
                        segment["text"],
                        segment["text_sha256"],
                    ),
                )
                con.execute(
                    """
                    INSERT INTO extracted_segments_fts(
                        extracted_segment_id,
                        text,
                        section_path
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        segment_id,
                        segment["text"],
                        segment["section_path"],
                    ),
                )

        return {
            "extraction_id": extraction_id,
            "manifestation_id": manifestation_id,
            "extractor_name": EXTRACTOR_NAME,
            "extractor_version": EXTRACTOR_VERSION,
            "source_url": source_url,
            "raw_sha256": raw_sha256,
            "normalized_sha256": normalized_sha256,
            "local_path": str(output_relative),
            "char_count": len(normalized_text),
            "segment_count": len(segments),
            "segment_types": counts,
            "reused": False,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract only the official DIAN RUT cancellation section "
            "from the RUT procedure web page."
        )
    )
    parser.add_argument("--manifestation-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    args = parser.parse_args()

    result = extract_manifestation(
        manifestation_id=args.manifestation_id,
        db_path=Path(args.db),
        data_root=Path(args.data_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
