# CASE v5 REST / Web / MCP Compose deployment

## Purpose

`compose.case.yaml` is the repository-owned, crawler-free application topology
for the current manual-test/product surface:

```text
external/reused provider
        |
        v
case-rest (CASE 5.0.0 / REST 2.0.0)
    |                         |
    v                         v
case-web                  case-mcp
```

The Compose layer only wires already-owned product runtimes. It does not
implement CASE research, retrieval, evidence, persistence, Web projection or MCP
semantics.

## Services and internal contract

The Compose project defines exactly three services:

- `case-rest` runs `python3 tools/case_rest_runtime_v2.py`, the executable
  runtime converged by issue #306;
- `case-web` builds the existing independent CASE console and sends its
  `/api/v2/cases` proxy to `http://case-rest:8766`;
- `case-mcp` builds the existing independent MCP gateway and uses
  `http://case-rest:8766` as its only CASE REST origin.

All three services share the explicit `case-app` bridge network. Web and MCP
have no SQLite, corpus, raw-evidence or CASE-state mount.

`case-web` and `case-mcp` both wait for `case-rest` to become healthy.
CASE readiness is a TCP check on port 8766; the #306 runtime binds that port only
after migration/configuration startup succeeds. Web reuses the console's
browser-chain healthcheck, including the #274 JavaScript/`.mjs` MIME checks.
MCP health uses its existing `/readyz` endpoint.

All services use `restart: unless-stopped`, which supports the intended
detached manual-test lifecycle.

## Required operator inputs

The committed file `docs/case-compose.env.example` is a non-secret example for
rendering the topology. An actual deployment must use an operator-owned env file
with these required values:

- `COL_TAXDATA_CORPUS_DB_PATH`: exact host path to an **isolated writable**
  SQLite corpus snapshot/copy. CASE v5 startup may apply the repository migration
  chain to this copy; do not point it at shared/production state.
- `COL_TAXDATA_CASE_STATE_PATH`: existing host directory for isolated CASE
  publication/output/audit state.
- `COL_TAXDATA_LLM_PROFILE_PATH`: existing host path to the JSON-compatible
  LLM profile consumed by #306.
- `COL_TAXDATA_PROVIDER_BASE_URL`: HTTP(S) provider base URL reachable from
  inside `case-rest`.

Bind mounts use `create_host_path: false`. A missing/typoed source path must
fail rather than silently create a host directory and mount the wrong state.
Raw evidence is not mounted.

The mounted LLM profile owns provider/model/profile identity and the existing
product runtime budgets such as request timeout, model context and output
limits. Compose maps `COL_TAXDATA_PROVIDER_BASE_URL` to the existing
`COL_TAXDATA_LLM_BASE_URL` override, so an image is not tied to the profile's
placeholder/authoring endpoint. If provider authentication is required, the
profile may set `api_key_env` to `COL_TAXDATA_LLM_API_KEY`; supply that value
only from the operator-owned environment. The committed example contains no
credential.

Do not use a provider URL that only listens on host loopback. This topology does
not assume `host.docker.internal`. When a Morichal/manual-test provider is
reachable only through an existing Docker network/alias, issue #301 owns the
runtime-specific network attachment/override and still supplies the explicit
provider URL.

## Optional runtime values

The environment also supports:

- `COL_TAXDATA_COMPOSE_PROJECT_NAME` (default `col-taxdata-case`);
- `COL_TAXDATA_BIND_ADDRESS` (default `127.0.0.1`);
- `COL_TAXDATA_REST_HOST_PORT` (default `8766`);
- `COL_TAXDATA_WEB_HOST_PORT` (default `8080`);
- `COL_TAXDATA_MCP_HOST_PORT` (default `8000`);
- `COL_TAXDATA_REST_V2_MAX_REQUEST_BYTES` (default `1048576`);
- `CASE_API_READ_TIMEOUT_SECONDS` (default `7260`);
- `CASE_REST_TIMEOUT_SECONDS` (default `7260`);
- `MCP_PATH` (default `/mcp`);
- `MCP_MAX_REQUEST_BYTES` (default `1048576`);
- `MCP_MAX_RESPONSE_BYTES` (default `8388608`);
- `MCP_BUNDLE_CACHE_ENTRIES` (default `32`).

The Web and MCP timeout defaults preserve their existing contracts and exceed
the admitted synchronous CASE runtime budget.

## Render/validate the topology

From `col-taxdata/`:

```bash
docker compose \
  --env-file docs/case-compose.env.example \
  -f compose.case.yaml \
  config
```

That command is non-mutating and requires no running Docker daemon. The example
paths are placeholders for configuration rendering only.

## Local-checkout lifecycle

For development from a checkout whose revision the operator has already
verified, copy the example environment to an operator-owned file, replace all
runtime paths/provider values, create the isolated inputs, then run:

```bash
docker compose --env-file /path/to/case.env -f compose.case.yaml up -d --build
docker compose --env-file /path/to/case.env -f compose.case.yaml ps
docker compose --env-file /path/to/case.env -f compose.case.yaml down
```

The local file deliberately builds the current checkout and tags images with
`COL_TAXDATA_IMAGE_TAG` (default `local`). It must not be used as evidence
that an immutable protected-main SHA was deployed.

## Immutable protected-main revision

When an operation requests an exact protected-main SHA, use the remote override
and one 40-character `COL_TAXDATA_REVISION`. The same value is used for every
Git build context and every image tag, so the build cannot silently fall back to
a stale local checkout:

```bash
export COL_TAXDATA_REVISION=<exact-protected-main-sha>

docker compose \
  --env-file /path/to/case.env \
  -f compose.case.yaml \
  -f compose.case.remote.yaml \
  config

docker compose \
  --env-file /path/to/case.env \
  -f compose.case.yaml \
  -f compose.case.remote.yaml \
  up -d --build

docker compose \
  --env-file /path/to/case.env \
  -f compose.case.yaml \
  -f compose.case.remote.yaml \
  ps

docker compose \
  --env-file /path/to/case.env \
  -f compose.case.yaml \
  -f compose.case.remote.yaml \
  down
```

`compose.case.remote.yaml` uses Git build contexts rooted at that exact
revision for `col-taxdata`, `web/case-console` and `mcp_gateway`; it does
not consume the local working tree.

## Ownership boundary with issue #301

Issue #307 owns only this reusable deployment definition and its static
validation. Issue #301 remains responsible for selecting/revalidating the exact
protected-main SHA, creating the isolated corpus copy and CASE-state directory,
supplying the operator env/profile, attaching a reused provider network when
needed, starting the stack, verifying readiness/retrieval, leaving it running,
and publishing the created/reused inventory.

No crawler, scheduler, Case Generator or Case Tester belongs in this Compose
project.
