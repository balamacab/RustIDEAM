from __future__ import annotations

from dataclasses import replace
from http import HTTPStatus
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock
from urllib import request as urlrequest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_application import (
    AnalysisOutcome,
    CaseMaterializationError,
    CasePersistenceError,
    CaseValidationError,
    case_input_sha256,
)
from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    INVALID_CASE_INPUT,
)
from case_http import (
    CaseHTTPApplication,
    CaseHTTPServer,
    DEFAULT_ENDPOINT,
    error_response,
    prepare_case_request,
)
from llm_client import (
    CASE_CONTEXT_LIMIT,
    CASE_OUTPUT_LIMIT,
    CASE_PROVIDER_TIMEOUT,
    CASE_STRUCTURING_UNAVAILABLE,
    ContextLimitError,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
    OutputLimitError,
)


PROBLEM = "  La sociedad consulta IVA.\nConservar este texto exactamente.  "
AS_OF_DATE = "2026-09-24"


def fake_outcome(case_input: dict, *, case_id: str = "CASE-http-smoke") -> AnalysisOutcome:
    return AnalysisOutcome(
        case_id=case_id,
        case_ref="case:http-smoke",
        result={
            "kind": "case_result",
            "contract_version": "3.0.0",
            "problem_echo": case_input["problem_text"],
        },
        persistence_mode="dry-run",
        registration={
            "case_reused": False,
            "claims_inserted": 0,
            "claims_reused": 0,
            "evidence_inserted": 0,
        },
        materialization={"updated_count": 0},
        validation={"valid": True},
    )


def make_llm_config() -> LLMPlatformConfig:
    route = ModelRoute(
        name="configured-model",
        routing_role="primary",
        context_tokens=100_000,
        max_output_tokens=1024,
    )
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="configured-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=route,
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


