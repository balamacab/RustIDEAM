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
        "SELECT manifestation_id, sha256, byte_size, local_path FROM manifestations ORDER BY manifestation_id"
    ).fetchall()


def check_raw_files_exist(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "RAW-001", "raw", ["manifestations"], spec="ADR-0002")
    if missing:
        return missing
    failures: list[str] = []
    for row in _manifestation_rows(ctx):
        path = _resolve_data_path(ctx.data_root, row[3])
        if not path.is_file():
            failures.append(f"{row[0]}: {row[3]}")
    if failures:
        return _error("RAW-001", "raw", "registered raw manifestation files are missing", len(failures), failures, spec="ADR-0002")
    return _pass("RAW-001", "raw", "all registered raw manifestation files exist", spec="ADR-0002")


def check_raw_byte_sizes(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "RAW-002", "raw", ["manifestations"], spec="ADR-0002")
    if missing:
        return missing
    failures: list[str] = []
    checked = 0
    for row in _manifestation_rows(ctx):
        if row[2] is None:
            continue
        path = _resolve_data_path(ctx.data_root, row[3])
        if not path.is_file():
            continue
        checked += 1
        actual = path.stat().st_size
        if actual != int(row[2]):
            failures.append(f"{row[0]}: recorded={row[2]} actual={actual}")
    if failures:
        return _error("RAW-002", "raw", "raw byte-size mismatches detected", len(failures), failures, spec="ADR-0002")
    return _pass("RAW-002", "raw", f"raw byte sizes match for {checked} registered files", spec="ADR-0002")


def check_raw_content_paths(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "RAW-003", "raw", ["manifestations"], spec="ADR-0002")
    if missing:
        return missing
    failures: list[str] = []
    for row in _manifestation_rows(ctx):
        sha = str(row[1]).lower()
        stored = Path(str(row[3]))
        parts = stored.parts
        valid = (
            len(parts) >= 4
            and parts[-4:-2] == ("raw", "sha256")
            and parts[-2].lower() == sha[:2]
            and Path(parts[-1]).stem.lower() == sha
        )
        if not valid:
            failures.append(f"{row[0]}: {row[3]}")
    if failures:
        return _error("RAW-003", "raw", "raw content-addressed paths disagree with registered SHA-256", len(failures), failures, spec="ADR-0002")
    return _pass("RAW-003", "raw", "raw paths agree with content-addressed SHA-256 layout", spec="ADR-0002")


def check_raw_hashes(ctx: DoctorContext) -> CheckResult:
    if ctx.mode != "full":
        return _info("RAW-004", "raw", "full raw SHA-256 verification skipped; run with --full", spec="ADR-0002")
    missing = _require_tables(ctx, "RAW-004", "raw", ["manifestations"], spec="ADR-0002")
    if missing:
        return missing
    failures: list[str] = []
    checked = 0
    for row in _manifestation_rows(ctx):
        path = _resolve_data_path(ctx.data_root, row[3])
        if not path.is_file():
            continue
        checked += 1
        actual = _sha256_file(path)
        if actual.lower() != str(row[1]).lower():
            failures.append(f"{row[0]}: expected={row[1]} actual={actual}")
    if failures:
        return _error("RAW-004", "raw", "raw SHA-256 mismatches detected", len(failures), failures, spec="ADR-0002")
    return _pass("RAW-004", "raw", f"full SHA-256 verified for {checked} raw files", spec="ADR-0002")


def _extraction_rows(ctx: DoctorContext) -> list[sqlite3.Row]:
    return ctx.con.execute(
        "SELECT extraction_id, normalized_sha256, byte_size, local_path FROM text_extractions ORDER BY extraction_id"
    ).fetchall()


