#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any


USER_AGENT = (
    "col-taxdata/1.0 "
    "(official-source archival research; respectful incremental crawler)"
)

TAX_SEEDS = [
    "https://normograma.dian.gov.co/dian/compilacion/tributario.html",
    "https://normograma.dian.gov.co/dian/compilacion/t_1_normativa_tributaria.html",
    "https://normograma.dian.gov.co/dian/compilacion/t_2_doctrina_tributaria.html",
    "https://normograma.dian.gov.co/dian/compilacion/t_3_jurisprudencia_tributaria.html",
]

ALLOWED_HOST = "normograma.dian.gov.co"
ALLOWED_PREFIX = "/dian/compilacion/"
DOC_PREFIX = "/dian/compilacion/docs/"
HTML_SUFFIXES = (".htm", ".html")


def index_allowed_for_scope(url: str, scope: str) -> bool:
    name = Path(urllib.parse.urlparse(url).path).name.lower()

    if scope == "tributario":
        return (
            name == "tributario.html"
            or name.startswith("t_")
            or name.startswith("nyb_novedades_derecho_tributario")
        )

    return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_after(seconds: int | float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="seconds")


def tool(name: str) -> str:
    return str(Path(__file__).resolve().parent / name)


class LinkParser(HTMLParser):
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


def canonical_url(base_url: str, href: str) -> str | None:
    value = href.strip()
    if not value or value.startswith(("#", "javascript:", "mailto:")):
        return None

    absolute = urllib.parse.urljoin(base_url, value)
    parsed = urllib.parse.urlparse(absolute)

    if parsed.scheme not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower() != ALLOWED_HOST:
        return None

    path = urllib.parse.unquote(parsed.path)
    if not path.startswith(ALLOWED_PREFIX):
        return None

    lower = path.lower()
    if not lower.endswith(HTML_SUFFIXES):
        return None

    # Normograma legal/index pages are static HTML. Query strings and
    # fragments are navigation noise for this corpus.
    return urllib.parse.urlunparse(
        ("https", ALLOWED_HOST, path, "", "", "")
    )


def classify_url(
    url: str,
    *,
    scope: str | None = None,
) -> str | None:
    path = urllib.parse.urlparse(url).path.lower()
    if not path.startswith(ALLOWED_PREFIX):
        return None
    if path.startswith(DOC_PREFIX) and path.endswith(HTML_SUFFIXES):
        return "document"
    if path.endswith(HTML_SUFFIXES):
        if scope is not None and not index_allowed_for_scope(url, scope):
            return None
        return "index"
    return None


