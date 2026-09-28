from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "web" / "case-console"
DOCKERFILE = CONSOLE / "Dockerfile"
HEALTHCHECK = CONSOLE / "nginx" / "healthcheck.sh"
APP = CONSOLE / "app.js"


class Issue0274WebMimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.healthcheck = HEALTHCHECK.read_text(encoding="utf-8")
        self.app = APP.read_text(encoding="utf-8")

    def test_image_maps_mjs_to_the_same_javascript_type_as_js(self) -> None:
        self.assertIn("application/javascript", self.dockerfile)
        self.assertIn("js mjs;", self.dockerfile)
        self.assertIn("/etc/nginx/mime.types", self.dockerfile)
        self.assertIn("grep -Eq", self.dockerfile)

    def test_runtime_healthcheck_covers_browser_boot_assets_and_mime(self) -> None:
        self.assertIn("/healthz", self.healthcheck)
        self.assertIn("/app.js", self.healthcheck)
        self.assertIn("/app-core.mjs", self.healthcheck)
        self.assertIn("/public-contract.json", self.healthcheck)
        self.assertIn("/fixtures/index.json", self.healthcheck)
        self.assertGreaterEqual(
            self.healthcheck.count("(application|text)/javascript"),
            2,
        )
        self.assertGreaterEqual(
            self.healthcheck.count("application/json"),
            2,
        )
        self.assertIn(
            'CMD ["/usr/local/bin/case-console-healthcheck"]',
            self.dockerfile,
        )

    def test_console_initialization_uses_boot_assets_then_enables_submit(self) -> None:
        self.assertIn(
            'from "./app-core.mjs"',
            self.app,
        )
        self.assertIn(
            'fetch("./public-contract.json"',
            self.app,
        )
        self.assertIn(
            'fetch("./fixtures/index.json"',
            self.app,
        )
        self.assertIn("contract = await contractResponse.json();", self.app)
        self.assertIn(
            "const fixtureDocument = await fixtureResponse.json();",
            self.app,
        )
        self.assertIn("submitButton.disabled = false;", self.app)
        self.assertIn(
            'showState("Ready. No request has been submitted.", "idle");',
            self.app,
        )

    def test_web_image_remains_static_code_only(self) -> None:
        forbidden = (
            "data/state",
            "taxdata.sqlite",
            "data/raw",
            "COPY ../",
            "ADD ../",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.dockerfile)


if __name__ == "__main__":
    unittest.main()
