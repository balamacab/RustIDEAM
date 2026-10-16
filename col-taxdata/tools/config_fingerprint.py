"""Deterministic SHA-256 identities for non-secret execution configuration.

Content identities intentionally exclude source paths and timestamps. Unavailable
inputs remain unavailable; they are never silently hashed as empty content.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import stat
from typing import Any


@dataclass(frozen=True)
class ConfigFingerprint:
    """A resolved digest or an explicit, data-free availability status."""

    status: str
    sha256: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "available":
            if self.sha256 is None or self.reason is not None:
                raise ValueError("invalid available fingerprint")
        elif self.status == "unavailable":
            if self.sha256 is not None or self.reason not in {
                "not_found", "not_regular_file", "read_error"
            }:
                raise ValueError("invalid unavailable fingerprint")
        else:
            raise ValueError("invalid fingerprint status")


def fingerprint_bytes(content: bytes) -> ConfigFingerprint:
    """Hash exact bytes, independent of any filename, path or encoding guess."""
    if not isinstance(content, bytes):
        raise TypeError("configuration content must be bytes")
    return ConfigFingerprint("available", hashlib.sha256(content).hexdigest())


def _assert_json_object_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("configuration JSON object keys must be strings")
            _assert_json_object_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_json_object_keys(child)


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON-compatible value using sorted keys and compact UTF-8.

    Reject non-JSON objects and non-finite numbers instead of coercing them.
    Serialization errors are sanitized so credentials are not echoed.
    """
    try:
        _assert_json_object_keys(value)
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("configuration cannot be serialized as canonical JSON") from None


def fingerprint_json(value: Any) -> ConfigFingerprint:
    """Hash canonical JSON bytes without including Python dict insertion order."""
    return fingerprint_bytes(canonical_json_bytes(value))


def fingerprint_file(path: str | Path) -> ConfigFingerprint:
    """Hash a regular file's exact content or report a bounded absent reason.

    Never include the path or underlying OS exception in the public result.
    """
    try:
        p = Path(path)
        info = p.stat()
        if not stat.S_ISREG(info.st_mode):
            return ConfigFingerprint("unavailable", reason="not_regular_file")
        content = p.read_bytes()
    except FileNotFoundError:
        return ConfigFingerprint("unavailable", reason="not_found")
    except (OSError, ValueError, TypeError):
        return ConfigFingerprint("unavailable", reason="read_error")
    return fingerprint_bytes(content)
