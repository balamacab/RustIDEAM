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
            failures.append(f"missing {row[0]}: {row[3]}")
            continue
        try:
            with path.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            failures.append(
                f"unreadable {row[0]}: {type(exc).__name__}: {exc}"
            )
    if failures:
        return _error(
            "RAW-001",
            "raw",
            "registered raw manifestation files are missing or unreadable",
            len(failures),
            failures,
            spec="ADR-0002",
        )
    return _pass(
        "RAW-001",
        "raw",
        "all registered raw manifestation files exist and are readable",
        spec="ADR-0002",
    )

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
        try:
            actual = path.stat().st_size
        except OSError as exc:
            failures.append(
                f"{row[0]}: stat failed: {type(exc).__name__}: {exc}"
            )
            continue
        checked += 1
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
        try:
            actual = _sha256_file(path)
        except OSError as exc:
            failures.append(
                f"{row[0]}: unreadable: {type(exc).__name__}: {exc}"
            )
            continue
        checked += 1
        if actual.lower() != str(row[1]).lower():
            failures.append(f"{row[0]}: expected={row[1]} actual={actual}")
    if failures:
        return _error("RAW-004", "raw", "raw SHA-256 mismatches or read failures detected", len(failures), failures, spec="ADR-0002")
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
        try:
            with path.open("rb") as handle:
                handle.read(1)
            actual_size = path.stat().st_size
        except OSError as exc:
            failures.append(
                f"unreadable {row[0]}: {type(exc).__name__}: {exc}"
            )
            continue
        checked += 1
        if actual_size != int(row[2]):
            failures.append(
                f"size {row[0]}: recorded={row[2]} actual={actual_size}"
            )
    if failures:
        return _error(
            "ARTIFACT-001",
            "artifact",
            "registered normalized/extracted artifacts are missing, unreadable, or wrong-sized",
            len(failures),
            failures,
            spec="architecture/data-lifecycle.md",
        )
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
        try:
            actual = _sha256_file(path)
        except OSError as exc:
            failures.append(
                f"{row[0]}: unreadable: {type(exc).__name__}: {exc}"
            )
            continue
        checked += 1
        if actual.lower() != str(row[1]).lower():
            failures.append(f"{row[0]}: expected={row[1]} actual={actual}")
    if failures:
        return _error(
            "ARTIFACT-002",
            "artifact",
            "normalized/extracted artifact SHA-256 mismatches or read failures detected",
            len(failures),
            failures,
            spec="architecture/data-lifecycle.md",
        )
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
        """
    ).fetchall()
    numbered_identity_types = set(ISSUER_SCOPED_TYPES) | {"LEY", "DECRETO"}
    for document_id, document_type, key, issuer in rows:
        # Not every canonical Document uses a numbered legal-act key shape.
        # Official guidance (for example CO:DIAN:TRAMITE:RUT_CANCELACION)
        # intentionally uses a domain key without number/year. Only enforce
        # numbered-key structure for types governed by source_identity.
        if str(document_type) not in numbered_identity_types:
            continue
        key_issuer, key_type, _number, _year = _parse_primary_key(str(key))
        if key_type is None:
            problems.append(f"{document_id}: malformed canonical key {key}")
            continue
        if str(document_type) != key_type:
            problems.append(f"{document_id}: document_type={document_type} key_type={key_type}")
        if str(document_type) in ISSUER_SCOPED_TYPES:
            if key_issuer is None:
                problems.append(f"{document_id}: issuer-scoped key is unqualified: {key}")
            if not issuer:
                problems.append(f"{document_id}: issuer-scoped primary identifier has no issuer")
            elif key_issuer is not None and str(issuer) != key_issuer:
                problems.append(f"{document_id}: issuer={issuer} key_issuer={key_issuer}")
    if problems:
        return _error("IDENTITY-002", "identity", "issuer-aware canonical-key invariants are violated", len(problems), problems, spec="ADR-0006")
    return _pass("IDENTITY-002", "identity", "numbered/issuer-scoped canonical identities are internally consistent", spec="ADR-0006")
def check_source_family_bindings(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "IDENTITY-003", "identity", ["manifestations", "sources", "documents", "document_identifiers"], spec="DEF-0001/DEF-0003")
    if missing:
        return missing

    primary_keys = {
        str(document_id): str(identifier_value)
        for document_id, identifier_value in ctx.con.execute(
            """
            SELECT document_id, identifier_value
            FROM document_identifiers
            WHERE identifier_type = 'canonical_key' AND is_primary = 1
            """
        )
    }
    problems: list[str] = []
    rows = ctx.con.execute(
        """
        SELECT m.manifestation_id, s.source_url, d.document_id, d.document_type
        FROM manifestations m
        JOIN sources s ON s.source_id = m.source_id
        JOIN documents d ON d.document_id = m.document_id
        WHERE m.document_id IS NOT NULL
        ORDER BY m.manifestation_id
        """
    ).fetchall()
    family_types = {
        DIAN_CONCEPTO: {"CONCEPTO"},
        DIAN_OFICIO: {"OFICIO", "CONCEPTO"},
        CORTE_CONSTITUCIONAL_SENTENCIA_C: {"SENTENCIA_C"},
        CONPES: {"CONPES"},
        CONSTITUCION_POLITICA: {"CONSTITUCION_POLITICA"},
    }
    for manifestation_id, source_url, document_id, document_type in rows:
        signal = classify_source_url(str(source_url))
        if signal.family in {UNKNOWN, JURISPRUDENCIA}:
            continue
        allowed = family_types.get(signal.family)
        if signal.family == NORMATIVE_ACT and signal.document_type:
            allowed = {signal.document_type}
        if allowed is not None and str(document_type) not in allowed:
            problems.append(f"{manifestation_id}: source_family={signal.family} document_type={document_type}")
            continue
        if signal.canonical_key and signal.family != DIAN_OFICIO:
            primary = primary_keys.get(str(document_id))
            if primary is not None and primary != signal.canonical_key:
                problems.append(f"{manifestation_id}: source_key={signal.canonical_key} primary_key={primary}")
    if problems:
        return _error("IDENTITY-003", "identity", "bound Document identity conflicts with deterministic source-family identity", len(problems), problems, spec="DEF-0001/DEF-0003")
    return _pass("IDENTITY-003", "identity", "bound Documents are compatible with deterministic source-family identity", spec="DEF-0001/DEF-0003")


def check_provision_observations(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "PROVISION-001", "provision", ["provision_observations", "extracted_segments"], spec="architecture/domain-model.md")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT po.provision_observation_id, po.extraction_id, es.extraction_id
        FROM provision_observations po
        JOIN extracted_segments es ON es.extracted_segment_id = po.extracted_segment_id
        WHERE po.extraction_id <> es.extraction_id
        ORDER BY po.provision_observation_id
        """
    ).fetchall()
    if rows:
        return _error("PROVISION-001", "provision", "provision observation segment belongs to a different extraction", len(rows), _examples(rows, 0), spec="architecture/domain-model.md")
    return _pass("PROVISION-001", "provision", "provision observations and segment extraction identities agree", spec="architecture/domain-model.md")


