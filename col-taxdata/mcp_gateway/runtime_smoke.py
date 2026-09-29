"""Container-build smoke test against the installed MCP SDK."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from mcp import Client

from gateway import CASE_CONTRACT_VERSION, REST_API_VERSION, TOOL_NAMES, GatewayService
from server import build_server


class FixtureRestClient:
    def research_case(
        self,
        *,
        problem_text,
        as_of_date=None,
        client_reference=None,
        caller_metadata=None,
        case_contract_version=CASE_CONTRACT_VERSION,
    ):
        assert case_contract_version == CASE_CONTRACT_VERSION
        external = {"problem_text": problem_text}
        if as_of_date is not None:
            external["as_of_date"] = as_of_date
        if client_reference is not None:
            external["client_reference"] = client_reference
        if caller_metadata is not None:
            external["caller_metadata"] = deepcopy(dict(caller_metadata))
        case_input = {
            "kind": "case_input",
            "contract_version": CASE_CONTRACT_VERSION,
            **external,
        }
        bundle = {
            "kind": "legal_research_bundle",
            "contract_version": CASE_CONTRACT_VERSION,
            "bundle_ref": "bundle:runtime-smoke",
            "status": "blocked",
            "case_input": case_input,
            "intake_draft": {},
            "research_plan": {},
            "research_result": {},
            "sources": [],
            "authorities": [],
            "evidence_spans": [],
            "normative_relationships": [],
            "rule_fragments": [],
            "deterministic_evaluations": [],
            "calculation_traces": [],
            "unresolved": [],
            "generated_at": "2026-09-27T00:00:00Z",
        }
        return {
            "api_version": REST_API_VERSION,
            "request_fingerprints": {
                "raw_request_sha256": "a" * 64,
                "case_input_sha256": "b" * 64,
            },
            "bundle": bundle,
        }


async def main() -> None:
    server = build_server(GatewayService(FixtureRestClient()))
    async with Client(server) as client:
        listing = await client.list_tools()
        names = tuple(tool.name for tool in listing.tools)
        assert names == TOOL_NAMES, (names, TOOL_NAMES)
        assert client.instructions and "originating/calling LLM" in client.instructions

        result = await client.call_tool(
            "research_case",
            {
                "problem_text": "Self-contained test case.",
                "client_reference": "runtime-smoke",
            },
        )
        assert not result.is_error
        assert result.structured_content is not None
        assert result.structured_content["bundle"]["bundle_ref"] == "bundle:runtime-smoke"

        # No prompts/resources become alternative privileged surfaces.
        assert (await client.list_prompts()).prompts == []
        assert (await client.list_resources()).resources == []


if __name__ == "__main__":
    asyncio.run(main())
