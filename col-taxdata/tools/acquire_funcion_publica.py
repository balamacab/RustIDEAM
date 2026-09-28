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

from document_family_identity import (
    SegmentIdentityInput,
    assess_supported_family_identity,
)
from extract_normograma_html import (
    VisibleBlockParser,
    build_segments,
    extract_manifestation,
    find_legal_body,
)
from fetch_source import fetch, host_is_allowed, load_allowed_domains
from register_simple_normative_act import register_simple_act
from resolve_references import resolve_references


ADAPTER_NAME = "funcion_publica_gestor_normativo"
ADAPTER_VERSION = "1"
AUTHORITY = "Departamento Administrativo de la Función Pública"
SOURCE_KIND = "gestor_normativo"
SEARCH_BASE_URL = (
    "https://www1.funcionpublica.gov.co/dafpIndexerBGN/norma/index"
)
SUPPORTED_TYPES = {
    "LEY": "Ley",
    "DECRETO": "Decreto",
}
CANONICAL_KEY_RE = re.compile(
    r"^CO:(?P<type>LEY|DECRETO):(?P<number>\d+[A-Z]?):(?P<year>\d{4})$"
)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = (
    "col-taxdata/1.0 "
    "(official-source coverage research; deterministic acquisition)"
)


@dataclass(frozen=True)
class TargetKey:
    canonical_key: str
    document_type: str
    number: str
    year: int

    @property
    def search_label(self) -> str:
        return SUPPORTED_TYPES[self.document_type]


class TargetDiscoveryError(RuntimeError):
    """Raised when an official target cannot be selected unambiguously."""


