#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import urllib.parse
import urllib.request
import uuid
from typing import Any

from extract_normograma_html import (
    VisibleBlockParser,
    build_segments,
    find_legal_body,
)
from fetch_source import fetch, host_is_allowed, load_allowed_domains
from register_simple_normative_act import register_simple_act
from resolve_references import resolve_references
from source_identity import assess_generic_normative_identity


ADAPTER_NAME = "secretaria_senado_ley"
ADAPTER_VERSION = "1"
AUTHORITY = "Secretaría General del Senado de la República"
SOURCE_KIND = "senado_basedoc"
SOURCE_HOST = "www.secretariasenado.gov.co"
SOURCE_PATH_PREFIX = "/senado/basedoc/"
SUPPORTED_KEY_RE = re.compile(
    r"^CO:LEY:(?P<number>\d+):(?P<year>\d{4})$"
)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = (
    "col-taxdata/1.0 "
    "(official-source coverage research; deterministic acquisition)"
)


@dataclass(frozen=True)
class LawTarget:
    """Canonical national-law target supported by this adapter."""

    canonical_key: str
    number: str
    year: int

    @property
    def filename(self) -> str:
        return f"ley_{int(self.number):04d}_{self.year}.html"

    @property
    def source_url(self) -> str:
        # The Senado BaseDoc endpoint currently serves these canonical pages
        # over HTTP. Acquisition remains restricted to this exact official
        # host/path and immutable bytes are content-addressed by fetch_source.
        return (
            f"http://{SOURCE_HOST}{SOURCE_PATH_PREFIX}{self.filename}"
        )


class SenateSourceError(RuntimeError):
    """Raised when an official Senate page is missing or contradicts demand."""


def parse_target_key(value: str) -> LawTarget:
    normalized = value.strip().upper()
    match = SUPPORTED_KEY_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(
            "Secretaría del Senado adapter supports only canonical national "
            "law keys shaped as CO:LEY:<number>:<year>"
        )
    number = str(int(match.group("number")))
    year = int(match.group("year"))
    return LawTarget(f"CO:LEY:{number}:{year}", number, year)


def validate_source_url(
    url: str,
    *,
    allowed_domains: set[str],
) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"}:
        raise SenateSourceError(f"unsupported source scheme: {url}")
    if host != SOURCE_HOST:
        raise SenateSourceError(f"refusing non-Senate source host: {url}")
    if not host_is_allowed(host, allowed_domains):
        raise SenateSourceError(f"source host is not allowlisted: {url}")
    if not parsed.path.startswith(SOURCE_PATH_PREFIX):
        raise SenateSourceError(f"refusing non-BaseDoc path: {url}")
    if parsed.query or parsed.fragment:
        raise SenateSourceError(f"refusing decorated BaseDoc URL: {url}")