def check_reference_chains(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "REF-001", "reference", ["reference_mentions", "reference_detection_runs", "extracted_segments"], spec="architecture/domain-model.md")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT rm.reference_mention_id
        FROM reference_mentions rm
        LEFT JOIN reference_detection_runs rdr ON rdr.detection_run_id = rm.detection_run_id
        LEFT JOIN extracted_segments es ON es.extracted_segment_id = rm.extracted_segment_id
        WHERE rdr.detection_run_id IS NULL OR es.extracted_segment_id IS NULL
           OR rm.extraction_id <> rdr.extraction_id OR rm.extraction_id <> es.extraction_id
        ORDER BY rm.reference_mention_id
        """
    ).fetchall()
    if rows:
        return _error("REF-001", "reference", "reference mention detector/extraction/segment chains are inconsistent", len(rows), _examples(rows, 0), spec="architecture/domain-model.md")
    return _pass("REF-001", "reference", "reference mention detector/extraction/segment chains are consistent", spec="architecture/domain-model.md")



def check_reference_resolutions(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "REF-002", "reference", ["reference_resolutions", "reference_mentions", "provisions"], spec="architecture/domain-model.md")
    if missing:
        return missing
    problems: list[str] = []
    rows = ctx.con.execute(
        """
        SELECT rr.reference_resolution_id, rm.mention_type, rr.status,
               rr.target_document_id, rr.target_provision_id, p.document_id
        FROM reference_resolutions rr
        JOIN reference_mentions rm ON rm.reference_mention_id = rr.reference_mention_id
        LEFT JOIN provisions p ON p.provision_id = rr.target_provision_id
        ORDER BY rr.reference_resolution_id
        """
    ).fetchall()
    for resolution_id, mention_type, status, target_document, target_provision, provision_document in rows:
        if status == "resolved":
            if target_document is None:
                problems.append(f"{resolution_id}: resolved without target_document_id")
            if mention_type == "article" and target_provision is None:
                problems.append(f"{resolution_id}: resolved article without target_provision_id")
        elif target_provision is not None:
            # The resolver intentionally preserves an unambiguous Document
            # target when an article/provision remains unresolved or ambiguous.
            problems.append(
                f"{resolution_id}: {status} resolution retains target_provision_id"
            )
        if target_provision is not None and provision_document != target_document:
            problems.append(f"{resolution_id}: target provision/document mismatch")
    if problems:
        return _error("REF-002", "reference", "reference resolution status/target invariants are violated", len(problems), problems, spec="architecture/domain-model.md")
    return _pass("REF-002", "reference", "reference resolution status and partial/full target bindings are consistent", spec="architecture/domain-model.md")
def _entity_table(entity_type: str) -> tuple[str, str] | None:
    return {
        "document": ("documents", "document_id"),
        "provision": ("provisions", "provision_id"),
        "manifestation": ("manifestations", "manifestation_id"),
        "evidence": ("evidence", "evidence_id"),
        "claim": ("claims", "claim_id"),
        "relationship": ("relationships", "relationship_id"),
        "temporal_event": ("temporal_events", "temporal_event_id"),
        "reference_mention": ("reference_mentions", "reference_mention_id"),
        "reference_resolution": ("reference_resolutions", "reference_resolution_id"),
        "explicit_relation_mention": (
            "explicit_relation_mentions",
            "relation_mention_id",
        ),
        "temporal_resolution": ("temporal_role_resolutions", "temporal_resolution_id"),
        "extraction": ("text_extractions", "extraction_id"),
        "extracted_segment": ("extracted_segments", "extracted_segment_id"),
        "source": ("sources", "source_id"),
    }.get(entity_type)


def _exists(ctx: DoctorContext, entity_type: str, entity_id: str) -> bool | None:
    target = _entity_table(entity_type)
    if target is None:
        return None
    table, column = target
    if not _table_exists(ctx.con, table):
        return False
    return ctx.con.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (entity_id,)).fetchone() is not None


def check_relationship_endpoints(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "REL-001", "relationship", ["relationships", "documents", "provisions"], spec="architecture/domain-model.md")
    if missing:
        return missing
    problems: list[str] = []
    unknown: list[str] = []
    for relationship_id, source_type, source_id, target_type, target_id in ctx.con.execute(
        "SELECT relationship_id, source_type, source_id, target_type, target_id FROM relationships ORDER BY relationship_id"
    ):
        source_exists = _exists(ctx, str(source_type), str(source_id))
        target_exists = _exists(ctx, str(target_type), str(target_id))
        if source_exists is False:
            problems.append(f"{relationship_id}: missing source {source_type}:{source_id}")
        elif source_exists is None:
            unknown.append(f"{relationship_id}: unknown source_type={source_type}")
        if target_exists is False:
            problems.append(f"{relationship_id}: missing target {target_type}:{target_id}")
        elif target_exists is None:
            unknown.append(f"{relationship_id}: unknown target_type={target_type}")
    if problems:
        return _error("REL-001", "relationship", "relationship endpoints reference missing canonical entities", len(problems), problems, spec="architecture/domain-model.md")
    if unknown:
        return _warn("REL-001", "relationship", "relationship endpoint types are not recognized by the current doctor contract", len(unknown), unknown, spec="architecture/domain-model.md")
    return _pass("REL-001", "relationship", "relationship endpoints resolve to existing canonical entities", spec="architecture/domain-model.md")


def check_relationship_provenance(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "REL-002", "relationship", ["relationships", "relationship_provenance", "reference_resolutions", "explicit_relation_mentions"], spec="architecture/domain-model.md")
    if missing:
        return missing
    problems: list[str] = []
    rows = ctx.con.execute(
        """
        SELECT r.relationship_id, r.status, r.evidence_id,
               rp.relationship_id, rr.status,
               erm.target_reference_mention_id, rr.reference_mention_id
        FROM relationships r
        LEFT JOIN relationship_provenance rp ON rp.relationship_id = r.relationship_id
        LEFT JOIN reference_resolutions rr ON rr.reference_resolution_id = rp.reference_resolution_id
        LEFT JOIN explicit_relation_mentions erm ON erm.relation_mention_id = rp.relation_mention_id
        ORDER BY r.relationship_id
        """
    ).fetchall()
    for relationship_id, status, evidence_id, provenance_id, resolution_status, relation_ref, resolution_ref in rows:
        if status == "validated":
            if evidence_id is None:
                problems.append(f"{relationship_id}: validated without evidence")
            if provenance_id is None:
                problems.append(f"{relationship_id}: validated without relationship_provenance")
            elif resolution_status != "resolved":
                problems.append(f"{relationship_id}: provenance resolution status={resolution_status}")
            elif relation_ref != resolution_ref:
                problems.append(f"{relationship_id}: provenance relation mention and resolution reference differ")
    if problems:
        return _error("REL-002", "relationship", "validated relationship provenance is incomplete or inconsistent", len(problems), problems, spec="architecture/domain-model.md")
    return _pass("REL-002", "relationship", "validated relationships retain consistent evidence/provenance", spec="architecture/domain-model.md")


def check_temporal_candidates(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "TEMP-001", "temporal", ["temporal_candidates", "text_extractions", "extracted_segments", "evidence"], spec="DEF-0004")
    if missing:
        return missing
    rows = ctx.con.execute(
        """
        SELECT tc.temporal_candidate_id
        FROM temporal_candidates tc
        LEFT JOIN text_extractions te ON te.extraction_id = tc.extraction_id
        LEFT JOIN extracted_segments es ON es.extracted_segment_id = tc.extracted_segment_id
        LEFT JOIN evidence e ON e.evidence_id = tc.evidence_id
        WHERE te.extraction_id IS NULL OR es.extracted_segment_id IS NULL OR e.evidence_id IS NULL
           OR te.manifestation_id <> tc.manifestation_id
           OR es.extraction_id <> tc.extraction_id
           OR e.manifestation_id <> tc.manifestation_id
           OR (e.extracted_segment_id IS NOT NULL AND e.extracted_segment_id <> tc.extracted_segment_id)
        ORDER BY tc.temporal_candidate_id
        """
    ).fetchall()
    if rows:
        return _error("TEMP-001", "temporal", "temporal candidate provenance chains are inconsistent", len(rows), _examples(rows, 0), spec="DEF-0004")
    return _pass("TEMP-001", "temporal", "temporal candidate provenance chains are internally consistent", spec="DEF-0004")


def check_temporal_resolutions(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "TEMP-002", "temporal", ["temporal_role_resolutions", "temporal_candidates"], spec="DEF-0004")
    if missing:
        return missing
    problems: list[str] = []
    rows = ctx.con.execute(
        """
        SELECT tr.temporal_resolution_id, tr.extraction_id, tr.document_id, tr.role,
               tr.status, tr.candidate_count, tr.trusted_candidate_count,
               tr.promoted_candidate_id, tr.processor_name, tr.processor_version
        FROM temporal_role_resolutions tr
        ORDER BY tr.temporal_resolution_id
        """
    ).fetchall()
    for row in rows:
        (resolution_id, extraction_id, document_id, role, status, candidate_count,
         trusted_count, promoted_id, processor_name, processor_version) = row
        actual_count, actual_trusted = ctx.con.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(is_trusted_structure), 0)
            FROM temporal_candidates
            WHERE extraction_id = ? AND document_id = ? AND role = ?
              AND processor_name = ? AND processor_version = ?
            """,
            (extraction_id, document_id, role, processor_name, processor_version),
        ).fetchone()
        if int(candidate_count) != int(actual_count) or int(trusted_count) != int(actual_trusted):
            problems.append(f"{resolution_id}: recorded counts={candidate_count}/{trusted_count} actual={actual_count}/{actual_trusted}")
        if status == "resolved":
            candidate = ctx.con.execute(
                """
                SELECT extraction_id, document_id, role, processor_name, processor_version
                FROM temporal_candidates WHERE temporal_candidate_id = ?
                """,
                (promoted_id,),
            ).fetchone()
            expected = (extraction_id, document_id, role, processor_name, processor_version)
            if candidate is None or tuple(candidate) != expected:
                problems.append(f"{resolution_id}: promoted candidate does not belong to the resolved role")
        elif promoted_id is not None:
            problems.append(f"{resolution_id}: {status} resolution retains promoted candidate")
    if problems:
        return _error("TEMP-002", "temporal", "temporal resolution status/count/promotion invariants are violated", len(problems), problems, spec="DEF-0004")
    return _pass("TEMP-002", "temporal", "temporal resolution counts/status/promotion are consistent", spec="DEF-0004")


