#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFECT_ID_RE = re.compile(r"^DEF-\d{4}$")
MANIFEST_ITEM_RE = re.compile(r"^  - id:\s*(\S+)\s*$")
MANIFEST_FIELD_RE = re.compile(r"^    ([A-Za-z0-9_]+):\s*(.*?)\s*$")
SPEC_HEADER_RE = re.compile(r"^#\s+(DEF-\d{4})\s+(?:—|-)\s+(.+?)\s*$")
SPEC_STATUS_RE = re.compile(
    r"^(?:status|Status):\s*(?:\*\*)?([A-Za-z0-9_-]+)(?:\*\*)?\s*$",
    re.MULTILINE,
)
INDEX_DEFECT_RE = re.compile(r"^\[(DEF-\d{4})\]\(([^)]+)\)$")


class CatalogError(ValueError):
    """Raised when the catalog files cannot be parsed deterministically."""


@dataclass(frozen=True)
class ManifestItem:
    item_id: str
    item_type: str
    status: str
    spec: str


@dataclass(frozen=True)
class IndexRow:
    item_id: str
    spec_link: str
    priority: str
    title: str
    github: str
    status: str


def _unquote_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_manifest_items(text: str) -> list[ManifestItem]:
    """Parse the stable top-level items scalar mapping used by manifest.yaml.

    This is intentionally not a general YAML parser. The repository manifest has
    a small, stable mapping shape for catalog identity/status fields, and keeping
    this check stdlib-only makes it deterministic in the trusted CI environment.
    """
    lines = text.splitlines()
    try:
        items_start = next(i for i, line in enumerate(lines) if line.strip() == "items:")
    except StopIteration as exc:
        raise CatalogError("manifest is missing top-level items:") from exc

    raw_items: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in lines[items_start + 1 :]:
        if line and not line.startswith(" "):
            break

        item_match = MANIFEST_ITEM_RE.match(line)
        if item_match:
            if current is not None:
                raw_items.append(current)
            current = {"id": _unquote_scalar(item_match.group(1))}
            continue

        if current is None:
            if line.strip():
                raise CatalogError(f"unexpected content under manifest items: {line!r}")
            continue

        field_match = MANIFEST_FIELD_RE.match(line)
        if not field_match:
            # Nested list values such as depends_on are not needed by this
            # focused consistency check and are deliberately ignored.
            continue
        key = field_match.group(1)
        if key in current:
            raise CatalogError(
                f"manifest item {current['id']} repeats scalar field {key}"
            )
        current[key] = _unquote_scalar(field_match.group(2))

    if current is not None:
        raw_items.append(current)
    if not raw_items:
        raise CatalogError("manifest items: contains no registered items")

    items: list[ManifestItem] = []
    seen_ids: set[str] = set()
    required = ("id", "type", "status", "spec")
    for raw in raw_items:
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise CatalogError(
                f"manifest item {raw.get('id', '<unknown>')} missing fields: "
                + ", ".join(missing)
            )
        item_id = raw["id"]
        if item_id in seen_ids:
            raise CatalogError(f"manifest repeats item id {item_id}")
        seen_ids.add(item_id)
        items.append(
            ManifestItem(
                item_id=item_id,
                item_type=raw["type"],
                status=raw["status"],
                spec=raw["spec"],
            )
        )
    return items


def parse_index_rows(text: str) -> list[IndexRow]:
    """Return defect rows from the human-readable Markdown index."""
    rows: list[IndexRow] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if len(cells) != 5:
            continue
        first = cells[0]
        match = INDEX_DEFECT_RE.fullmatch(first)
        if match:
            rows.append(
                IndexRow(
                    item_id=match.group(1),
                    spec_link=match.group(2),
                    priority=cells[1],
                    title=cells[2],
                    github=cells[3],
                    status=cells[4],
                )
            )
            continue
        if "DEF-" in first and first not in {"ID", "---"}:
            raise CatalogError(
                f"malformed defect index row at line {line_number}: {first}"
            )
    return rows


