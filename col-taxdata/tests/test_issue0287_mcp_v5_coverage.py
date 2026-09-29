"""Regression tests for GitHub issue #287 MCP v5 coverage compatibility."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = PROJECT_ROOT / "mcp_gateway"
V1_FIXTURES = PROJECT_ROOT / "specs" / "application" / "examples" / "case-rest-v1"
V2_FIXTURES = PROJECT_ROOT / "specs" / "application" / "examples" / "case-rest-v2"

sys.path.insert(0, str(MCP_ROOT))

import gateway as gateway_module  # noqa: E402
from gateway import (  # noqa: E402
    CASE_CONTRACT_VERSION,
    GATEWAY_CONTRACT_VERSION,
    SUPPORTED_CASE_CONTRACT_VERSIONS,
    TOOL_NAMES,
    V5_CASE_CONTRACT_VERSION,
    BundleStore,
    CaseRestClient,
    GatewayConfig,
    GatewayError,
    GatewayService,
)


def load_fixture(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def request_kwargs(root: Path) -> dict:
    value = load_fixture(root, "request.json")
    return {
        "problem_text": value["problem_text"],
        "as_of_date": value.get("as_of_date"),
        "client_reference": value.get("client_reference"),
        "caller_metadata": value.get("caller_metadata"),
    }


def success_factory(root: Path, fixture_name: str, contract_version: str):
    fixture = load_fixture(root, fixture_name)

    def factory(raw: bytes) -> tuple[int, dict]:
        submitted = json.loads(raw)
        case_input = {
            "kind": "case_input",
            "contract_version": contract_version,
            **submitted,
        }
        payload = deepcopy(fixture)
        if payload["bundle"]["case_input"] != case_input:
            raise AssertionError("REST fixture no longer matches its request fixture")
        payload["request_fingerprints"] = {
            "raw_request_sha256": hashlib.sha256(raw).hexdigest(),
            "case_input_sha256": hashlib.sha256(
                canonical_bytes(case_input)
            ).hexdigest(),
        }
        return 200, payload

    return factory


class RunningMockREST:
    def __init__(self, expected_path: str, factory):
        self.expected_path = expected_path
        self.factory = factory
        self.paths: list[str] = []
        self.server = None
        self.thread = None

    def __enter__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def do_POST(self):
                outer.paths.append(self.path)
                if self.path != outer.expected_path:
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                status, payload = outer.factory(raw)
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
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def base_url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        assert self.server is not None
        assert self.thread is not None
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def all_mapping_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(all_mapping_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(all_mapping_keys(child))
    return keys


def missing_fact_bundle() -> dict:
    payload = load_fixture(V2_FIXTURES, "complete-response.json")
    bundle = payload["bundle"]
    bundle["status"] = "partial"
    bundle["research_result"]["status"] = "partial"

    missing_fact = {
        "kind": "intake_fact",
        "contract_version": "5.0.0",
        "fact_ref": "fact:personal-threshold",
        "label": "Monto personal para evaluar el umbral",
        "state": "missing",
        "requires_confirmation": True,
        "needed_information": "Indique el monto personal que debe compararse con el umbral.",
    }
    bundle["intake_draft"]["facts"].append(missing_fact)

    personal_aspect = {
        "kind": "research_aspect",
        "contract_version": "5.0.0",
        "aspect_ref": "aspect:personal-threshold",
        "question_ref": "question:q1",
        "origin": "profile",
        "scope_status": "profiled_finite",
        "dimension_key": "personal-threshold",
        "research_goal": "Evaluar la regla general con el dato personal faltante.",
        "required": True,
        "fact_refs": ["fact:personal-threshold"],
        "sequence": 1,
        "decomposition_status": "certain",
        "profile_id": "fixture-tax",
        "profile_version": "1",
    }
    personal_task = {
        "kind": "research_task",
        "contract_version": "5.0.0",
        "task_ref": "task:personal-threshold",
        "question_ref": "question:q1",
        "aspect_ref": "aspect:personal-threshold",
        "required": True,
        "origin": "platform_required",
        "purpose": "primary_research",
        "strategy": "thematic_search",
        "target": {"kind": "query", "query_text": "evaluación personal del umbral"},
        "depth": 0,
        "sequence": 1,
    }
    omission = {
        "kind": "omitted_work",
        "contract_version": "5.0.0",
        "omission_ref": "omission:personal-threshold",
        "aspect_ref": "aspect:personal-threshold",
        "task_ref": "task:personal-threshold",
        "class": "research",
        "reason": "blocked_by_facts",
        "required": True,
        "description": "La evaluación personal requiere el monto faltante.",
    }
    unresolved = {
        "kind": "unresolved_item",
        "contract_version": "5.0.0",
        "unresolved_ref": "unresolved:personal-threshold",
        "stage": "coverage",
        "category": "missing_fact",
        "description": "No puede personalizarse la evaluación sin el monto del caso.",
        "related_fact_refs": ["fact:personal-threshold"],
        "related_question_refs": ["question:q1"],
        "related_aspect_refs": ["aspect:personal-threshold"],
        "related_task_refs": ["task:personal-threshold"],
        "related_coverage_refs": ["coverage:personal-threshold"],
        "related_omission_refs": ["omission:personal-threshold"],
        "needed_information": missing_fact["needed_information"],
        "next_action": "ask_client",
    }
    coverage = {
        "kind": "aspect_coverage",
        "contract_version": "5.0.0",
        "coverage_ref": "coverage:personal-threshold",
        "aspect_ref": "aspect:personal-threshold",
        "task_refs": ["task:personal-threshold"],
        "selection_refs": [],
        "omission_refs": ["omission:personal-threshold"],
        "unresolved_refs": ["unresolved:personal-threshold"],
        "execution_status": "blocked",
        "evidence_status": "not_assessed",
        "authority_status": "unassessed",
        "temporal_status": "unassessed",
        "fact_status": "missing",
        "synthesis_status": "requires_facts",
        "support_closure": "incomplete",
        "limitation_codes": ["missing_facts"],
    }

    bundle["research_plan"]["aspects"].append(personal_aspect)
    bundle["research_plan"]["tasks"].append(personal_task)
    bundle["research_result"]["aspect_coverage"].append(coverage)
    bundle["research_result"]["omitted_work"].append(omission)
    bundle["research_result"]["unresolved_refs"].append(unresolved["unresolved_ref"])
    bundle["unresolved"].append(unresolved)
    return payload


class Issue0287VersionNegotiationTests(unittest.TestCase):
    def test_historical_v4_remains_default_and_exact(self):
        factory = success_factory(V1_FIXTURES, "complete-response.json", "4.0.0")
        with RunningMockREST("/v1/cases", factory) as running:
            service = GatewayService.from_config(GatewayConfig(base_url=running.base_url))
            result = service.research_case(**request_kwargs(V1_FIXTURES))

        self.assertEqual(CASE_CONTRACT_VERSION, "4.0.0")
        self.assertEqual(result["bundle"], load_fixture(V1_FIXTURES, "complete-response.json")["bundle"])
        self.assertNotIn("research_coverage", result)
        self.assertEqual(running.paths, ["/v1/cases"])

    def test_explicit_v5_uses_rest_v2_and_preserves_full_bundle_and_coverage(self):
        expected = load_fixture(V2_FIXTURES, "complete-response.json")
        factory = success_factory(V2_FIXTURES, "complete-response.json", "5.0.0")
        with RunningMockREST("/v2/cases", factory) as running:
            service = GatewayService.from_config(GatewayConfig(base_url=running.base_url))
            result = service.research_case(
                **request_kwargs(V2_FIXTURES),
                case_contract_version=V5_CASE_CONTRACT_VERSION,
            )
            reread = service.get_case_research(bundle_handle=result["bundle_handle"])

        self.assertEqual(SUPPORTED_CASE_CONTRACT_VERSIONS, ("4.0.0", "5.0.0"))
        self.assertEqual(GATEWAY_CONTRACT_VERSION, "2.0.0")
        self.assertEqual(running.paths, ["/v2/cases"])
        self.assertEqual(result["bundle"], expected["bundle"])
        self.assertEqual(reread["bundle"], expected["bundle"])
        coverage = result["research_coverage"]
        self.assertEqual(
            coverage["questions"],
            expected["bundle"]["intake_draft"]["questions"],
        )
        self.assertEqual(
            coverage["aspects"],
            expected["bundle"]["research_plan"]["aspects"],
        )
        self.assertEqual(
            coverage["evidence_selections"],
            expected["bundle"]["research_result"]["evidence_selections"],
        )
        self.assertEqual(
            coverage["aspect_coverage"],
            expected["bundle"]["research_result"]["aspect_coverage"],
        )
        self.assertEqual(
            coverage["unresolved"],
            expected["bundle"]["unresolved"],
        )
        self.assertNotIn("supported", all_mapping_keys(coverage))
        self.assertIn("not a legal conclusion", coverage["projection_notice"])

    def test_unsupported_version_fails_before_http_with_actionable_stable_error(self):
        client = CaseRestClient(GatewayConfig(base_url="http://case-rest.example:8765"))
        with mock.patch.object(gateway_module.urlrequest, "urlopen") as opener:
            with self.assertRaises(GatewayError) as raised:
                client.research_case(
                    problem_text="unsupported version fixture",
                    case_contract_version="6.0.0",
                )

        self.assertEqual(raised.exception.code, "MCP_CASE_UNSUPPORTED_VERSION")
        self.assertFalse(raised.exception.retryable)
        self.assertIn("6.0.0", raised.exception.message)
        self.assertIn("4.0.0, 5.0.0", raised.exception.message)
        opener.assert_not_called()

    def test_v2_public_error_keeps_existing_mcp_mapping(self):
        fixture = load_fixture(V2_FIXTURES, "service-unavailable-error.json")

        def factory(raw: bytes):
            payload = deepcopy(fixture)
            payload["request_fingerprints"] = {
                "raw_request_sha256": hashlib.sha256(raw).hexdigest()
            }
            return 503, payload

        with RunningMockREST("/v2/cases", factory) as running:
            client = CaseRestClient(GatewayConfig(base_url=running.base_url))
            with self.assertRaises(GatewayError) as raised:
                client.research_case(
                    **request_kwargs(V2_FIXTURES),
                    case_contract_version="5.0.0",
                )

        self.assertEqual(raised.exception.code, "MCP_CASE_UPSTREAM_UNAVAILABLE")
        self.assertEqual(
            raised.exception.upstream_code,
            "CASE_API_SERVICE_UNAVAILABLE",
        )
        self.assertTrue(raised.exception.retryable)


class Issue0287CoverageProjectionTests(unittest.TestCase):
    def service_with_v5_bundle(self, payload: dict) -> tuple[GatewayService, str]:
        store = BundleStore()
        handle = store.put(payload)
        return GatewayService(rest_client=object(), store=store), handle

    def test_evidence_and_authority_views_navigate_only_explicit_v5_links(self):
        payload = load_fixture(V2_FIXTURES, "complete-response.json")
        service, handle = self.service_with_v5_bundle(payload)
        bundle = payload["bundle"]
        evidence = bundle["evidence_spans"][0]
        authority = bundle["authorities"][0]

        evidence_view = service.get_evidence(
            bundle_handle=handle,
            evidence_ref=evidence["evidence_ref"],
        )
        authority_view = service.get_authority(
            bundle_handle=handle,
            authority_ref=authority["authority_ref"],
        )

        for view in (evidence_view, authority_view):
            links = view["research_links"]
            self.assertEqual(links["questions"], bundle["intake_draft"]["questions"])
            self.assertEqual(links["aspects"], bundle["research_plan"]["aspects"])
            self.assertEqual(
                links["evidence_selections"],
                bundle["research_result"]["evidence_selections"],
            )
            self.assertEqual(
                links["aspect_coverage"],
                bundle["research_result"]["aspect_coverage"],
            )
            self.assertEqual(links["unresolved"], [])
            self.assertNotIn("supported", all_mapping_keys(links))

        self.assertEqual(evidence_view["evidence_span"], evidence)
        self.assertEqual(evidence_view["authority"], authority)

    def test_missing_personal_fact_is_visible_without_blocking_general_support(self):
        payload = missing_fact_bundle()
        service, handle = self.service_with_v5_bundle(payload)

        view = service.get_case_research(bundle_handle=handle)
        coverage = view["research_coverage"]
        by_aspect = {
            item["aspect_ref"]: item for item in coverage["aspect_coverage"]
        }

        self.assertEqual(view["bundle"]["status"], "partial")
        self.assertEqual(
            by_aspect["aspect:narrow-rule"]["support_closure"],
            "complete",
        )
        self.assertEqual(
            by_aspect["aspect:personal-threshold"]["fact_status"],
            "missing",
        )
        self.assertEqual(
            by_aspect["aspect:personal-threshold"]["synthesis_status"],
            "requires_facts",
        )
        self.assertEqual(
            coverage["missing_or_ambiguous_facts"][0]["needed_information"],
            "Indique el monto personal que debe compararse con el umbral.",
        )
        self.assertEqual(
            coverage["unresolved"][0]["needed_information"],
            "Indique el monto personal que debe compararse con el umbral.",
        )
        self.assertEqual(
            coverage["unresolved"][0]["next_action"],
            "ask_client",
        )

    def test_tool_surface_remains_seven_and_no_pagination_or_writeback_tool_is_added(self):
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
        self.assertTrue(
            set(TOOL_NAMES).isdisjoint(
                {
                    "get_next_page",
                    "get_resource_window",
                    "write_inference",
                    "save_inference",
                    "persist_inference",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