class LinkParser(HTMLParser):
    """Collect links from server-rendered Gestor Normativo search results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def parse_target_key(value: str) -> TargetKey:
    normalized = value.strip().upper()
    match = CANONICAL_KEY_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(
            "Función Pública adapter supports only canonical national "
            "Ley/Decreto keys shaped as CO:LEY:<number>:<year> or "
            "CO:DECRETO:<number>:<year>"
        )
    number = match.group("number")
    if number.isdigit():
        number = str(int(number))
    else:
        number = str(int(number[:-1])) + number[-1]
    document_type = match.group("type")
    year = int(match.group("year"))
    canonical_key = f"CO:{document_type}:{number}:{year}"
    return TargetKey(canonical_key, document_type, number, year)


def build_search_url(target: TargetKey) -> str:
    query = urllib.parse.urlencode(
        {
            "find": "FindNext",
            "filtroEntidad": "Nivel Nacional",
            "filtroNumero": target.number,
            "filtroSubtema": "VALOR_REEMPLAZAR",
            "filtroTipoDocumento": target.search_label,
            "ordenarPor": "FECHA_EXPEDICION",
        }
    )
    return f"{SEARCH_BASE_URL}?{query}"


def _is_funcion_publica_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower().rstrip(".")
    return (
        host == "funcionpublica.gov.co"
        or host.endswith(".funcionpublica.gov.co")
    )


def canonical_target_url(base_url: str, href: str) -> str | None:
    absolute = urllib.parse.urljoin(base_url, href)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not _is_funcion_publica_host(parsed.hostname):
        return None
    if parsed.path.rstrip("/") != "/eva/gestornormativo/norma.php":
        return None
    identifiers = urllib.parse.parse_qs(parsed.query).get("i", [])
    if len(identifiers) != 1 or not identifiers[0].isdigit():
        return None
    return urllib.parse.urlunparse(
        (
            "https",
            parsed.netloc.lower(),
            "/eva/gestornormativo/norma.php",
            "",
            urllib.parse.urlencode({"i": identifiers[0]}),
            "",
        )
    )


def parse_search_candidates(search_url: str, html_text: str) -> list[str]:
    parser = LinkParser()
    parser.feed(html_text)
    parser.close()
    candidates = {
        candidate
        for href in parser.links
        if (candidate := canonical_target_url(search_url, href)) is not None
    }
    return sorted(candidates)


def read_official_html(
    url: str,
    *,
    allowed_domains: set[str],
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not host_is_allowed(parsed.hostname, allowed_domains)
        or not _is_funcion_publica_host(parsed.hostname)
    ):
        raise TargetDiscoveryError(
            f"refusing non-Función-Pública discovery URL: {url}"
        )

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
        final = urllib.parse.urlparse(final_url)
        if (
            not final.hostname
            or not host_is_allowed(final.hostname, allowed_domains)
            or not _is_funcion_publica_host(final.hostname)
        ):
            raise TargetDiscoveryError(
                f"official discovery redirected outside allowlist: {final_url}"
            )
        content_type = response.headers.get("Content-Type") or ""
        data = response.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise TargetDiscoveryError(
            f"official discovery exceeded max_bytes={max_bytes}"
        )
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"text/html", "application/xhtml+xml", ""}:
        raise TargetDiscoveryError(
            f"unexpected Gestor Normativo content type: {content_type}"
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    return {
        "requested_url": url,
        "final_url": final_url,
        "content_type": content_type,
        "bytes": data,
        "text": text,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def assess_target_html(
    *,
    source_url: str,
    html_text: str,
) -> dict[str, Any]:
    parser = VisibleBlockParser()
    parser.feed(html_text)
    parser.close()
    body = find_legal_body(parser.blocks, source_url=source_url)
    normalized_text, segment_dicts = build_segments(body)
    segments = [
        SegmentIdentityInput(
            int(item["sequence_no"]),
            str(item["segment_type"]),
            str(item["text"]),
        )
        for item in segment_dicts
    ]
    result = assess_supported_family_identity(source_url, segments)
    if result is None:
        raise TargetDiscoveryError(
            "Función Pública target did not enter its source-family parser"
        )
    return {
        "status": result.assessment.status,
        "reason_code": result.assessment.reason_code,
        "canonical_key": (
            result.identity.canonical_key
            if result.identity is not None
            else None
        ),
        "title": result.title,
        "segment_count": len(segment_dicts),
        "normalized_sha256": hashlib.sha256(
            normalized_text.encode("utf-8")
        ).hexdigest(),
    }


def discover_target(
    target: TargetKey,
    *,
    allowed_domains: set[str],
    timeout: float,
    max_bytes: int,
    max_candidates: int,
) -> dict[str, Any]:
    search_url = build_search_url(target)
    search = read_official_html(
        search_url,
        allowed_domains=allowed_domains,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    candidates = parse_search_candidates(search["final_url"], search["text"])
    if not candidates:
        raise TargetDiscoveryError(
            f"no official Gestor Normativo candidates for {target.canonical_key}"
        )
    if len(candidates) > max_candidates:
        raise TargetDiscoveryError(
            f"refusing {len(candidates)} search candidates; "
            f"max_candidates={max_candidates}"
        )

    matches: list[dict[str, Any]] = []
    inspected: list[dict[str, Any]] = []
    for candidate_url in candidates:
        page = read_official_html(
            candidate_url,
            allowed_domains=allowed_domains,
            timeout=timeout,
            max_bytes=max_bytes,
        )
        assessment = assess_target_html(
            source_url=candidate_url,
            html_text=page["text"],
        )
        record = {
            "url": candidate_url,
            "final_url": page["final_url"],
            "raw_sha256": page["sha256"],
            **assessment,
        }
        inspected.append(record)
        if (
            assessment["status"] == "accepted"
            and assessment["canonical_key"] == target.canonical_key
        ):
            matches.append(record)

    if len(matches) != 1:
        raise TargetDiscoveryError(
            "expected exactly one official target for "
            f"{target.canonical_key}; matched={len(matches)}; "
            f"inspected={len(inspected)}"
        )

    return {
        "search_url": search_url,
        "search_final_url": search["final_url"],
        "candidate_count": len(candidates),
        "inspected": inspected,
        "selected": matches[0],
    }


def deterministic_source_id(source_url: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"col-taxdata:funcion-publica-source:{source_url}",
    )
    return "SRC-FP-" + value.hex


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


def demand_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
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


def document_exists(con: sqlite3.Connection, canonical_key: str) -> bool:
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
            selected = []
            for raw_key in requested_keys:
                target = parse_target_key(raw_key)
                row = by_key.get(target.canonical_key)
                selected.append(
                    row
                    if row is not None
                    else {
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
    max_candidates: int,
    apply: bool,
) -> dict[str, Any]:
    target: TargetKey = entry["target"]
    allowed_domains = load_allowed_domains(allowed_domains_path)
    con = sqlite3.connect(db_path)
    try:
        already_present = document_exists(con, target.canonical_key)
        before_reviews = open_missing_review_count(con, target.canonical_key)
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
        resolution_results = reconcile_target(db_path, target.canonical_key)
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
            "target_document_reviews_closed": before_reviews - after_reviews,
        }

    discovery = discover_target(
        target,
        allowed_domains=allowed_domains,
        timeout=timeout,
        max_bytes=max_bytes,
        max_candidates=max_candidates,
    )
    selected = discovery["selected"]
    source_url = str(selected["url"])
    source_id = deterministic_source_id(source_url)

    if not apply:
        return {
            **base_report,
            "mode": "preview",
            "action": "acquire_register_reconcile",
            "persistent_mutation": False,
            "source_id": source_id,
            "official_source": selected,
            "search": {
                "url": discovery["search_url"],
                "candidate_count": discovery["candidate_count"],
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
    if fetch_result["sha256"] != selected["raw_sha256"]:
        raise TargetDiscoveryError(
            "official target changed between discovery and archival; "
            "raw evidence was preserved but canonical registration was refused"
        )

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
        raise TargetDiscoveryError(
            "archived target did not register as the requested canonical key"
        )

    resolution_results = reconcile_target(db_path, target.canonical_key)
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
            "Preview or acquire high-demand missing national Ley/Decreto "
            "targets from the official Función Pública Gestor Normativo."
        )
    )
    parser.add_argument(
        "--canonical-key",
        action="append",
        default=[],
        help=(
            "Explicit target key. Repeat for multiple targets. Without this "
            "option, targets are selected by open missing-review frequency."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum demand-ranked targets when --canonical-key is omitted.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Persist acquisition/derived state. Without --apply the command "
            "is a non-mutating network-backed preview."
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
    parser.add_argument("--max-candidates", type=int, default=25)
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
            "no supported open Ley/Decreto TARGET_DOCUMENT_NOT_FOUND targets"
        )

    results = [
        preview_or_apply_target(
            entry,
            db_path=db_path,
            data_root=Path(args.data_root),
            allowed_domains_path=Path(args.allowed_domains),
            timeout=args.timeout,
            max_bytes=args.max_bytes,
            max_candidates=args.max_candidates,
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
