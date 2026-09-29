"""MCP transport adapter for the independent col-taxdata legal-research gateway.

The transport layer is intentionally thin: tools delegate to GatewayService,
which can communicate with CASE only through the published versioned REST
contracts.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from gateway import (
    CASE_CONTRACT_VERSION,
    GATEWAY_CONTRACT_VERSION,
    REST_API_VERSION,
    SUPPORTED_CASE_CONTRACT_VERSIONS,
    SUPPORTED_REST_API_VERSIONS,
    GatewayConfig,
    GatewayConfigError,
    GatewayError,
    GatewayService,
)

ORIGINATING_LLM_INSTRUCTIONS = """
col-taxdata-mcp is a legal-research evidence gateway, not a legal-answer model.

The originating/calling LLM owns extraction from files available in its own
environment. If a user supplies PDFs, images, spreadsheets, emails, or other
artifacts, inspect those artifacts yourself, extract the case facts/questions,
and call research_case with a self-contained textual problem_text plus normal
scalar metadata. Do not pass binary uploads, local filesystem paths, arbitrary
document URLs, OCR jobs, or attachments to this gateway.

col-taxdata owns canonical legal identity, official-source provenance, exact
source spans, temporal/normative relationships, structured rule/evidence data,
bounded deterministic calculations/evaluations, and explicit unresolved state.
Treat those returned structures as the citable support. Any synthesis,
interpretation, or final-answer prose that you generate remains consumer-owned
inference and is not canonical col-taxdata evidence. This gateway exposes no
tool that writes consumer inference back into canonical evidence.
""".strip()


def _tool_error(exc: GatewayError) -> ToolError:
    # Serialize only our stable public error surface. Never forward exception
    # strings from HTTP libraries or upstream service diagnostics.
    return ToolError(
        json.dumps(
            exc.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def build_server(service: GatewayService | None = None) -> MCPServer:
    """Build the MCP server around an injected or environment-backed service."""
    gateway = service or GatewayService.from_env()
    mcp = MCPServer(
        name="col-taxdata-mcp",
        title="col-taxdata Legal Research",
        description=(
            "Independent semantic MCP gateway over the published col-taxdata "
            "versioned CASE REST LegalResearchBundle contracts."
        ),
        instructions=ORIGINATING_LLM_INSTRUCTIONS,
        version=GATEWAY_CONTRACT_VERSION,
    )

    @mcp.tool()
    def research_case(
        problem_text: str,
        as_of_date: str | None = None,
        client_reference: str | None = None,
        caller_metadata: dict[str, str | int | float | bool | None] | None = None,
        case_contract_version: str = CASE_CONTRACT_VERSION,
    ) -> dict[str, Any]:
        """Research a self-contained textual case through versioned CASE REST.

        CASE 4.0.0 remains the historical default. Select 5.0.0 explicitly for
        v5 aspect/coverage semantics. The caller must process files/attachments
        in its own environment before calling this tool.
        """
        try:
            return gateway.research_case(
                problem_text=problem_text,
                as_of_date=as_of_date,
                client_reference=client_reference,
                caller_metadata=caller_metadata,
                case_contract_version=case_contract_version,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_case_research(bundle_handle: str) -> dict[str, Any]:
        """Return the exact cached bundle plus any version-specific projection."""
        try:
            return gateway.get_case_research(bundle_handle=bundle_handle)
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_authority(
        bundle_handle: str,
        authority_ref: str,
    ) -> dict[str, Any]:
        """Return one canonical authority and its exact bundle-backed support."""
        try:
            return gateway.get_authority(
                bundle_handle=bundle_handle,
                authority_ref=authority_ref,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_provision(
        bundle_handle: str,
        provision_ref: str,
    ) -> dict[str, Any]:
        """Project an existing provision ref without inventing provision data."""
        try:
            return gateway.get_provision(
                bundle_handle=bundle_handle,
                provision_ref=provision_ref,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_evidence(
        bundle_handle: str,
        evidence_ref: str,
    ) -> dict[str, Any]:
        """Return an exact evidence span with its authority and official source."""
        try:
            return gateway.get_evidence(
                bundle_handle=bundle_handle,
                evidence_ref=evidence_ref,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_normative_relationships(
        bundle_handle: str,
        authority_ref: str | None = None,
        relationship_type: str | None = None,
    ) -> dict[str, Any]:
        """Return only normative relationships already present in the bundle."""
        try:
            return gateway.get_normative_relationships(
                bundle_handle=bundle_handle,
                authority_ref=authority_ref,
                relationship_type=relationship_type,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool()
    def get_calculation(
        bundle_handle: str,
        calculation_ref: str,
    ) -> dict[str, Any]:
        """Return a deterministic calculation trace and its cited supports."""
        try:
            return gateway.get_calculation(
                bundle_handle=bundle_handle,
                calculation_ref=calculation_ref,
            )
        except GatewayError as exc:
            raise _tool_error(exc) from exc

    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
            }
        )

    @mcp.custom_route("/readyz", methods=["GET"], include_in_schema=False)
    async def readyz(_request: Request) -> JSONResponse:
        # Construction has already validated all required runtime configuration.
        # Readiness deliberately does not create a fake legal-research request.
        return JSONResponse(
            {
                "status": "ready",
                "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
                "case_rest_api_version": REST_API_VERSION,
                "supported_case_contract_versions": list(
                    SUPPORTED_CASE_CONTRACT_VERSIONS
                ),
                "supported_case_rest_api_versions": list(
                    SUPPORTED_REST_API_VERSIONS
                ),
            }
        )

    return mcp


def _configured_port() -> int:
    raw = os.environ.get("MCP_PORT", "8000")
    try:
        port = int(raw)
    except ValueError as exc:
        raise GatewayConfigError("MCP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise GatewayConfigError("MCP_PORT must be between 1 and 65535")
    return port


def _configured_path() -> str:
    path = os.environ.get("MCP_PATH", "/mcp")
    if not path.startswith("/") or "?" in path or "#" in path:
        raise GatewayConfigError(
            "MCP_PATH must be an absolute path without query or fragment"
        )
    return path


def main() -> None:
    config = GatewayConfig.from_env()
    service = GatewayService.from_config(config)
    mcp = build_server(service)
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")

    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport != "streamable-http":
        raise GatewayConfigError(
            "MCP_TRANSPORT must be 'streamable-http' or 'stdio'"
        )

    host = os.environ.get("MCP_HOST")
    if not host:
        raise GatewayConfigError(
            "MCP_HOST is required for streamable-http; no host/IP is hardcoded"
        )

    # Protocol framing adds JSON-RPC/MCP overhead beyond the underlying CASE
    # request. The REST payload remains independently bounded by GatewayConfig.
    max_protocol_bytes = config.max_request_bytes * 2
    mcp.run(
        transport="streamable-http",
        host=host,
        port=_configured_port(),
        streamable_http_path=_configured_path(),
        stateless_http=True,
        json_response=True,
        max_request_body_size=max_protocol_bytes,
    )


if __name__ == "__main__":
    main()
