# CASE operator console

Issue #143 introduced this directory as an independently deployable presentation
client for the CASE public REST boundary. Issue #286 advances the active browser
contract to REST v2 / CASE v5 so operators can inspect question/aspect research
coverage without turning the browser into a legal inference layer.

## Runtime boundary

The active browser submission path is the same-origin `/api/v2/cases`. nginx
forwards that exact operation to the configured CASE REST origin. The historical
`/api/v1/cases` path remains deliberately available for CASE v4 compatibility and
regression validation. There is no generic proxy route, backend source import,
SQLite access, writable CASE mount, provider credential field, direct model call,
or canonical write-back path.

The console health endpoint is local to the console and deliberately does not
depend on CASE health, so the console lifecycle remains independent.

## Build and run

From this directory:

```bash
docker build -t col-taxdata-web-console:local .
docker run --rm \
  --name col-taxdata-web-console \
  -e CASE_API_UPSTREAM=http://case-api.example:8765 \
  -e CASE_API_READ_TIMEOUT_SECONDS=7260 \
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

`CASE_API_READ_TIMEOUT_SECONDS` controls how long nginx waits between reads from
the synchronous CASE REST response. It must be an integer from 7201 through 86400
seconds. The default is 7260 seconds, which provides 60 seconds of transport grace
beyond the admitted 7200-second CASE validation runtime. If that upstream budget
changes, update this boundary and its regression test together.

Health:

```bash
curl --fail http://127.0.0.1:8080/healthz
```

## Contract, coverage and fixtures

`public-contract.json` is the small browser projection of the authoritative REST
v2 / CASE v5 OpenAPI and JSON Schema. Repository tests compare the projection
with those authoritative artifacts so undocumented assumptions fail CI.

The Coverage view is a read-only projection of public CASE v5 fields:

- question -> research aspect;
- execution/evidence/authority/temporal/fact/support-closure states;
- explicit omissions and unresolved limitations;
- selected exact evidence;
- authority metadata supplied by CASE;
- official source links supplied by CASE;
- explicit external-synthesis handoff where the contract says interpretation is
  outside canonical platform state.

It never upgrades retrieval into legal applicability, guesses missing metadata,
or converts research coverage into a legal conclusion. A blank `as_of_date` is
sent as omission, not replaced with a browser/server clock value; the resulting
unassessed temporal state remains visible.

`fixtures/index.json` continues to contain only public caller-owned request
fields and never auto-submits. `fixtures/coverage-states.json` is a synthetic,
presentation-only regression matrix for complete/partial/blocked,
not-researched, unknown-profile and requires-facts display states. It is not a
corpus artifact or a correctness authority for CASE research.

Raw JSON inspection remains available and `Export raw JSON` downloads the exact
received public payload as formatted JSON for operator inspection.

## Historical compatibility

REST v1 / CASE v4 remains a supported historical response contract. The console
does not fabricate v5 aspect coverage for it: it shows an explicit historical
version message while retaining the existing Result/Research/Evidence/Raw views.
Unsupported or mismatched API/bundle versions likewise produce an explicit
version message and preserve raw JSON rather than silently reinterpreting it.

## Trust boundary

The console is presentation-only. It does not create a legal answer, infer
missing status, validate evidence, calculate taxes, repair responses, invoke a
model, or promote browser/consumer prose to canonical evidence or state.
