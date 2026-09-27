from __future__ import annotations

import contextlib
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "web" / "case-console"
TOOLS = ROOT / "tools"
REST_SCHEMA = ROOT / "specs" / "application" / "schemas" / "case-rest-api-v1.schema.json"
V4_SCHEMA = ROOT / "specs" / "application" / "schemas" / "case-contracts-v4.schema.json"
OPENAPI = ROOT / "specs" / "application" / "openapi" / "case-rest-api-v1.openapi.json"
REST_EXAMPLES = ROOT / "specs" / "application" / "examples" / "case-rest-v1"
DEF0015 = ROOT / "tests" / "fixtures" / "def0015_webcam_authority_inversion.json"
ISSUE67 = ROOT / "config" / "benchmarks" / "issue65" / "request.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CaseConsoleContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_json(CONSOLE / "public-contract.json")
        self.fixture_document = load_json(CONSOLE / "fixtures" / "index.json")

    def test_client_projection_matches_authoritative_rest_contract(self):
        rest = load_json(REST_SCHEMA)
        v4 = load_json(V4_SCHEMA)
        openapi = load_json(OPENAPI)

        request_fields = set(rest["$defs"]["CaseSubmissionRequest"]["properties"])
        success_fields = set(rest["$defs"]["CaseResearchResponse"]["properties"])
        error_fields = set(rest["$defs"]["ErrorResponse"]["properties"])
        bundle_fields = set(v4["$defs"]["LegalResearchBundle"]["properties"])

        self.assertEqual(self.contract["api_version"], "1.0.0")
        self.assertEqual(self.contract["method"], "POST")
        self.assertIn(self.contract["api_path"], openapi["paths"])
        self.assertIn("post", openapi["paths"][self.contract["api_path"]])
        self.assertEqual(set(self.contract["request_fields"]), request_fields)
        self.assertEqual(set(self.contract["success_top_level_fields"]), success_fields)
        self.assertEqual(set(self.contract["error_top_level_fields"]), error_fields)
        self.assertEqual(set(self.contract["bundle_fields"]), bundle_fields)
        self.assertEqual(self.contract["proxy_path"], "/api" + self.contract["api_path"])

    def test_fixture_loader_contains_only_caller_owned_fields(self):
        allowed = set(self.contract["request_fields"])
        fixtures = self.fixture_document["fixtures"]
        self.assertEqual(
            {fixture["id"] for fixture in fixtures},
            {
                "def0015-webcam-natural-person",
                "case0002-lineage",
                "issue67-historical",
            },
        )
        for fixture in fixtures:
            request = fixture["request"]
            self.assertTrue(set(request).issubset(allowed))
            self.assertIsInstance(request["problem_text"], str)
            self.assertTrue(request["problem_text"])
            serialized = json.dumps(fixture, ensure_ascii=False).lower()
            for forbidden in (
                "expected_conclusions",
                "canonical_ids",
                "evidence_bindings",
                "source_hints",
                "api_key",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_def0015_and_issue67_fixture_inputs_are_exact_repository_lineage(self):
        fixtures = {item["id"]: item["request"] for item in self.fixture_document["fixtures"]}
        self.assertEqual(
            fixtures["def0015-webcam-natural-person"],
            load_json(DEF0015)["case_input"],
        )
        self.assertEqual(fixtures["issue67-historical"], load_json(ISSUE67))

    def test_case0002_fixture_is_frozen_caller_input_not_internal_state(self):
        fixtures = {item["id"]: item["request"] for item in self.fixture_document["fixtures"]}
        request = fixtures["case0002-lineage"]
        self.assertEqual(request["as_of_date"], "2026-09-24")
        self.assertIn("servicios de diseño, gestión y optimización", request["problem_text"])
        self.assertIn("autorretención especial", request["problem_text"])
        self.assertNotIn("DOC-", json.dumps(request))
        self.assertNotIn("PROV-", json.dumps(request))
        self.assertNotIn("EVD-", json.dumps(request))

    def test_frontend_has_no_unsafe_html_secret_storage_or_backend_address(self):
        app = (CONSOLE / "app.js").read_text(encoding="utf-8")
        core = (CONSOLE / "app-core.mjs").read_text(encoding="utf-8")
        combined = app + "\n" + core
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "localStorage",
            "sessionStorage",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertNotIn("http://", combined)
        self.assertNotIn("https://", combined)
        self.assertIn(".textContent", app)
        self.assertIn('credentials: "omit"', app)
        self.assertNotIn("api_key", combined.lower())
        self.assertNotIn("CONSOLE_TRANSPORT_ERROR", combined)
        self.assertIn("local console state, not a CASE REST response", app)

    def test_proxy_and_container_are_strictly_independent(self):
        template = (CONSOLE / "nginx" / "case-console.conf.template").read_text(
            encoding="utf-8"
        )
        entrypoint = (CONSOLE / "nginx" / "20-configure-case-upstream.sh").read_text(
            encoding="utf-8"
        )
        dockerfile = (CONSOLE / "Dockerfile").read_text(encoding="utf-8")
        compose = (CONSOLE / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("location = /api/v1/cases", template)
        self.assertIn("limit_except POST", template)
        self.assertIn("proxy_pass __CASE_API_UPSTREAM__/v1/cases;", template)
        self.assertNotIn("location /api/", template)
        self.assertIn("CASE_API_UPSTREAM", entrypoint)
        self.assertIn("without a path, query or fragment", entrypoint)
        self.assertIn("Content-Security-Policy", template)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertNotIn("COPY ../", dockerfile)
        self.assertNotIn("tools/", dockerfile)
        self.assertNotIn("schema/", dockerfile)
        self.assertNotIn("volumes:", compose)

    def test_contract_fixtures_build_views_without_undocumented_bundle_fields(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable for ES-module contract fixture smoke")

        script = r"""
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const moduleUrl = pathToFileURL(process.argv[1]).href;
const { buildViewModels, VIEW_BUNDLE_FIELDS } = await import(moduleUrl);
const contract = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const allowed = new Set(contract.bundle_fields);
for (const fields of Object.values(VIEW_BUNDLE_FIELDS)) {
  for (const field of fields) {
    if (!allowed.has(field)) throw new Error("undocumented bundle field: " + field);
  }
}
for (const fixturePath of process.argv.slice(3)) {
  const payload = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  const views = buildViewModels(payload);
  if (!views.raw || !views.result || !views.diagnostics) {
    throw new Error("fixture did not render required views: " + fixturePath);
  }
}
"""
        fixtures = [
            REST_EXAMPLES / "complete-response.json",
            REST_EXAMPLES / "partial-response.json",
            REST_EXAMPLES / "unresolved-response.json",
            REST_EXAMPLES / "invalid-request-error.json",
            REST_EXAMPLES / "service-unavailable-error.json",
        ]
        subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                script,
                str(CONSOLE / "app-core.mjs"),
                str(CONSOLE / "public-contract.json"),
                *map(str, fixtures),
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_malicious_public_text_can_only_reach_text_content_renderer(self):
        app = (CONSOLE / "app.js").read_text(encoding="utf-8")
        malicious = '<img src=x onerror="globalThis.pwned=true">'
        # Regression intent: external values are JSON-serialized and assigned to
        # textContent; there is no HTML parser sink in the frontend.
        rendered = json.dumps({"exact_text": malicious}, ensure_ascii=False, indent=2)
        self.assertIn(malicious, rendered)
        self.assertIn("pre.textContent = JSON.stringify(value, null, 2);", app)
        self.assertNotIn("innerHTML", app)


class CaseConsoleContainerTests(unittest.TestCase):
    image = "col-taxdata-case-console-issue143-test"

    @classmethod
    def setUpClass(cls):
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is unavailable")
        probe = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode != 0:
            raise unittest.SkipTest("docker daemon is unavailable")

    def _free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_image_health_independence_and_real_rest_adapter_proxy(self):
        sys.path.insert(0, str(TOOLS))
        try:
            from case_rest_api import CaseRESTApplication, CaseRESTServer
        finally:
            sys.path.pop(0)

        request_payload = load_json(REST_EXAMPLES / "request.json")
        complete = load_json(REST_EXAMPLES / "complete-response.json")
        bundle = complete["bundle"]
        observed = {}

        def research(case_input):
            observed["case_input"] = case_input
            return bundle

        server = CaseRESTServer(("0.0.0.0", 0), CaseRESTApplication(research))
        api_port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        subprocess.run(
            ["docker", "build", "-t", self.image, "."],
            cwd=CONSOLE,
            check=True,
            capture_output=True,
            text=True,
        )

        console_port = self._free_port()
        name = "col-taxdata-case-console-issue143-test"
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        try:
            run = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--add-host",
                    "host.docker.internal:host-gateway",
                    "-e",
                    f"CASE_API_UPSTREAM=http://host.docker.internal:{api_port}",
                    "-p",
                    f"127.0.0.1:{console_port}:8080",
                    self.image,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(run.stdout.strip())

            deadline = time.monotonic() + 20
            while True:
                try:
                    with urlopen(
                        f"http://127.0.0.1:{console_port}/healthz", timeout=1
                    ) as response:
                        self.assertEqual(response.status, 200)
                        break
                except Exception:
                    if time.monotonic() >= deadline:
                        self.fail("console did not become healthy")
                    time.sleep(0.25)

            body = json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            req = Request(
                f"http://127.0.0.1:{console_port}/api/v1/cases",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=10) as response:
                proxied = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
            self.assertEqual(proxied["api_version"], "1.0.0")
            self.assertEqual(observed["case_input"]["problem_text"], request_payload["problem_text"])
            self.assertEqual(observed["case_input"].get("as_of_date"), request_payload.get("as_of_date"))

            inspect = subprocess.run(
                ["docker", "inspect", name],
                check=True,
                capture_output=True,
                text=True,
            )
            data = json.loads(inspect.stdout)[0]
            self.assertEqual(data["Mounts"], [])
            self.assertIn(
                data["State"]["Health"]["Status"],
                {"starting", "healthy"},
            )

            # Backend lifecycle is independent: stopping the CASE adapter must not
            # make the static console health endpoint fail.
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            with urlopen(
                f"http://127.0.0.1:{console_port}/healthz", timeout=2
            ) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            subprocess.run(["docker", "rmi", "-f", self.image], capture_output=True)


if __name__ == "__main__":
    unittest.main()
