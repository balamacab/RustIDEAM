"""Regression tests for GitHub issue #256 MCP upstream timeout semantics."""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = PROJECT_ROOT / "mcp_gateway"
PROFILE = PROJECT_ROOT / "config" / "llm" / "case-validation-reference-v2.yaml"
WEB_TIMEOUT_CONFIG = (
    PROJECT_ROOT / "web" / "case-console" / "nginx" / "20-configure-case-upstream.sh"
)

sys.path.insert(0, str(MCP_ROOT))

import gateway as gateway_module  # noqa: E402
from gateway import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    TOOL_NAMES,
    CaseRestClient,
    GatewayConfig,
    GatewayConfigError,
    GatewayError,
)


def shell_constant(script: str, name: str) -> int:
    match = re.search(rf"^{name}=([0-9]+)$", script, flags=re.MULTILINE)
    if match is None:
        raise AssertionError(f"missing shell constant {name}")
    return int(match.group(1))


class Issue0256McpTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.web_config = WEB_TIMEOUT_CONFIG.read_text(encoding="utf-8")

    def test_mcp_timeout_policy_matches_web_and_exceeds_case_runtime_budget(self):
        case_budget = float(self.profile["request_timeout_seconds"])
        web_default = shell_constant(
            self.web_config, "DEFAULT_CASE_API_READ_TIMEOUT_SECONDS"
        )
        web_minimum = shell_constant(
            self.web_config, "MIN_CASE_API_READ_TIMEOUT_SECONDS"
        )
        web_maximum = shell_constant(
            self.web_config, "MAX_CASE_API_READ_TIMEOUT_SECONDS"
        )

        self.assertGreater(MIN_TIMEOUT_SECONDS, case_budget)
        self.assertGreater(DEFAULT_TIMEOUT_SECONDS, case_budget)
        self.assertGreaterEqual(DEFAULT_TIMEOUT_SECONDS, MIN_TIMEOUT_SECONDS)
        self.assertLessEqual(DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, web_default)
        self.assertEqual(MIN_TIMEOUT_SECONDS, web_minimum)
        self.assertEqual(MAX_TIMEOUT_SECONDS, web_maximum)

        compose = (PROJECT_ROOT / "compose.mcp.yaml").read_text(encoding="utf-8")
        readme = (MCP_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            f"CASE_REST_TIMEOUT_SECONDS: "
            f"${{CASE_REST_TIMEOUT_SECONDS:-{int(DEFAULT_TIMEOUT_SECONDS)}}}",
            compose,
        )
        self.assertIn("valid range `7201` through `86400`", readme)

    def test_valid_env_timeout_reaches_urlopen_once(self):
        with mock.patch.dict(
            os.environ,
            {
                "CASE_REST_BASE_URL": "http://case-rest.example:8765",
                "CASE_REST_TIMEOUT_SECONDS": "8000",
            },
            clear=True,
        ):
            config = GatewayConfig.from_env()

        self.assertEqual(config.timeout_seconds, 8000.0)
        client = CaseRestClient(config)
        with mock.patch.object(
            gateway_module.urlrequest,
            "urlopen",
            side_effect=socket.timeout("controlled upstream timeout"),
        ) as opener:
            with self.assertRaises(GatewayError) as raised:
                client.research_case(problem_text="timeout propagation fixture")

        self.assertEqual(raised.exception.code, "MCP_CASE_UPSTREAM_TIMEOUT")
        self.assertTrue(raised.exception.retryable)
        opener.assert_called_once()
        self.assertEqual(
            opener.call_args.kwargs["timeout"],
            8000.0,
        )

    def test_invalid_or_out_of_contract_env_timeout_fails_before_serving(self):
        invalid_values = (
            "7200",
            "0",
            "-1",
            "86401",
            "nan",
            "inf",
            "not-a-number",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with mock.patch.dict(
                    os.environ,
                    {
                        "CASE_REST_BASE_URL": "http://case-rest.example:8765",
                        "CASE_REST_TIMEOUT_SECONDS": value,
                    },
                    clear=True,
                ):
                    with self.assertRaises(GatewayConfigError):
                        GatewayConfig.from_env()

    def test_short_controlled_timeout_maps_once_without_retry(self):
        # Production configuration is intentionally bounded above 7200 seconds.
        # Lower the test-only bounds so this unit can exercise the timeout branch
        # without waiting for the production envelope.
        with (
            mock.patch.object(gateway_module, "MIN_TIMEOUT_SECONDS", 0.001),
            mock.patch.object(gateway_module, "MAX_TIMEOUT_SECONDS", 1.0),
        ):
            config = GatewayConfig(
                base_url="http://case-rest.example:8765",
                timeout_seconds=0.01,
            )

        client = CaseRestClient(config)
        with mock.patch.object(
            gateway_module.urlrequest,
            "urlopen",
            side_effect=socket.timeout("controlled short timeout"),
        ) as opener:
            with self.assertRaises(GatewayError) as raised:
                client.research_case(problem_text="short timeout fixture")

        self.assertEqual(raised.exception.code, "MCP_CASE_UPSTREAM_TIMEOUT")
        self.assertTrue(raised.exception.retryable)
        opener.assert_called_once()
        self.assertEqual(opener.call_args.kwargs["timeout"], 0.01)

    def test_existing_mcp_tool_surface_remains_exactly_seven_tools(self):
        self.assertEqual(
            TOOL_NAMES,
            (
                "research_case",
                "get_case_research",
                "get_authority",
                "get_provision",
                "get_evidence",
                "get_normative_relationships",
                "get_calculation",
            ),
        )


if __name__ == "__main__":
    unittest.main()
