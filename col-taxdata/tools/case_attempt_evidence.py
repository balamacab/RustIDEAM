from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


EVIDENCE_FORMAT_VERSION = 1


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

    provider_request_sha256: str | None = None
    raw_response: bytes | None = None
    finish_reason: Any = None
    usage: Any = None
    assistant_content: str | None = None
    candidate_payload: dict[str, Any] | None = None


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
    """Write immutable, non-canonical evidence for rejected LLM attempts.

    Raw provider bytes and assistant content are stored only beneath the CASE
    runtime artifact root. Request headers and credentials are intentionally
    outside this interface and therefore cannot be captured.
    """

    def __init__(self, root: Path):
        self.root = root

    def record(
        self,
        *,
        attempt_id: str,
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
        attempt_dir = self.root / attempt_id
        # mkdir without exist_ok makes attempt identity immutable: a retry must
        # allocate a new ID rather than overwrite forensic evidence.
        attempt_dir.mkdir(parents=True, exist_ok=False)

        ev = evidence or GenerationEvidence()
        raw_meta = self._write_optional_bytes(
            attempt_dir / "provider-response.bin",
            ev.raw_response,
        )
        content_bytes = (
            ev.assistant_content.encode("utf-8")
            if ev.assistant_content is not None
            else None
        )
        content_meta = self._write_optional_bytes(
            attempt_dir / "assistant-content.txt",
            content_bytes,
        )
        candidate_bytes = (
            deterministic_json_bytes(ev.candidate_payload)
            if ev.candidate_payload is not None
            else None
        )
        candidate_meta = self._write_optional_bytes(
            attempt_dir / "candidate.json",
            candidate_bytes,
        )

        manifest = {
            "kind": "rejected_case_structuring_attempt",
            "evidence_format_version": EVIDENCE_FORMAT_VERSION,
            "canonical": False,
            "attempt_id": attempt_id,
            "case_input_sha256": case_input_sha256,
            "provider_request_sha256": ev.provider_request_sha256,
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
                "finish_reason": ev.finish_reason,
                "usage": ev.usage,
            },
            "artifacts": {
                "provider_response": raw_meta,
                "assistant_content": content_meta,
                "candidate_payload": candidate_meta,
            },
        }
        manifest_path = attempt_dir / "manifest.json"
        with manifest_path.open("xb") as handle:
            handle.write(deterministic_json_bytes(manifest) + b"\n")
        return manifest_path

    @staticmethod
    def _write_optional_bytes(path: Path, value: bytes | None) -> dict[str, Any]:
        if value is None:
            return {
                "present": False,
                "path": None,
                "sha256": None,
                "bytes": 0,
            }
        with path.open("xb") as handle:
            handle.write(value)
        return {
            "present": True,
            "path": path.name,
            "sha256": sha256_bytes(value),
            "bytes": len(value),
        }
