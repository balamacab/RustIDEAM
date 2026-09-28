# Issue #142 — Fresh affected Phase-1 r5 validation report

## Gate

**AUTOMATED_TECHNICAL_GATE: FAIL**

Operator acceptance was **not requested**.

This is a fresh affected validation after #188/#189 and their descendant corrections converged. Historical failed #142 executions remain historical evidence and were not reused as PASS evidence. Product code was not patched by #142.

## Exact validated identities

- protected product main: `afcae6d71090307cdb5f573414cc4a455c35a49f`
- CASE contract: `4.0.0`
- REST API: `1.0.0`
- MCP protocol: Streamable HTTP, path `/mcp`
- selected exact-main repository suite: **201/201 PASS**
- intake profile: `case-migration-rtx3070-v1`
- provider: `operator-llama-cpp-migration-test`
- served model: `gemma-4-E2B-it-Q4_K_M`
- admitted model SHA-256: `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8`
- provider context: 16384
- provider GPU layers: 99
- provider image lineage: `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`
- backend image ID: `sha256:34395b776cb4e3ba97270a768ac8b9eca3a90513e102641508040af3fecddc0c`
- web image ID: `sha256:131a515e0d0cf531f9d1a3ce05f72e3633661a5011fd30cf4704472fa979b623`
- MCP image ID: `sha256:45ecd087f574f642cf70882d208d1d9774f695351ca551adfbc498baf22c97f3`
- validation root: `/home/user/col-taxdata-validation-142-r5-afcae6d`
- isolated manifestation count: 1,984

The source corpus was copied with SQLite online backup into isolated writable state. Production raw/canonical state was not mounted as writable application state.

## Frozen controls

All three pre-existing control commitments matched before scoring.

| Case | Problem/control commitment |
|---|---|
| A | problem `410a96f2d738846b541e6a4b468c111f090a9ab54f8f45d8cf5f33bd31db0bd6`; control `be125739327fcef4c972c1e7f7dc1fa7744a8a0354c884bdab767b7cb0982305` |
| B | problem `79acbbc54bdb4e4970ae90e2cf775852a2d050fb417b29fd4a5d16963f564458`; control `7ddf7098a2c76e149abdb36ed825c1f37c42f12e3167d4099a718dcb578c1c01` |
| C | problem `05941a02065e0596cd2fcb8deec05034469f4b244920eb131a0e9d8fe015e0b9`; control `80d15c4c6ce25f088f20d78d13574cf5fa96ac1baba468d341120742fe82c928` |

No scored case was retried.

## Case A — direct REST

- transport: direct REST `POST /v1/cases`
- HTTP status: **500**
- public error: `CASE_API_INTEGRITY_FAILURE`, retryable=false
- private diagnostic family: `structuring_integrity`
- private diagnostic code: `INVALID_INTAKE_DRAFT`
- request SHA-256: `9417a8a251271018c0a7775127ba6e1e32f55469047455b83a6aa3e8986b4589`
- frozen artifact SHA-256: `250f4fc357feaee61a3e2d442eb10c8169769df36821884bab6571aead1b4155`
- rejected attempt: `ATT-1fe4a03846b5475eb492aae2f9fc1b40`
- rejected candidate SHA-256: `d4b44af5e1710f9b89be4020eb427d242b5d57ac3d3bedfcb6a6790d62d5cd20`
- failure path: `$.facts[0].state`
- failure detail: `missing/ambiguous fact conflicts with information already stated in explicit client text`

The provider emitted the selected gross-income and gross-patrimony facts as `missing`, despite the client text explicitly providing 1,100 UVT gross income, 3,900 UVT gross patrimony and the 2025 UVT basis. The fail-closed semantic validator therefore correctly rejected the corrupted IntakeDraft, but the product cannot complete this valid case.

**Result: FAIL.**

## Case B — independent web console -> REST

- transport: independent #143 same-origin `/api/v1/cases` proxy to REST
- HTTP status: **500**
- public error: `CASE_API_INTEGRITY_FAILURE`, retryable=false
- private diagnostic family: `structuring_integrity`
- private diagnostic code: `INVALID_INTAKE_DRAFT`
- request SHA-256: `7d1eea276a6719a75ff7156eb86a803b45fddcf3a68eb2de14e7b26bba5290c3`
- frozen artifact SHA-256: `62ec6ec1aa4a70c016d72dde8e2dc794f2f58a7e6b1032d8d8ea6caede2b00c2`
- rejected attempt: `ATT-0dc28716d86747a6bad5c92d50d265b0`
- rejected candidate SHA-256: `f9cab69520927ff8dd1289f4af25ba1f4dadb92d19beae43fe14b32dd6eb169b`
- failure path: `$.facts[2].state`
- failure detail: `missing/ambiguous fact conflicts with information already stated in explicit client text`

The provider candidate marked the stated Colombian SAS/service nature, Canadian customer, absence of Colombian presence, execution from Colombia, exclusive foreign use, and August-2026 invoice/payment as `missing`. The validator rejected rather than silently accepting false missing state.

**Result: FAIL.**

## Case C — MCP Streamable HTTP -> REST

- transport: real MCP `research_case` -> #144 REST
- bundle ref: `bundle:442722b880c1129f1dbc577f9d525370`
- bundle status: `partial`
- canonical bundle SHA-256: `6606c95fd73e22c024b5b5f594638db06b6c9a547e93c292ecc42218749cf120`
- frozen MCP artifact SHA-256: `3d2ce84cfca6b28b978357333420944b8ca423a8e60a8a653e6215add67e64d9`
- exact tool surface: seven intended tools
- prompts/resources: empty
- follow-up bundle exact-match: PASS
- first-evidence projection exact-match: PASS
- intake questions: 5/5 `legal/open`
- platform-required research coverage: 5/5 open legal questions
- authorities: 311
- EvidenceSpans: 4,016
- normative relationships: 3,090
- RuleFragments: 22
- deterministic evaluations/calculations: 0/0
- unresolved items: 582

