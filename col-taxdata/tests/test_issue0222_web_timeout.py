from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "web" / "case-console"
PROFILE = ROOT / "config" / "llm" / "case-validation-reference-v2.yaml"


def shell_constant(script: str, name: str) -> int:
    match = re.search(rf"^{name}=([0-9]+)$", script, flags=re.MULTILINE)
    if match is None:
        raise AssertionError(f"missing shell constant {name}")
    return int(match.group(1))


class Issue0222WebTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.template = (
            CONSOLE / "nginx" / "case-console.conf.template"
        ).read_text(encoding="utf-8")
        self.entrypoint = (
            CONSOLE / "nginx" / "20-configure-case-upstream.sh"
        ).read_text(encoding="utf-8")
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))

    def test_proxy_timeout_is_runtime_configured_not_fixed_at_300_seconds(self):
        self.assertIn(
            "proxy_read_timeout __CASE_API_READ_TIMEOUT_SECONDS__s;",
            self.template,
        )
        self.assertNotIn("proxy_read_timeout 300s;", self.template)
        self.assertIn(
            "__CASE_API_READ_TIMEOUT_SECONDS__",
            self.entrypoint,
        )

    def test_default_and_minimum_exceed_admitted_case_runtime_budget(self):
        upstream_timeout = int(self.profile["request_timeout_seconds"])
        default_timeout = shell_constant(
            self.entrypoint, "DEFAULT_CASE_API_READ_TIMEOUT_SECONDS"
        )
        minimum_timeout = shell_constant(
            self.entrypoint, "MIN_CASE_API_READ_TIMEOUT_SECONDS"
        )
        maximum_timeout = shell_constant(
            self.entrypoint, "MAX_CASE_API_READ_TIMEOUT_SECONDS"
        )

        self.assertGreater(default_timeout, upstream_timeout)
        self.assertGreater(minimum_timeout, upstream_timeout)
        self.assertGreaterEqual(default_timeout, minimum_timeout)
        self.assertLessEqual(default_timeout, maximum_timeout)

    def test_entrypoint_rejects_unbounded_or_too_short_timeout_values(self):
        self.assertIn(
            "CASE_API_READ_TIMEOUT_SECONDS must be an integer number of seconds",
            self.entrypoint,
        )
        self.assertIn(
            'if [ "$CASE_API_READ_TIMEOUT_SECONDS" -lt '
            '"$MIN_CASE_API_READ_TIMEOUT_SECONDS" ]',
            self.entrypoint,
        )
        self.assertIn(
            '[ "$CASE_API_READ_TIMEOUT_SECONDS" -gt '
            '"$MAX_CASE_API_READ_TIMEOUT_SECONDS" ]',
            self.entrypoint,
        )

    def test_compose_and_documentation_expose_the_validated_default(self):
        default_timeout = shell_constant(
            self.entrypoint, "DEFAULT_CASE_API_READ_TIMEOUT_SECONDS"
        )
        compose = (CONSOLE / "compose.yaml").read_text(encoding="utf-8")
        readme = (CONSOLE / "README.md").read_text(encoding="utf-8")

        self.assertIn(
            f"CASE_API_READ_TIMEOUT_SECONDS: "
            f"${{CASE_API_READ_TIMEOUT_SECONDS:-{default_timeout}}}",
            compose,
        )
        self.assertIn(
            f"CASE_API_READ_TIMEOUT_SECONDS={default_timeout}",
            readme,
        )
        self.assertIn("7201 through 86400", readme)

    def test_existing_narrow_proxy_and_security_boundary_are_preserved(self):
        self.assertIn("location = /api/v1/cases", self.template)
        self.assertIn("limit_except POST", self.template)
        self.assertIn(
            "proxy_pass __CASE_API_UPSTREAM__/v1/cases;",
            self.template,
        )
        self.assertNotIn("location /api/", self.template)
        self.assertIn("proxy_set_header Cookie \"\";", self.template)
        self.assertIn("proxy_set_header Authorization \"\";", self.template)
        self.assertIn("Content-Security-Policy", self.template)


if __name__ == "__main__":
    unittest.main()
