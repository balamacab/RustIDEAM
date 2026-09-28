#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from case_application import (
    CaseAnalysisIntegrityError,
    ResearchAnalysisOutcome,
    analyze_case,
)
from case_attempt_evidence import RejectedStructuringEvidenceStore
from case_contract_validation_v4 import CONTRACT_VERSION as CASE_CONTRACT_VERSION
from case_intake_factory import build_case_intake_composition
from case_rest_api import (
    API_VERSION,
    DEFAULT_MAX_REQUEST_BYTES,
    CaseRESTApplication,
    CaseRESTServer,
)
from init_db import migrate_database


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "llm" / "local-platform.yaml"
DEFAULT_SCHEMA_DIR = ROOT / "schema"
REQUIRED_V4_MIGRATION = "016_case_v4_bundle_persistence.sql"
REQUIRED_V4_TABLES = frozenset({"case_v4_bundles", "case_v4_artifacts"})
STARTUP_FAILURE = "CASE_REST_RUNTIME_STARTUP_FAILURE"


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None else int(value)


def prepare_case_runtime_database(
    *,
    db_path: Path,
    schema_dir: Path = DEFAULT_SCHEMA_DIR,
) -> dict[str, object]:
    """Bring one writable CASE database to repository schema before serving.

    The normal append-only/hash-checked migration engine remains the authority.
    Explicit v4 checks turn missing/incomplete schema into a startup failure
    instead of allowing the first valid request to discover it in persistence.
    """
    migration = migrate_database(
        db_path=db_path,
        schema_dir=schema_dir,
        emit=None,
    )

    con = sqlite3.connect(db_path)
    try:
        recorded = {
            row[0]
            for row in con.execute(
                "SELECT schema_name FROM schema_metadata"
            )
        }
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        con.close()

    if REQUIRED_V4_MIGRATION not in recorded:
        raise RuntimeError(
            "CASE v4 persistence migration is not recorded after bootstrap: "
            + REQUIRED_V4_MIGRATION
        )
    missing_tables = sorted(REQUIRED_V4_TABLES - tables)
    if missing_tables:
        raise RuntimeError(
            "CASE v4 persistence schema is incomplete after bootstrap; "
            "missing table(s): " + ", ".join(missing_tables)
        )

    return {
        "applied": list(migration["applied"]),
        "already_applied": list(migration["already_applied"]),
        "required_migration": REQUIRED_V4_MIGRATION,
        "required_tables": sorted(REQUIRED_V4_TABLES),
    }


def build_runtime_application(
    *,
    db_path: Path,
    case_root: Path,
    config_path: Path,
    dry_run: bool,
) -> tuple[CaseRESTApplication, str, str]:
    """Compose the evidence-first CASE v4 application behind REST v1."""
    evidence_store = RejectedStructuringEvidenceStore(
        case_root / "_audit" / "rejected-structuring-attempts"
    )
    composition = build_case_intake_composition(
        config_path,
        evidence_store=evidence_store,
    )

    def researcher(
        case_input: dict[str, Any],
        *,
        request_fingerprints: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        outcome = analyze_case(
            case_input=case_input,
            db_path=db_path,
            case_root=case_root,
            structurer=composition.structurer,
            dry_run=dry_run,
            include_debug_provenance=False,
            request_fingerprints=request_fingerprints,
        )
        if not isinstance(outcome, ResearchAnalysisOutcome):
            raise CaseAnalysisIntegrityError(
                "REST v1 runtime received a non-v4 CASE analysis outcome"
            )
        return outcome.bundle

    return (
        CaseRESTApplication(
            researcher,
            forward_request_fingerprints=True,
        ),
        composition.provider,
        composition.primary_model,
    )


def _startup_failure(stage: str, exc: Exception) -> int:
    print(
        json.dumps(
            {
                "event": "case_rest_runtime_startup",
                "status": "FAIL",
                "error": STARTUP_FAILURE,
                "stage": stage,
                "detail": str(exc),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
        flush=True,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Start the writable CASE v4 / REST v1 runtime after applying and "
            "verifying the repository SQLite migration set."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("COL_TAXDATA_REST_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("COL_TAXDATA_REST_PORT", 8765),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get(
            "COL_TAXDATA_DB",
            "data/state/taxdata.sqlite",
        ),
    )
    parser.add_argument(
        "--case-root",
        default=os.environ.get("COL_TAXDATA_CASE_ROOT", "data/cases"),
    )
    parser.add_argument(
        "--config",
        default=os.environ.get(
            "COL_TAXDATA_LLM_CONFIG",
            str(DEFAULT_CONFIG),
        ),
    )
    parser.add_argument(
        "--schema-dir",
        default=os.environ.get(
            "COL_TAXDATA_SCHEMA_DIR",
            str(DEFAULT_SCHEMA_DIR),
        ),
    )
    parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=_env_int(
            "COL_TAXDATA_REST_MAX_REQUEST_BYTES",
            DEFAULT_MAX_REQUEST_BYTES,
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview CASE bundle persistence/materialization after schema "
            "bootstrap. Schema migrations still apply to the configured "
            "writable database."
        ),
    )
    args = parser.parse_args()

    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if args.max_request_bytes < 1:
        parser.error("--max-request-bytes must be positive")

    db_path = Path(args.db)
    case_root = Path(args.case_root)

    try:
        application, provider, model = build_runtime_application(
            db_path=db_path,
            case_root=case_root,
            config_path=Path(args.config),
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _startup_failure("configuration", exc)

    try:
        schema = prepare_case_runtime_database(
            db_path=db_path,
            schema_dir=Path(args.schema_dir),
        )
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _startup_failure("schema_migration", exc)

    try:
        server = CaseRESTServer(
            (args.host, args.port),
            application,
            max_request_bytes=args.max_request_bytes,
        )
    except (OSError, ValueError) as exc:
        return _startup_failure("bind", exc)

    host, port = server.server_address[:2]
    print(
        json.dumps(
            {
                "event": "case_rest_runtime_ready",
                "status": "READY",
                "case_contract_version": CASE_CONTRACT_VERSION,
                "rest_api_version": API_VERSION,
                "host": host,
                "port": port,
                "provider": provider,
                "model": model,
                "schema": schema,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
