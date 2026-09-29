from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "web" / "case-console"
REST_V2_SCHEMA = ROOT / "specs" / "application" / "schemas" / "case-rest-api-v2.schema.json"
V5_SCHEMA = ROOT / "specs" / "application" / "schemas" / "case-contracts-v5.schema.json"
OPENAPI_V2 = ROOT / "specs" / "application" / "openapi" / "case-rest-api-v2.openapi.json"
REST_V2_EXAMPLES = ROOT / "specs" / "application" / "examples" / "case-rest-v2"
DISPLAY_FIXTURES = CONSOLE / "fixtures" / "coverage-states.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Issue0286CaseConsoleCoverageTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_json(CONSOLE / "public-contract.json")
        self.display_fixtures = load_json(DISPLAY_FIXTURES)

    def test_active_projection_matches_authoritative_rest_v2_and_case_v5(self):
        rest = load_json(REST_V2_SCHEMA)
        v5 = load_json(V5_SCHEMA)
        openapi = load_json(OPENAPI_V2)

        request_fields = set(rest["$defs"]["CaseSubmissionRequest"]["properties"])
        success_fields = set(rest["$defs"]["CaseResearchResponse"]["properties"])
        error_fields = set(rest["$defs"]["ErrorResponse"]["properties"])
        bundle_fields = set(v5["$defs"]["LegalResearchBundle"]["properties"])

        self.assertEqual(self.contract["api_version"], "2.0.0")
        self.assertEqual(self.contract["application_contract_version"], "5.0.0")
        self.assertEqual(self.contract["method"], "POST")
        self.assertEqual(self.contract["api_path"], "/v2/cases")
        self.assertEqual(self.contract["proxy_path"], "/api/v2/cases")
        self.assertIn("/api/v1/cases", self.contract["historical_proxy_paths"])
        self.assertIn(self.contract["api_path"], openapi["paths"])
        self.assertEqual(set(self.contract["request_fields"]), request_fields)
        self.assertEqual(set(self.contract["success_top_level_fields"]), success_fields)
        self.assertEqual(set(self.contract["error_top_level_fields"]), error_fields)
        self.assertEqual(set(self.contract["bundle_fields"]), bundle_fields)

    def test_display_fixture_matrix_covers_required_issue_states(self):
        cases = {case["id"]: case for case in self.display_fixtures["cases"]}
        self.assertEqual(
            set(cases),
            {
                "complete",
                "partial-limited",
                "blocked",
                "not-researched",
                "unknown-profile",
                "requires-facts",
            },
        )
        self.assertEqual(cases["complete"]["payload"]["bundle"]["status"], "complete")
        self.assertEqual(cases["partial-limited"]["payload"]["bundle"]["status"], "partial")
        self.assertEqual(cases["blocked"]["payload"]["bundle"]["status"], "blocked")

    def test_browser_projection_and_dom_renderer_expose_states_evidence_and_sources(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable for browser-side ES-module regression")

        script = r'''
import fs from "node:fs";
import { pathToFileURL } from "node:url";

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.className = "";
    this.children = [];
    this.attributes = {};
    this._text = "";
    this.href = "";
    this.target = "";
    this.rel = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent ?? String(child)).join(""); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ""; this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}
const document = { createElement(tag) { return new FakeNode(tag); } };

function walk(node, predicate, output = []) {
  if (predicate(node)) output.push(node);
  for (const child of node.children ?? []) {
    if (child && typeof child === "object") walk(child, predicate, output);
  }
  return output;
}

const coreUrl = pathToFileURL(process.argv[1]).href;
const rendererUrl = pathToFileURL(process.argv[2]).href;
const { buildRequest, buildRawExport, buildViewModels } = await import(coreUrl);
const { renderCoverage, safeHttpUrl } = await import(rendererUrl);
const fixtureDocument = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

for (const scenario of fixtureDocument.cases) {
  const views = buildViewModels(scenario.payload);
  if (!views.coverage?.available) throw new Error(`${scenario.id}: v5 coverage unavailable`);
  const panel = new FakeNode("div");
  renderCoverage(document, panel, views.coverage);
  const rendered = panel.textContent;
  for (const expected of scenario.expected_text) {
    if (!rendered.includes(expected)) {
      throw new Error(`${scenario.id}: missing rendered text: ${expected}\n${rendered}`);
    }
  }
  if (scenario.expected_source_uri) {
    const links = walk(panel, (node) => node.tagName === "A");
    if (!links.some((link) => link.href === scenario.expected_source_uri)) {
      throw new Error(`${scenario.id}: official source link missing`);
    }
  }
}

if (safeHttpUrl("javascript:alert(1)") !== null) throw new Error("unsafe source URI accepted");
if (safeHttpUrl("data:text/html,pwn") !== null) throw new Error("data source URI accepted");

const undated = buildRequest("question", "", "", "");
if (Object.prototype.hasOwnProperty.call(undated, "as_of_date")) throw new Error("blank date was silently inserted");
const dated = buildRequest("question", "2026-09-29", "", "");
if (dated.as_of_date !== "2026-09-29") throw new Error("caller date not preserved");

const exported = buildRawExport(fixtureDocument.cases[0].payload);
if (!exported.filename.includes("2.0.0")) throw new Error("raw export version missing");
if (JSON.parse(exported.text).api_version !== "2.0.0") throw new Error("raw export changed payload");

const legacy = buildViewModels({
  api_version: "1.0.0",
  request_fingerprints: {raw_request_sha256: "a".repeat(64), case_input_sha256: "b".repeat(64)},
  bundle: {kind:"legal_research_bundle", contract_version:"4.0.0", bundle_ref:"bundle:legacy", status:"partial"}
});
if (legacy.coverage.available !== false || legacy.coverage.compatibility !== "legacy") throw new Error("legacy version message missing");
if (!legacy.coverage.version_message.includes("supported historical contract")) throw new Error("legacy contract not explicit");

const unsupported = buildViewModels({
  api_version: "9.0.0",
  request_fingerprints: {},
  bundle: {kind:"legal_research_bundle", contract_version:"9.0.0"}
});
if (unsupported.coverage.compatibility !== "unsupported") throw new Error("unsupported contract not explicit");
if (unsupported.raw.api_version !== "9.0.0") throw new Error("unsupported raw payload was lost");
'''
        subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                script,
                str(CONSOLE / "app-core.mjs"),
                str(CONSOLE / "coverage-renderer.mjs"),
                str(DISPLAY_FIXTURES),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_v2_success_and_error_examples_remain_projectable(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable for ES-module contract fixture smoke")
        script = r'''
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const { buildViewModels } = await import(pathToFileURL(process.argv[1]).href);
for (const path of process.argv.slice(2)) {
  const payload = JSON.parse(fs.readFileSync(path, "utf8"));
  const views = buildViewModels(payload);
  if (!views.raw || !views.result || !views.diagnostics) throw new Error("response view missing: " + path);
}
'''
        subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                script,
                str(CONSOLE / "app-core.mjs"),
                str(REST_V2_EXAMPLES / "complete-response.json"),
                str(REST_V2_EXAMPLES / "invalid-request-error.json"),
                str(REST_V2_EXAMPLES / "service-unavailable-error.json"),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_browser_shell_exposes_coverage_date_policy_and_raw_export(self):
        index = (CONSOLE / "index.html").read_text(encoding="utf-8")
        app = (CONSOLE / "app.js").read_text(encoding="utf-8")
        core = (CONSOLE / "app-core.mjs").read_text(encoding="utf-8")
        renderer = (CONSOLE / "coverage-renderer.mjs").read_text(encoding="utf-8")
        combined = "\n".join((app, core, renderer))

        self.assertIn('data-view="coverage"', index)
        self.assertIn('id="export-raw"', index)
        self.assertIn("If blank, no date is sent", index)
        self.assertIn("Temporal applicability must remain explicitly unassessed", index)
        self.assertIn('from "./coverage-renderer.mjs"', app)
        self.assertIn("buildRawExport", app)
        self.assertIn("URL.createObjectURL", app)
        self.assertIn('credentials: "omit"', app)
        self.assertIn("Interpretive synthesis remains external", renderer)
        self.assertIn("the console does not guess missing fields", renderer)

        for forbidden in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "localStorage",
            "sessionStorage",
            "sqlite",
            "tools/case_",
            "openai",
        ):
            self.assertNotIn(forbidden, combined.lower())

    def test_proxy_is_versioned_and_remains_narrow(self):
        template = (CONSOLE / "nginx" / "case-console.conf.template").read_text(encoding="utf-8")
        self.assertIn("location = /api/v2/cases", template)
        self.assertIn("proxy_pass __CASE_API_UPSTREAM__/v2/cases;", template)
        self.assertIn("location = /api/v1/cases", template)
        self.assertIn("proxy_pass __CASE_API_UPSTREAM__/v1/cases;", template)
        self.assertNotIn("location /api/", template)
        self.assertGreaterEqual(template.count("limit_except POST"), 2)
        self.assertGreaterEqual(template.count('proxy_set_header Cookie "";'), 2)
        self.assertGreaterEqual(template.count('proxy_set_header Authorization "";'), 2)

    def test_module_mime_healthcheck_covers_new_renderer_and_fixture(self):
        dockerfile = (CONSOLE / "Dockerfile").read_text(encoding="utf-8")
        healthcheck = (CONSOLE / "nginx" / "healthcheck.sh").read_text(encoding="utf-8")
        self.assertIn("COPY coverage-renderer.mjs", dockerfile)
        self.assertIn("js mjs;", dockerfile)
        self.assertIn('/coverage-renderer.mjs', healthcheck)
        self.assertIn('/fixtures/coverage-states.json', healthcheck)
        self.assertGreaterEqual(healthcheck.count("(application|text)/javascript"), 3)
        self.assertGreaterEqual(healthcheck.count("application/json"), 3)

    def test_presentation_fixture_is_synthetic_and_not_a_corpus_artifact(self):
        serialized = json.dumps(self.display_fixtures, ensure_ascii=False).lower()
        self.assertIn("synthetic", serialized)
        self.assertNotIn("data/raw", serialized)
        self.assertNotIn("taxdata.sqlite", serialized)
        self.assertNotIn("expected_conclusions", serialized)


if __name__ == "__main__":
    unittest.main()
