#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from materialize_case_report import render_report
from materialize_case_sources import render_source_manifest


def _sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_case_materializations(
    con: sqlite3.Connection,
    *,
    case_id: str,
    case_dir: Path,
) -> list[tuple[Path, str]]:
    """Render every checked-in materialization governed by canonical case state."""
    return [
        (
            case_dir / "sources" / "manifest.json",
            render_source_manifest(con, case_id=case_id),
        ),
        (
            case_dir / "report.md",
            render_report(
                con=con,
                case_id=case_id,
                case_dir=case_dir,
            ),
        ),
    ]


def plan_case_materializations(
    con: sqlite3.Connection,
    *,
    case_id: str,
    case_dir: Path,
    include_diff: bool = False,
) -> dict[str, object]:
    """Compare stored artifacts with canonical renders without mutating files."""
    artifacts: list[dict[str, object]] = []

    for path, rendered in canonical_case_materializations(
        con,
        case_id=case_id,
        case_dir=case_dir,
    ):
        stored = path.read_text(encoding="utf-8") if path.exists() else None
        if stored is None:
            status = "missing"
        elif stored == rendered:
            status = "current"
        else:
            status = "stale"

        artifact: dict[str, object] = {
            "path": str(path),
            "status": status,
            "before_sha256": _sha256_text(stored),
            "canonical_sha256": _sha256_text(rendered),
        }
        if include_diff and stored != rendered:
            artifact["diff"] = "".join(
                difflib.unified_diff(
                    (stored or "").splitlines(keepends=True),
                    rendered.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=f"{path} (canonical)",
                )
            )
        artifacts.append(artifact)

    return {
        "case_id": case_id,
        "current_count": sum(a["status"] == "current" for a in artifacts),
        "stale_count": sum(a["status"] == "stale" for a in artifacts),
        "missing_count": sum(a["status"] == "missing" for a in artifacts),
        "would_write_count": sum(
            a["status"] in {"stale", "missing"}
            for a in artifacts
        ),
        "artifacts": artifacts,
    }


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def refresh_case_materializations(
    con: sqlite3.Connection,
    *,
    case_id: str,
    case_dir: Path,
    write: bool,
    include_diff: bool = False,
) -> dict[str, object]:
    """Preview or explicitly refresh deterministic case materializations."""
    before = plan_case_materializations(
        con,
        case_id=case_id,
        case_dir=case_dir,
        include_diff=include_diff,
    )

    updated_paths: list[str] = []
    if write:
        canonical = dict(
            canonical_case_materializations(
                con,
                case_id=case_id,
                case_dir=case_dir,
            )
        )
        for artifact in before["artifacts"]:
            if artifact["status"] == "current":
                continue
            path = Path(str(artifact["path"]))
            _atomic_write_text(path, canonical[path])
            updated_paths.append(str(path))

        after = plan_case_materializations(
            con,
            case_id=case_id,
            case_dir=case_dir,
        )
        if after["would_write_count"] != 0:
            raise RuntimeError(
                "case materialization refresh did not converge to current state"
            )
    else:
        after = before

    return {
        "case_id": case_id,
        "mode": "write" if write else "preview",
        "updated_count": len(updated_paths),
        "updated_paths": updated_paths,
        "before": before,
        "after": after,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or refresh deterministic case report/source "
            "materializations from canonical SQLite state."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply the previewed materialization updates. Default is dry-run.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Include deterministic unified diffs for stale/missing artifacts.",
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    try:
        result = refresh_case_materializations(
            con,
            case_id=args.case_id,
            case_dir=Path(args.case_dir),
            write=args.write,
            include_diff=args.diff,
        )
    finally:
        con.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