def check_review_queue(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "REVIEW-001", "review", ["review_queue"], spec="architecture/domain-model.md")
    if missing:
        return missing
    problems: list[str] = []
    unknown: list[str] = []
    for review_id, entity_type, entity_id in ctx.con.execute(
        "SELECT review_id, entity_type, entity_id FROM review_queue ORDER BY review_id"
    ):
        exists = _exists(ctx, str(entity_type), str(entity_id))
        if exists is False:
            problems.append(f"{review_id}: missing {entity_type}:{entity_id}")
        elif exists is None:
            unknown.append(f"{review_id}: unknown entity_type={entity_type}")
    if problems:
        return _error("REVIEW-001", "review", "review queue items reference missing entities", len(problems), problems, spec="architecture/domain-model.md")
    if unknown:
        return _warn("REVIEW-001", "review", "review queue contains entity types outside the current doctor mapping", len(unknown), unknown, spec="architecture/domain-model.md")
    return _pass("REVIEW-001", "review", "review queue entity references resolve", spec="architecture/domain-model.md")


def check_fts_sync(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "FTS-001", "retrieval", ["extracted_segments", "extracted_segments_fts"], spec="architecture/overview.md § Retrieval")
    if missing:
        return missing
    missing_rows = ctx.con.execute(
        """
        SELECT es.rowid, es.extracted_segment_id
        FROM extracted_segments es
        LEFT JOIN extracted_segments_fts f ON f.rowid = es.rowid
        WHERE f.rowid IS NULL
        ORDER BY es.rowid
        """
    ).fetchall()
    orphan_rows = ctx.con.execute(
        """
        SELECT f.rowid
        FROM extracted_segments_fts f
        LEFT JOIN extracted_segments es ON es.rowid = f.rowid
        WHERE es.rowid IS NULL
        ORDER BY f.rowid
        """
    ).fetchall()
    problems = [f"missing FTS row for {row[1]} (rowid={row[0]})" for row in missing_rows]
    problems.extend(f"orphan FTS rowid={row[0]}" for row in orphan_rows)
    if problems:
        return _error("FTS-001", "retrieval", "contentless extracted-segment FTS rowid synchronization is stale", len(problems), problems, spec="architecture/overview.md § Retrieval")
    return _pass("FTS-001", "retrieval", "extracted_segments and contentless FTS rowids are synchronized", spec="architecture/overview.md § Retrieval")


