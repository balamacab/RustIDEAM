"""Read-only, deterministic fingerprints of *ordered applied* migrations.

`schema_metadata` does not store an ordinal. Never infer migration order
from SQLite rowid or applied_at; the caller must supply authoritative order.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePath
import re
import sqlite3
from typing import Sequence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MigrationFingerprint:
    """Digest if known, otherwise a precise, non-sensitive failure classification."""

    status: str
    sha256: str | None = None
    count: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "available":
            if self.sha256 is None or not _SHA256.fullmatch(self.sha256):
                raise ValueError("invalid available fingerprint")
            if self.reason is not None or self.count is None or self.count < 0:
                raise ValueError("invalid available fingerprint")
        elif self.status in {"unavailable", "inconsistent"}:
            if self.sha256 is not None or self.count is not None or not self.reason:
                raise ValueError("invalid unavailable fingerprint")
        else:
            raise ValueError("invalid fingerprint status")


def _unavailable(reason: str) -> MigrationFingerprint:
    return MigrationFingerprint("unavailable", reason=reason)


def _inconsistent(reason: str) -> MigrationFingerprint:
    return MigrationFingerprint("inconsistent", reason=reason)


def _valid_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and name.endswith(".sql")
        and name not in {".", ".."}
        and PurePath(name).name == name
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
    )


def fingerprint_applied_migrations(
    ordered_migrations: Sequence[tuple[str, str]] | None,
) -> MigrationFingerprint:
    """Hash canonical JSON of ordered (migration filename, recorded SHA-256) pairs.

    None means order/state is unknown, *not* an empty migration sequence.
    Records must be supplied in the verified historical order, not a set,
    SQLite query result without ORDER BY, or a silently sorted list.
    """
    if ordered_migrations is None:
        return _unavailable("ordered_migrations_unavailable")
    if not isinstance(ordered_migrations, (tuple, list)):
        return _inconsistent("invalid_migration_sequence")
    canonical: list[list[str]] = []
    seen: set[str] = set()
    for pair in ordered_migrations:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            return _inconsistent("invalid_migration_record")
        name, digest = pair
        if not _valid_name(name):
            return _inconsistent("invalid_migration_name")
        if name in seen:
            return _inconsistent("duplicate_migration")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            return _inconsistent("invalid_migration_sha256")
        seen.add(name)
        canonical.append([name, digest])
    # Domain/version separation prevents confusing this identity with raw
    # config hashes, byte hashes or a future version of the schema.
    payload = {
        "kind": "col-taxdata-applied-migrations",
        "version": 1,
        "ordered": canonical,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return MigrationFingerprint(
        "available", sha256=hashlib.sha256(encoded).hexdigest(),
        count=len(canonical),
    )


def fingerprint_schema_metadata(
    connection: sqlite3.Connection,
    *,
    applied_order: Sequence[str] | None,
) -> MigrationFingerprint:
    """Read existing SQLite schema_metadata without mutating it.

    applied_order must be the *exact*, externally verified ordered set of
    applied migration names. SQLite metadata has no ordinal, so an absent
    applied_order is explicitly unavailable. Extra/missing/duplicate DB rows
    are inconsistent, rather than silently sorted or interpreted by time.
    """
    if applied_order is None:
        return _unavailable("applied_order_unavailable")
    if not isinstance(applied_order, (tuple, list)):
        return _inconsistent("invalid_applied_order")
    if any(not _valid_name(name) for name in applied_order):
        return _inconsistent("invalid_migration_name")
    if len(set(applied_order)) != len(applied_order):
        return _inconsistent("duplicate_applied_order")

    try:
        rows = connection.execute(
            "SELECT schema_name, schema_sha256 FROM schema_metadata"
        ).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return _unavailable("schema_metadata_unavailable")

    by_name: dict[str, str] = {}
    for row in rows:
        if len(row) != 2 or not _valid_name(row[0]):
            return _inconsistent("invalid_schema_metadata")
        name, digest = row
        if name in by_name:
            return _inconsistent("duplicate_migration")
        by_name[name] = digest

    if set(by_name) != set(applied_order):
        return _inconsistent("applied_migration_set_mismatch")
    return fingerprint_applied_migrations(
        [(name, by_name[name]) for name in applied_order]
    )
