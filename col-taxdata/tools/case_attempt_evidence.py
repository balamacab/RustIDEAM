from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


EVIDENCE_SCHEMA_VERSION = 1

FAILURE_TRANSPORT = "transport"
FAILURE_PROVIDER_ENVELOPE = "provider_envelope"
FAILURE_JSON_PARSE = "json_parse"
FAILURE_OUTPUT_CEILING = "output_ceiling"
FAILURE_SCHEMA_VALIDATION = "schema_validation"
FAILURE_SEMANTIC_VALIDATION = "semantic_validation"


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

    This object intentionally contains no request headers, authorization material,
    API keys, or provider response headers. provider_response_bytes is the exact
    HTTP response body when one was received.
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


def _artifact_record(
    *,
    path: str,
    data: bytes | None,
    encoding: str,
) -> dict[str, Any]:
    if data is None:
        return {
            "present": False,
            "path": None,
            "encoding": encoding,
            "sha256": None,
            "size_bytes": 0,
        }
    return {
        "present": True,
        "path": path,
        "encoding": encoding,
        "sha256": sha256_hex(data),
        "size_bytes": len(data),
    }


def _write_private_new(path: Path, data: bytes) -> None:
    """Create one evidence file exactly once with owner-only permissions."""
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
        # Retain a partial file rather than silently destroying evidence of a
        # failed persistence attempt. The attempt directory is never reused.
        raise


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
        """Persist a rejected attempt exactly once and return its directory.

        The manifest is written last. Existing attempt directories are never
        overwritten, so retries must use distinct attempt identifiers.
        """
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt_dir = self.root / attempt_id
        attempt_dir.mkdir(mode=0o700)

        provider_response = generation.provider_response_bytes
        assistant_bytes = (
            generation.assistant_content.encode("utf-8")
            if generation.assistant_content is not None
            else None
        )
        candidate_bytes = generation.candidate_json_bytes

        provider_record = _artifact_record(
            path="provider-response.bin",
            data=provider_response,
            encoding="binary",
        )
        assistant_record = _artifact_record(
            path="assistant-content.txt",
            data=assistant_bytes,
            encoding="utf-8",
        )
        candidate_record = _artifact_record(
            path="candidate.json",
            data=candidate_bytes,
            encoding="utf-8-canonical-json",
        )

        if provider_response is not None:
            _write_private_new(
                attempt_dir / provider_record["path"],
                provider_response,
            )
        if assistant_bytes is not None:
            _write_private_new(
                attempt_dir / assistant_record["path"],
                assistant_bytes,
            )
        if candidate_bytes is not None:
            _write_private_new(
                attempt_dir / candidate_record["path"],
                candidate_bytes,
            )

        manifest = {
            "kind": "rejected_structuring_attempt",
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "run_reference": run_reference,
            "started_at": started_at,
            "ended_at": ended_at,
            "case_input_sha256": case_input_sha256,
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
            "artifacts": {
                "provider_response": provider_record,
                "assistant_content": assistant_record,
                "candidate": candidate_record,
            },
            "security_boundary": {
                "request_headers_captured": False,
                "response_headers_captured": False,
                "authorization_captured": False,
                "api_key_captured": False,
                "provider_request_body_captured": False,
            },
            "canonical_state": False,
        }
        _write_private_new(
            attempt_dir / "manifest.json",
            canonical_json_bytes(manifest) + b"\n",
        )
        return attempt_dir