def _read_spec_identity(path: Path) -> tuple[str, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"cannot read spec {path}: {exc}") from exc

    header = next((line for line in text.splitlines() if line.startswith("# ")), None)
    if header is None:
        raise CatalogError(f"spec {path} is missing an H1 DEF header")
    match = SPEC_HEADER_RE.fullmatch(header)
    if not match:
        raise CatalogError(f"spec {path} has malformed DEF header: {header!r}")

    statuses = SPEC_STATUS_RE.findall(text)
    distinct_statuses = list(dict.fromkeys(statuses))
    if len(distinct_statuses) > 1:
        raise CatalogError(
            f"spec {path} has conflicting Status fields: {distinct_statuses}"
        )
    return match.group(1), distinct_statuses[0] if distinct_statuses else None


def _resolve_index_link(index_path: Path, link: str) -> Path:
    if "://" in link or link.startswith("#"):
        raise CatalogError(f"defect index spec link must be repository-relative: {link}")
    return (index_path.parent / link).resolve()


def validate_defect_catalog(project_root: Path) -> list[str]:
    """Validate manifest/spec/index convergence for registered defect items only."""
    project_root = project_root.resolve()
    manifest_path = project_root / "specs" / "manifest.yaml"
    index_path = project_root / "specs" / "defects" / "README.md"

    manifest_text = manifest_path.read_text(encoding="utf-8")
    index_text = index_path.read_text(encoding="utf-8")
    items = parse_manifest_items(manifest_text)
    index_rows = parse_index_rows(index_text)

    rows_by_id: dict[str, list[IndexRow]] = {}
    for row in index_rows:
        rows_by_id.setdefault(row.item_id, []).append(row)

    errors: list[str] = []
    for item in items:
        if item.item_type != "defect":
            continue
        if not DEFECT_ID_RE.fullmatch(item.item_id):
            errors.append(f"{item.item_id}: defect item id is not DEF-NNNN")
            continue

        spec_path = (project_root / item.spec).resolve()
        if not spec_path.is_file():
            errors.append(f"{item.item_id}: manifest spec does not exist: {item.spec}")
        else:
            try:
                spec_id, spec_status = _read_spec_identity(spec_path)
            except CatalogError as exc:
                errors.append(f"{item.item_id}: {exc}")
            else:
                if spec_id != item.item_id:
                    errors.append(
                        f"{item.item_id}: spec header id is {spec_id}, expected {item.item_id}"
                    )
                if spec_status is not None and spec_status != item.status:
                    errors.append(
                        f"{item.item_id}: spec status {spec_status!r} "
                        f"does not match manifest {item.status!r}"
                    )

        rows = rows_by_id.get(item.item_id, [])
        if len(rows) != 1:
            errors.append(
                f"{item.item_id}: defect index must contain exactly one row; found {len(rows)}"
            )
            continue

        row = rows[0]
        try:
            linked_path = _resolve_index_link(index_path, row.spec_link)
        except CatalogError as exc:
            errors.append(f"{item.item_id}: {exc}")
        else:
            if linked_path != spec_path:
                errors.append(
                    f"{item.item_id}: index link {row.spec_link!r} "
                    f"does not resolve to manifest spec {item.spec!r}"
                )
        if row.status != item.status:
            errors.append(
                f"{item.item_id}: index status {row.status!r} "
                f"does not match manifest {item.status!r}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate registered defect manifest/spec/index convergence."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the col-taxdata project root.",
    )
    args = parser.parse_args(argv)
    try:
        errors = validate_defect_catalog(args.project_root)
    except (CatalogError, OSError, UnicodeError) as exc:
        print(f"defect catalog: ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"defect catalog: FAIL: {error}", file=sys.stderr)
        return 1
    print("defect catalog: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
