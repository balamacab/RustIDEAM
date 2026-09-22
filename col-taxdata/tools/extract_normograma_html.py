#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXTRACTOR_NAME = "normograma_html"
EXTRACTOR_VERSION = "2"

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "tbody", "tfoot", "thead", "ul",
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
PORTAL_ANNOTATION_PREFIXES = (
    "CONSULTAR LA VIGENCIA DE ESTA NORMA DIRECTAMENTE EN LOS ARTICULOS QUE MODIFICA Y/O ADICIONA",
)


@dataclass(frozen=True)
class RawBlock:
    text: str
    kind: str = "text"


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


def is_portal_annotation(text: str) -> bool:
    key = normalize_key(text).strip("<> ")
    return any(key.startswith(prefix) for prefix in PORTAL_ANNOTATION_PREFIXES)


class VisibleBlockParser(HTMLParser):
    """Extract visible text while preserving table rows as single blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[RawBlock] = []
        self.current: list[str] = []
        self.skip_depth = 0
        self.table_depth = 0
        self.row_depth = 0
        self.cell_depth = 0
        self.current_row: list[str] = []
        self.current_cell: list[str] = []

    def append_block(self, text: str, kind: str = "text") -> None:
        text = normalize_space(text)
        if not text:
            return
        block = RawBlock(text=text, kind=kind)
        if self.blocks and self.blocks[-1] == block:
            return
        self.blocks.append(block)

    def flush_text(self) -> None:
        text = normalize_space(" ".join(self.current))
        self.current.clear()
        if text:
            self.append_block(text, "text")

    def flush_cell(self) -> None:
        text = normalize_space(" ".join(self.current_cell))
        self.current_cell.clear()
        if text:
            self.current_row.append(text)

    def flush_row(self) -> None:
        self.flush_cell()
        if self.current_row:
            self.append_block(" | ".join(self.current_row), "table_row")
        self.current_row.clear()

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()

        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "table":
            self.flush_text()
            self.table_depth += 1
            return

        if self.table_depth and tag == "tr":
            self.flush_text()
            if self.row_depth:
                self.flush_row()
            self.row_depth += 1
            self.current_row.clear()
            return

        if self.row_depth and tag in {"td", "th"}:
            self.flush_cell()
            self.cell_depth += 1
            return

        if tag == "br":
            if self.cell_depth:
                self.current_cell.append(" ")
            else:
                self.flush_text()
            return

        if tag in BLOCK_TAGS and not self.cell_depth:
            self.flush_text()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        if tag in {"td", "th"} and self.cell_depth:
            self.flush_cell()
            self.cell_depth -= 1
            return

        if tag == "tr" and self.row_depth:
            self.flush_row()
            self.row_depth -= 1
            return

        if tag == "table" and self.table_depth:
            if self.row_depth:
                self.flush_row()
                self.row_depth = 0
            self.table_depth -= 1
            self.flush_text()
            return

        if tag in BLOCK_TAGS and not self.cell_depth:
            self.flush_text()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return

        value = normalize_space(data)
        if not value:
            return

        if self.cell_depth:
            self.current_cell.append(value)
        else:
            self.current.append(value)

    def close(self) -> None:
        super().close()
        if self.row_depth:
            self.flush_row()
        self.flush_text()


def find_legal_body(blocks: list[RawBlock]) -> list[RawBlock]:
    candidates: list[int] = []
    for i, block in enumerate(blocks):
        if LEGAL_HEADING_RE.match(normalize_key(block.text)):
            candidates.append(i)

    if not candidates:
        raise RuntimeError("legal document heading was not detected")

    start = next(
        (
            i
            for i in candidates
            if uppercase_ratio(blocks[i].text) >= 0.80
        ),
        candidates[0],
    )

    end = len(blocks)
    for i in range(start + 1, len(blocks)):
        if normalize_key(blocks[i].text) in FOOTER_MARKERS:
            end = i
            break

    body = [
        block
        for block in blocks[start:end]
        if not is_portal_annotation(block.text)
    ]
    if len(body) < 5:
        raise RuntimeError("detected legal body is unexpectedly short")
    return body


def classify_segment(block: RawBlock) -> str:
    text = block.text
    key = normalize_key(text)

    if block.kind == "table_row":
        return "table_row"
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


def build_segments(
    blocks: list[RawBlock],
) -> tuple[str, list[dict[str, object]]]:
    texts = [block.text for block in blocks]
    normalized_text = "\n\n".join(texts) + "\n"
    segments: list[dict[str, object]] = []
    cursor = 0
    current_section: str | None = None

    for sequence_no, block in enumerate(blocks, start=1):
        text = block.text
        segment_type = classify_segment(block)
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

        counts = dict(
            sorted(Counter(segment["segment_type"] for segment in segments).items())
        )

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
