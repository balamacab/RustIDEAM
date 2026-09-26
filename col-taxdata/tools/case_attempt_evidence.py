from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid


EVIDENCE_SCHEMA_VERSION = 2
SUPPRESSION_CREDENTIAL_MATERIAL = "credential_material_detected"

FAILURE_TRANSPORT = "transport"
FAILURE_PROVIDER_ENVELOPE = "provider_envelope"
FAILURE_JSON_PARSE = "json_parse"
FAILURE_OUTPUT_CEILING = "output_ceiling"
FAILURE_SCHEMA_VALIDATION = "schema_validation"
FAILURE_SEMANTIC_VALIDATION = "semantic_validation"

_DIRECTORY_FSYNC_UNSUPPORTED = {
    errno.EBADF,
    errno.EINVAL,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def utc_audit_now() -> str:
    """Return a stable UTC timestamp for execution-evidence manifests."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_hex(data: bytes) -> str:
    """Return the lowercase SHA-256 digest for exact evidence bytes."""
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically without changing the represented value."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def split_validation_detail(detail: str) -> tuple[str | None, str]:
    """Separate the validator JSON path while retaining its exact message."""
    if detail.startswith("$") and ": " in detail:
        path, message = detail.split(": ", 1)
        return path, message
    return None, detail


@dataclass(frozen=True)
class GenerationEvidence:
    """Provider-neutral evidence observed while producing one model candidate.

    configured_secret_values carries only exact credential values that were
    actually resolved for the outbound request. It is deliberately excluded
    from repr/equality and is consumed only to decide whether evidence bytes
    may be persisted. No generic secret scanning is performed.
    """

    provider_contacted: bool
    provider_request_sha256: str | None = None
    response_schema_sha256: str | None = None
    provider_response_bytes: bytes | None = None
    http_status: int | None = None
    served_model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    assistant_content: str | None = None
    candidate_json_bytes: bytes | None = None
    configured_secret_values: tuple[bytes, ...] = field(
        default_factory=tuple,
        repr=False,
        compare=False,
    )

    @classmethod
    def candidate_only(cls, candidate: Any) -> "GenerationEvidence":
        """Represent a provider-neutral candidate when raw transport is unavailable."""
        try:
            candidate_bytes = canonical_json_bytes(candidate)
        except (TypeError, ValueError):
            candidate_bytes = None
        return cls(
            provider_contacted=True,
            candidate_json_bytes=candidate_bytes,
        )


def _normalized_secrets(values: tuple[bytes, ...]) -> tuple[bytes, ...]:
    """Return deterministic unique non-empty credential byte strings."""
    return tuple(dict.fromkeys(value for value in values if value))


def _contains_configured_secret(data: bytes, secrets: tuple[bytes, ...]) -> bool:
    return any(secret in data for secret in secrets)


def _artifact_record(
    *,
    path: str,
    data: bytes | None,
    encoding: str,
    configured_secrets: tuple[bytes, ...],
) -> tuple[dict[str, Any], bytes | None]:
    """Describe an artifact and suppress exact bytes if they contain a known secret."""
    if data is None:
        return (
            {
                "present": False,
                "persisted": False,
                "path": None,
                "encoding": encoding,
                "sha256": None,
                "size_bytes": 0,
                "suppressed": False,
                "suppression_reason": None,
            },
            None,
        )

    suppressed = _contains_configured_secret(data, configured_secrets)
    record = {
        "present": True,
        "persisted": not suppressed,
        "path": None if suppressed else path,
        "encoding": encoding,
        "sha256": sha256_hex(data),
        "size_bytes": len(data),
        "suppressed": suppressed,
        "suppression_reason": (
            SUPPRESSION_CREDENTIAL_MATERIAL if suppressed else None
        ),
    }
    return record, None if suppressed else data


def _sanitize_manifest_value(
    value: Any,
    configured_secrets: tuple[bytes, ...],
) -> Any:
    """Remove exact configured credentials from non-artifact manifest metadata."""
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if _contains_configured_secret(encoded, configured_secrets):
            return {
                "suppressed": True,
                "suppression_reason": SUPPRESSION_CREDENTIAL_MATERIAL,
            }
        return value
    if isinstance(value, list):
        return [
            _sanitize_manifest_value(item, configured_secrets)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_manifest_value(item, configured_secrets)
            for item in value
        ]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_bytes = key_text.encode("utf-8")
            if _contains_configured_secret(key_bytes, configured_secrets):
                key_text = "suppressed-key-" + sha256_hex(key_bytes)[:16]
            sanitized[key_text] = _sanitize_manifest_value(
                item,
                configured_secrets,
            )
        return sanitized
    return value


def _write_private_new(path: Path, data: bytes) -> None:
    """Create one evidence file exactly once, flush it, and fsync its bytes."""
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # A partial staging file is deliberately left non-canonical for forensic
        # diagnosis. It can never appear under a published ATT-* directory.
        raise


def _fsync_directory(path: Path) -> None:
    """Fsync directory metadata when the platform supports directory fsync."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in _DIRECTORY_FSYNC_UNSUPPORTED:
            return
        raise
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in _DIRECTORY_FSYNC_UNSUPPORTED:
                raise
    finally:
        os.close(fd)


def _publish_staged_attempt(
    *,
    root: Path,
    staging_dir: Path,
    final_dir: Path,
    attempt_id: str,
) -> None:
    """Atomically publish one fully staged attempt without overwriting an ID."""
    lock_digest = sha256_hex(attempt_id.encode("utf-8"))[:32]
    lock_path = root / f".publish-{lock_digest}.lock"
    lock_fd = os.open(
        lock_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        if final_dir.exists():
            raise FileExistsError(
                f"rejected-attempt directory already exists: {final_dir}"
            )
        # staging_dir and final_dir are siblings under root, so rename remains
        # on one filesystem and exposes either no final attempt or a complete one.
        os.rename(staging_dir, final_dir)
        _fsync_directory(root)
    finally:
        os.close(lock_fd)
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


class RejectedStructuringEvidenceStore:
    """Append-only filesystem store for rejected CASE model attempts."""

    def __init__(self, root: Path):
        self.root = root

    def write_rejected_attempt(
        self,
        *,
        attempt_id: str,
        run_reference: str,
        started_at: str,
        ended_at: str,
        case_input_sha256: str,
        request_fingerprints: dict[str, str] | None,
        adapter: str,
        provider: str,
        requested_model: str,
        routing_role: str,
        contract_version: str,
        prompt_template_id: str,
        prompt_template_version: str,
        failure_code: str,
        failure_stage: str,
        failure_path: str | None,
        failure_detail: str,
        generation: GenerationEvidence,
    ) -> Path:
        """Stage, fsync, and atomically publish one rejected attempt.

        Credential secrecy has precedence over exact byte retention. Artifact
        hashes and lengths are computed from the exact in-memory bytes before a
        contaminated artifact is suppressed. Staging directories are explicitly
        non-canonical and are never named ATT-*.
        """
        if not attempt_id.startswith("ATT-") or Path(attempt_id).name != attempt_id:
            raise ValueError("attempt_id must be a single ATT-* path component")

        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        final_dir = self.root / attempt_id
        if final_dir.exists():
            raise FileExistsError(
                f"rejected-attempt directory already exists: {final_dir}"
            )

        staging_dir = self.root / f".staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(mode=0o700)

        configured_secrets = _normalized_secrets(
            generation.configured_secret_values
        )
        provider_response = generation.provider_response_bytes
        assistant_bytes = (
            generation.assistant_content.encode("utf-8")
            if generation.assistant_content is not None
            else None
        )
        candidate_bytes = generation.candidate_json_bytes

        provider_record, provider_to_write = _artifact_record(
            path="provider-response.bin",
            data=provider_response,
            encoding="binary",
            configured_secrets=configured_secrets,
        )
        assistant_record, assistant_to_write = _artifact_record(
            path="assistant-content.txt",
            data=assistant_bytes,
            encoding="utf-8",
            configured_secrets=configured_secrets,
        )
        candidate_record, candidate_to_write = _artifact_record(
            path="candidate.json",
            data=candidate_bytes,
            encoding="utf-8-canonical-json",
            configured_secrets=configured_secrets,
        )

        artifact_records = {
            "provider_response": provider_record,
            "assistant_content": assistant_record,
            "candidate": candidate_record,
        }
        suppressed_artifacts = [
            name
            for name, record in artifact_records.items()
            if record["suppressed"]
        ]

        if provider_to_write is not None:
            _write_private_new(
                staging_dir / provider_record["path"],
                provider_to_write,
            )
        if assistant_to_write is not None:
            _write_private_new(
                staging_dir / assistant_record["path"],
                assistant_to_write,
            )
        if candidate_to_write is not None:
            _write_private_new(
                staging_dir / candidate_record["path"],
                candidate_to_write,
            )

        manifest = {
            "kind": "rejected_structuring_attempt",
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "run_reference": run_reference,
            "started_at": started_at,
            "ended_at": ended_at,
            "case_input_sha256": case_input_sha256,
            "request_fingerprints": request_fingerprints or {},
            "adapter": adapter,
            "provider": provider,
            "requested_model": requested_model,
            "served_model": generation.served_model,
            "routing_role": routing_role,
            "contract_version": contract_version,
            "prompt_template_id": prompt_template_id,
            "prompt_template_version": prompt_template_version,
            "provider_contacted": generation.provider_contacted,
            "provider_request_sha256": generation.provider_request_sha256,
            "response_schema_sha256": generation.response_schema_sha256,
            "http_status": generation.http_status,
            "finish_reason": generation.finish_reason,
            "usage": generation.usage,
            "failure": {
                "code": failure_code,
                "stage": failure_stage,
                "path": failure_path,
                "detail": failure_detail,
            },
            "artifacts": artifact_records,
            "security_boundary": {
                "request_headers_captured": False,
                "response_headers_captured": False,
                "authorization_captured": False,
                "api_key_captured": False,
                "provider_request_body_captured": False,
                "credential_secrecy_precedes_exact_response": True,
                "configured_secret_detection": "exact-runtime-values-only",
                "suppressed_artifacts": suppressed_artifacts,
            },
            "canonical_state": False,
        }
        manifest = _sanitize_manifest_value(manifest, configured_secrets)
        manifest_bytes = canonical_json_bytes(manifest) + b"\n"

        # This backstop prevents any future manifest field from accidentally
        # reintroducing a configured credential after artifact suppression.
        if _contains_configured_secret(manifest_bytes, configured_secrets):
            raise ValueError(
                "credential material remains in rejected-attempt manifest"
            )

        # The manifest is staged last, after every artifact decision is final.
        _write_private_new(staging_dir / "manifest.json", manifest_bytes)
        _fsync_directory(staging_dir)
        _fsync_directory(self.root)

        _publish_staged_attempt(
            root=self.root,
            staging_dir=staging_dir,
            final_dir=final_dir,
            attempt_id=attempt_id,
        )
        return final_dir
