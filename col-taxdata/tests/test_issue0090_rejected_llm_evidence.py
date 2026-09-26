from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_case import _error_payload as cli_error_payload
from case_application import AnalysisOutcome
from case_attempt_evidence import (
    GenerationEvidence,
    GenerationResult,
    RejectedAttemptEvidenceStore,
    deterministic_json_bytes,
)
from case_contract_validation import CaseContractError, INVALID_CASE_DRAFT
from case_http import (
    DEFAULT_CONFIG,
    build_runtime_application,
    error_response,
    prepare_case_request,
)
from llm_client import (
    CASE_OUTPUT_LIMIT,
    CASE_PROVIDER_TIMEOUT,
    CaseStructuringService,
    ContextLimitError,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
    StructuredGenerationCapability,
)


PROBLEM = "La sociedad está en liquidación."
CASE_INPUT = {
    "kind": "case_input",
    "contract_version": "3.0.0",
    "problem_text": PROBLEM,
}


def config(
    *,
    attempts: int = 1,
    api_key_env: str | None = None,
    context_tokens: int = 100_000,
) -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://provider.invalid/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("test-model", "primary", context_tokens, 1024),
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


def semantic_invalid_payload(*, quote: str = "texto inexistente") -> dict:
    payload = valid_payload()
    payload["facts"] = [
        {
            "kind": "case_fact",
            "contract_version": "3.0.0",
            "fact_ref": "fact:bad",
            "label": "Estado",
            "value": "liquidación",
            "state": "user_provided",
            "source_quote": quote,
            "requires_confirmation": False,
        }
    ]
    return payload


def envelope_bytes(
    content: str,
    *,
    finish_reason: str = "stop",
    usage: dict | None = None,
) -> bytes:
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
    def __init__(self, raw: bytes, *, status: int = 200):
        self.raw = raw
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def manifests(root: Path) -> list[Path]:
    return sorted(root.glob("attempt-*/manifest.json"))


def store_args(
    attempt_id: str,
    *,
    evidence: GenerationEvidence | None = None,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "raw_request_sha256": "1" * 64,
        "case_input_sha256": "2" * 64,
        "adapter": "test-adapter",
        "provider": "test-provider",
        "model": "test-model",
        "routing_role": "primary",
        "contract_version": "3.0.0",
        "prompt_template_id": "case-structuring-v3",
        "prompt_template_version": "4",
        "schema_version": "3.0.0",
        "started_at": "2026-09-26T00:00:00+00:00",
        "ended_at": "2026-09-26T00:00:01+00:00",
        "failure_stage": "semantic_validation",
        "failure_code": INVALID_CASE_DRAFT,
        "failure_detail": "$.facts[0].source_quote: invalid quote",
        "failure_path": "$.facts[0].source_quote",
        "evidence": evidence
        or GenerationEvidence(
            provider_request_attempted=True,
            provider_request_sha256="3" * 64,
            http_status=200,
            served_model="test-model",
            raw_response=b'{"raw":true}',
            finish_reason="stop",
            usage={"completion_tokens": 1},
            assistant_content="{}",
            candidate_json=b"{}",
        ),
    }