def check_extracted_files(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "ARTIFACT-001", "artifact", ["text_extractions"], spec="architecture/data-lifecycle.md")
    if missing:
        return missing
    failures: list[str] = []
    checked = 0
    for row in _extraction_rows(ctx):
        path = _resolve_data_path(ctx.data_root, row[3])
        if not path.is_file():
            failures.append(f"missing {row[0]}: {row[3]}")
            continue
        checked += 1
        if path.stat().st_size != int(row[2]):
            failures.append(f"size {row[0]}: recorded={row[2]} actual={path.stat().st_size}")
    if failures:
        return _error("ARTIFACT-001", "artifact", "registered normalized/extracted artifacts are missing or wrong-sized", len(failures), failures, spec="architecture/data-lifecycle.md")
    return _pass("ARTIFACT-001", "artifact", f"registered extraction files exist with expected size ({checked} checked)", spec="architecture/data-lifecycle.md")


def check_extracted_hashes(ctx: DoctorContext) -> CheckResult:
    if ctx.mode != "full":
        return _info("ARTIFACT-002", "artifact", "full normalized/extracted artifact hashing skipped; run with --full", spec="architecture/data-lifecycle.md")
    missing = _require_tables(ctx, "ARTIFACT-002", "artifact", ["text_extractions"], spec="architecture/data-lifecycle.md")
    if missing:
        return missing
    failures: list[str] = []
    checked = 0
    for row in _extraction_rows(ctx):
        path = _resolve_data_path(ctx.data_root, row[3])
        if not path.is_file():
            continue
        checked += 1
        actual = _sha256_file(path)
        if actual.lower() != str(row[1]).lower():
            failures.append(f"{row[0]}: expected={row[1]} actual={actual}")
    if failures:
        return _error("ARTIFACT-002", "artifact", "normalized/extracted artifact SHA-256 mismatches detected", len(failures), failures, spec="architecture/data-lifecycle.md")
    return _pass("ARTIFACT-002", "artifact", f"full SHA-256 verified for {checked} normalized/extracted files", spec="architecture/data-lifecycle.md")


def check_segment_hashes(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "ARTIFACT-003", "artifact", ["extracted_segments"], spec="architecture/data-lifecycle.md")
    if missing:
        return missing
    failures: list[str] = []
    total = 0
    for segment_id, text, expected in ctx.con.execute(
        "SELECT extracted_segment_id, text, text_sha256 FROM extracted_segments ORDER BY extracted_segment_id"
    ):
        total += 1
        actual = _sha256_text(str(text))
        if actual.lower() != str(expected).lower():
            failures.append(f"{segment_id}: expected={expected} actual={actual}")
    if failures:
        return _error("ARTIFACT-003", "artifact", "extracted-segment text fingerprints do not match persisted text", len(failures), failures, spec="architecture/data-lifecycle.md")
    return _pass("ARTIFACT-003", "artifact", f"text SHA-256 matches for {total} extracted segments", spec="architecture/data-lifecycle.md")


def check_evidence_manifestation(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "PROV-001", "provenance", ["evidence", "manifestations", "sources"], spec="architecture/domain-model.md")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT e.evidence_id, e.source_sha256, m.sha256, e.source_url, s.source_url
        FROM evidence e
        JOIN manifestations m ON m.manifestation_id = e.manifestation_id
        JOIN sources s ON s.source_id = m.source_id
        WHERE e.source_sha256 <> m.sha256 OR e.source_url <> s.source_url
        ORDER BY e.evidence_id
        """
    ).fetchall()
    if rows:
        return _error("PROV-001", "provenance", "evidence source URL/SHA does not match its Manifestation/Source", len(rows), _examples(rows, 0), spec="architecture/domain-model.md")
    return _pass("PROV-001", "provenance", "evidence source URL/SHA chains match registered Manifestations", spec="architecture/domain-model.md")


def check_evidence_segment_chain(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "PROV-002", "provenance", ["evidence", "extracted_segments", "text_extractions"], spec="architecture/domain-model.md")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT e.evidence_id, e.extracted_segment_id, e.manifestation_id
        FROM evidence e
        LEFT JOIN extracted_segments es ON es.extracted_segment_id = e.extracted_segment_id
        LEFT JOIN text_extractions te ON te.extraction_id = es.extraction_id
        WHERE e.extracted_segment_id IS NOT NULL
          AND (es.extracted_segment_id IS NULL OR te.extraction_id IS NULL OR te.manifestation_id <> e.manifestation_id)
        ORDER BY e.evidence_id
        """
    ).fetchall()
    if rows:
        return _error("PROV-002", "provenance", "evidence segment chain does not resolve to the same Manifestation", len(rows), _examples(rows, 0, 1), spec="architecture/domain-model.md")
    return _pass("PROV-002", "provenance", "evidence segment -> extraction -> manifestation chains are consistent", spec="architecture/domain-model.md")


