from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from case_bundle_persistence_v4 import (
    BundlePersistenceError,
    load_legal_research_bundle as load_v4_bundle,
    persist_and_materialize_legal_research_bundle as persist_v4_bundle,
)
from case_bundle_persistence_v5 import (
    load_legal_research_bundle as load_v5_bundle,
    persist_and_materialize_legal_research_bundle as persist_v5_bundle,
)
from case_contract_dispatch import V4_CONTRACT_VERSION, V5_CONTRACT_VERSION


UNSUPPORTED_BUNDLE_PERSISTENCE_VERSION = "UNSUPPORTED_BUNDLE_PERSISTENCE_VERSION"


def _unsupported(version: object) -> BundlePersistenceError:
    return BundlePersistenceError(
        f"{UNSUPPORTED_BUNDLE_PERSISTENCE_VERSION}: {version!r}"
    )


def persist_and_materialize_versioned_bundle(
    *,
    db_path: Path,
    case_root: Path,
    case_ref: str,
    bundle: dict[str, Any],
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch durable bundle publication only by explicit contract version."""
    version = bundle.get("contract_version")
    if version == V4_CONTRACT_VERSION:
        return persist_v4_bundle(
            db_path=db_path,
            case_root=case_root,
            case_ref=case_ref,
            bundle=bundle,
            dry_run=dry_run,
        )
    if version == V5_CONTRACT_VERSION:
        return persist_v5_bundle(
            db_path=db_path,
            case_root=case_root,
            case_ref=case_ref,
            bundle=bundle,
            dry_run=dry_run,
        )
    raise _unsupported(version)


def load_versioned_bundle(
    con: sqlite3.Connection,
    *,
    bundle_ref: str,
    contract_version: str,
) -> dict[str, Any]:
    """Load historical state under the version it declared; never coerce it."""
    if contract_version == V4_CONTRACT_VERSION:
        return load_v4_bundle(con, bundle_ref=bundle_ref)
    if contract_version == V5_CONTRACT_VERSION:
        return load_v5_bundle(con, bundle_ref=bundle_ref)
    raise _unsupported(contract_version)
