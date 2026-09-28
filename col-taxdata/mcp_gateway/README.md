# col-taxdata MCP legal-research gateway

This directory is the independently deployable MCP adapter introduced by GitHub issue #145.

## Boundary

```text
MCP client / external LLM
        |
        | MCP semantic tools
        v
col-taxdata-mcp
        |
        | HTTP/JSON only
        v
CASE public REST v1
```

The gateway does **not** import CASE/backend Python packages, open SQLite, read corpus/case files, mount backend storage, or call an inference provider. Its only semantic dependency is the published CASE REST v1 contract.

The gateway keeps a small bounded in-memory cache so follow-up tools can address a bundle returned by `research_case`. A `mcpbundle:...` handle is an ephemeral gateway-local convenience identifier; it is not canonical legal identity and is never persisted.

## Originating LLM/file responsibility

If the user supplied PDFs, images, spreadsheets, email, or other artifacts, the originating LLM/client must inspect those artifacts in its own environment, extract the relevant facts/questions, and submit a self-contained textual `problem_text`.

The MCP contract intentionally has no binary upload, filesystem-path, arbitrary-document-URL, OCR, or attachment-persistence argument. The returned LegalResearchBundle supplies legal research/evidence. Any interpretation, synthesis, or final prose produced by the external LLM remains consumer-owned and cannot be written back as canonical evidence through this gateway.

## MCP tools

The server exposes exactly these semantic tools:

- `research_case` — submit caller-owned textual case fields through `POST /v1/cases`;
- `get_case_research` — retrieve the exact cached REST bundle;
- `get_authority` — project one existing canonical authority and its bundle support;
- `get_provision` — project an existing provision reference/evidence without inventing a standalone Provision object;
- `get_evidence` — return an exact evidence span with authority/source;
- `get_normative_relationships` — filter relationships already present in the bundle;
- `get_calculation` — return a deterministic calculation trace and cited supports.

There is no generic HTTP proxy, URL-fetch tool, provider tool, canonical-evidence write tool, prompt surface, or resource surface.

## Runtime configuration

Required for Streamable HTTP:

- `CASE_REST_BASE_URL` — base URL of a server implementing CASE REST v1;
- `MCP_HOST` — listen host supplied at deployment time.

Optional:

- `MCP_PORT` (default `8000`);
- `MCP_PATH` (default `/mcp`);
- `CASE_REST_TIMEOUT_SECONDS` (default `7260`; valid range `7201` through `86400`);
- `MCP_MAX_REQUEST_BYTES` (default `1048576`);
- `MCP_MAX_RESPONSE_BYTES` (default `8388608`);
- `MCP_BUNDLE_CACHE_ENTRIES` (default `32`).

`CASE_REST_BASE_URL` must be absolute HTTP(S), may not contain embedded credentials, and is fixed for the process lifetime. Tool calls cannot supply or override upstream URLs.

`CASE_REST_TIMEOUT_SECONDS` bounds the synchronous MCP→REST request. The lower bound deliberately exceeds the admitted `7200`-second CASE request budget, and the default adds 60 seconds of outer-transport grace. MCP must therefore not expire a request that is still valid under the supported CASE runtime. Invalid, non-finite, or out-of-range values fail gateway configuration before serving.

The public process also exposes:

- `GET /healthz` — process health only;
- `GET /readyz` — configuration/server readiness and contract versions.

Neither endpoint exposes the upstream URL, credentials, provider diagnostics, case text, or storage internals.

## Container

The build context is this directory only, so the image cannot accidentally copy backend source or corpus storage.

```bash
docker build -t col-taxdata-mcp:local mcp_gateway
```

The image build runs `runtime_smoke.py` against the installed, pinned MCP SDK and fails if tool discovery or a semantic tool call is broken.

Run through the independent compose file:

```bash
CASE_REST_BASE_URL=http://case-api:8765 \
MCP_HOST=0.0.0.0 \
docker compose -f compose.mcp.yaml up --build mcp
```

No backend filesystem/SQLite volume is mounted. The container root filesystem is read-only apart from `/tmp`.

## Transport and errors

Deployment uses MCP Streamable HTTP. REST v1 public errors are mapped to stable `MCP_CASE_*` tool errors. Upstream exception text, URLs, provider details, stack traces, credentials, and local paths are not copied into MCP errors.

Exact evidence text, source/span refs, SHA-256 values, opaque provenance refs, unresolved state, and deterministic trace objects are passed through from the REST LegalResearchBundle without repair or inference.