def check_validated_claim_evidence(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "PROV-003", "provenance", ["claims", "evidence"], spec="architecture/domain-model.md")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT c.claim_id
        FROM claims c
        LEFT JOIN evidence e ON e.claim_id = c.claim_id
        WHERE c.status IN ('validated', 'human_verified')
        GROUP BY c.claim_id
        HAVING COUNT(e.evidence_id) = 0
        ORDER BY c.claim_id
        """
    ).fetchall()
    if rows:
        return _error("PROV-003", "provenance", "validated/human-verified claims lack evidence", len(rows), _examples(rows, 0), spec="architecture/domain-model.md")
    return _pass("PROV-003", "provenance", "validated/human-verified claims retain evidence bindings", spec="architecture/domain-model.md")


def check_identity_uniqueness(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "IDENTITY-001", "identity", ["documents", "document_identifiers"], spec="ADR-0006")
    if missing:
        return missing
    collisions = ctx.con.execute(
        """
        SELECT identifier_value, COUNT(DISTINCT document_id) AS n
        FROM document_identifiers
        WHERE identifier_type = 'canonical_key' AND is_primary = 1
        GROUP BY identifier_value
        HAVING COUNT(DISTINCT document_id) > 1
        ORDER BY identifier_value
        """
    ).fetchall()
    multi_primary = ctx.con.execute(
        """
        SELECT document_id, COUNT(*) AS n
        FROM document_identifiers
        WHERE identifier_type = 'canonical_key' AND is_primary = 1
        GROUP BY document_id
        HAVING COUNT(*) > 1
        ORDER BY document_id
        """
    ).fetchall()
    problems = [f"collision {row[0]} ({row[1]} documents)" for row in collisions]
    problems.extend(f"multiple primary keys {row[0]} ({row[1]})" for row in multi_primary)
    if problems:
        return _error("IDENTITY-001", "identity", "canonical primary-key uniqueness is violated", len(problems), problems, spec="ADR-0006")
    return _pass("IDENTITY-001", "identity", "canonical primary keys do not collide across distinct Documents", spec="ADR-0006")


def _parse_primary_key(value: str) -> tuple[str | None, str | None, str | None, int | None]:
    parts = value.split(":")
    try:
        if len(parts) == 5 and parts[0] == "CO":
            return parts[1], parts[2], parts[3], int(parts[4])
        if len(parts) == 4 and parts[0] == "CO":
            return None, parts[1], parts[2], int(parts[3])
    except ValueError:
        pass
    return None, None, None, None


def check_issuer_aware_identity(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "IDENTITY-002", "identity", ["documents", "document_identifiers"], spec="ADR-0006")
    if missing:
        return missing
    problems: list[str] = []
    rows = ctx.con.execute(
        """
        SELECT d.document_id, d.document_type, di.identifier_value, di.issuer
        FROM documents d
        JOIN document_identifiers di ON di.document_id = d.document_id
        WHERE di.identifier_type = 'canonical_key' AND di.is_primary = 1
        ORDER BY d.document_id
