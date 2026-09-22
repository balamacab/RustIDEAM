#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_BYTES = 100 * 1024 * 1024

CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_allowed_domains(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = data.get("allowed_domains", [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError("allowed_domains must be a list of strings")
    return {v.strip().lower() for v in values if v.strip()}


def host_is_allowed(hostname: str, allowed_domains: set[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain)
               for domain in allowed_domains)


def extension_for(content_type: str | None, final_url: str) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[mime]

    suffix = Path(urllib.parse.urlparse(final_url).path).suffix.lower()
    if 1 <= len(suffix) <= 10 and suffix.replace(".", "").isalnum():
        return suffix

    return ".bin"


def ensure_schema(con: sqlite3.Connection) -> None:
    required = {"sources", "manifestations", "fetches"}
    found = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = required - found
    if missing:
        raise RuntimeError(
            "database schema is incomplete; missing tables: "
            + ", ".join(sorted(missing))
        )


def deterministic_manifestation_id(source_id: str, sha256: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"col-taxdata:{source_id}:{sha256}",
    )
    return "MAN-" + value.hex


def fetch(
    *,
    source_id: str,
    url: str,
    authority: str,
    source_kind: str,
    db_path: Path,
    data_root: Path,
    allowed_domains_path: Path,
    timeout: float,
    max_bytes: int,
    user_agent: str,
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only absolute HTTP/HTTPS URLs are accepted")

    allowed_domains = load_allowed_domains(allowed_domains_path)
    if not host_is_allowed(parsed.hostname, allowed_domains):
        raise ValueError(f"source domain is not allowlisted: {parsed.hostname}")

    started_at = utc_now()
    fetch_id = "FETCH-" + uuid.uuid4().hex

    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = data_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    tmp_path: Path | None = None

    try:
        ensure_schema(con)

        existing = con.execute(
            "SELECT source_id FROM sources WHERE source_url = ?",
            (url,),
        ).fetchone()

        if existing is not None and existing[0] != source_id:
            raise RuntimeError(
                f"URL already belongs to source_id={existing[0]}, "
                f"not {source_id}"
            )

        con.execute(
            """
            INSERT INTO sources(
                source_id, source_url, authority, source_kind,
                discovered_from, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                authority = excluded.authority,
                source_kind = excluded.source_kind,
                last_seen_at = excluded.last_seen_at
            """,
            (source_id, url, authority, source_kind, started_at, started_at),
        )
        con.commit()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": (
                    "text/html,application/pdf,application/xhtml+xml,"
                    "application/xml,text/plain,*/*;q=0.8"
                ),
            },
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            final_parsed = urllib.parse.urlparse(final_url)

            if (
                not final_parsed.hostname
                or not host_is_allowed(final_parsed.hostname, allowed_domains)
            ):
                raise RuntimeError(
                    f"redirected outside official allowlist: {final_url}"
                )

            status = getattr(response, "status", 200)
            content_type = response.headers.get("Content-Type")
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")

            hasher = hashlib.sha256()
            byte_size = 0

            fd, tmp_name = tempfile.mkstemp(prefix="fetch-", dir=tmp_dir)
            os.close(fd)
            tmp_path = Path(tmp_name)

            with tmp_path.open("wb") as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    byte_size += len(chunk)
                    if byte_size > max_bytes:
                        raise RuntimeError(
                            f"download exceeded max_bytes={max_bytes}"
                        )

                    hasher.update(chunk)
                    output.write(chunk)

            sha256 = hasher.hexdigest()
            ext = extension_for(content_type, final_url)
            relative_path = (
                Path("raw")
                / "sha256"
                / sha256[:2]
                / f"{sha256}{ext}"
            )
            final_path = data_root / relative_path
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                tmp_path.unlink()
                tmp_path = None
            else:
                os.replace(tmp_path, final_path)
                tmp_path = None

            manifestation_id = deterministic_manifestation_id(
                source_id,
                sha256,
            )
            finished_at = utc_now()

            con.execute(
                """
                INSERT OR IGNORE INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, http_etag,
                    http_last_modified, local_path, parser_version
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    manifestation_id,
                    source_id,
                    content_type,
                    sha256,
                    byte_size,
                    finished_at,
                    etag,
                    last_modified,
                    str(relative_path),
                ),
            )

            con.execute(
                """
                INSERT INTO fetches(
                    fetch_id, source_id, requested_url, final_url,
                    started_at, finished_at, http_status, content_type,
                    byte_size, sha256, etag, last_modified, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    fetch_id,
                    source_id,
                    url,
                    final_url,
                    started_at,
                    finished_at,
                    status,
                    content_type,
                    byte_size,
                    sha256,
                    etag,
                    last_modified,
                ),
            )
            con.commit()

            return {
                "fetch_id": fetch_id,
                "source_id": source_id,
                "manifestation_id": manifestation_id,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "byte_size": byte_size,
                "sha256": sha256,
                "local_path": str(relative_path),
                "retrieved_at": finished_at,
            }

    except Exception as exc:
        finished_at = utc_now()

        try:
            ensure_schema(con)
            source_exists = con.execute(
                "SELECT 1 FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()

            if source_exists is not None:
                con.execute(
                    """
                    INSERT INTO fetches(
                        fetch_id, source_id, requested_url, final_url,
                        started_at, finished_at, http_status, content_type,
                        byte_size, sha256, etag, last_modified, error
                    )
                    VALUES (
                        ?, ?, ?, NULL, ?, ?, NULL, NULL,
                        NULL, NULL, NULL, NULL, ?
                    )
                    """,
                    (
                        fetch_id,
                        source_id,
                        url,
                        started_at,
                        finished_at,
                        f"{type(exc).__name__}: {exc}",
                    ),
                )
                con.commit()
        except Exception:
            pass

        raise

    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()

        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one allowlisted official source into immutable raw storage."
        )
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--allowed-domains",
        default="config/official_domains.json",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--user-agent",
        default=(
            "col-taxdata/0.1 "
            "(+local research; primary-source preservation)"
        ),
    )
    args = parser.parse_args()

    result = fetch(
        source_id=args.source_id,
        url=args.url,
        authority=args.authority,
        source_kind=args.source_kind,
        db_path=Path(args.db),
        data_root=Path(args.data_root),
        allowed_domains_path=Path(args.allowed_domains),
        timeout=args.timeout,
        max_bytes=args.max_bytes,
        user_agent=args.user_agent,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
