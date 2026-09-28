"""Regression coverage for GitHub issue #221 CASE v4 error boundaries."""

from __future__ import annotations

import io
import json
from http import HTTPStatus
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlrequest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
MCP_ROOT = ROOT / "mcp_gateway"
FIXTURE_ROOT = (
    ROOT / "specs" / "application" / "examples" / "case-rest-v1"
)

sys.path.insert(0, str(TOOLS_ROOT))
sys.path.insert(0, str(MCP_ROOT))

from case_application import analyze_case  # noqa: E402
from case_contract_validation import CaseContractError  # noqa: E402
from case_contract_validation_v4 import INVALID_INTAKE_DRAFT  # noqa: E402
from case_rest_api import (  # noqa: E402
    CASE_API_INTEGRITY_FAILURE,
    CASE_API_INTERNAL_ERROR,
    CASE_API_SERVICE_UNAVAILABLE,
    CASE_API_TIMEOUT,
    CaseRESTApplication,
    CaseRESTServer,
    DEFAULT_ENDPOINT,
    validate_error_payload,
)
from gateway import (  # noqa: E402
    GatewayConfig,
    GatewayError,
    GatewayService,
)
from llm_client import (  # noqa: E402
    CASE_OUTPUT_LIMIT,
    CASE_PROVIDER_TIMEOUT,
    CASE_STRUCTURING_UNAVAILABLE,
    LLMClientError,
)


class RaisingStructurer:
    """Minimal structurer double that fails before any corpus access."""

    def __init__(self, error: Exception):
        self.error = error

    def structure(self, _case_input, *, request_fingerprints=None):
        del request_fingerprints
        raise self.error


