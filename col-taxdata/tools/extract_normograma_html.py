#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

EXTRACTOR_NAME = "normograma_html"
EXTRACTOR_VERSION = "1"

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

LEGAL_HEADING_RE = re.compile(
    r"^(DECRETO|RESOLUCI[ÓO]N|CONCEPTO|OFICIO|LEY|SENTENCIA|CIRCULAR)"
    r"\s+(?:N[ÚU]MERO\s+)?[A-Z0-9._/-]+\s+DE\s+\d{4}\b",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile(r"^[“\"']?ART[IÍ]CULO\s+[^\s]+", re.IGNORECASE)
REG_ARTICLE_RE = re.compile(
    r"^[“\"']?ART[IÍ]CULO\s+\d+(?:\.\d+){2,}\b",
    re.IGNORECASE,
)
PARAGRAPH_RE = re.compile(r"^[“\"']?PAR[ÁA]GRAFO\b", re.IGNORECASE)
NUMERAL_RE = re.compile(r"^\d+(?:\.\d+)*\.\s+")
FOOTER_MARKERS = {
    "COMPILACIÓN JURÍDICA DIAN",
    "COMPILACION JURIDICA DIAN",
}


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


def normalize_space(value: str) -> str:
    value = html.unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return normalize_space(value).upper()


def uppercase_ratio(value: str) -> float:
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)


class VisibleBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.current: list[str] = []
        self.skip_depth = 0

    def flush(self) -> None:
        text = normalize_space(" ".join(self.current))
        self.current.clear()
        if text and (not self.blocks or self.blocks[-1] != text):
            self.blocks.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS or tag == "br":
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            value = normalize_space(data)
            if value:
                self.current.append(value)

    def close(self) -> None:
        super().close()
        self.flush()


def find_legal_body(blocks: list[str]) -> list[str]:
    candidates: list[int] = []
    for i, block in enumerate(blocks):
        if LEGAL_HEADING_RE.match(normalize_key(block)):
            candidates.append(i)

    if not candidates:
        raise RuntimeError("legal document heading was not detected")

    start = next(
        (i for i in candidates if uppercase_ratio(blocks[i]) >= 0.80),
        candidates[0],
    )

    end = len(blocks)
    for i in range(start + 1, len(blocks)):
        if normalize_key(blocks[i]) in FOOTER_MARKERS:
            end = i
            break

    body = blocks[start:end]
    if len(body) < 5:
        raise RuntimeError("detected legal body is unexpectedly short")
    return body


def classify_segment(text: str) -> str:
    key = normalize_key(text)

    if LEGAL_HEADING_RE.match(key):
        return "document_heading"
    if REG_ARTICLE_RE.match(key):
        return "regulatory_article"
    if ARTICLE_RE.match(key):
        return "article"
    if PARAGRAPH_RE.match(key):
        return "paragraph"
    if NUMERAL_RE.match(text):
        return "numeral"
    if key in {"CONSIDERANDO:", "CONSIDERANDO", "DECRETA:", "DECRETA"}:
        return "structural_heading"
    if key.startswith("PUBLÍQUESE") or key.startswith("PUBLIQUESE"):
        return "closing"
    if len(text) <= 240 and uppercase_ratio(text) >= 0.90:
        return "section_heading"
    if key.startswith("QUE "):
        return "consideration"
    return "text"


def build_segments(blocks: list[str]) -> tuple[str, list[dict[str, object]]]:
    normalized_text = "\n\n".join(blocks) + "\n"
    segments: list[dict[str, object]] = []
    cursor = 0
    current_section: str | None = None

    for sequence_no, text in enumerate(blocks, start=1):
        segment_type = classify_segment(text)
        if segment_type in {
            "document_heading",
            "article",
            "regulatory_article",
            "section_heading",
            "structural_heading",
        }:
            current_section = text[:500]

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

    return normalized_text, segments


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


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


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
                m.manifestation_id,
                m.content_type,
                m.sha256,
                m.byte_size,
                m.local_path,
                s.source_url
            FROM manifestations m
            JOIN sources s ON s.source_id = m.source_id
            WHERE m.manifestation_id = ?
            """,
            (manifestation_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(f"manifestation not found: {manifestation_id}")

        _, content_type, raw_sha256, raw_size, local_path, source_url = row
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        if mime not in {"text/html", "application/xhtml+xml"}:
            raise RuntimeError(f"unsupported content type: {content_type}")

        raw_path = data_root / local_path
        if not raw_path.is_file():
            raise RuntimeError(f"raw source missing: {raw_path}")

        if raw_path.stat().st_size != raw_size:
            raise RuntimeError("raw source size differs from database")

        actual_raw_hash = sha256_file(raw_path)
        if actual_raw_hash != raw_sha256:
            raise RuntimeError("raw source SHA-256 differs from database")

        raw_bytes = raw_path.read_bytes()
        try:
            raw_html = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_html = raw_bytes.decode("latin-1")

        parser = VisibleBlockParser()
        parser.feed(raw_html)
        parser.close()

        body_blocks = find_legal_body(parser.blocks)
        normalized_text, segments = build_segments(body_blocks)
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
                "source_url": source_url,
                "raw_sha256": raw_sha256,
                "normalized_sha256": normalized_sha256,
                "local_path": str(output_relative),
                "char_count": len(normalized_text),
                "segment_count": len(segments),
                "reused": True,
            }

        created_at = utc_now()

        with con:
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id,
                    extractor_name, extractor_version,
                    normalized_sha256, byte_size, char_count,
                    segment_count, local_path, created_at, status
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
                        f"{segment['sequence_no']}:{segment['text_sha256']}"
                    ),
                )
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id, extraction_id, sequence_no,
                        segment_type, section_path, char_start, char_end,
                        text, text_sha256
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
                        extracted_segment_id, text, section_path
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
            "source_url": source_url,
            "raw_sha256": raw_sha256,
            "normalized_sha256": normalized_sha256,
            "local_path": str(output_relative),
            "char_count": len(normalized_text),
            "segment_count": len(segments),
            "reused": False,
        }

    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract and segment one Normograma DIAN HTML manifestation."
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