class ProviderNeutralEvidenceClient:
    adapter_id = "vendor-neutral-adapter"
    provider_id = "vendor-neutral-provider"
    structured_generation_capability = StructuredGenerationCapability(
        mechanism="vendor-constrained-json",
        schema_constrained=True,
        direct_object=True,
        post_response_repair=False,
    )

    def __init__(self, payload: dict, raw: bytes):
        self.payload = payload
        self.raw = raw

    def complete_case_draft(self, *, case_input: dict, route: ModelRoute):
        del case_input
        content = json.dumps(
            self.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return GenerationResult(
            payload=self.payload,
            evidence=GenerationEvidence(
                provider_request_attempted=True,
                provider_request_sha256="a" * 64,
                http_status=207,
                served_model=route.name,
                raw_response=self.raw,
                finish_reason="stop",
                usage={"completion_tokens": 7},
                assistant_content=content,
                candidate_payload=self.payload,
                candidate_json=deterministic_json_bytes(self.payload),
            ),
        )


class Issue0090RejectedEvidenceTests(unittest.TestCase):
    def _service(self, root: Path, *, cfg: LLMPlatformConfig | None = None):
        selected = cfg or config()
        return CaseStructuringService(
            selected,
            OpenAICompatibleLLMClient(selected),
            evidence_root=root,
        )

    def test_semantic_rejection_preserves_exact_provider_output_candidate_and_request_hashes(self):
        payload = semantic_invalid_payload()
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        raw = envelope_bytes(content)
        raw_request_sha = "b" * 64

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(CaseContractError) as raised:
                self._service(root).structure(
                    CASE_INPUT,
                    raw_request_sha256=raw_request_sha,
                )

            self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
            items = manifests(root)
            self.assertEqual(len(items), 1)
            manifest = json.loads(items[0].read_text(encoding="utf-8"))
            attempt_dir = items[0].parent
            self.assertFalse(manifest["canonical"])
            self.assertTrue(manifest["provider_request_attempted"])
            self.assertEqual(manifest["failure"]["stage"], "semantic_validation")
            self.assertEqual(manifest["failure"]["path"], "$.facts[0].source_quote")
            self.assertEqual(
                manifest["request_fingerprints"]["raw_request_sha256"],
                raw_request_sha,
            )
            self.assertEqual(
                manifest["request_fingerprints"]["case_input_sha256"],
                manifest["case_input_sha256"],
            )
            self.assertEqual(manifest["provider"]["http_status"], 200)
            self.assertEqual(manifest["provider"]["served_model"], "test-model")
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

    def test_partial_malformed_envelope_keeps_available_metadata(self):
        raw = json.dumps(
            {
                "model": "test-model",
                "choices": [{"finish_reason": "stop"}],
                "usage": {"completion_tokens": 42},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw, status=206),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError):
                self._service(root).structure(CASE_INPUT)
            manifest = json.loads(manifests(root)[0].read_text("utf-8"))
            self.assertEqual(
                manifest["failure"]["stage"],
                "provider_envelope_parse",
            )
            self.assertEqual(manifest["provider"]["http_status"], 206)
            self.assertEqual(manifest["provider"]["served_model"], "test-model")
            self.assertEqual(manifest["provider"]["finish_reason"], "stop")
            self.assertEqual(
                manifest["provider"]["usage"]["completion_tokens"],
                42,
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

    def test_parsed_non_object_candidate_is_preserved_deterministically(self):
        raw = envelope_bytes("[1,2]")
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(LLMClientError):
                self._service(root).structure(CASE_INPUT)
            manifest_path = manifests(root)[0]
            manifest = json.loads(manifest_path.read_text("utf-8"))
            candidate = (manifest_path.parent / "candidate.json").read_bytes()
            self.assertEqual(manifest["failure"]["stage"], "schema_validation")
            self.assertEqual(candidate, b"[1,2]")
            self.assertEqual(
                manifest["artifacts"]["candidate_payload"]["sha256"],
                hashlib.sha256(candidate).hexdigest(),
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
            self.assertTrue(manifest["provider_request_attempted"])
            self.assertFalse(manifest["artifacts"]["provider_response"]["present"])
            self.assertIsNone(manifest["artifacts"]["provider_response"]["sha256"])

    def test_pre_provider_context_failure_does_not_create_rejected_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "llm_client.urlrequest.urlopen",
        ) as opened:
            root = Path(tmp) / "audit"
            with self.assertRaises(ContextLimitError):
                self._service(
                    root,
                    cfg=config(context_tokens=1),
                ).structure(CASE_INPUT)
            opened.assert_not_called()
            self.assertEqual(manifests(root), [])

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

    def test_retries_create_distinct_attempt_artifacts(self):
        raw = envelope_bytes('{"bad"')
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

    def test_store_is_create_once_and_collision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "audit"
            store = RejectedAttemptEvidenceStore(root)
            args = store_args("attempt-fixed")
            manifest_path = store.record(**args)
            before = {
                path.name: path.read_bytes()
                for path in manifest_path.parent.iterdir()
            }
            with self.assertRaises(FileExistsError):
                store.record(**args)
            after = {
                path.name: path.read_bytes()
                for path in manifest_path.parent.iterdir()
            }
            self.assertEqual(before, after)

    def test_same_attempt_id_concurrency_publishes_exactly_one_complete_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "audit"
            store = RejectedAttemptEvidenceStore(root)
            args = store_args("attempt-concurrent")
            barrier = threading.Barrier(2)

            def publish() -> str:
                barrier.wait()
                try:
                    store.record(**args)
                except FileExistsError:
                    return "exists"
                return "ok"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _item: publish(), range(2)))

            self.assertEqual(sorted(results), ["exists", "ok"])
            final = root / "attempt-concurrent"
            self.assertTrue((final / "manifest.json").is_file())
            self.assertTrue((final / "provider-response.bin").is_file())
            self.assertEqual(
                [path for path in root.iterdir() if path.name.startswith(".")],
                [],
            )

    def test_partial_write_failure_never_publishes_final_attempt_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "audit"
            store = RejectedAttemptEvidenceStore(root)
            original = RejectedAttemptEvidenceStore._write_bytes

            def flaky(path: Path, value: bytes) -> None:
                if path.name == "assistant-content.txt":
                    raise OSError("synthetic disk failure")
                original(path, value)

            with mock.patch.object(
                RejectedAttemptEvidenceStore,
                "_write_bytes",
                side_effect=flaky,
            ):
                with self.assertRaises(OSError):
                    store.record(**store_args("attempt-partial"))

            self.assertFalse((root / "attempt-partial").exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_store_rejects_path_escape_attempt_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RejectedAttemptEvidenceStore(Path(tmp) / "audit")
            with self.assertRaises(ValueError):
                store.record(**store_args("../escape"))

    def test_provider_neutral_adapter_preserves_evidence_without_openai_transport(self):
        payload = semantic_invalid_payload()
        raw = b"vendor-neutral-exact-response"
        cfg = config()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "audit"
            service = CaseStructuringService(
                cfg,
                ProviderNeutralEvidenceClient(payload, raw),
                evidence_root=root,
            )
            with self.assertRaises(CaseContractError):
                service.structure(CASE_INPUT)

            manifest_path = manifests(root)[0]
            manifest = json.loads(manifest_path.read_text("utf-8"))
            self.assertEqual(manifest["adapter"], "vendor-neutral-adapter")
            self.assertEqual(manifest["adapter_id"], "vendor-neutral-adapter")
            self.assertEqual(manifest["provider_id"], "vendor-neutral-provider")
            self.assertEqual(manifest["requested_model"], "test-model")
            self.assertEqual(manifest["provider"]["served_model"], "test-model")
            self.assertEqual(manifest["provider"]["http_status"], 207)
            self.assertEqual(
                (manifest_path.parent / "provider-response.bin").read_bytes(),
                raw,
            )

    def test_http_runtime_passes_raw_request_hash_to_case_orchestrator(self):
        raw = json.dumps(
            {
                "problem_text": PROBLEM,
                "as_of_date": "2026-09-25",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        prepared = prepare_case_request(raw)
        expected = mock.sentinel.analysis_outcome

        with mock.patch(
            "case_http.analyze_case",
            return_value=expected,
        ) as analyzer:
            application, _provider, _model = build_runtime_application(
                db_path=Path("data/state/test.sqlite"),
                case_root=Path("data/cases"),
                config_path=DEFAULT_CONFIG,
                dry_run=True,
            )
            actual = application.analyze(
                prepared.case_input,
                raw_request_sha256=prepared.raw_request_sha256,
            )

        self.assertIs(actual, expected)
        self.assertEqual(
            analyzer.call_args.kwargs["raw_request_sha256"],
            prepared.raw_request_sha256,
        )

    def test_client_surfaces_do_not_echo_rejected_model_values(self):
        marker = "MODEL-PRIVATE-FRAGMENT"
        contract_exc = CaseContractError(
            INVALID_CASE_DRAFT,
            f"$.facts[0].state: unsupported value {marker!r}",
        )
        http_payload = error_response(contract_exc).payload
        cli_payload = cli_error_payload(contract_exc)
        self.assertNotIn(marker, json.dumps(http_payload))
        self.assertNotIn(marker, json.dumps(cli_payload))
        self.assertEqual(http_payload["validation_path"], "$.facts[0].state")

        llm_exc = LLMClientError(
            INVALID_CASE_DRAFT,
            f"malformed provider output includes {marker}",
        )
        self.assertNotIn(
            marker,
            json.dumps(error_response(llm_exc).payload),
        )
        self.assertNotIn(
            marker,
            json.dumps(cli_error_payload(llm_exc)),
        )

    def test_configured_api_key_echo_is_suppressed_from_all_audit_payload_files(self):
        secret = "super-secret-api-key"
        payload = semantic_invalid_payload(quote=secret)
        raw = envelope_bytes(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        cfg = config(api_key_env="ISSUE90_TEST_KEY")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"ISSUE90_TEST_KEY": secret},
        ), mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(raw),
        ):
            root = Path(tmp) / "audit"
            with self.assertRaises(CaseContractError):
                self._service(root, cfg=cfg).structure(CASE_INPUT)

            manifest_path = manifests(root)[0]
            manifest = json.loads(manifest_path.read_text("utf-8"))
            self.assertEqual(
                manifest["provider"]["payload_omission_reason"],
                "configured_api_key_material_detected",
            )
            for artifact in manifest["artifacts"].values():
                self.assertFalse(artifact["present"])
            for path in manifest_path.parent.iterdir():
                self.assertNotIn(secret.encode("utf-8"), path.read_bytes())

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
