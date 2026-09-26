from __future__ import annotations

from dataclasses import replace
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

from case_application import analyze_case
from case_attempt_evidence import (
    FAILURE_JSON_PARSE,
    FAILURE_OUTPUT_CEILING,
    FAILURE_PROVIDER_ENVELOPE,
    FAILURE_SCHEMA_VALIDATION,
    FAILURE_SEMANTIC_VALIDATION,
    FAILURE_TRANSPORT,
    RejectedStructuringEvidenceStore,
    canonical_json_bytes,
)
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
    OutputLimitError,
)


PROBLEM = (
    "La sociedad está en liquidación y solicita saber qué requisitos debe "
    "cumplir para cancelar su registro tributario."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
    }


def valid_payload() -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
        "facts": [],
        "questions": [],
        "candidate_claims": [
            {
                "kind": "candidate_claim",
                "contract_version": "3.0.0",
                "claim_ref": "claim:main",
                "text": (
                    "La cancelación exige revisar previamente las obligaciones "
                    "tributarias pendientes."
                ),
                "status": "candidate",
                "requires_canonical_validation": True,
                "target_hints": ["cancelación registro tributario"],
            }
        ],
        "unresolved": [],
    }


def semantic_invalid_payload() -> dict:
    payload = valid_payload()
    payload["candidate_claims"][0]["target_hints"] = ["DOC-forged"]
    return payload


def make_config(
    *,
    primary_attempts: int = 1,
    api_key_env: str | None = None,
) -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("primary-model", "primary", 100_000, 1024),
        auxiliary=None,
        review=None,
        primary_attempts=primary_attempts,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=api_key_env,
    )


def envelope_bytes(
    content: str,
    *,
    finish_reason: str = "stop",
    usage: dict | None = None,
    extra: dict | None = None,
) -> bytes:
    envelope = {
        "model": "primary-model",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ],
        "usage": usage or {"completion_tokens": 17, "prompt_tokens": 41},
    }
    if extra:
        envelope.update(extra)
    return json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class Response:
    def __init__(self, raw: bytes, status: int = 200):
        self.raw = raw
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def attempt_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def read_manifest(attempt_dir: Path) -> dict:
    return json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))


class Issue0090RejectedLLMOutputEvidenceTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        *,
        config: LLMPlatformConfig | None = None,
    ) -> CaseStructuringService:
        config = config or make_config()
        return CaseStructuringService(
            config,
            OpenAICompatibleLLMClient(config),
            evidence_store=RejectedStructuringEvidenceStore(root),
        )

    def test_semantic_rejection_preserves_exact_provider_output_and_hashes(self):
        candidate = semantic_invalid_payload()
        content = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        raw = envelope_bytes(content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            service = self._service(root)
            input_sha = hashlib.sha256(
                canonical_json_bytes(case_input())
            ).hexdigest()
            request_fingerprints = {
                "raw_request_sha256": "a" * 64,
                "case_input_sha256": input_sha,
            }
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError) as raised:
                    service.structure(
                        case_input(),
                        request_fingerprints=request_fingerprints,
                    )

            self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)

            self.assertEqual(
                (attempt / "provider-response.bin").read_bytes(),
                raw,
            )
            self.assertEqual(
                (attempt / "assistant-content.txt").read_text(encoding="utf-8"),
                content,
            )
            stored_candidate = (attempt / "candidate.json").read_bytes()
            self.assertEqual(stored_candidate, canonical_json_bytes(candidate))
            for name, filename in (
                ("provider_response", "provider-response.bin"),
                ("assistant_content", "assistant-content.txt"),
                ("candidate", "candidate.json"),
            ):
                data = (attempt / filename).read_bytes()
                self.assertEqual(
                    hashlib.sha256(data).hexdigest(),
                    manifest["artifacts"][name]["sha256"],
                )
            self.assertEqual(
                manifest["failure"]["stage"],
                FAILURE_SEMANTIC_VALIDATION,
            )
            self.assertEqual(
                manifest["failure"]["path"],
                "$.candidate_claims[0].target_hints",
            )
            self.assertEqual(
                manifest["failure"]["detail"],
                raised.exception.detail,
            )
            self.assertEqual(manifest["failure"]["code"], INVALID_CASE_DRAFT)
            self.assertEqual(manifest["adapter"], "openai-compatible")
            self.assertEqual(manifest["provider"], "test-provider")
            self.assertEqual(manifest["requested_model"], "primary-model")
            self.assertEqual(manifest["contract_version"], "3.0.0")
            self.assertEqual(manifest["prompt_template_id"], "case-structuring-v3")
            self.assertTrue(manifest["provider_request_sha256"])
            self.assertTrue(manifest["response_schema_sha256"])
            self.assertEqual(manifest["case_input_sha256"], input_sha)
            self.assertEqual(
                manifest["request_fingerprints"],
                request_fingerprints,
            )
            self.assertFalse(manifest["canonical_state"])

    def test_malformed_assistant_json_preserves_raw_bytes(self):
        raw = envelope_bytes('{"kind":"case_draft"')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(LLMClientError):
                    self._service(root).structure(case_input())

            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)
            self.assertEqual(manifest["failure"]["stage"], FAILURE_JSON_PARSE)
            self.assertEqual(
                (attempt / "provider-response.bin").read_bytes(),
                raw,
            )
            self.assertTrue(manifest["artifacts"]["assistant_content"]["present"])
            self.assertFalse(manifest["artifacts"]["candidate"]["present"])

    def test_malformed_provider_envelope_preserves_available_raw_response(self):
        raw = b'{"model":"primary-model","choices":[{}],"usage":{"completion_tokens":3}}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(LLMClientError):
                    self._service(root).structure(case_input())

            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)
            self.assertEqual(
                manifest["failure"]["stage"],
                FAILURE_PROVIDER_ENVELOPE,
            )
            self.assertEqual(
                (attempt / "provider-response.bin").read_bytes(),
                raw,
            )
            self.assertFalse(manifest["artifacts"]["assistant_content"]["present"])

    def test_timeout_records_explicit_absence_without_fabricating_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                side_effect=TimeoutError("provider stalled"),
            ):
                with self.assertRaises(LLMClientError) as raised:
                    self._service(root).structure(case_input())

            self.assertEqual(raised.exception.code, CASE_PROVIDER_TIMEOUT)
            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)
            self.assertEqual(manifest["failure"]["stage"], FAILURE_TRANSPORT)
            self.assertTrue(manifest["provider_contacted"])
            self.assertFalse(manifest["artifacts"]["provider_response"]["present"])
            self.assertFalse((attempt / "provider-response.bin").exists())

    def test_output_ceiling_preserves_response_finish_reason_and_usage(self):
        config = make_config()
        usage = {"completion_tokens": config.primary.max_output_tokens}
        raw = envelope_bytes(
            "{}",
            finish_reason="stop",
            usage=usage,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(OutputLimitError) as raised:
                    self._service(root, config=config).structure(case_input())

            self.assertEqual(raised.exception.code, CASE_OUTPUT_LIMIT)
            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)
            self.assertEqual(
                manifest["failure"]["stage"],
                FAILURE_OUTPUT_CEILING,
            )
            self.assertEqual(manifest["finish_reason"], "stop")
            self.assertEqual(manifest["usage"], usage)
            self.assertEqual(
                (attempt / "provider-response.bin").read_bytes(),
                raw,
            )

    def test_schema_rejection_is_classified_after_authoritative_validation(self):
        candidate = valid_payload()
        candidate["facts"] = "not-an-array"
        raw = envelope_bytes(json.dumps(candidate, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root).structure(case_input())

            [attempt] = attempt_dirs(root)
            manifest = read_manifest(attempt)
            self.assertEqual(
                manifest["failure"]["stage"],
                FAILURE_SCHEMA_VALIDATION,
            )
            self.assertTrue(manifest["failure"]["path"].startswith("$.facts"))

    def test_valid_accepted_draft_is_not_mislabeled_as_rejected_evidence(self):
        raw = envelope_bytes(json.dumps(valid_payload(), ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                outcome = self._service(root).structure(case_input())

            self.assertEqual(outcome.draft["kind"], "case_draft")
            self.assertEqual(attempt_dirs(root), [])
            self.assertNotIn("generation_evidence", outcome.draft)

    def test_failed_structuring_does_not_mutate_case_or_corpus_state(self):
        raw = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False)
        )
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            root = temp / "cases"
            db_path = temp / "corpus.sqlite"
            audit = root / "_audit" / "rejected-structuring-attempts"
            service = self._service(audit)
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    analyze_case(
                        case_input=case_input(),
                        db_path=db_path,
                        case_root=root,
                        structurer=service,
                    )

            self.assertFalse(db_path.exists())
            self.assertEqual(len(attempt_dirs(audit)), 1)
            non_audit_children = [
                path for path in root.iterdir() if path.name != "_audit"
            ]
            self.assertEqual(non_audit_children, [])

    def test_retries_use_distinct_immutable_attempt_artifacts(self):
        config = make_config(primary_attempts=2)
        raw_one = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False),
            extra={"request_tag": "first"},
        )
        raw_two = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False),
            extra={"request_tag": "second"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                side_effect=[Response(raw_one), Response(raw_two)],
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root, config=config).structure(case_input())

            attempts = attempt_dirs(root)
            self.assertEqual(len(attempts), 2)
            self.assertNotEqual(attempts[0].name, attempts[1].name)
            provider_bodies = {
                (path / "provider-response.bin").read_bytes() for path in attempts
            }
            self.assertEqual(provider_bodies, {raw_one, raw_two})
            snapshots = {
                path.name: {
                    file.name: file.read_bytes()
                    for file in path.iterdir()
                    if file.is_file()
                }
                for path in attempts
            }
            self.assertEqual(
                snapshots,
                {
                    path.name: {
                        file.name: file.read_bytes()
                        for file in path.iterdir()
                        if file.is_file()
                    }
                    for path in attempts
                },
            )

    def test_successful_retry_has_distinct_run_identity_and_keeps_failed_artifact(self):
        config = make_config(primary_attempts=2)
        bad_raw = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False)
        )
        good_raw = envelope_bytes(json.dumps(valid_payload(), ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                side_effect=[Response(bad_raw), Response(good_raw)],
            ):
                outcome = self._service(root, config=config).structure(case_input())

            [failed_attempt] = attempt_dirs(root)
            failed_manifest = read_manifest(failed_attempt)
            self.assertNotEqual(
                failed_manifest["run_reference"],
                outcome.draft["model_metadata"]["run_reference"],
            )
            self.assertEqual(
                (failed_attempt / "provider-response.bin").read_bytes(),
                bad_raw,
            )

    def test_http_error_response_does_not_leak_rejected_provider_content(self):
        marker = "RAW-REJECTED-CONTENT-MUST-NOT-LEAK"
        raw = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False),
            extra={"provider_debug": marker},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError) as raised:
                    self._service(root).structure(case_input())

            response = error_response(raised.exception)
            serialized = json.dumps(response.payload, ensure_ascii=False)
            self.assertNotIn(marker, serialized)
            [attempt] = attempt_dirs(root)
            self.assertIn(
                marker.encode("utf-8"),
                (attempt / "provider-response.bin").read_bytes(),
            )

    def test_artifact_never_captures_authorization_or_api_key_material(self):
        secret = "issue90-super-secret-api-key"
        config = replace(make_config(), api_key_env="ISSUE90_TEST_API_KEY")
        raw = envelope_bytes(
            json.dumps(semantic_invalid_payload(), ensure_ascii=False)
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"ISSUE90_TEST_API_KEY": secret},
        ):
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root, config=config).structure(case_input())

            [attempt] = attempt_dirs(root)
            combined = b"".join(
                path.read_bytes()
                for path in attempt.iterdir()
                if path.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), combined)
            manifest = read_manifest(attempt)
            self.assertFalse(
                manifest["security_boundary"]["authorization_captured"]
            )
            self.assertFalse(
                manifest["security_boundary"]["provider_request_body_captured"]
            )


if __name__ == "__main__":
    unittest.main()