The prior #188 C-style question-category defect remains corrected. The prior #189 treaty-coverage defect also remains corrected in this run: exact evidence contains four `beneficios empresariales` hits, seventeen royalty-material hits, forty-five permanent-establishment hits, and fifteen Spain/treaty hits.

Evidence integrity checks over C:

| Invariant | Result |
|---|---:|
| missing EvidenceSpan owner authority | 0 |
| EvidenceSpan document/authority mismatch | 0 |
| missing EvidenceSpan source | 0 |
| recomputed exact-text SHA mismatch | 0 |
| dangling RuleFragment evidence refs | 0 |

The ResearchContext fingerprint is populated with corpus snapshot, schema/migration fingerprint, retrieval configuration/version, planner version and `as_of_date=2026-09-27`; unavailable fields are empty.

**Result: PASS for the C path/control exercised.**

## Independent boundaries / lifecycle

- #143 web has no backend/SQLite mounts.
- MCP has no backend/SQLite mounts.
- backend uses only isolated validation DB/case state plus its normal anonymous `/app/data` volume.
- web independent restart: PASS, `/healthz -> 200 text/plain "ok\n"`.
- backend independent restart: PASS.
- web remained healthy after backend restart: PASS.
- MCP `/readyz`: PASS, gateway/API contract 1.0.0.

Because A/B failed, the web real-result view-model rendering criterion could not be demonstrated with B in this run; the transport failure was correctly surfaced instead.

## Raw/provenance invariants

- manifestation count: **1,984 -> 1,984**
- manifestation SHA-registry fingerprint before/after: `1d8740fd60a14b77418cd4ff806a1a0fd9eca8ccdfc02be4bfb2f3b9c6126645` unchanged
- production corpus/raw evidence mutation: none
- production crawler/service mutation: none

## Owned blocker

No duplicate defect was created.

Existing issue **#254 — Fresh protected main rejects valid A/B intake as INVALID_INTAKE_DRAFT** is OPEN and owned by DEV-1 on the same base SHA `afcae6d...`.

#142 posted the exact r5 rejected-attempt identities, candidate hashes and failure paths to #254. The append-only rejected-attempt evidence remains preserved in the r5 validation root under `case-state/_audit/rejected-structuring-attempts`.

#142 remains blocked until #254 independently converges on protected main and a new affected #142 run is explicitly warranted.

## Validation-harness incidents

### r4 health-contract mismatch

r4 stopped before any scored A/B/C submission because the historical harness attempted to parse #143 `/healthz` as JSON. The authoritative #143 nginx contract is `200 text/plain "ok\n"`.

No r4 A/B/C artifact or Phase-1 summary exists. r4 evidence was frozen and a separate r5 harness was created; no scored attempt was consumed by r4.

### Initial r4 branch-materialization failure

An initial preparation command fetched the recreated validation branch only into `FETCH_HEAD`, leaving the stale remote-tracking ref. Materialization aborted before validation-network creation or provider execution. The corrected setup used an explicit remote-tracking refspec.

These were harness/setup failures, not product PASS/FAIL results.

## Remote access efficiency

Remote runtime was necessary because #142 explicitly requires the admitted real #133 model and actual REST/web/MCP/container-boundary validation.

The initial budget was three batched phases. Actual SSH execution calls materially exceeded that budget because:

1. two pre-score harness/setup failures had to be diagnosed without consuming scored attempts;
2. the SSH MCP server enforces a 30-second per-call limit, while each admitted model execution is longer-running;
3. A/B/C were deliberately executed by one durable runner and observed through bounded artifact checks rather than retried or reissued.

The overrun is retained as an execution-efficiency deviation. No extra provider attempt was used to compensate.

## Acceptance matrix

| Criterion | Status |
|---|---|
| controls committed before scored runs | PASS |
| exact admitted #133 runtime/profile | PASS |
| exact protected-main validation | PASS |
| selected repository suite | PASS — 201/201 |
| REST / web / MCP independent boundaries | PASS |
| raw manifestation registry unchanged | PASS |
| C legal-question classification / platform coverage | PASS |
| C Colombia-Spain treaty material coverage | PASS |
| C evidence owner/source/hash graph | PASS |
| C research-context fingerprint | PASS |
| MCP seven-tool / no-prompts / no-resources surface | PASS |
| independent web/backend lifecycle | PASS |
| A explicit-fact intake acceptance | **FAIL — #254** |
| A bounded evaluator path | **FAIL/BLOCKED — no accepted IntakeDraft** |
| B explicit-fact intake acceptance | **FAIL — #254** |
| B real web-result rendering | **FAIL/BLOCKED — upstream intake failure** |
| complete successful LegalResearchBundle through all A/B/C surfaces | **FAIL** |
| automated technical gate | **FAIL** |
| operator acceptance | NOT REQUESTED |

## Recovery

1. #254 independently resolves/converges on protected main.
2. #142 does not modify product code.
3. A new affected Phase-1 run may then execute only according to the #142 lifecycle and no-retry discipline.
4. Phase 2/operator handoff remains forbidden until a fresh `AUTOMATED_TECHNICAL_GATE: PASS`.

The r5 validation root, logs, isolated DB and rejected-attempt audit evidence remain preserved after teardown of only the r5 validation containers/network.