def read_official_html(
    target: LawTarget,
    *,
    allowed_domains: set[str],
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    """Read one deterministic official law page without persisting state."""

    url = target.source_url
    validate_source_url(url, allowed_domains=allowed_domains)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        validate_source_url(final_url, allowed_domains=allowed_domains)
        final_path = urllib.parse.urlparse(final_url).path
        if Path(final_path).name.lower() != target.filename:
            raise SenateSourceError(
                "official source redirected to a different legal document"
            )
        content_type = response.headers.get("Content-Type") or ""
        raw = response.read(max_bytes + 1)

    if len(raw) > max_bytes:
        raise SenateSourceError(
            f"official source exceeded max_bytes={max_bytes}"
        )
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"text/html", "application/xhtml+xml", ""}:
        raise SenateSourceError(
            f"unexpected Senate content type: {content_type}"
        )

    try:
        html_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        html_text = raw.decode("latin-1")

    return {
        "requested_url": url,
        "final_url": final_url,
        "content_type": content_type,
        "bytes": raw,
        "text": html_text,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def assess_target_html(
    target: LawTarget,
    *,
    source_url: str,
    html_text: str,
) -> dict[str, Any]:
    """Prove source/content identity with the existing canonical identity gate."""

    parser = VisibleBlockParser()
    parser.feed(html_text)
    parser.close()
    body = find_legal_body(parser.blocks, source_url=source_url)
    normalized_text, segments = build_segments(body)

    heading = next(
        (
            str(segment["text"])
            for segment in segments
            if segment["segment_type"] == "document_heading"
        ),
        None,
    )
    if heading is None:
        raise SenateSourceError("official page has no legal document heading")

    assessment = assess_generic_normative_identity(source_url, heading)
    observed_key = (
        assessment.content.canonical_key
        if assessment.content is not None
        else None
    )
    if not assessment.accepted or observed_key != target.canonical_key:
        raise SenateSourceError(
            "official page identity does not match requested target: "
            f"expected={target.canonical_key} observed={observed_key} "
            f"reason={assessment.reason_code}"
        )

    return {
        "status": assessment.status,
        "canonical_key": observed_key,
        "issuer_key": assessment.content.issuer_key,
        "heading": heading,
        "segment_count": len(segments),
        "normalized_sha256": hashlib.sha256(
            normalized_text.encode("utf-8")
        ).hexdigest(),
    }


def deterministic_source_id(source_url: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"col-taxdata:secretaria-senado-source:{source_url}",
    )
    return "SRC-SEN-" + value.hex


def open_missing_review_count(
    con: sqlite3.Connection,
    canonical_key: str,
) -> int:
    return int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM review_queue rq
            JOIN reference_mentions rm
              ON rm.reference_mention_id = rq.entity_id
            WHERE rq.entity_type = 'reference_mention'
              AND rq.reason_code = 'TARGET_DOCUMENT_NOT_FOUND'
              AND rq.resolved_at IS NULL
              AND rm.target_document_key = ?
            """,
            (canonical_key,),
        ).fetchone()[0]
    )


def detection_runs_for_key(
    con: sqlite3.Connection,
    canonical_key: str,
) -> list[str]:
    return [
        str(row[0])
        for row in con.execute(
            """
            SELECT DISTINCT detection_run_id
            FROM reference_mentions
            WHERE target_document_key = ?
            ORDER BY detection_run_id
            """,
            (canonical_key,),
        ).fetchall()
    ]


def document_exists(
    con: sqlite3.Connection,
    canonical_key: str,
) -> bool:
    return (
        con.execute(
            """
            SELECT 1
            FROM document_identifiers
            WHERE identifier_type = 'canonical_key'
              AND identifier_value = ?
            LIMIT 1
            """,
            (canonical_key,),
        ).fetchone()
        is not None
    )


def demand_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rank currently missing law targets by unresolved-reference demand."""

    rows = con.execute(
        """
        SELECT
            rm.target_document_key,
            COUNT(DISTINCT rq.review_id) AS open_reviews,
            COUNT(DISTINCT rm.detection_run_id) AS detection_runs
        FROM review_queue rq
        JOIN reference_mentions rm
          ON rm.reference_mention_id = rq.entity_id
        WHERE rq.entity_type = 'reference_mention'
          AND rq.reason_code = 'TARGET_DOCUMENT_NOT_FOUND'
          AND rq.resolved_at IS NULL
        GROUP BY rm.target_document_key
        ORDER BY open_reviews DESC, rm.target_document_key
        """
    ).fetchall()

    result: list[dict[str, Any]] = []
    for canonical_key, open_reviews, detection_runs in rows:
        try:
            target = parse_target_key(str(canonical_key))
        except ValueError:
            continue
        result.append(
            {
                "target": target,
                "open_reviews": int(open_reviews),
                "detection_runs": int(detection_runs),
            }
        )
    return result


def select_targets(
    db_path: Path,
    *,
    requested_keys: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("--limit must be at least 1")

    con = sqlite3.connect(db_path)
    try:
        demand = demand_rows(con)
        by_key = {
            row["target"].canonical_key: row
            for row in demand
        }
        if requested_keys:
            selected: list[dict[str, Any]] = []
            for raw_key in requested_keys:
                target = parse_target_key(raw_key)
                row = by_key.get(target.canonical_key)
                if row is not None:
                    selected.append(row)
                    continue
                selected.append(
                    {
                        "target": target,
                        "open_reviews": 0,
                        "detection_runs": len(
                            detection_runs_for_key(
                                con,
                                target.canonical_key,
                            )
                        ),
                    }
                )
            return selected
        return demand[:limit]
    finally:
        con.close()


def reconcile_target(
    db_path: Path,
    canonical_key: str,
) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    try:
        run_ids = detection_runs_for_key(con, canonical_key)
    finally:
        con.close()

    return [
        resolve_references(
            detection_run_id=run_id,
            db_path=db_path,
            relations_only=False,
            target_document_key=canonical_key,
        )
        for run_id in run_ids
    ]


def preview_or_apply_target(
    entry: dict[str, Any],
    *,
    db_path: Path,
    data_root: Path,
    allowed_domains_path: Path,
    timeout: float,
    max_bytes: int,
    apply: bool,
) -> dict[str, Any]:
    """Preview or acquire one demanded law through the normal evidence path."""

    target: LawTarget = entry["target"]
    allowed_domains = load_allowed_domains(allowed_domains_path)

    con = sqlite3.connect(db_path)
    try:
        already_present = document_exists(con, target.canonical_key)
        before_reviews = open_missing_review_count(
            con,
            target.canonical_key,
        )
        run_ids = detection_runs_for_key(con, target.canonical_key)
    finally:
        con.close()

    base_report: dict[str, Any] = {
        "canonical_key": target.canonical_key,
        "demand_open_reviews": entry["open_reviews"],
        "before_open_target_document_reviews": before_reviews,
        "detection_runs": run_ids,
        "document_already_present": already_present,
    }

    if already_present:
        if not apply:
            return {
                **base_report,
                "mode": "preview",
                "action": "reconcile_existing_document",
                "persistent_mutation": False,
            }
        resolution_results = reconcile_target(
            db_path,
            target.canonical_key,
        )
        con = sqlite3.connect(db_path)
        try:
            after_reviews = open_missing_review_count(
                con,
                target.canonical_key,
            )
        finally:
            con.close()
        return {
            **base_report,
            "mode": "apply",
            "action": "reconciled_existing_document",
            "resolution_results": resolution_results,
            "after_open_target_document_reviews": after_reviews,
            "target_document_reviews_closed": (
                before_reviews - after_reviews
            ),
        }

    page = read_official_html(
        target,
        allowed_domains=allowed_domains,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    assessment = assess_target_html(
        target,
        source_url=str(page["final_url"]),
        html_text=str(page["text"]),
    )
    source_url = str(page["final_url"])
    source_id = deterministic_source_id(source_url)

    if not apply:
        return {
            **base_report,
            "mode": "preview",
            "action": "acquire_register_reconcile",
            "persistent_mutation": False,
            "source_id": source_id,
            "official_source": {
                "url": source_url,
                "raw_sha256": page["sha256"],
                **assessment,
            },
            "would_reconcile_detection_runs": run_ids,
        }

    fetch_result = fetch(
        source_id=source_id,
        url=source_url,
        authority=AUTHORITY,
        source_kind=SOURCE_KIND,
        db_path=db_path,
        data_root=data_root,
        allowed_domains_path=allowed_domains_path,
        timeout=timeout,
        max_bytes=max_bytes,
        user_agent=USER_AGENT,
    )
    if fetch_result["sha256"] != page["sha256"]:
        raise SenateSourceError(
            "official source changed between preview and archival; "
            "raw evidence was preserved but canonical registration was refused"
        )

    from extract_normograma_html import extract_manifestation

    extraction_result = extract_manifestation(
        manifestation_id=str(fetch_result["manifestation_id"]),
        db_path=db_path,
        data_root=data_root,
        dry_run=False,
    )
    registration_result = register_simple_act(
        extraction_id=str(extraction_result["extraction_id"]),
        db_path=db_path,
        expected_canonical_key=target.canonical_key,
    )
    if registration_result.get("canonical_key") != target.canonical_key:
        raise SenateSourceError(
            "archived law did not register as the requested canonical key"
        )

    resolution_results = reconcile_target(
        db_path,
        target.canonical_key,
    )
    con = sqlite3.connect(db_path)
    try:
        after_reviews = open_missing_review_count(
            con,
            target.canonical_key,
        )
    finally:
        con.close()

    return {
        **base_report,
        "mode": "apply",
        "action": "acquired_registered_reconciled",
        "source_id": source_id,
        "fetch": fetch_result,
        "extraction": extraction_result,
        "registration": registration_result,
        "resolution_results": resolution_results,
        "after_open_target_document_reviews": after_reviews,
        "target_document_reviews_closed": before_reviews - after_reviews,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or acquire high-demand missing national Ley targets "
            "from the official Secretaría del Senado BaseDoc corpus."
        )
    )
    parser.add_argument(
        "--canonical-key",
        action="append",
        default=[],
        help=(
            "Explicit law target. Repeat for multiple targets. Without this "
            "option, targets are ranked by open missing-document reviews."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum demand-ranked targets when no explicit key is supplied.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Persist acquisition/derived state. Without --apply the command "
            "performs a non-mutating network-backed preview."
        ),
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--allowed-domains",
        default="config/official_domains.json",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        raise RuntimeError(f"database not found: {db_path}")

    selected = select_targets(
        db_path,
        requested_keys=args.canonical_key,
        limit=args.limit,
    )
    if not selected:
        raise RuntimeError(
            "no supported open Ley TARGET_DOCUMENT_NOT_FOUND targets"
        )

    results = [
        preview_or_apply_target(
            entry,
            db_path=db_path,
            data_root=Path(args.data_root),
            allowed_domains_path=Path(args.allowed_domains),
            timeout=args.timeout,
            max_bytes=args.max_bytes,
            apply=args.apply,
        )
        for entry in selected
    ]
    print(
        json.dumps(
            {
                "adapter_name": ADAPTER_NAME,
                "adapter_version": ADAPTER_VERSION,
                "mode": "apply" if args.apply else "preview",
                "targets": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