def check_case_items(ctx: DoctorContext) -> CheckResult:
    missing = _require_tables(ctx, "CASE-001", "case", ["case_items", "cases"], spec="architecture/data-lifecycle.md § Case analysis")
    if missing:
        return missing
    problems: list[str] = []
    unknown: list[str] = []
    for case_id, item_type, item_id in ctx.con.execute(
        "SELECT case_id, item_type, item_id FROM case_items ORDER BY case_id, item_type, item_id"
    ):
        exists = _exists(ctx, str(item_type), str(item_id))
        if exists is False:
            problems.append(f"{case_id}: missing {item_type}:{item_id}")
        elif exists is None:
            unknown.append(f"{case_id}: unknown item_type={item_type}")
    if problems:
        return _error("CASE-001", "case", "case items reference missing corpus entities", len(problems), problems, spec="architecture/data-lifecycle.md § Case analysis")
    if unknown:
        return _warn("CASE-001", "case", "case items contain types outside the current doctor mapping", len(unknown), unknown, spec="architecture/data-lifecycle.md § Case analysis")
    return _pass("CASE-001", "case", "case item references resolve for known corpus entity types", spec="architecture/data-lifecycle.md § Case analysis")


CHECKS: tuple[Check, ...] = (
    check_db_integrity,
    check_foreign_keys,
    check_migration_hashes,
    check_raw_files_exist,
    check_raw_byte_sizes,
    check_raw_content_paths,
    check_raw_hashes,
    check_extracted_files,
    check_extracted_hashes,
    check_segment_hashes,
    check_evidence_manifestation,
    check_evidence_segment_chain,
    check_validated_claim_evidence,
    check_identity_uniqueness,
    check_issuer_aware_identity,
    check_source_family_bindings,
    check_provision_observations,
    check_reference_chains,
    check_reference_resolutions,
    check_relationship_endpoints,
    check_relationship_provenance,
    check_temporal_candidates,
    check_temporal_resolutions,
    check_review_queue,
    check_fts_sync,
    check_case_items,
)


