from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_attempt_evidence import deterministic_json_bytes
from case_contract_validation import CaseContractError, INVALID_CASE_DRAFT
from case_http import error_response
from llm_client import (
    CASE_OUTPUT_LIMIT,
    CASE_PROVIDER_TIMEOUT,
    CaseStructuringService,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
)


PROBLEM = "La sociedad está en liquidación."
CASE_INPUT = {
    "kind": "case_input",
    "contract_version": "3.0.0",
    "problem_text": PROBLEM,
}


def config(*, attempts: int = 1, api_key_env: str | None = None) -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://provider.invalid/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("test-model", "primary", 100_000, 1024),
        auxiliary=None,
        review=None,
        primary_attempts=attempts,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=api_key_env,
    )


def valid_payload() -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
        "facts": [],
        "questions": [],
        "candidate_claims": [],
        "unresolved": [],
    }


def envelope_bytes(content: str, *, finish_reason: str = "stop", usage: dict | None = None) -> bytes:
    return json.dumps(
        {
            "model": "test-model",
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ],
            "usage": usage or {"completion_tokens": 10},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class Response:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def manifests(root: Path) -> list[Path]:
    return sorted(root.glob("attempt-*/manifest.json"))


class Issue0090RejectedEvidenceTests(unittest.TestCase):
    def _service(self, root: Path, *, cfg: LLMPlatformConfig | None = None):
        selected = cfg or config()
        return CaseStructuringService(
            selected,
            OpenAICompatibleLLMClient(selected),
            evidence_root=root,
        )

    def test_semantic_rejection_preserves_exact_provider_output_and_candidate(self):
        payload = valid_payload()
        payload["facts"] = [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:bad",
                "label": "Estado",
                "value": "liquidación",
                "state": "user_provided",
                "source_quote": "texto inexistente",
                "requires_confirmation": False,
            }
        ]
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        raw = envelope_bytes(content)

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(CaseContractError) as raised:
                self._service(root).structure(CASE_INPUT)

            self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
            items = manifests(root)
            self.assertEqual(len(items), 1)
            manifest = json.loads(items[0].read_text(encoding="utf-8"))
            attempt_dir = items[0].parent
            self.assertFalse(manifest["canonical"])
            self.assertEqual(manifest["failure"]["stage"], "semantic_validation")
            self.assertEqual(manifest["failure"]["path"], "$.facts[0].source_quote")
            self.assertEqual(
                (attempt_dir / "provider-response.bin").read_bytes(),
                raw,
            )
            self.assertEqual(
                manifest["artifacts"]["provider_response"]["sha256"],
                hashlib.sha256(raw).hexdigest(),
            )
            candidate_bytes = (attempt_dir / "candidate.json").read_bytes()
            self.assertEqual(candidate_bytes, deterministic_json_bytes(payload))
            self.assertEqual(
                manifest["artifacts"]["candidate_payload"]["sha256"],
                hashlib.sha256(candidate_bytes).hexdigest(),
            )

    def test_malformed_json_preserves_raw_and_assistant_content(self):
        content = '{"kind":"case_draft"'
        raw = envelope_bytes(content)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError):
                self._service(root).structure(CASE_INPUT)
            manifest_path = manifests(root)[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["failure"]["stage"], "json_parse")
            self.assertEqual(
                (manifest_path.parent / "provider-response.bin").read_bytes(),
                raw,
            )
            self.assertEqual(
                (manifest_path.parent / "assistant-content.txt").read_text("utf-8"),
                content,
            )

    def test_malformed_provider_envelope_preserves_available_raw_bytes(self):
        raw = b'{"unexpected":true}'
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError):
                self._service(root).structure(CASE_INPUT)
            manifest_path = manifests(root)[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["failure"]["stage"],
                "provider_envelope_parse",
            )
            self.assertEqual(
                (manifest_path.parent / "provider-response.bin").read_bytes(),
                raw,
            )

    def test_timeout_records_explicit_absence_without_fabricated_response(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            side_effect=TimeoutError("provider timeout"),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError) as raised:
                self._service(root).structure(CASE_INPUT)
            self.assertEqual(raised.exception.code, CASE_PROVIDER_TIMEOUT)
            manifest = json.loads(manifests(root)[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["failure"]["stage"], "transport")
            self.assertFalse(manifest["artifacts"]["provider_response"]["present"])
            self.assertIsNone(manifest["artifacts"]["provider_response"]["sha256"])

    def test_output_ceiling_preserves_response_finish_reason_and_usage(self):
        raw = envelope_bytes(
            json.dumps(valid_payload()),
            finish_reason="length",
            usage={"completion_tokens": 1024, "prompt_tokens": 50},
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError) as raised:
                self._service(root).structure(CASE_INPUT)
            self.assertEqual(raised.exception.code, CASE_OUTPUT_LIMIT)
            manifest = json.loads(manifests(root)[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["failure"]["stage"], "output_ceiling")
            self.assertEqual(manifest["provider"]["finish_reason"], "length")
            self.assertEqual(manifest["provider"]["usage"]["completion_tokens"], 1024)

    def test_valid_draft_creates_no_rejected_artifact(self):
        raw = envelope_bytes(json.dumps(valid_payload()))
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            outcome = self._service(root).structure(CASE_INPUT)
            self.assertEqual(outcome.draft["kind"], "case_draft")
            self.assertEqual(manifests(root), [])

    def test_retries_create_distinct_immutable_attempt_directories(self):
        content = '{"bad"'
        raw = envelope_bytes(content)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError):
                self._service(root, cfg=config(attempts=2)).structure(CASE_INPUT)
            items = manifests(root)
            self.assertEqual(len(items), 2)
            self.assertNotEqual(items[0].parent.name, items[1].parent.name)
            before = [path.read_bytes() for path in items]
            self.assertEqual(before, [path.read_bytes() for path in items])

    def test_http_error_and_audit_manifest_do_not_leak_raw_content_or_api_key(self):
        secret = "super-secret-api-key"
        invalid = valid_payload()
        invalid["problem_text"] = "model changed client text"
        raw = envelope_bytes(json.dumps(invalid))
        cfg = config(api_key_env="ISSUE90_TEST_KEY")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"ISSUE90_TEST_KEY": secret},
        ), mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(CaseContractError) as raised:
                self._service(root, cfg=cfg).structure(CASE_INPUT)
            response = error_response(raised.exception)
            serialized_error = json.dumps(response.payload, ensure_ascii=False)
            self.assertNotIn(raw.decode("utf-8"), serialized_error)
            self.assertNotIn(secret, serialized_error)

            manifest_path = manifests(root)[0]
            manifest_bytes = manifest_path.read_bytes()
            self.assertNotIn(secret.encode("utf-8"), manifest_bytes)
            self.assertNotIn(b"Authorization", manifest_bytes)

    def test_failed_structuring_writes_only_noncanonical_audit_artifacts(self):
        raw = envelope_bytes('{"bad"')
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp)
            evidence_root = root / "_audit" / "rejected-structuring-attempts"
            with self.assertRaises(LLMClientError):
                self._service(evidence_root).structure(CASE_INPUT)
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["_audit"],
            )
            manifest = json.loads(manifests(evidence_root)[0].read_text("utf-8"))
            self.assertEqual(manifest["kind"], "rejected_case_structuring_attempt")
            self.assertFalse(manifest["canonical"])


if __name__ == "__main__":
    unittest.main()
