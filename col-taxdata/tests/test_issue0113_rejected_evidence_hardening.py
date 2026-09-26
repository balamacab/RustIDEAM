from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_attempt_evidence
from case_attempt_evidence import (
    GenerationEvidence,
    RejectedStructuringEvidenceStore,
    SUPPRESSION_CREDENTIAL_MATERIAL,
    canonical_json_bytes,
)
from case_contract_validation import CaseContractError
from llm_client import (
    CASE_EVIDENCE_PERSISTENCE_FAILED,
    CaseStructuringService,
    EvidencePersistenceError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
)


PROBLEM = (
    "La sociedad está en liquidación y solicita saber qué requisitos debe "
    "cumplir para cancelar su registro tributario."
)
SECRET_ENV = "ISSUE113_TEST_API_KEY"


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
                "text": "La cancelación exige revisar obligaciones pendientes.",
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


def make_config(*, api_key_env: str | None = None) -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("primary-model", "primary", 100_000, 1024),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=api_key_env,
    )


def envelope_bytes(content: str, *, extra: dict | None = None) -> bytes:
    envelope = {
        "model": "primary-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content},
            }
        ],
        "usage": {"completion_tokens": 17, "prompt_tokens": 41},
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


def published_attempts(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("ATT-")
    )


def staging_attempts(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith(".staging-")
    )


def read_manifest(attempt: Path) -> dict:
    return json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))


def store_generation(
    *,
    raw: bytes = b'{"response":"ordinary"}',
    assistant: str = '{"candidate":"ordinary"}',
    candidate: dict | None = None,
    secrets: tuple[bytes, ...] = (),
) -> GenerationEvidence:
    candidate = candidate if candidate is not None else {"candidate": "ordinary"}
    return GenerationEvidence(
        provider_contacted=True,
        provider_request_sha256="a" * 64,
        response_schema_sha256="b" * 64,
        provider_response_bytes=raw,
        http_status=200,
        served_model="primary-model",
        finish_reason="stop",
        usage={"completion_tokens": 1},
        assistant_content=assistant,
        candidate_json_bytes=canonical_json_bytes(candidate),
        configured_secret_values=secrets,
    )


def write_store_attempt(
    store: RejectedStructuringEvidenceStore,
    *,
    attempt_id: str,
    generation: GenerationEvidence,
    run_reference: str = "run:test",
) -> Path:
    return store.write_rejected_attempt(
        attempt_id=attempt_id,
        run_reference=run_reference,
        started_at="2026-09-26T00:00:00+00:00",
        ended_at="2026-09-26T00:00:01+00:00",
        case_input_sha256="c" * 64,
        request_fingerprints={"case_input_sha256": "c" * 64},
        adapter="openai-compatible",
        provider="test-provider",
        requested_model="primary-model",
        routing_role="primary",
        contract_version="3.0.0",
        prompt_template_id="case-structuring-v3",
        prompt_template_version="4",
        failure_code="INVALID_CASE_DRAFT",
        failure_stage="semantic_validation",
        failure_path="$.facts[0].source_quote",
        failure_detail="semantic rejection",
        generation=generation,
    )


class Issue0113RejectedEvidenceHardeningTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        *,
        config: LLMPlatformConfig | None = None,
        evidence_store=None,
    ) -> CaseStructuringService:
        config = config or make_config()
        store = (
            evidence_store
            if evidence_store is not None
            else RejectedStructuringEvidenceStore(root)
        )
        return CaseStructuringService(
            config,
            OpenAICompatibleLLMClient(config),
            evidence_store=store,
        )

    def test_ordinary_rejected_provider_response_remains_byte_exact(self):
        candidate = semantic_invalid_payload()
        content = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        raw = envelope_bytes(content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root).structure(case_input())

            [attempt] = published_attempts(root)
            manifest = read_manifest(attempt)
            self.assertEqual((attempt / "provider-response.bin").read_bytes(), raw)
            self.assertFalse(
                manifest["artifacts"]["provider_response"]["suppressed"]
            )
            self.assertTrue(
                manifest["artifacts"]["provider_response"]["persisted"]
            )

    def test_api_key_used_only_outbound_is_not_persisted(self):
        secret = "issue113-outbound-only-api-key"
        config = replace(make_config(), api_key_env=SECRET_ENV)
        candidate = semantic_invalid_payload()
        raw = envelope_bytes(json.dumps(candidate, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {SECRET_ENV: secret},
        ):
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ) as urlopen:
                with self.assertRaises(CaseContractError):
                    self._service(root, config=config).structure(case_input())

            request = urlopen.call_args.args[0]
            self.assertEqual(
                request.get_header("Authorization"),
                f"Bearer {secret}",
            )
            [attempt] = published_attempts(root)
            combined = b"".join(
                file.read_bytes() for file in attempt.iterdir() if file.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), combined)
            self.assertEqual((attempt / "provider-response.bin").read_bytes(), raw)

    def test_echoed_api_key_suppresses_raw_response_but_records_hash_and_length(self):
        secret = "issue113-echoed-provider-secret"
        config = make_config(api_key_env=SECRET_ENV)
        content = json.dumps(
            semantic_invalid_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw = envelope_bytes(content, extra={"provider_debug": secret})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {SECRET_ENV: secret},
        ):
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root, config=config).structure(case_input())

            [attempt] = published_attempts(root)
            manifest_bytes = (attempt / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            response_record = manifest["artifacts"]["provider_response"]
            self.assertTrue(response_record["present"])
            self.assertFalse(response_record["persisted"])
            self.assertTrue(response_record["suppressed"])
            self.assertEqual(
                response_record["suppression_reason"],
                SUPPRESSION_CREDENTIAL_MATERIAL,
            )
            self.assertEqual(response_record["size_bytes"], len(raw))
            self.assertEqual(
                response_record["sha256"],
                hashlib.sha256(raw).hexdigest(),
            )
            self.assertFalse((attempt / "provider-response.bin").exists())
            self.assertNotIn(secret.encode("utf-8"), manifest_bytes)
            self.assertEqual(
                manifest["security_boundary"]["suppressed_artifacts"],
                ["provider_response"],
            )

    def test_echoed_api_key_suppresses_contaminated_derivative_artifacts(self):
        secret = "issue113-derivative-secret"
        config = make_config(api_key_env=SECRET_ENV)
        candidate = semantic_invalid_payload()
        candidate["candidate_claims"][0]["text"] = f"provider echoed {secret}"
        content = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        raw = envelope_bytes(content)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {SECRET_ENV: secret},
        ):
            root = Path(tmp) / "rejected"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(CaseContractError):
                    self._service(root, config=config).structure(case_input())

            [attempt] = published_attempts(root)
            manifest = read_manifest(attempt)
            for name, filename in (
                ("provider_response", "provider-response.bin"),
                ("assistant_content", "assistant-content.txt"),
                ("candidate", "candidate.json"),
            ):
                record = manifest["artifacts"][name]
                self.assertTrue(record["present"])
                self.assertTrue(record["suppressed"])
                self.assertFalse(record["persisted"])
                self.assertFalse((attempt / filename).exists())
            combined = b"".join(
                file.read_bytes() for file in attempt.iterdir() if file.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), combined)

    def test_no_configured_secret_does_not_suppress_arbitrary_legal_text(self):
        marker = "texto-legal-que-parece-un-secreto-pero-no-esta-configurado"
        raw = envelope_bytes("{}", extra={"legal_text": marker})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            attempt = write_store_attempt(
                store,
                attempt_id="ATT-no-secret",
                generation=store_generation(raw=raw, secrets=()),
            )
            manifest = read_manifest(attempt)
            self.assertFalse(
                manifest["artifacts"]["provider_response"]["suppressed"]
            )
            self.assertEqual((attempt / "provider-response.bin").read_bytes(), raw)

    def test_failure_after_first_staged_artifact_never_publishes_final_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            real_write = case_attempt_evidence._write_private_new
            calls = 0

            def fail_after_first(path: Path, data: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                real_write(path, data)

            with mock.patch(
                "case_attempt_evidence._write_private_new",
                side_effect=fail_after_first,
            ):
                with self.assertRaises(OSError):
                    write_store_attempt(
                        store,
                        attempt_id="ATT-partial-write",
                        generation=store_generation(),
                    )

            self.assertEqual(published_attempts(root), [])
            [staging] = staging_attempts(root)
            self.assertEqual(
                stat.S_IMODE(staging.stat().st_mode),
                0o700,
            )
            self.assertFalse((staging / "manifest.json").exists())

    def test_failure_after_manifest_staging_before_rename_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            with mock.patch(
                "case_attempt_evidence._publish_staged_attempt",
                side_effect=OSError("injected publish failure"),
            ):
                with self.assertRaises(OSError):
                    write_store_attempt(
                        store,
                        attempt_id="ATT-pre-rename",
                        generation=store_generation(),
                    )

            self.assertEqual(published_attempts(root), [])
            [staging] = staging_attempts(root)
            self.assertTrue((staging / "manifest.json").exists())

    def test_successful_publish_exposes_only_fully_staged_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            real_rename = os.rename
            observed: dict[str, object] = {}

            def checked_rename(src, dst):
                staging = Path(src)
                final = Path(dst)
                observed["final_existed_before_rename"] = final.exists()
                observed["staged_files"] = {
                    path.name for path in staging.iterdir() if path.is_file()
                }
                return real_rename(src, dst)

            with mock.patch(
                "case_attempt_evidence.os.rename",
                side_effect=checked_rename,
            ):
                attempt = write_store_attempt(
                    store,
                    attempt_id="ATT-atomic-success",
                    generation=store_generation(),
                )

            self.assertFalse(observed["final_existed_before_rename"])
            self.assertEqual(
                observed["staged_files"],
                {
                    "provider-response.bin",
                    "assistant-content.txt",
                    "candidate.json",
                    "manifest.json",
                },
            )
            self.assertEqual(published_attempts(root), [attempt])
            self.assertEqual(staging_attempts(root), [])
            self.assertEqual(stat.S_IMODE(attempt.stat().st_mode), 0o700)

    def test_existing_final_attempt_id_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            attempt = write_store_attempt(
                store,
                attempt_id="ATT-create-once",
                generation=store_generation(raw=b"first"),
            )
            snapshot = {
                path.name: path.read_bytes()
                for path in attempt.iterdir()
                if path.is_file()
            }

            with self.assertRaises(FileExistsError):
                write_store_attempt(
                    store,
                    attempt_id="ATT-create-once",
                    generation=store_generation(raw=b"second"),
                )

            self.assertEqual(
                snapshot,
                {
                    path.name: path.read_bytes()
                    for path in attempt.iterdir()
                    if path.is_file()
                },
            )

    def test_concurrent_writers_cannot_publish_same_final_attempt_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)

            def publish(tag: str):
                return write_store_attempt(
                    store,
                    attempt_id="ATT-concurrent",
                    run_reference=f"run:{tag}",
                    generation=store_generation(raw=tag.encode("utf-8")),
                )

            results: list[object] = []
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(publish, tag) for tag in ("one", "two")]
                for future in futures:
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append(exc)

            self.assertEqual(
                sum(isinstance(item, Path) for item in results),
                1,
            )
            self.assertEqual(
                sum(isinstance(item, FileExistsError) for item in results),
                1,
            )
            [attempt] = published_attempts(root)
            self.assertTrue((attempt / "manifest.json").exists())

    def test_later_attempt_leaves_prior_published_attempt_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rejected"
            store = RejectedStructuringEvidenceStore(root)
            first = write_store_attempt(
                store,
                attempt_id="ATT-first-failure",
                generation=store_generation(raw=b"first"),
            )
            snapshot = {
                path.name: path.read_bytes()
                for path in first.iterdir()
                if path.is_file()
            }

            second = write_store_attempt(
                store,
                attempt_id="ATT-later-retry",
                generation=store_generation(raw=b"second"),
            )

            self.assertNotEqual(first, second)
            self.assertEqual(
                snapshot,
                {
                    path.name: path.read_bytes()
                    for path in first.iterdir()
                    if path.is_file()
                },
            )

    def test_evidence_persistence_failure_is_fail_closed_and_keeps_original_cause(self):
        class FailingStore:
            def write_rejected_attempt(self, **kwargs):
                del kwargs
                raise OSError("simulated disk failure")

        candidate = semantic_invalid_payload()
        raw = envelope_bytes(json.dumps(candidate, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unused"
            with mock.patch(
                "llm_client.urlrequest.urlopen",
                return_value=Response(raw),
            ):
                with self.assertRaises(EvidencePersistenceError) as raised:
                    self._service(
                        root,
                        evidence_store=FailingStore(),
                    ).structure(case_input())

            self.assertEqual(
                raised.exception.code,
                CASE_EVIDENCE_PERSISTENCE_FAILED,
            )
            self.assertEqual(
                raised.exception.persistence_error_type,
                "OSError",
            )
            self.assertIsInstance(raised.exception.__cause__, CaseContractError)
            self.assertEqual(published_attempts(root), [])


if __name__ == "__main__":
    unittest.main()