def open_read_only_database(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.resolve(strict=True)
    con = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA query_only = ON")
    return con


def run_doctor(
    *,
    db_path: Path,
    data_root: Path,
    schema_dir: Path,
    mode: str = "quick",
    scopes: Sequence[str] = (),
) -> DoctorReport:
    selected = set(scopes)
    unknown = selected - set(VALID_SCOPES)
    if unknown:
        raise ValueError("unknown scope(s): " + ", ".join(sorted(unknown)))
    if mode not in {"quick", "full"}:
        raise ValueError(f"unsupported mode: {mode}")

    con = open_read_only_database(db_path)
    try:
        ctx = DoctorContext(con, db_path, data_root, schema_dir, mode)
        checks: list[CheckResult] = []
        for check in CHECKS:
            result = check(ctx)
            if selected and result.scope not in selected:
                continue
            checks.append(result)
        return DoctorReport(mode, str(db_path), tuple(checks))
    finally:
        con.close()


def render_human(report: DoctorReport) -> str:
    groups: dict[str, list[CheckResult]] = {}
    for check in report.checks:
        groups.setdefault(check.scope, []).append(check)

    lines: list[str] = []
    for scope in VALID_SCOPES:
        scope_checks = groups.get(scope)
        if not scope_checks:
            continue
        lines.append(scope.upper())
        for check in scope_checks:
            suffix = f" ({check.affected_count} affected)" if check.affected_count else ""
            lines.append(f"  {check.check_id:<13} {check.status:<5} {check.description}{suffix}")
            for example in check.examples:
                lines.append(f"    - {example}")
        lines.append("")

    summary = report.summary()
    lines.append("RESULT")
    lines.append(
        "  " + "  ".join(f"{summary[name]} {name}" for name in ("PASS", "WARN", "INFO", "ERROR"))
    )
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only col-taxdata corpus doctor / invariant validator."
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite", help="SQLite corpus database path")
    parser.add_argument("--data-root", default="data", help="Root used to resolve registered corpus artifact paths")
    parser.add_argument("--schema-dir", default="schema", help="Directory containing append-only SQL migrations")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Run routine structural checks without full-file hashing (default)")
    mode.add_argument("--full", action="store_true", help="Run structural checks plus full raw/extracted SHA-256 verification")
    parser.add_argument("--scope", action="append", choices=VALID_SCOPES, default=[], help="Run only the selected invariant family; repeatable")
    parser.add_argument("--format", choices=("human", "json"), default="human", help="Output format")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected_mode = "full" if args.full else "quick"
    try:
        report = run_doctor(
            db_path=Path(args.db),
            data_root=Path(args.data_root),
            schema_dir=Path(args.schema_dir),
            mode=selected_mode,
            scopes=args.scope,
        )
    except Exception as exc:
        if args.format == "json":
            print(json.dumps({"status": "validator_error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"VALIDATOR ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_human(report))
    return 1 if report.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
