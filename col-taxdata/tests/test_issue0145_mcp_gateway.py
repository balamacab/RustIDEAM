"""Regression and boundary tests for GitHub issue #145."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = PROJECT_ROOT / "mcp_gateway"
TOOLS_ROOT = PROJECT_ROOT / "tools"
FIXTURE_ROOT = (
    PROJECT_ROOT / "specs" / "application" / "examples" / "case-rest-v1"
)

sys.path.insert(0, str(MCP_ROOT))

from gateway import (  # noqa: E402
    CASE_CONTRACT_VERSION,
    REST_API_VERSION,
    TOOL_NAMES,
    BundleStore,
    CaseRestClient,
    GatewayConfig,
    GatewayError,
    GatewayService,
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def request_fixture() -> dict:
    return load_fixture("request.json")


def request_kwargs() -> dict:
    value = request_fixture()
    return {
        "problem_text": value["problem_text"],
        "as_of_date": value.get("as_of_date"),
        "client_reference": value.get("client_reference"),
        "caller_metadata": value.get("caller_metadata"),
    }


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def success_factory(fixture_name: str):
    fixture = load_fixture(fixture_name)

    def factory(raw: bytes) -> tuple[int, dict]:
        submitted = json.loads(raw)
        case_input = {
            "kind": "case_input",
            "contract_version": CASE_CONTRACT_VERSION,
            **submitted,
        }
        payload = deepcopy(fixture)
        # The checked-in fixtures share the request fixture. Keep this assertion
        # explicit so tests fail if #144 contract fixtures drift incompatibly.
        if payload["bundle"]["case_input"] != case_input:
            raise AssertionError("REST fixture no longer matches request fixture")
        payload["request_fingerprints"] = {
            "raw_request_sha256": hashlib.sha256(raw).hexdigest(),
            "case_input_sha256": hashlib.sha256(
                canonical_bytes(case_input)
            ).hexdigest(),
        }
        return 200, payload

    return factory


class RunningMockREST:
    def __init__(self, factory):
        self.factory = factory
        self.server = None
        self.thread = None

    def __enter__(self):
        factory = self.factory

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def do_POST(self):
                if self.path != "/v1/cases":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                status, payload = factory(raw)
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        assert self.server is not None
        assert self.thread is not None
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Issue0145ContractFixtureTests(unittest.TestCase):
    def service_for(self, fixture_name: str):
        running = RunningMockREST(success_factory(fixture_name))
        base_url = running.__enter__()
        self.addCleanup(running.__exit__, None, None, None)
        return GatewayService.from_config(GatewayConfig(base_url=base_url))

    def test_complete_partial_and_blocked_fixtures_map_deterministically(self):
        expected = (
            ("complete-response.json", "complete"),
            ("partial-response.json", "partial"),
            ("unresolved-response.json", "blocked"),
        )
        for fixture_name, status in expected:
            with self.subTest(fixture=fixture_name):
                service = self.service_for(fixture_name)
                first = service.research_case(**request_kwargs())
                second = service.research_case(**request_kwargs())

                self.assertEqual(first["bundle"]["status"], status)
                self.assertEqual(first["bundle"], load_fixture(fixture_name)["bundle"])
                self.assertEqual(first["bundle"], second["bundle"])
                self.assertEqual(first["bundle_handle"], second["bundle_handle"])
                self.assertEqual(first["handle_scope"], "ephemeral_noncanonical")
                self.assertEqual(
                    service.get_case_research(
                        bundle_handle=first["bundle_handle"]
                    )["bundle"],
                    first["bundle"],
                )

    def test_exact_evidence_source_refs_spans_and_hashes_survive_projection(self):
        service = self.service_for("complete-response.json")
        researched = service.research_case(**request_kwargs())
        bundle = researched["bundle"]
        handle = researched["bundle_handle"]
        evidence = bundle["evidence_spans"][0]
        source = bundle["sources"][0]

        view = service.get_evidence(
            bundle_handle=handle,
            evidence_ref=evidence["evidence_ref"],
        )

        self.assertEqual(view["evidence_span"], evidence)
        self.assertEqual(view["source"], source)
        self.assertEqual(view["source"]["source_uri"], source["source_uri"])
        self.assertEqual(view["evidence_span"]["exact_text"], evidence["exact_text"])
        self.assertEqual(
            view["evidence_span"]["source_sha256"],
            evidence["source_sha256"],
        )
        self.assertEqual(
            view["evidence_span"]["text_sha256"],
            evidence["text_sha256"],
        )
        self.assertEqual(
            view["evidence_span"]["provenance_ref"],
            evidence["provenance_ref"],
        )
        self.assertEqual(view["evidence_span"]["span_ref"], evidence["span_ref"])

    def test_authority_and_provision_views_only_project_existing_bundle_data(self):
        service = self.service_for("complete-response.json")
        researched = service.research_case(**request_kwargs())
        bundle = researched["bundle"]
        handle = researched["bundle_handle"]
        authority = bundle["authorities"][0]
        provision_ref = authority["provision_refs"][0]

        authority_view = service.get_authority(
            bundle_handle=handle,
            authority_ref=authority["authority_ref"],
        )
        provision_view = service.get_provision(
            bundle_handle=handle,
            provision_ref=provision_ref,
        )

        self.assertEqual(authority_view["authority"], authority)
        self.assertEqual(authority_view["sources"], bundle["sources"])
        self.assertEqual(authority_view["evidence_spans"], bundle["evidence_spans"])
        self.assertEqual(provision_view["provision_ref"], provision_ref)
        self.assertEqual(provision_view["authorities"], [authority])
        self.assertEqual(provision_view["evidence_spans"], bundle["evidence_spans"])
        self.assertIn("does not infer", provision_view["projection_notice"])

        with self.assertRaises(GatewayError) as missing:
            service.get_provision(
                bundle_handle=handle,
                provision_ref="provision:not-present",
            )
        self.assertEqual(missing.exception.code, "MCP_PROVISION_NOT_FOUND")

    def test_relationship_and_calculation_views_never_synthesize_missing_support(self):
        envelope = load_fixture("complete-response.json")
        bundle = envelope["bundle"]
        bundle["normative_relationships"] = [
            {
                "kind": "normative_relationship",
                "contract_version": CASE_CONTRACT_VERSION,
                "relationship_ref": "relationship:fixture",
                "relationship_type": "modifies",
                "source_authority_ref": "authority:law",
                "target_authority_ref": "authority:other",
                "evidence_refs": ["evidence:article-1"],
                "provenance_ref": "provenance:relationship",
                "status": "resolved",
            }
        ]
        bundle["rule_fragments"] = [
            {
                "kind": "rule_fragment",
                "contract_version": CASE_CONTRACT_VERSION,
                "rule_ref": "rule:fixture",
            }
        ]
        bundle["calculation_traces"] = [
            {
                "kind": "calculation_trace",
                "contract_version": CASE_CONTRACT_VERSION,
                "calculation_ref": "calculation:fixture",
                "rule_refs": ["rule:fixture"],
                "evidence_refs": ["evidence:article-1"],
                "formula": "x",
            }
        ]
        bundle["deterministic_evaluations"] = [
            {
                "kind": "deterministic_evaluation",
                "contract_version": CASE_CONTRACT_VERSION,
                "evaluation_ref": "evaluation:fixture",
                "calculation_trace_refs": ["calculation:fixture"],
            }
        ]
        store = BundleStore()
        handle = store.put(envelope)
        service = GatewayService(rest_client=object(), store=store)

        relationships = service.get_normative_relationships(
            bundle_handle=handle,
            authority_ref="authority:law",
        )
        calculation = service.get_calculation(
            bundle_handle=handle,
            calculation_ref="calculation:fixture",
        )

        self.assertEqual(
            relationships["normative_relationships"],
            bundle["normative_relationships"],
        )
        self.assertEqual(calculation["calculation"], bundle["calculation_traces"][0])
        self.assertEqual(
            calculation["deterministic_evaluations"],
            bundle["deterministic_evaluations"],
        )
        self.assertEqual(calculation["rule_fragments"], bundle["rule_fragments"])
        self.assertEqual(calculation["evidence_spans"], bundle["evidence_spans"])


class Issue0145RestBoundaryTests(unittest.TestCase):
    def test_public_rest_error_maps_to_stable_mcp_error_without_message_leak(self):
        def factory(raw: bytes):
            payload = load_fixture("service-unavailable-error.json")
            payload["request_fingerprints"] = {
                "raw_request_sha256": hashlib.sha256(raw).hexdigest()
            }
            return 503, payload

        with RunningMockREST(factory) as base_url:
            client = CaseRestClient(GatewayConfig(base_url=base_url))
            with self.assertRaises(GatewayError) as raised:
                client.research_case(**request_kwargs())

        error = raised.exception
        self.assertEqual(error.code, "MCP_CASE_UPSTREAM_UNAVAILABLE")
        self.assertTrue(error.retryable)
        self.assertEqual(error.upstream_code, "CASE_API_SERVICE_UNAVAILABLE")
        self.assertNotIn(
            load_fixture("service-unavailable-error.json")["error"]["message"],
            error.message,
        )

    def test_fingerprint_rebinding_is_rejected(self):
        base_factory = success_factory("complete-response.json")

        def factory(raw: bytes):
            status, payload = base_factory(raw)
            payload["request_fingerprints"]["case_input_sha256"] = "f" * 64
            return status, payload

        with RunningMockREST(factory) as base_url:
            client = CaseRestClient(GatewayConfig(base_url=base_url))
            with self.assertRaises(GatewayError) as raised:
                client.research_case(**request_kwargs())

        self.assertEqual(
            raised.exception.code,
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
        )

    def test_request_and_response_limits_are_enforced(self):
        tiny = GatewayConfig(
            base_url="http://127.0.0.1:9",
            max_request_bytes=8,
        )
        with self.assertRaises(GatewayError) as request_error:
            CaseRestClient(tiny).research_case(problem_text="too large")
        self.assertEqual(request_error.exception.code, "MCP_CASE_REQUEST_TOO_LARGE")

        def factory(_raw: bytes):
            return 200, {"padding": "x" * 4096}

        with RunningMockREST(factory) as base_url:
            client = CaseRestClient(
                GatewayConfig(base_url=base_url, max_response_bytes=128)
            )
            with self.assertRaises(GatewayError) as response_error:
                client.research_case(problem_text="x")
        self.assertEqual(
            response_error.exception.code,
            "MCP_CASE_RESPONSE_TOO_LARGE",
        )

    def test_tool_calls_cannot_override_upstream_url_or_submit_files(self):
        server_source = (MCP_ROOT / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(server_source)
        tool_defs = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in TOOL_NAMES
        }
        self.assertEqual(set(tool_defs), set(TOOL_NAMES))

        forbidden_arguments = {
            "url",
            "base_url",
            "document_url",
            "file",
            "file_path",
            "filesystem_path",
            "attachment",
            "attachments",
            "binary",
            "ocr",
            "ocr_payload",
            "consumer_inference",
            "final_answer",
        }
        for name, node in tool_defs.items():
            with self.subTest(tool=name):
                arguments = {arg.arg for arg in node.args.args}
                self.assertTrue(arguments.isdisjoint(forbidden_arguments))


class Issue0145ArchitectureTests(unittest.TestCase):
    def test_gateway_has_no_backend_storage_or_inference_provider_dependency(self):
        gateway_source = (MCP_ROOT / "gateway.py").read_text(encoding="utf-8")
        server_source = (MCP_ROOT / "server.py").read_text(encoding="utf-8")
        combined = (gateway_source + "\n" + server_source).lower()

        for forbidden in (
            "import sqlite3",
            "case_application",
            "case_contracts",
            "tools.case_",
            "import openai",
            "import anthropic",
            "import google",
            "llama.cpp",
            "api_key",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

        gateway_tree = ast.parse(gateway_source)
        imported_roots = set()
        for node in ast.walk(gateway_tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(
            imported_roots.issubset(
                {
                    "__future__",
                    "copy",
                    "hashlib",
                    "json",
                    "os",
                    "re",
                    "socket",
                    "collections",
                    "dataclasses",
                    "typing",
                    "urllib",
                }
            ),
            imported_roots,
        )

    def test_deployable_copies_only_gateway_context_and_mounts_no_backend_storage(self):
        dockerfile = (MCP_ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "compose.mcp.yaml").read_text(encoding="utf-8")
        self.assertNotIn("COPY ..", dockerfile)
        self.assertIn("COPY gateway.py server.py runtime_smoke.py /app/", dockerfile)
        self.assertIn("context: ./mcp_gateway", compose)
        self.assertNotIn("volumes:", compose)
        self.assertNotIn("sqlite", compose.lower())
        self.assertNotIn("openai", compose.lower())
        self.assertNotIn("anthropic", compose.lower())
        self.assertNotIn("google", compose.lower())

    def test_gateway_tool_surface_is_exact_and_has_no_writeback_surface(self):
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
        source = (MCP_ROOT / "server.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("write_evidence", source)
        self.assertNotIn("save_inference", source)
        self.assertNotIn("persist_inference", source)

    def test_server_source_compiles_without_importing_runtime_dependency(self):
        source = (MCP_ROOT / "server.py").read_text(encoding="utf-8")
        compile(source, str(MCP_ROOT / "server.py"), "exec")


class Issue0145RealCaseRestAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS_ROOT))
        from case_rest_api import CaseRESTApplication, CaseRESTServer

        cls.CaseRESTApplication = CaseRESTApplication
        cls.CaseRESTServer = CaseRESTServer

    def test_same_gateway_client_works_against_repository_case_rest_server(self):
        fixture = load_fixture("complete-response.json")

        def researcher(_case_input: dict) -> dict:
            return deepcopy(fixture["bundle"])

        server = self.CaseRESTServer(
            ("127.0.0.1", 0),
            self.CaseRESTApplication(researcher),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            service = GatewayService.from_config(
                GatewayConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    timeout_seconds=3,
                )
            )
            result = service.research_case(**request_kwargs())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.assertEqual(result["bundle"], fixture["bundle"])
        self.assertEqual(result["bundle"]["status"], "complete")
        self.assertEqual(
            result["bundle"]["evidence_spans"][0]["exact_text"],
            fixture["bundle"]["evidence_spans"][0]["exact_text"],
        )


if __name__ == "__main__":
    unittest.main()
