#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Callable, Iterable, Sequence

from source_identity import (
    CONPES,
    CONSTITUCION_POLITICA,
    CORTE_CONSTITUCIONAL_SENTENCIA_C,
    DIAN_CONCEPTO,
    DIAN_OFICIO,
    ISSUER_SCOPED_TYPES,
    JURISPRUDENCIA,
    NORMATIVE_ACT,
    UNKNOWN,
    classify_source_url,
)


MAX_EXAMPLES = 10
VALID_SCOPES = (
    "database",
    "raw",
    "artifact",
    "provenance",
    "identity",
    "provision",
    "reference",
    "relationship",
    "temporal",
    "review",
    "retrieval",
    "case",
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    scope: str
    status: str
    severity: str
    description: str
    affected_count: int = 0
    examples: tuple[str, ...] = ()
    spec_reference: str | None = None

    def to_json(self) -> dict[str, object]:
        data = asdict(self)
        data["examples"] = list(self.examples)
        return data


@dataclass(frozen=True)
class DoctorReport:
    mode: str
    db: str
    checks: tuple[CheckResult, ...]

    @property
    def has_errors(self) -> bool:
        return any(check.status == "ERROR" for check in self.checks)

    def summary(self) -> dict[str, int]:
        counts = Counter(check.status for check in self.checks)
        return {key: counts.get(key, 0) for key in ("PASS", "WARN", "INFO", "ERROR")}

    def to_json(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "db": self.db,
            "summary": self.summary(),
            "checks": [check.to_json() for check in self.checks],
        }


@dataclass(frozen=True)
class DoctorContext:
    con: sqlite3.Connection
    db_path: Path
    data_root: Path
    schema_dir: Path
    mode: str


Check = Callable[[DoctorContext], CheckResult]


def _pass(check_id: str, scope: str, description: str, *, spec: str | None = None) -> CheckResult:
    return CheckResult(check_id, scope, "PASS", "INFO", description, spec_reference=spec)


def _info(check_id: str, scope: str, description: str, *, spec: str | None = None) -> CheckResult:
    return CheckResult(check_id, scope, "INFO", "INFO", description, spec_reference=spec)


def _warn(
    check_id: str,
    scope: str,
    description: str,
    count: int,
    examples: Iterable[object] = (),
    *,
    spec: str | None = None,
) -> CheckResult:
    return CheckResult(
        check_id,
        scope,
        "WARN",
        "WARNING",
        description,
        count,
        tuple(str(value) for value in list(examples)[:MAX_EXAMPLES]),
        spec,
    )


def _error(
    check_id: str,
    scope: str,
    description: str,
    count: int,
    examples: Iterable[object] = (),
    *,
    spec: str | None = None,
) -> CheckResult:
    return CheckResult(
        check_id,
        scope,
        "ERROR",
        "ERROR",
        description,
        count,
        tuple(str(value) for value in list(examples)[:MAX_EXAMPLES]),
        spec,
    )


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (table,),
    ).fetchone() is not None


def _missing_tables(con: sqlite3.Connection, tables: Sequence[str]) -> list[str]:
    return [table for table in tables if not _table_exists(con, table)]


def _require_tables(
    ctx: DoctorContext,
    check_id: str,
    scope: str,
    tables: Sequence[str],
    *,
    spec: str | None = None,
) -> CheckResult | None:
    missing = _missing_tables(ctx.con, tables)
    if not missing:
        return None
    return _error(
        check_id,
        scope,
        "required schema objects are missing",
        len(missing),
        missing,
        spec=spec,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_data_path(data_root: Path, stored_path: str) -> Path:
    path = Path(stored_path)
    return path if path.is_absolute() else data_root / path


def _examples(rows: Iterable[Sequence[object]], *indexes: int) -> list[str]:
    values: list[str] = []
    for row in rows:
        if indexes:
            values.append(" | ".join(str(row[index]) for index in indexes))
        else:
            values.append(" | ".join(str(value) for value in row))
        if len(values) >= MAX_EXAMPLES:
            break
    return values


def check_db_integrity(ctx: DoctorContext) -> CheckResult:
    pragma = "integrity_check" if ctx.mode == "full" else "quick_check"
    rows = ctx.con.execute(f"PRAGMA {pragma}").fetchall()
    messages = [str(row[0]) for row in rows]
    if messages == ["ok"]:
        return _pass("DB-001", "database", f"SQLite {pragma} returned ok", spec="ADR-0001")
    return _error("DB-001", "database", f"SQLite {pragma} reported corruption", len(messages), messages, spec="ADR-0001")


def check_foreign_keys(ctx: DoctorContext) -> CheckResult:
    rows = ctx.con.execute("PRAGMA foreign_key_check").fetchall()
    if not rows:
        return _pass("DB-002", "database", "all declared foreign-key constraints are valid", spec="architecture/domain-model.md")
    return _error("DB-002", "database", "foreign-key violations detected", len(rows), _examples(rows), spec="architecture/domain-model.md")


def check_migration_hashes(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "DB-003", "database", ["schema_metadata"], spec="ADR-0003")
    if missing:
        return missing

    files = sorted(ctx.schema_dir.glob("*.sql"))
    if not files:
        return _error("DB-003", "database", "no migration files found", 1, [str(ctx.schema_dir)], spec="ADR-0003")

    recorded = {
        str(name): str(schema_hash)
        for name, schema_hash in ctx.con.execute(
            "SELECT schema_name, schema_sha256 FROM schema_metadata"
        )
    }
    expected_names = {path.name for path in files}
    problems: list[str] = []

    for path in files:
        stored = recorded.get(path.name)
        if stored is None:
            problems.append(f"missing metadata: {path.name}")
            continue
        actual = _sha256_file(path)
        if stored != actual:
            problems.append(f"hash drift: {path.name}")

    for stale_name in sorted(set(recorded) - expected_names):
        problems.append(f"metadata without migration file: {stale_name}")

    if problems:
        return _error("DB-003", "database", "migration metadata/hash drift detected", len(problems), problems, spec="ADR-0003")
    return _pass("DB-003", "database", f"{len(files)} applied migration hashes match repository files", spec="ADR-0003")


def _manifestation_rows(ctx: DoctorContext) -> list[sqlite3.Row]:
    return ctx.con.execute(
