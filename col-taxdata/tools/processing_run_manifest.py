"""Deterministic, data-minimal versioned processing-run provenance (#260).

This module serializes caller-supplied execution facts. It never probes a live
host, database, container or Git repository; unknown is distinct from empty.
No configuration bytes, environment mappings, command lines or credentials
are accepted into the manifest. Callers must supply non-sensitive identifiers.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from .config_fingerprint import ConfigFingerprint, canonical_json_bytes
    from .migration_fingerprint import MigrationFingerprint
except ImportError:
    from config_fingerprint import ConfigFingerprint, canonical_json_bytes
    from migration_fingerprint import MigrationFingerprint

KIND = "col-taxdata-processing-run"
SCHEMA_VERSION = 1
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:+-]{0,127}$")
_RUNTIME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+:-]{0,127}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestError(ValueError):
    """Malformed or unverified provenance; error text never reflects input."""


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or not _IDENT.fullmatch(value):
        raise ManifestError(f"invalid {field} identifier")
    return value


def _fact(value: Any, regex: re.Pattern[str], field: str) -> dict[str, Any]:
    if value is None:
        return {"status": "unavailable", "reason": "not_supplied"}
    if type(value) is not str or not regex.fullmatch(value):
        raise ManifestError(f"invalid {field} identity")
    return {"status": "available", "value": value}


def _config(value: ConfigFingerprint) -> dict[str, Any]:
    if not isinstance(value, ConfigFingerprint):
        raise ManifestError("configuration fingerprint required")
    if value.status == "available":
        if not isinstance(value.sha256, str) or not _SHA256.fullmatch(value.sha256):
            raise ManifestError("invalid configuration digest")
        return {"status": "available", "sha256": value.sha256}
    if value.status == "unavailable" and value.reason in {
        "not_found", "not_regular_file", "read_error"
    }:
        return {"status": "unavailable", "reason": value.reason}
    raise ManifestError("invalid configuration status")


def _migrations(value: MigrationFingerprint) -> dict[str, Any]:
    if not isinstance(value, MigrationFingerprint):
        raise ManifestError("migration fingerprint required")
    if value.status == "available":
        if (not isinstance(value.sha256, str) or not _SHA256.fullmatch(value.sha256)
                or type(value.count) is not int or value.count < 0):
            raise ManifestError("invalid migration digest")
        return {"status": "available", "sha256": value.sha256, "count": value.count}
    if value.status in {"unavailable", "inconsistent"}:
        if type(value.reason) is not str or not _IDENT.fullmatch(value.reason):
            raise ManifestError("invalid migration status")
        return {"status": value.status, "reason": value.reason}
    raise ManifestError("invalid migration status")


def make_run_manifest(
    *,
    run_id: str,
    pipeline: str,
    tool_name: str,
    config_fingerprint: ConfigFingerprint,
    migration_fingerprint: MigrationFingerprint,
    tool_version: str | None = None,
    git_commit_sha: str | None = None,
    input_sha256: str | None = None,
    python_version: str | None = None,
    runtime_platform: str | None = None,
    container_digest: str | None = None,
) -> dict[str, Any]:
    """Create a fixed allowlisted JSON record with explicit unknown facts.

    Digests are accepted only from the separate #258/#259 validated types.
    The caller supplies actual execution identifiers; no revision, image or
    input identity is ever silently inferred from the current environment.
    """
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run": {"id": _identifier(run_id, "run"),
                "pipeline": _identifier(pipeline, "pipeline")},
        "tool": {"name": _identifier(tool_name, "tool"),
                 "version": _fact(tool_version, _RUNTIME, "tool version")},
        "source": {"git_commit_sha": _fact(git_commit_sha, _SHA40, "Git commit")},
        "configuration": _config(config_fingerprint),
        "migrations": _migrations(migration_fingerprint),
        "input": {"sha256": _fact(input_sha256, _SHA256, "input")},
        "runtime": {
            "python_version": _fact(python_version, _RUNTIME, "Python version"),
            "platform": _fact(runtime_platform, _RUNTIME, "runtime platform"),
            "container_digest": _fact(container_digest, _IMAGE_DIGEST, "image digest"),
        },
    }


def serialize_run_manifest(**kwargs: Any) -> bytes:
    """Stable UTF-8 canonical bytes, with no timestamps or random fields."""
    return canonical_json_bytes(make_run_manifest(**kwargs)) + b"\n"
