from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


EVIDENCE_FORMAT_VERSION = 2


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def deterministic_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class GenerationEvidence:
    """Lossless provider-return evidence carried to the CASE trust boundary."""

    provider_request_attempted: bool = False
    provider_request_sha256: str | None = None
    http_status: int | None = None
    served_model: Any = None
    raw_response: bytes | None = None
    finish_reason: Any = None
    usage: Any = None
    assistant_content: str | None = None
    candidate_payload: dict[str, Any] | None = None
    candidate_json: bytes | None = None
    payload_omission_reason: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    """Parsed candidate plus provider evidence; candidate is still untrusted."""

    payload: dict[str, Any]
    evidence: GenerationEvidence

    def __getitem__(self, key: str) -> Any:
        """Preserve legacy adapter callers that index the returned candidate."""
        return self.payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self.payload


class RejectedAttemptEvidenceStore:
    """Atomically publish immutable, non-canonical rejected-attempt evidence.

    Each complete attempt is assembled in a private staging directory and then
    atomically renamed into its final create-once path. Request/response headers
    and credentials are intentionally outside this interface.
    """

    def __init__(self, root: Path):
        self.root = root

    def record(
        self,
        *,
        attempt_id: str,
        raw_request_sha256: str | None,
        case_input_sha256: str,
        adapter: str,
        provider: str,
        model: str,
        routing_role: str,
        contract_version: str,
        prompt_template_id: str,
        prompt_template_version: str,
        schema_version: str,
        started_at: str,
        ended_at: str,
        failure_stage: str,
        failure_code: str,
        failure_detail: str,
        failure_path: str | None,
        evidence: GenerationEvidence | None,
    ) -> Path:
        self._validate_attempt_id(attempt_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt_dir = self.root / attempt_id
        if attempt_dir.exists():
            raise FileExistsError(f"attempt evidence already exists: {attempt_id}")

        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{attempt_id}.tmp-",
                dir=self.root,
            )
        )
        try:
            os.chmod(staging_dir, 0o700)
            ev = evidence or GenerationEvidence()
            raw_meta = self._write_optional_bytes(
                staging_dir / "provider-response.bin",
                ev.raw_response,
            )
            content_bytes = (
                ev.assistant_content.encode("utf-8")
                if ev.assistant_content is not None
                else None
            )
            content_meta = self._write_optional_bytes(
                staging_dir / "assistant-content.txt",
                content_bytes,
            )
            if ev.candidate_json is not None:
                candidate_bytes = ev.candidate_json
            elif ev.candidate_payload is not None:
                candidate_bytes = deterministic_json_bytes(ev.candidate_payload)
            else:
                candidate_bytes = None
            candidate_meta = self._write_optional_bytes(
                staging_dir / "candidate.json",
                candidate_bytes,
            )

            manifest = {
                "kind": "rejected_case_structuring_attempt",
                "evidence_format_version": EVIDENCE_FORMAT_VERSION,
                "canonical": False,
                "attempt_id": attempt_id,
                "request_fingerprints": {
                    "raw_request_sha256": raw_request_sha256,
                    "case_input_sha256": case_input_sha256,
                    "provider_request_sha256": ev.provider_request_sha256,
                },
                # Retained as top-level compatibility fields for existing audit
                # consumers while request_fingerprints is the authoritative group.
                "raw_request_sha256": raw_request_sha256,
                "case_input_sha256": case_input_sha256,
                "provider_request_sha256": ev.provider_request_sha256,
                "provider_request_attempted": ev.provider_request_attempted,
                "adapter": adapter,
                "provider": provider,
                "model": model,
                "routing_role": routing_role,
                "contract_version": contract_version,
                "schema_version": schema_version,
                "prompt_template_id": prompt_template_id,
                "prompt_template_version": prompt_template_version,
                "started_at": started_at,
                "ended_at": ended_at,
                "failure": {
                    "stage": failure_stage,
                    "code": failure_code,
                    "path": failure_path,
                    "detail": failure_detail,
                },
                "provider": {
                    "http_status": ev.http_status,
                    "served_model": ev.served_model,
                    "finish_reason": ev.finish_reason,
                    "usage": ev.usage,
                    "payload_omission_reason": ev.payload_omission_reason,
                },
                "artifacts": {
                    "provider_response": raw_meta,
                    "assistant_content": content_meta,
                    "candidate_payload": candidate_meta,
                },
            }
            manifest_path = staging_dir / "manifest.json"
            self._write_bytes(
                manifest_path,
                deterministic_json_bytes(manifest) + b"\n",
            )
            self._fsync_directory(staging_dir)

            try:
                os.rename(staging_dir, attempt_dir)
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                    raise FileExistsError(
                        f"attempt evidence already exists: {attempt_id}"
                    ) from exc
                raise
            self._fsync_directory(self.root)
            return attempt_dir / "manifest.json"
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    @staticmethod
    def _validate_attempt_id(attempt_id: str) -> None:
        if (
            not attempt_id
            or attempt_id in {".", ".."}
            or Path(attempt_id).name != attempt_id
            or "/" in attempt_id
            or "\\" in attempt_id
        ):
            raise ValueError("attempt_id must be a single safe path component")

    @staticmethod
    def _write_bytes(path: Path, value: bytes) -> None:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())

    @classmethod
    def _write_optional_bytes(
        cls,
        path: Path,
        value: bytes | None,
    ) -> dict[str, Any]:
        if value is None:
            return {
                "present": False,
                "path": None,
                "sha256": None,
                "bytes": 0,
            }
        cls._write_bytes(path, value)
        return {
            "present": True,
            "path": path.name,
            "sha256": sha256_bytes(value),
            "bytes": len(value),
        }

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
