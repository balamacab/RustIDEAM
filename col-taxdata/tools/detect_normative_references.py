#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path

DETECTOR_NAME = "normative_reference_regex"
DETECTOR_VERSION = "1"

DOCUMENT_RE = re.compile(
    r"\b(?P<type>Ley|Decreto|Resoluci[oó]n|Circular|Concepto|Oficio)"
    r"(?:\s+[ÚU]nico)?"
    r"\s+(?:(?:N[uú]mero|No\.?|Nro\.?)\s*)?"
    r"(?P<number>\d+[A-Za-z]?)"
    r"\s+de\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

ARTICLE_SCOPE_RE = re.compile(
    r"\bart[ií]culos?\s+"
    r"(?P<articles>"
    r"\d+(?:\.\d+)*(?:-\d+)?"
    r"(?:\s*\.?\s*(?:,|y)\s*"
    r"\d+(?:\.\d+)*(?:-\d+)?)*"
    r")"
    r"\s+(?:del|de\s+la)\s+"
    r"(?P<target>"
    r"Estatuto\s+Tributario"
    r"|(?:Ley|Decreto|Resoluci[oó]n)"
    r"(?:\s+[ÚU]nico)?"
    r"\s+(?:(?:N[uú]mero|No\.?|Nro\.?)\s*)?"
    r"\d+[A-Za-z]?\s+de\s+\d{4}"
    r")",
    re.IGNORECASE,
)

ARTICLE_TOKEN_RE = re.compile(r"\d+(?:\.\d+)*(?:-\d+)?")

ET_RE = re.compile(r"\bEstatuto\s+Tributario\b", re.IGNORECASE)

RELATION_TRIGGERS = (
    (re.compile(r"\bsustit[uú]yanse\b", re.IGNORECASE), "substitutes"),
    (re.compile(r"\bsustituye\b", re.IGNORECASE), "substitutes"),
    (re.compile(r"\bmodif[ií]quese\b", re.IGNORECASE), "modifies"),
    (re.compile(r"\bmodifica\b", re.IGNORECASE), "modifies"),
    (re.compile(r"\badici[oó]nese\b", re.IGNORECASE), "adds"),
    (re.compile(r"\badiciona\b", re.IGNORECASE), "adds"),
    (re.compile(r"\bder[oó]guense\b", re.IGNORECASE), "repeals"),
    (re.compile(r"\bder[oó]guese\b", re.IGNORECASE), "repeals"),
    (re.compile(r"\bderoga\b", re.IGNORECASE), "repeals"),
)


@dataclass(frozen=True)
class TargetDocument:
    key: str
    document_type: str
    number: str | None
    year: int | None


@dataclass(frozen=True)
class Mention:
    mention_type: str
    raw_text: str
    context_text: str
    normalized_reference: str
    target: TargetDocument
    article_designation: str | None
    char_start: int
    char_end: int
    confidence: float
    requires_human_review: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_id(prefix: str, material: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, material)
    return f"{prefix}-{value.hex}"


def normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_document_type(value: str) -> str:
    key = normalize_ascii(value).upper()
    mapping = {
        "LEY": "LEY",
        "DECRETO": "DECRETO",
        "RESOLUCION": "RESOLUCION",
        "CIRCULAR": "CIRCULAR",
        "CONCEPTO": "CONCEPTO",
        "OFICIO": "OFICIO",
    }
    return mapping[key]


def target_from_document_match(match: re.Match[str]) -> TargetDocument:
    document_type = normalize_document_type(match.group("type"))
    number = match.group("number").upper()
    year = int(match.group("year"))
    return TargetDocument(
        key=f"CO:{document_type}:{number}:{year}",
        document_type=document_type,
        number=number,
        year=year,
    )


def target_from_text(value: str) -> TargetDocument:
    if ET_RE.fullmatch(value.strip()):
        return TargetDocument(
            key="CO:ESTATUTO_TRIBUTARIO",
            document_type="ESTATUTO_TRIBUTARIO",
            number=None,
            year=None,
        )

    match = DOCUMENT_RE.fullmatch(value.strip())
    if not match:
        raise RuntimeError(f"unsupported target document expression: {value!r}")
    return target_from_document_match(match)


def extract_mentions(text: str) -> list[Mention]:
    mentions: list[Mention] = []
    occupied: set[tuple[int, int, str]] = set()

    for scope in ARTICLE_SCOPE_RE.finditer(text):
        target = target_from_text(scope.group("target"))
        articles_text = scope.group("articles")
        articles_base = scope.start("articles")
        context_text = scope.group(0)

        for token in ARTICLE_TOKEN_RE.finditer(articles_text):
            article = token.group(0).rstrip(".")
            start = articles_base + token.start()
            end = articles_base + token.end()
            normalized = f"{target.key}:ART:{article}"
            key = (start, end, normalized)
            if key in occupied:
                continue
            occupied.add(key)
            mentions.append(
                Mention(
                    mention_type="article",
                    raw_text=text[start:end],
                    context_text=context_text,
                    normalized_reference=normalized,
                    target=target,
                    article_designation=article,
                    char_start=start,
                    char_end=end,
                    confidence=1.0,
                )
            )

    for match in DOCUMENT_RE.finditer(text):
        target = target_from_document_match(match)
        normalized = target.key
        key = (match.start(), match.end(), normalized)
        if key in occupied:
            continue
        occupied.add(key)
        mentions.append(
            Mention(
                mention_type="document",
                raw_text=match.group(0),
                context_text=match.group(0),
                normalized_reference=normalized,
                target=target,
                article_designation=None,
                char_start=match.start(),
                char_end=match.end(),
                confidence=1.0,
            )
        )

    for match in ET_RE.finditer(text):
        target = TargetDocument(
            key="CO:ESTATUTO_TRIBUTARIO",
            document_type="ESTATUTO_TRIBUTARIO",
            number=None,
            year=None,
        )
        normalized = target.key
        key = (match.start(), match.end(), normalized)
        if key in occupied:
            continue
        occupied.add(key)
        mentions.append(
            Mention(
                mention_type="document",
                raw_text=match.group(0),
                context_text=match.group(0),
                normalized_reference=normalized,
                target=target,
                article_designation=None,
                char_start=match.start(),
                char_end=match.end(),
                confidence=1.0,
            )
        )

    mentions.sort(
        key=lambda item: (
            item.char_start,
            item.char_end,
            item.mention_type,
            item.normalized_reference,
        )
    )
    return mentions


def relation_trigger_before(
    text: str,
    target_start: int,
) -> tuple[str, str] | None:
    candidates: list[tuple[int, str, str]] = []

    for regex, relation_type in RELATION_TRIGGERS:
        for match in regex.finditer(text, 0, target_start):
            candidates.append((match.start(), match.group(0), relation_type))

    if not candidates:
        return None

    _, trigger_text, relation_type = max(candidates, key=lambda item: item[0])
    return trigger_text, relation_type


def is_current_document_operational_segment(
    segment_type: str,
    text: str,
) -> bool:
    if segment_type != "article":
        return False

    upper = normalize_ascii(text).upper()
    if "EL PRESENTE DECRETO" in upper:
        return True

    prefix = upper[:240]
    return any(
        token in prefix
        for token in (
            "SUSTITUYANSE",
            "MODIFIQUESE",
            "ADICIONESE",
            "DEROGUENSE",
            "DEROGUESE",
        )
    )


def detect(
    *,
    extraction_id: str,
    db_path: Path,
) -> dict[str, object]:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        extraction = con.execute(
            """
            SELECT extraction_id, extractor_name, extractor_version
            FROM text_extractions
            WHERE extraction_id = ?
            """,
            (extraction_id,),
        ).fetchone()

        if extraction is None:
            raise RuntimeError(f"extraction not found: {extraction_id}")

        detection_run_id = deterministic_id(
            "RDR",
            (
                f"col-taxdata:{extraction_id}:"
                f"{DETECTOR_NAME}:{DETECTOR_VERSION}"
            ),
        )

        existing = con.execute(
            """
            SELECT mention_count, relation_count
            FROM reference_detection_runs
            WHERE detection_run_id = ?
            """,
            (detection_run_id,),
        ).fetchone()

        if existing is not None:
            return {
                "detection_run_id": detection_run_id,
                "extraction_id": extraction_id,
                "detector_name": DETECTOR_NAME,
                "detector_version": DETECTOR_VERSION,
                "mention_count": existing[0],
                "relation_count": existing[1],
                "reused": True,
            }

        segments = con.execute(
            """
            SELECT
                extracted_segment_id,
                sequence_no,
                segment_type,
                text
            FROM extracted_segments
            WHERE extraction_id = ?
            ORDER BY sequence_no
            """,
            (extraction_id,),
        ).fetchall()

        if not segments:
            raise RuntimeError("extraction has no segments")

        pending_mentions: list[tuple] = []
        pending_relations: list[tuple] = []

        for segment_id, sequence_no, segment_type, text in segments:
            mentions = extract_mentions(text)
            mention_ids: dict[tuple, str] = {}

            for mention in mentions:
                mention_id = deterministic_id(
                    "REF",
                    (
                        f"col-taxdata:{detection_run_id}:{segment_id}:"
                        f"{mention.mention_type}:{mention.char_start}:"
                        f"{mention.char_end}:{mention.normalized_reference}"
                    ),
                )
                mention_ids[
                    (
                        mention.mention_type,
                        mention.char_start,
                        mention.char_end,
                        mention.normalized_reference,
                    )
                ] = mention_id

                pending_mentions.append(
                    (
                        mention_id,
                        detection_run_id,
                        extraction_id,
                        segment_id,
                        mention.mention_type,
                        mention.raw_text,
                        mention.context_text,
                        mention.normalized_reference,
                        mention.target.key,
                        mention.target.document_type,
                        mention.target.number,
                        mention.target.year,
                        mention.article_designation,
                        mention.char_start,
                        mention.char_end,
                        f"{DETECTOR_NAME}:{DETECTOR_VERSION}",
                        mention.confidence,
                        mention.requires_human_review,
                        "candidate",
                    )
                )

            if not is_current_document_operational_segment(segment_type, text):
                continue

            for mention in mentions:
                if mention.mention_type != "article":
                    continue

                trigger = relation_trigger_before(text, mention.char_start)
                if trigger is None:
                    continue

                trigger_text, relation_type = trigger
                mention_id = mention_ids[
                    (
                        mention.mention_type,
                        mention.char_start,
                        mention.char_end,
                        mention.normalized_reference,
                    )
                ]
                relation_id = deterministic_id(
                    "RLM",
                    (
                        f"col-taxdata:{detection_run_id}:{segment_id}:"
                        f"{mention_id}:{relation_type}"
                    ),
                )
                pending_relations.append(
                    (
                        relation_id,
                        detection_run_id,
                        extraction_id,
                        segment_id,
                        mention_id,
                        relation_type,
                        "current_document_to_target",
                        trigger_text,
                        mention.context_text,
                        f"{DETECTOR_NAME}:{DETECTOR_VERSION}",
                        1.0,
                        0,
                        "candidate",
                    )
                )

        with con:
            con.execute(
                """
                INSERT INTO reference_detection_runs(
                    detection_run_id, extraction_id,
                    detector_name, detector_version,
                    mention_count, relation_count,
                    created_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'success')
                """,
                (
                    detection_run_id,
                    extraction_id,
                    DETECTOR_NAME,
                    DETECTOR_VERSION,
                    len(pending_mentions),
                    len(pending_relations),
                    utc_now(),
                ),
            )

            con.executemany(
                """
                INSERT INTO reference_mentions(
                    reference_mention_id, detection_run_id,
                    extraction_id, extracted_segment_id,
                    mention_type, raw_text, context_text,
                    normalized_reference,
                    target_document_key, target_document_type,
                    target_document_number, target_document_year,
                    article_designation,
                    char_start, char_end,
                    detection_method, confidence,
                    requires_human_review, status
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                pending_mentions,
            )

            con.executemany(
                """
                INSERT INTO explicit_relation_mentions(
                    relation_mention_id, detection_run_id,
                    extraction_id, extracted_segment_id,
                    target_reference_mention_id,
                    relation_type, direction,
                    trigger_text, context_text,
                    detection_method, confidence,
                    requires_human_review, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pending_relations,
            )

        return {
            "detection_run_id": detection_run_id,
            "extraction_id": extraction_id,
            "detector_name": DETECTOR_NAME,
            "detector_version": DETECTOR_VERSION,
            "mention_count": len(pending_mentions),
            "relation_count": len(pending_relations),
            "reused": False,
        }

    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect explicit normative references and conservative "
            "current-document relations from a versioned extraction."
        )
    )
    parser.add_argument("--extraction-id", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    args = parser.parse_args()

    result = detect(
        extraction_id=args.extraction_id,
        db_path=Path(args.db),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