class Issue0066RequestContractTests(unittest.TestCase):
    def test_exact_problem_text_is_preserved(self):
        raw = json.dumps(
            {
                "problem_text": PROBLEM,
                "as_of_date": AS_OF_DATE,
                "client_reference": "external-matter-66",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        prepared = prepare_case_request(raw)

        self.assertEqual(prepared.case_input["problem_text"], PROBLEM)
        self.assertEqual(prepared.case_input["as_of_date"], AS_OF_DATE)
        self.assertEqual(
            prepared.case_input["client_reference"],
            "external-matter-66",
        )
        self.assertEqual(prepared.case_input["kind"], "case_input")
        self.assertEqual(prepared.case_input["contract_version"], "3.0.0")

    def test_raw_and_canonical_fingerprints_have_distinct_contracts(self):
        raw_a = (
            '{"problem_text":"Consulta simple","as_of_date":"2026-09-24"}'
        ).encode("utf-8")
        raw_b = (
            '{ "as_of_date": "2026-09-24", '
            '"problem_text": "Consulta simple" }'
        ).encode("utf-8")

        first = prepare_case_request(raw_a)
        second = prepare_case_request(raw_b)

        self.assertNotEqual(
            first.raw_request_sha256,
            second.raw_request_sha256,
        )
        self.assertEqual(
            first.case_input_sha256,
            second.case_input_sha256,
        )
        self.assertEqual(
            first.case_input_sha256,
            case_input_sha256(first.case_input),
        )

    def test_http_contract_requires_as_of_date(self):
        raw = json.dumps({"problem_text": "Consulta"}).encode("utf-8")
        with self.assertRaises(CaseContractError) as raised:
            prepare_case_request(raw)
        self.assertEqual(raised.exception.code, INVALID_CASE_INPUT)

    def test_caller_cannot_seed_internal_or_server_owned_fields(self):
        forbidden = {
            "model": "configured-model",
            "backend": "llama.cpp",
            "case_id": "CASE-forged",
            "document_id": "DOC-forged",
            "source_hints": ["DIAN"],
            "evidence_bindings": ["EVD-forged"],
            "expected_conclusions": ["resultado esperado"],
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                raw = json.dumps(
                    {
                        "problem_text": "Consulta",
                        "as_of_date": AS_OF_DATE,
                        field: value,
                    }
                ).encode("utf-8")
                with self.assertRaises(CaseContractError) as raised:
                    prepare_case_request(raw)
                self.assertEqual(
                    raised.exception.code,
                    INVALID_CASE_INPUT,
                )

    def test_internal_identifier_cannot_hide_in_client_reference(self):
        for value in (
            "CASE-1234",
            "DOC-abc",
            "PROV-abc",
            "SEG-abc",
            "EVD-abc",
        ):
            with self.subTest(value=value):
                raw = json.dumps(
                    {
                        "problem_text": "Consulta",
                        "as_of_date": AS_OF_DATE,
                        "client_reference": value,
                    }
                ).encode("utf-8")
                with self.assertRaises(CaseContractError) as raised:
                    prepare_case_request(raw)
                self.assertEqual(
                    raised.exception.code,
                    INVALID_CASE_INPUT,
                )


class Issue0066TransportParityTests(unittest.TestCase):
    def test_transport_delegates_exact_case_input_to_application_callable(self):
        captured: list[dict] = []

        def analyzer(case_input: dict) -> AnalysisOutcome:
            captured.append(case_input)
            return fake_outcome(case_input)

        raw = json.dumps(
            {
                "problem_text": PROBLEM,
                "as_of_date": AS_OF_DATE,
                "client_reference": "matter-66",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        prepared = prepare_case_request(raw)
        application = CaseHTTPApplication(analyzer)

        outcome = application.analyze(prepared.case_input)

        self.assertEqual(captured, [prepared.case_input])
        self.assertEqual(captured[0]["problem_text"], PROBLEM)
        self.assertEqual(outcome.case_id, "CASE-http-smoke")

    def test_same_request_contract_is_backend_agnostic(self):
        raw = json.dumps(
            {
                "problem_text": "Caso de humo no benchmark.",
                "as_of_date": AS_OF_DATE,
            }
        ).encode("utf-8")
        prepared = prepare_case_request(raw)
        seen: list[tuple[str, dict]] = []

        for backend in ("quadro-e2b", "npu-e2b", "npu-12b"):
            def analyzer(case_input: dict, backend_name: str = backend) -> AnalysisOutcome:
                seen.append((backend_name, dict(case_input)))
                return fake_outcome(
                    case_input,
                    case_id=f"CASE-{backend_name}",
                )

            CaseHTTPApplication(analyzer).analyze(prepared.case_input)

        self.assertEqual(len(seen), 3)
        self.assertTrue(
            all(case_input == prepared.case_input for _, case_input in seen)
        )
        self.assertNotIn("model", prepared.case_input)
        self.assertNotIn("backend", prepared.case_input)

    def test_non_benchmark_http_smoke_call(self):
        captured: list[dict] = []

        def analyzer(case_input: dict) -> AnalysisOutcome:
            captured.append(case_input)
            return fake_outcome(case_input)

        server = CaseHTTPServer(
            ("127.0.0.1", 0),
            CaseHTTPApplication(analyzer),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            host, port = server.server_address[:2]
            raw = json.dumps(
                {
                    "problem_text": "Consulta HTTP mínima de humo.",
                    "as_of_date": AS_OF_DATE,
                }
            ).encode("utf-8")
            req = urlrequest.Request(
                f"http://{host}:{port}{DEFAULT_ENDPOINT}",
                data=raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_http.sys.stderr", io.StringIO()):
                with urlrequest.urlopen(req, timeout=3) as response:
                    payload = json.loads(response.read())

            self.assertEqual(response.status, HTTPStatus.OK)
            self.assertEqual(payload["case_id"], "CASE-http-smoke")
            self.assertEqual(
                payload["case_result"]["problem_echo"],
                "Consulta HTTP mínima de humo.",
            )
            self.assertEqual(
                set(payload["request_fingerprints"]),
                {"raw_request_sha256", "case_input_sha256"},
            )
            self.assertEqual(
                captured[0]["problem_text"],
                "Consulta HTTP mínima de humo.",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_http_rejection_is_machine_readable_and_audited_by_raw_hash(self):
        server = CaseHTTPServer(
            ("127.0.0.1", 0),
            CaseHTTPApplication(fake_outcome),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            host, port = server.server_address[:2]
            raw = json.dumps(
                {
                    "problem_text": "Consulta",
                    "as_of_date": AS_OF_DATE,
                    "model": "forged",
                }
            ).encode("utf-8")
            req = urlrequest.Request(
                f"http://{host}:{port}{DEFAULT_ENDPOINT}",
                data=raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_http.sys.stderr", io.StringIO()):
                with self.assertRaises(Exception) as raised:
                    urlrequest.urlopen(req, timeout=3)
            http_error = raised.exception
            self.assertEqual(http_error.code, HTTPStatus.BAD_REQUEST)
            payload = json.loads(http_error.read())
            self.assertEqual(payload["error"], INVALID_CASE_INPUT)
            self.assertEqual(
                set(payload["request_fingerprints"]),
                {"raw_request_sha256"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class Issue0066ErrorSemanticsTests(unittest.TestCase):
    def test_transport_maps_required_failure_categories(self):
        cases = [
            (
                CaseContractError(INVALID_CASE_INPUT, "bad request"),
                HTTPStatus.BAD_REQUEST,
                INVALID_CASE_INPUT,
            ),
            (
                LLMClientError(
                    CASE_PROVIDER_TIMEOUT,
                    "provider timed out",
                    retryable=True,
                ),
                HTTPStatus.GATEWAY_TIMEOUT,
                CASE_PROVIDER_TIMEOUT,
            ),
            (
                LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    "provider unavailable",
                    retryable=True,
                ),
                HTTPStatus.SERVICE_UNAVAILABLE,
                CASE_STRUCTURING_UNAVAILABLE,
            ),
            (
                LLMClientError(
                    INVALID_CASE_DRAFT,
                    "malformed structured output",
                    retryable=True,
                ),
                HTTPStatus.BAD_GATEWAY,
                INVALID_CASE_DRAFT,
            ),
            (
                ContextLimitError(
                    "context exceeded",
                    {"truncated": False},
                ),
                HTTPStatus.UNPROCESSABLE_ENTITY,
                CASE_CONTEXT_LIMIT,
            ),
            (
                OutputLimitError(
                    "output ceiling reached",
                    {"truncated": True},
                ),
                HTTPStatus.BAD_GATEWAY,
                CASE_OUTPUT_LIMIT,
            ),
            (
                CasePersistenceError("database write failed"),
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "CASE_PERSISTENCE_FAILURE",
            ),
            (
                CaseMaterializationError("render failed"),
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "CASE_MATERIALIZATION_FAILURE",
            ),
            (
                CaseValidationError("bundle invalid"),
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "CASE_VALIDATION_FAILURE",
            ),
        ]
        for exc, expected_status, expected_code in cases:
            with self.subTest(code=expected_code):
                response = error_response(exc)
                self.assertEqual(response.status, expected_status)
                self.assertEqual(
                    response.payload["error"],
                    expected_code,
                )

    def test_llm_adapter_detects_output_ceiling_even_with_stop_reason(self):
        config = make_llm_config()
        client = OpenAICompatibleLLMClient(config)
        envelope = {
            "model": config.primary.name,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "{}"},
                }
            ],
            "usage": {
                "completion_tokens": config.primary.max_output_tokens,
            },
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(envelope).encode("utf-8")

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(),
        ):
            with self.assertRaises(OutputLimitError) as raised:
                client.complete_case_draft(
                    case_input={
                        "kind": "case_input",
                        "contract_version": "3.0.0",
                        "problem_text": "Consulta",
                        "as_of_date": AS_OF_DATE,
                    },
                    route=config.primary,
                )
        self.assertEqual(raised.exception.code, CASE_OUTPUT_LIMIT)
        self.assertEqual(
            raised.exception.metadata["completion_tokens"],
            config.primary.max_output_tokens,
        )

    def test_llm_adapter_distinguishes_provider_timeout(self):
        config = make_llm_config()
        client = OpenAICompatibleLLMClient(config)
        with mock.patch(
            "llm_client.urlrequest.urlopen",
            side_effect=TimeoutError("slow backend"),
        ):
            with self.assertRaises(LLMClientError) as raised:
                client.complete_case_draft(
                    case_input={
                        "kind": "case_input",
                        "contract_version": "3.0.0",
                        "problem_text": "Consulta",
                        "as_of_date": AS_OF_DATE,
                    },
                    route=config.primary,
                )
        self.assertEqual(raised.exception.code, CASE_PROVIDER_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
