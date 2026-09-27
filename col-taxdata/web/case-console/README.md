# CASE operator console

Issue #143 implements this directory as an independently deployable presentation
client for the published CASE REST v1 contract from issue #144.

## Runtime boundary

The browser speaks only to the same-origin path `/api/v1/cases`. nginx forwards
that exact operation to the configured CASE REST **origin**. There is no generic
proxy route, backend source import, SQLite access, writable CASE mount, provider
credential field, or provider/LLM request path.

The console health endpoint is local to the console and deliberately does not depend
on CASE health, so the console lifecycle remains independent.

## Build and run

From this directory:

```bash
docker build -t col-taxdata-web-console:local .
docker run --rm \
  --name col-taxdata-web-console \
  -e CASE_API_UPSTREAM=http://case-api.example:8765 \
  -p 8080:8080 \
  col-taxdata-web-console:local
```

Or:

```bash
CASE_API_UPSTREAM=http://case-api.example:8765 docker compose up --build
```

`CASE_API_UPSTREAM` is runtime-only deployment configuration. It must be an
`http://` or `https://` origin with an optional numeric port and no path, query
or fragment. The value is rendered only into nginx configuration; it is never
delivered to browser JavaScript.

Health:

```bash
curl --fail http://127.0.0.1:8080/healthz
```

## Contract and fixtures

`public-contract.json` is a small client projection of the authoritative #144
OpenAPI/JSON Schema. Repository tests compare the projection with those authoritative
artifacts so undocumented assumptions fail CI.

`fixtures/index.json` contains only public caller-owned request fields. The loader
never submits automatically. It includes the requested DEF-0015, CASE-0002 and
retained historical #67 inputs; it contains no expected answers, canonical IDs,
evidence bindings, source hints, provider controls or credentials.

## Trust boundary

The console displays public LegalResearchBundle state. It does not create a legal
answer, infer missing status, validate evidence, calculate taxes, repair responses or
promote provider metadata to legal authority. Raw JSON remains available for direct
operator inspection.