def source_kind_for_url(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name.lower()
    if name.startswith(("oficio_dian_", "concepto_dian_")):
        return "doctrina"
    if name == "estatuto_tributario.htm":
        return "norma_compilada"
    if name == "decreto_1625_2016.htm":
        return "normograma_html"
    if name.startswith("resolucion_"):
        return "resolucion"
    if name.startswith("decreto_"):
        return "decreto"
    if name.startswith("ley_"):
        return "ley"
    if name.startswith("circular_"):
        return "circular"
    if name.startswith(("sentencia_", "auto_")):
        return "jurisprudencia"
    return "normograma_html"


def deterministic_source_id(url: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "col-taxdata:dian-source:" + url,
    )
    return "SRC-DIAN-" + value.hex


def run_json(
    args: list[str],
    *,
    tolerate: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    proc = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if proc.returncode != 0:
        error = (
            f"exit={proc.returncode} command={' '.join(args)}\n"
            f"stdout={proc.stdout[-4000:]}\n"
            f"stderr={proc.stderr[-4000:]}"
        )
        if tolerate:
            return None, error
        raise RuntimeError(error)

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        error = (
            "expected JSON from command "
            + " ".join(args)
            + f"; stdout={proc.stdout[-4000:]}"
        )
        if tolerate:
            return None, error
        raise RuntimeError(error)


def ensure_db(db: Path, schema_dir: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            tool("init_db.py"),
            "--db",
            str(db),
            "--schema-dir",
            str(schema_dir),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)


def enqueue(
    con: sqlite3.Connection,
    *,
    url: str,
    item_type: str,
    scope: str,
    depth: int,
    discovered_from: str | None,
) -> bool:
    now = utc_now()
    cur = con.execute(
        """
        INSERT OR IGNORE INTO dian_crawl_queue(
            url, item_type, scope, depth, discovered_from,
            status, attempts, first_seen_at, next_attempt_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
        """,
        (
            url,
            item_type,
            scope,
            depth,
            discovered_from,
            now,
            now,
        ),
    )
    if discovered_from:
        con.execute(
            """
            INSERT OR IGNORE INTO dian_discovery_edges(
                parent_url, child_url, discovered_at
            )
            VALUES (?, ?, ?)
            """,
            (discovered_from, url, now),
        )
    return bool(cur.rowcount)


def seed(con: sqlite3.Connection, scope: str) -> int:
    if scope != "tributario":
        raise RuntimeError(f"unsupported scope: {scope}")
    inserted = 0
    with con:
        for url in TAX_SEEDS:
            inserted += int(
                enqueue(
                    con,
                    url=url,
                    item_type="index",
                    scope=scope,
                    depth=0,
                    discovered_from=None,
                )
            )
    return inserted


def purge_out_of_scope_queue(
    con: sqlite3.Connection,
    scope: str,
) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT url, item_type, discovered_from
        FROM dian_crawl_queue
        WHERE scope = ?
        """,
        (scope,),
    ).fetchall()

    remove: set[str] = set()
    for url, item_type, discovered_from in rows:
        if item_type == "index":
            if not index_allowed_for_scope(url, scope):
                remove.add(url)
            continue

        if item_type == "document" and discovered_from:
            parent_path = urllib.parse.urlparse(discovered_from).path.lower()
            if (
                not parent_path.startswith(DOC_PREFIX)
                and not index_allowed_for_scope(discovered_from, scope)
            ):
                remove.add(url)

    if not remove:
        return {
            "queue_items_removed": 0,
            "discovery_edges_removed": 0,
        }

    queue_removed = 0
    edges_removed = 0
    with con:
        for url in sorted(remove):
            cur = con.execute(
                "DELETE FROM dian_crawl_queue WHERE url = ? AND scope = ?",
                (url, scope),
            )
            queue_removed += cur.rowcount

            cur = con.execute(
                """
                DELETE FROM dian_discovery_edges
                WHERE parent_url = ? OR child_url = ?
                """,
                (url, url),
            )
            edges_removed += cur.rowcount

    return {
        "queue_items_removed": queue_removed,
        "discovery_edges_removed": edges_removed,
    }


def reset_stale_running(
    con: sqlite3.Connection,
    stale_seconds: int,
) -> int:
    threshold = (
        datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    ).isoformat(timespec="seconds")
    now = utc_now()
    with con:
        cur = con.execute(
            """
            UPDATE dian_crawl_queue
            SET status = 'error',
                last_error = COALESCE(
                    last_error,
                    'worker interrupted while item was running'
                ),
                next_attempt_at = ?
            WHERE status = 'running'
              AND last_attempt_at IS NOT NULL
              AND last_attempt_at < ?
            """,
            (now, threshold),
        )
    return cur.rowcount


def fetch_index(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
) -> tuple[str, str, int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        parsed = urllib.parse.urlparse(final_url)
        if (parsed.hostname or "").lower() != ALLOWED_HOST:
            raise RuntimeError(
                f"index redirected outside Normograma: {final_url}"
            )
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError(
                f"index exceeded max_bytes={max_bytes}: {url}"
            )
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            text = data.decode(charset)
        except (LookupError, UnicodeDecodeError):
            text = data.decode("latin-1", errors="replace")
        return text, hashlib.sha256(data).hexdigest(), len(data)


def discover_links(
    con: sqlite3.Connection,
    *,
    parent_url: str,
    html: str,
    scope: str,
    depth: int,
    max_depth: int,
    documents_only: bool,
) -> dict[str, int]:
    parser = LinkParser()
    parser.feed(html)

    counts = {
        "links_seen": len(parser.links),
        "indexes_added": 0,
        "documents_added": 0,
    }

    seen: set[str] = set()
    with con:
        for href in parser.links:
            url = canonical_url(parent_url, href)
            if not url or url in seen or url == parent_url:
                continue
            seen.add(url)

            item_type = classify_url(url, scope=scope)
            if item_type is None:
                continue
            if documents_only and item_type != "document":
                continue
            if item_type == "index" and depth + 1 > max_depth:
                continue

            added = enqueue(
                con,
                url=url,
                item_type=item_type,
                scope=scope,
                depth=depth + 1,
                discovered_from=parent_url,
            )
            if added:
                if item_type == "index":
                    counts["indexes_added"] += 1
                else:
                    counts["documents_added"] += 1
    return counts


def existing_or_new_source_id(
    con: sqlite3.Connection,
    url: str,
) -> str:
    row = con.execute(
        "SELECT source_id FROM sources WHERE source_url = ?",
        (url,),
    ).fetchone()
    if row:
        return row[0]
    return deterministic_source_id(url)


def document_identity_exists(
    con: sqlite3.Connection,
    manifestation_id: str,
) -> bool:
    row = con.execute(
        """
        SELECT document_id
        FROM manifestations
        WHERE manifestation_id = ?
        """,
        (manifestation_id,),
    ).fetchone()
    return bool(row and row[0])


def process_document(
    con: sqlite3.Connection,
    *,
    url: str,
    scope: str,
    depth: int,
    db: Path,
    data_root: Path,
    timeout: float,
    max_bytes: int,
    max_depth: int,
) -> dict[str, Any]:
    source_id = existing_or_new_source_id(con, url)
    source_kind = source_kind_for_url(url)
    stages: list[dict[str, Any]] = []
    warnings: list[str] = []

    fetched, error = run_json(
        [
            sys.executable,
            tool("fetch_source.py"),
            "--source-id",
            source_id,
            "--url",
            url,
            "--authority",
            "DIAN",
            "--source-kind",
            source_kind,
            "--db",
            str(db),
            "--data-root",
            str(data_root),
            "--timeout",
            str(timeout),
            "--max-bytes",
            str(max_bytes),
        ],
    )
    if error:
        raise RuntimeError(error)
    assert fetched is not None
    stages.append({"stage": "fetch", "result": fetched})

    manifestation_id = str(fetched["manifestation_id"])

    with con:
        con.execute(
            """
            UPDATE sources
            SET discovered_from = COALESCE(
                discovered_from,
                (
                    SELECT discovered_from
                    FROM dian_crawl_queue
                    WHERE url = ?
                )
            )
            WHERE source_id = ?
            """,
            (url, source_id),
        )

    row = con.execute(
        """
        SELECT content_type, local_path, sha256
        FROM manifestations
        WHERE manifestation_id = ?
        """,
        (manifestation_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"manifestation disappeared after fetch: {manifestation_id}"
        )

    content_type, local_path, sha256 = row
    if not (content_type or "").lower().startswith(
        ("text/html", "application/xhtml+xml")
    ):
        return {
            "source_id": source_id,
            "manifestation_id": manifestation_id,
            "extraction_id": None,
            "sha256": sha256,
            "stages": stages,
            "warnings": warnings,
        }

    extracted, error = run_json(
        [
            sys.executable,
            tool("extract_normograma_html.py"),
            "--manifestation-id",
            manifestation_id,
            "--db",
            str(db),
            "--data-root",
            str(data_root),
        ],
    )
    if error:
        raise RuntimeError(error)
    assert extracted is not None
    extraction_id = str(extracted["extraction_id"])
    stages.append({"stage": "extract", "result": extracted})

    name = Path(urllib.parse.urlparse(url).path).name.lower()

    registry_tool: str
    if name == "estatuto_tributario.htm":
        registry_tool = "register_estatuto_tributario.py"
    elif name == "decreto_1625_2016.htm":
        registry_tool = "register_compiled_provisions.py"
    elif source_kind == "doctrina":
        registry_tool = "register_dian_doctrine.py"
    else:
        registry_tool = "register_simple_normative_act.py"

    registered, reg_error = run_json(
        [
            sys.executable,
            tool(registry_tool),
            "--extraction-id",
            extraction_id,
            "--db",
            str(db),
        ],
        tolerate=True,
    )
    if reg_error:
        warnings.append(
            f"{registry_tool}: {reg_error}"
        )
        if registry_tool == "register_simple_normative_act.py":
            fallback, fallback_error = run_json(
                [
                    sys.executable,
                    tool("register_document_identity.py"),
                    "--extraction-id",
                    extraction_id,
                    "--db",
                    str(db),
                ],
                tolerate=True,
            )
            if fallback_error:
                warnings.append(
                    "register_document_identity.py: "
                    + fallback_error
                )
            elif fallback is not None:
                stages.append(
                    {
                        "stage": "register_document_identity",
                        "result": fallback,
                    }
                )
    elif registered is not None:
        stages.append(
            {"stage": registry_tool.removesuffix(".py"), "result": registered}
        )

    detected, detection_error = run_json(
        [
            sys.executable,
            tool("detect_normative_references.py"),
            "--extraction-id",
            extraction_id,
            "--db",
            str(db),
        ],
        tolerate=True,
    )
    detection_run_id: str | None = None
    if detection_error:
        warnings.append(
            "detect_normative_references.py: " + detection_error
        )
    elif detected is not None:
        detection_run_id = str(detected["detection_run_id"])
        stages.append(
            {"stage": "detect_normative_references", "result": detected}
        )

    if document_identity_exists(con, manifestation_id):
        temporal, temporal_error = run_json(
            [
                sys.executable,
                tool("extract_document_temporality.py"),
                "--extraction-id",
                extraction_id,
                "--db",
                str(db),
            ],
            tolerate=True,
        )
        if temporal_error:
            warnings.append(
                "extract_document_temporality.py: " + temporal_error
            )
        elif temporal is not None:
            stages.append(
                {"stage": "extract_document_temporality", "result": temporal}
            )

    if detection_run_id:
        resolution, resolution_error = run_json(
            [
                sys.executable,
                tool("resolve_references.py"),
                "--detection-run-id",
                detection_run_id,
                "--relations-only",
                "--db",
                str(db),
            ],
            tolerate=True,
        )
        if resolution_error:
            warnings.append(
                "resolve_references.py: " + resolution_error
            )
        elif resolution is not None:
            stages.append(
                {"stage": "resolve_references", "result": resolution}
            )

        for promoter in (
            "promote_operational_relationships.py",
            "promote_editorial_relationships.py",
        ):
            promoted, promote_error = run_json(
                [
                    sys.executable,
                    tool(promoter),
                    "--detection-run-id",
                    detection_run_id,
                    "--db",
                    str(db),
                ],
                tolerate=True,
            )
            if promote_error:
                warnings.append(promoter + ": " + promote_error)
            elif promoted is not None:
                stages.append(
                    {
                        "stage": promoter.removesuffix(".py"),
                        "result": promoted,
                    }
                )

    raw_path = data_root / str(local_path)
    if raw_path.exists():
        try:
            html = raw_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            discovered = discover_links(
                con,
                parent_url=url,
                html=html,
                scope=scope,
                depth=depth,
                max_depth=max_depth,
                documents_only=True,
            )
            stages.append(
                {"stage": "discover_document_links", "result": discovered}
            )
        except Exception as exc:
            warnings.append(
                f"discover_document_links: {type(exc).__name__}: {exc}"
            )

    return {
        "source_id": source_id,
        "manifestation_id": manifestation_id,
        "extraction_id": extraction_id,
        "sha256": sha256,
        "stages": stages,
        "warnings": warnings,
    }


def reconcile_unresolved(
    con: sqlite3.Connection,
    *,
    db: Path,
    limit: int,
) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT DISTINCT dr.detection_run_id
        FROM reference_detection_runs dr
        JOIN explicit_relation_mentions erm
          ON erm.detection_run_id = dr.detection_run_id
        JOIN reference_mentions rm
          ON rm.reference_mention_id =
             erm.target_reference_mention_id
        LEFT JOIN reference_resolutions rr
          ON rr.reference_mention_id = rm.reference_mention_id
         AND rr.resolution_method =
             'canonical_reference_resolver:1'
        WHERE rr.reference_resolution_id IS NULL
           OR rr.status != 'resolved'
        ORDER BY dr.created_at
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    out = {
        "runs_considered": len(rows),
        "resolved_runs": 0,
        "promotions_attempted": 0,
    }

    for (run_id,) in rows:
        result, error = run_json(
            [
                sys.executable,
                tool("resolve_references.py"),
                "--detection-run-id",
                run_id,
                "--relations-only",
                "--db",
                str(db),
            ],
            tolerate=True,
        )
        if error:
            continue
        if result is not None:
            out["resolved_runs"] += 1

        for promoter in (
            "promote_operational_relationships.py",
            "promote_editorial_relationships.py",
        ):
            _result, _error = run_json(
                [
                    sys.executable,
                    tool(promoter),
                    "--detection-run-id",
                    run_id,
                    "--db",
                    str(db),
                ],
                tolerate=True,
            )
            out["promotions_attempted"] += 1

    return out


def due_item(
    con: sqlite3.Connection,
) -> tuple[str, str, str, int, int] | None:
    row = con.execute(
        """
        SELECT url, item_type, scope, depth, attempts
        FROM dian_crawl_queue
        WHERE status IN ('pending', 'done', 'error')
          AND next_attempt_at <= ?
        ORDER BY
            CASE item_type WHEN 'index' THEN 0 ELSE 1 END,
            depth,
            next_attempt_at,
            first_seen_at
        LIMIT 1
        """,
        (utc_now(),),
    ).fetchone()
    if row is None:
        return None
    return (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        int(row[3]),
        int(row[4]),
    )


def claim_item(
    con: sqlite3.Connection,
    url: str,
) -> None:
    with con:
        con.execute(
            """
            UPDATE dian_crawl_queue
            SET status = 'running',
                attempts = attempts + 1,
                last_attempt_at = ?,
                last_error = NULL
            WHERE url = ?
            """,
            (utc_now(), url),
        )


def finish_item(
    con: sqlite3.Connection,
    *,
    url: str,
    refresh_seconds: int,
    result: dict[str, Any],
) -> None:
    with con:
        con.execute(
            """
            UPDATE dian_crawl_queue
            SET status = 'done',
                source_id = COALESCE(?, source_id),
                manifestation_id = COALESCE(?, manifestation_id),
                extraction_id = COALESCE(?, extraction_id),
                content_sha256 = COALESCE(?, content_sha256),
                processing_json = ?,
                completed_at = ?,
                next_attempt_at = ?,
                last_error = NULL
            WHERE url = ?
            """,
            (
                result.get("source_id"),
                result.get("manifestation_id"),
                result.get("extraction_id"),
                result.get("sha256"),
                json.dumps(result, ensure_ascii=False),
                utc_now(),
                utc_after(refresh_seconds),
                url,
            ),
        )


def fail_item(
    con: sqlite3.Connection,
    *,
    url: str,
    attempts_before: int,
    error: Exception,
    base_backoff: int,
    max_backoff: int,
) -> None:
    delay = min(
        max_backoff,
        base_backoff * (2 ** min(attempts_before, 8)),
    )
    message = f"{type(error).__name__}: {error}"
    with con:
        con.execute(
            """
            UPDATE dian_crawl_queue
            SET status = 'error',
                last_error = ?,
                next_attempt_at = ?
            WHERE url = ?
            """,
            (
                message[-12000:],
                utc_after(delay),
                url,
            ),
        )


def status_payload(con: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        f"{item_type}:{status}": count
        for item_type, status, count in con.execute(
            """
            SELECT item_type, status, COUNT(*)
            FROM dian_crawl_queue
            GROUP BY item_type, status
            ORDER BY item_type, status
            """
        )
    }

    errors = [
        {
            "url": row[0],
            "attempts": row[1],
            "next_attempt_at": row[2],
            "error": row[3],
        }
        for row in con.execute(
            """
            SELECT url, attempts, next_attempt_at, last_error
            FROM dian_crawl_queue
            WHERE status = 'error'
            ORDER BY last_attempt_at DESC
            LIMIT 10
            """
        )
    ]

    source_count = con.execute(
        """
        SELECT COUNT(*)
        FROM sources
        WHERE source_url LIKE
              'https://normograma.dian.gov.co/dian/compilacion/%'
        """
    ).fetchone()[0]

    manifestation_count = con.execute(
        """
        SELECT COUNT(*)
        FROM manifestations m
        JOIN sources s ON s.source_id = m.source_id
        WHERE s.source_url LIKE
              'https://normograma.dian.gov.co/dian/compilacion/%'
        """
    ).fetchone()[0]

    return {
        "queue": counts,
        "normograma_sources": source_count,
        "normograma_manifestations": manifestation_count,
        "recent_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously discover, archive, extract, register and "
            "cross-reference official DIAN Normograma documents."
        )
    )
    parser.add_argument("--scope", default="tributario")
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--schema-dir", default="schema")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--idle-sleep", type=int, default=300)
    parser.add_argument(
        "--index-refresh-seconds",
        type=int,
        default=21600,
    )
    parser.add_argument(
        "--document-refresh-seconds",
        type=int,
        default=604800,
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=100 * 1024 * 1024,
    )
    parser.add_argument(
        "--index-max-bytes",
        type=int,
        default=20 * 1024 * 1024,
    )
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--reconcile-limit", type=int, default=500)
    parser.add_argument("--stale-running-seconds", type=int, default=3600)
    parser.add_argument("--base-backoff", type=int, default=60)
    parser.add_argument("--max-backoff", type=int, default=21600)
    parser.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="0 means unlimited.",
    )
    args = parser.parse_args()

    db = Path(args.db)
    data_root = Path(args.data_root)
    schema_dir = Path(args.schema_dir)

    ensure_db(db, schema_dir)

    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")

    try:
        if args.status:
            print(
                json.dumps(
                    status_payload(con),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        reset = reset_stale_running(
            con,
            args.stale_running_seconds,
        )
        purged = purge_out_of_scope_queue(con, args.scope)
        inserted = seed(con, args.scope)
        print(
            json.dumps(
                {
                    "event": "crawler_started",
                    "at": utc_now(),
                    "scope": args.scope,
                    "seeded": inserted,
                    "stale_running_reset": reset,
                    "scope_cleanup": purged,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        processed = 0
        since_reconcile = 0

        while True:
            item = due_item(con)
            if item is None:
                reconciliation = reconcile_unresolved(
                    con,
                    db=db,
                    limit=args.reconcile_limit,
                )
                print(
                    json.dumps(
                        {
                            "event": "idle",
                            "at": utc_now(),
                            "status": status_payload(con),
                            "reconciliation": reconciliation,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if not args.continuous:
                    return 0
                time.sleep(args.idle_sleep)
                continue

            url, item_type, scope, depth, attempts_before = item
            claim_item(con, url)

            started = time.monotonic()
            try:
                if item_type == "index":
                    html, digest, byte_size = fetch_index(
                        url,
                        timeout=args.timeout,
                        max_bytes=args.index_max_bytes,
                    )
                    discovery = discover_links(
                        con,
                        parent_url=url,
                        html=html,
                        scope=scope,
                        depth=depth,
                        max_depth=args.max_depth,
                        documents_only=False,
                    )
                    result = {
                        "source_id": None,
                        "manifestation_id": None,
                        "extraction_id": None,
                        "sha256": digest,
                        "byte_size": byte_size,
                        "discovery": discovery,
                    }
                    finish_item(
                        con,
                        url=url,
                        refresh_seconds=args.index_refresh_seconds,
                        result=result,
                    )
                else:
                    result = process_document(
                        con,
                        url=url,
                        scope=scope,
                        depth=depth,
                        db=db,
                        data_root=data_root,
                        timeout=args.timeout,
                        max_bytes=args.max_bytes,
                        max_depth=args.max_depth,
                    )
                    finish_item(
                        con,
                        url=url,
                        refresh_seconds=args.document_refresh_seconds,
                        result=result,
                    )
                    since_reconcile += 1

                processed += 1
                print(
                    json.dumps(
                        {
                            "event": "processed",
                            "at": utc_now(),
                            "item_type": item_type,
                            "url": url,
                            "elapsed_seconds": round(
                                time.monotonic() - started,
                                3,
                            ),
                            "processed_this_run": processed,
                            "warnings": result.get("warnings", []),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                fail_item(
                    con,
                    url=url,
                    attempts_before=attempts_before,
                    error=exc,
                    base_backoff=args.base_backoff,
                    max_backoff=args.max_backoff,
                )
                print(
                    json.dumps(
                        {
                            "event": "error",
                            "at": utc_now(),
                            "item_type": item_type,
                            "url": url,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            if since_reconcile >= 100:
                reconciliation = reconcile_unresolved(
                    con,
                    db=db,
                    limit=args.reconcile_limit,
                )
                print(
                    json.dumps(
                        {
                            "event": "reconcile",
                            "at": utc_now(),
                            "result": reconciliation,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                since_reconcile = 0

            if args.max_items and processed >= args.max_items:
                print(
                    json.dumps(
                        {
                            "event": "max_items_reached",
                            "processed": processed,
                            "status": status_payload(con),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return 0

            if args.delay > 0:
                time.sleep(args.delay)

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