class RunningIntegratedREST:
    """Serve the real REST boundary over analyze_case with a failing structurer."""

    def __init__(self, error: Exception):
        structurer = RaisingStructurer(error)

        def researcher(case_input, *, request_fingerprints=None):
            outcome = analyze_case(
                case_input=case_input,
                db_path=Path("/unused/issue221.sqlite"),
                case_root=Path("/unused/issue221-cases"),
                structurer=structurer,
                request_fingerprints=request_fingerprints,
            )
            return outcome.bundle

        self.server = CaseRESTServer(
            ("127.0.0.1", 0),
            CaseRESTApplication(
                researcher,
                forward_request_fingerprints=True,
            ),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def request_bytes() -> bytes:
    return (FIXTURE_ROOT / "request.json").read_bytes()


def request_kwargs() -> dict:
    payload = json.loads(request_bytes())
    return {
        "problem_text": payload["problem_text"],
        "as_of_date": payload.get("as_of_date"),
        "client_reference": payload.get("client_reference"),
        "caller_metadata": payload.get("caller_metadata"),
    }


def call_rest(error: Exception) -> tuple[int, dict, dict]:
    audit = io.StringIO()
    with RunningIntegratedREST(error) as running:
        req = urlrequest.Request(
            running.base_url + DEFAULT_ENDPOINT,
            data=request_bytes(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch("case_rest_api.sys.stderr", audit):
            with unittest.TestCase().assertRaises(urlerror.HTTPError) as raised:
                urlrequest.urlopen(req, timeout=3)
        response_error = raised.exception
        payload = json.loads(response_error.read())

    validate_error_payload(payload)
    audit_payload = json.loads(audit.getvalue().strip())
    return response_error.code, payload, audit_payload


def call_mcp(error: Exception) -> GatewayError:
    with RunningIntegratedREST(error) as running:
        gateway = GatewayService.from_config(
            GatewayConfig(base_url=running.base_url)
        )
        with unittest.TestCase().assertRaises(GatewayError) as raised:
            gateway.research_case(**request_kwargs())
    return raised.exception


class Issue0221RESTBoundaryTests(unittest.TestCase):
    def test_expected_v4_structuring_families_use_stable_public_taxonomy(self):
        cases = (
            (
                "semantic rejection",
                lambda: CaseContractError(
                    INVALID_INTAKE_DRAFT,
                    "$.facts: private semantic rejection token=do-not-leak",
                ),
                HTTPStatus.INTERNAL_SERVER_ERROR,
                CASE_API_INTEGRITY_FAILURE,
                "structuring_integrity",
                INVALID_INTAKE_DRAFT,
            ),
            (
                "structured output ceiling",
                lambda: LLMClientError(
                    CASE_OUTPUT_LIMIT,
                    "private model limit /srv/provider token=do-not-leak",
                ),
                HTTPStatus.INTERNAL_SERVER_ERROR,
                CASE_API_INTEGRITY_FAILURE,
                "structuring_integrity",
                CASE_OUTPUT_LIMIT,
            ),
            (
                "provider unavailable",
                lambda: LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    "private provider https://127.0.0.1 token=do-not-leak",
                    retryable=True,
                ),
                HTTPStatus.SERVICE_UNAVAILABLE,
                CASE_API_SERVICE_UNAVAILABLE,
                "structuring_provider_unavailable",
                CASE_STRUCTURING_UNAVAILABLE,
            ),
            (
                "provider timeout",
                lambda: LLMClientError(
                    CASE_PROVIDER_TIMEOUT,
                    "private provider timeout token=do-not-leak",
                    retryable=True,
                ),
                HTTPStatus.GATEWAY_TIMEOUT,
                CASE_API_TIMEOUT,
                "structuring_provider_timeout",
                CASE_PROVIDER_TIMEOUT,
            ),
        )

        for (
            name,
            make_error,
            expected_status,
            expected_code,
            diagnostic_family,
            diagnostic_code,
        ) in cases:
            with self.subTest(name=name):
                status, payload, audit = call_rest(make_error())

                self.assertEqual(status, expected_status)
                self.assertEqual(payload["error"]["code"], expected_code)
                self.assertEqual(audit["error"], expected_code)
                self.assertEqual(
                    audit["diagnostic"],
                    {
                        "family": diagnostic_family,
                        "code": diagnostic_code,
                    },
                )

                public = json.dumps(payload, sort_keys=True)
                server_audit = json.dumps(audit, sort_keys=True)
                for secret in (
                    "do-not-leak",
                    "/srv/provider",
                    "127.0.0.1",
                    "private semantic rejection",
                    "private provider",
                ):
                    self.assertNotIn(secret, public)
                    self.assertNotIn(secret, server_audit)

    def test_genuinely_unexpected_exception_remains_internal(self):
        status, payload, audit = call_rest(
            RuntimeError(
                "programming bug /srv/private/runtime token=do-not-leak"
            )
        )

        self.assertEqual(status, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertEqual(payload["error"]["code"], CASE_API_INTERNAL_ERROR)
        self.assertEqual(
            audit["diagnostic"],
            {
                "family": "unexpected_exception",
                "code": "RuntimeError",
            },
        )
        serialized = json.dumps({"public": payload, "audit": audit})
        self.assertNotIn("/srv/private", serialized)
        self.assertNotIn("do-not-leak", serialized)


class Issue0221MCPBoundaryTests(unittest.TestCase):
    def test_integrated_rest_failures_reach_expected_mcp_taxonomy(self):
        cases = (
            (
                lambda: CaseContractError(
                    INVALID_INTAKE_DRAFT,
                    "$.facts: private intake detail token=do-not-leak",
                ),
                "MCP_CASE_UPSTREAM_INTEGRITY_FAILURE",
                CASE_API_INTEGRITY_FAILURE,
                False,
            ),
            (
                lambda: LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    "private provider URL/token must not cross MCP",
                    retryable=True,
                ),
                "MCP_CASE_UPSTREAM_UNAVAILABLE",
                CASE_API_SERVICE_UNAVAILABLE,
                True,
            ),
            (
                lambda: LLMClientError(
                    CASE_PROVIDER_TIMEOUT,
                    "private provider timeout must not cross MCP",
                    retryable=True,
                ),
                "MCP_CASE_UPSTREAM_TIMEOUT",
                CASE_API_TIMEOUT,
                True,
            ),
            (
                lambda: RuntimeError(
                    "private programming failure token=do-not-leak"
                ),
                "MCP_CASE_UPSTREAM_INTERNAL_ERROR",
                CASE_API_INTERNAL_ERROR,
                False,
            ),
        )

        for make_error, expected_code, upstream_code, retryable in cases:
            with self.subTest(expected_code=expected_code):
                error = call_mcp(make_error())
                self.assertEqual(error.code, expected_code)
                self.assertEqual(error.upstream_code, upstream_code)
                self.assertEqual(error.retryable, retryable)
                self.assertNotIn("private", error.message)
                self.assertNotIn("token", error.message)


if __name__ == "__main__":
    unittest.main()
