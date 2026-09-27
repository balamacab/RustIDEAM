# Issue #142 — Phase-1 E2E validation report

Date: 2026-09-27  
State: **BLOCKED**  
Automated gate: **AUTOMATED_TECHNICAL_GATE: FAIL**  
Operator acceptance: **NOT REQUESTED**

## Scope

This report records the controlled Phase-1 validation required by GitHub issue #142. No product code was patched in order to make a validation case pass.

Product source under test:

- repository: `balamacab/RustIDEAM`
- project: `col-taxdata/`
- exact `main`: `8c98ffe3379f7a270f201bb809e119d150a7fd14`
- validation branch: `agent/issue-142-e2e-validation`
- harness HEAD at the final scored run: `a4df67ef035eeaf96509ca00ef5df04eb99f52a7`

Current GitHub `main` was revalidated after the failure and remained the same SHA.

## Independent controls frozen before execution

The three fresh #142 cases and their independent authority/evidence controls were committed before any scored model execution in `control-plan.json`.

| Case | Input SHA-256 | Control SHA-256 |
|---|---|---|
| A — natural-person filing | `410a96f2d738846b541e6a4b468c111f090a9ab54f8f45d8cf5f33bd31db0bd6` | `be125739327fcef4c972c1e7f7dc1fa7744a8a0354c884bdab767b7cb0982305` |
| B — export-of-services IVA | `79acbbc54bdb4e4970ae90e2cf775852a2d050fb417b29fd4a5d16963f564458` | `7ddf7098a2c76e149abdb36ed825c1f37c42f12e3167d4099a718dcb578c1c01` |
| C — complex Spain SaaS/services | `05941a02065e0596cd2fcb8deec05034469f4b244920eb131a0e9d8fe015e0b9` | `80d15c4c6ce25f088f20d78d13574cf5fa96ac1baba468d341120742fe82c928` |

Only each `problem_text` was submitted to the internal model. Control material was not supplied to the model.

## Runtime identities

Internal intake runtime:

- profile: `case-migration-rtx3070-v1`
- provider: `operator-llama-cpp-migration-test`
- served model: `gemma-4-E2B-it-Q4_K_M`
- admitted model artifact SHA-256: `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8`
- admitted llama.cpp image digest: `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`
- live health: PASS
- live model discovery: PASS; model name matched the admitted profile
- live context reported by provider: 16384

Published contracts:

- CASE contract: `4.0.0`
- REST API: `1.0.0`
- MCP gateway contract: `1.0.0`
- MCP transport: Streamable HTTP
- MCP path: `/mcp`

Exact-main validation images:

- backend image: `sha256:5ce4b83de84cde3e19ebb77b84e56d8174f8f3b93fca244f1269c53454ccf3a9`
- web image: `sha256:33d8693d907aa9be5e5229f3a0be9251443217f60bbc7b5f19a78a1fc3065158`
- MCP image: `sha256:3c2829e3b32c44b3bf127483331ddb3e546f65bc4885a4e1c8fad4373343e157`

Scored-run container IDs captured before teardown:

- backend: `cd88f4dfca77870c36118dbfe4bae04ef5c0cb7ca85bf8f14d7013c0175fab28`
- web: `a52acb504b80004d6da0d27c5afa1b583b2edd128edb7bcd1148bbbea381d54d`
- MCP: `688a98ee211e6f3c0ae955dc5bec84d505a755f950e58691139dc0071ab1de73`

## Isolated state

The production database was opened read-only and copied with Python SQLite's online backup API into the isolated #142 validation root. Current isolated state identity after applying exact-main migrations:

- database SHA-256: `e4355610be8f4e49005d5d281e9ce74c69ea301cb9e504ae9b7dfeb13b8d3a00`
- manifestations: `1984`
- deterministic `(manifestation_id, sha256)` registry fingerprint: `1d8740fd60a14b77418cd4ff806a1a0fd9eca8ccdfc02be4bfb2f3b9c6126645`

The backend never mounted the production corpus/data path. Its writable mounts were limited to the isolated validation state/case root; the validation harness itself was read-only. Web and MCP had no filesystem mounts. The production crawler remained running and untouched.

## Repository validation

Before the fresh E2E cases, the selected integrated issue-test suite ran against the exact main worktree:

`Ran 167 tests in 10.089s — OK`

This proves the merged unit/integration contracts still pass, but it does not override the real-corpus E2E failure below.

## Scored E2E results

### A — REST

Transport: direct public `POST /v1/cases`.

Result:

- HTTP: `500`
- error: `CASE_API_INTERNAL_ERROR`
- retryable: `false`
- case-input fingerprint: `c0502cd7f19ed2ffa2ac1b3b56cb3bd0fdfab98c1767f81997160d26b4cd8117`
- raw-request fingerprint: `9417a8a251271018c0a7775127ba6e1e32f55469047455b83a6aa3e8986b4589`
- LegalResearchBundle: **not produced**
- bundle SHA-256: **N/A**

### B — independent web console -> REST

Transport: #143 same-origin `/api/v1/cases` proxy to #144.

Result:

- HTTP: `500`
- error: `CASE_API_INTERNAL_ERROR`
- retryable: `false`
- case-input fingerprint: `5fdd697a0924d9c6aca90b711b701256f1ea8d774cd7c79eaf716724eb6495b2`
- raw-request fingerprint: `7d1eea276a6719a75ff7156eb86a803b45fddcf3a68eb2de14e7b26bba5290c3`
- LegalResearchBundle: **not produced**
- bundle SHA-256: **N/A**

The web container itself was healthy and had no backend/SQLite/case filesystem mount.

### C — MCP -> REST

Transport: real MCP v2.2.0 Streamable HTTP client -> #145 gateway -> #144 REST.

The gateway reached the same backend and correctly converted the upstream public failure to:

- MCP error: `MCP_CASE_UPSTREAM_INTERNAL_ERROR`
- upstream: `CASE_API_INTERNAL_ERROR`
- HTTP: `500`
- retryable: `false`
- backend case-input fingerprint: `21f055a11992c7fb8ba2a21414cd0920c017b59958c61764ea4c1629dd06b9a4`
- backend raw-request fingerprint: `ccc50b7742bee28be37caefe99a27721cdced5a430f665a8abd0f11dad0927d0`
- LegalResearchBundle: **not produced**
- bundle SHA-256: **N/A**

MCP discovery-only validation after the failure:

```text
research_case
get_case_research
get_authority
get_provision
get_evidence
get_normative_relationships
get_calculation
```

Prompts: none. Resources: none. This confirms the intended seven-tool semantic surface and no alternate prompt/resource authority surface.

## Root-cause isolation

The failure is not a #133 availability problem.

A separate, explicitly non-scored diagnostic using the exact same admitted #133 profile completed intake structuring:

```text
DIAGNOSTIC_STRUCTURING=PASS
facts 1 questions 1
```

The backend container also reached the admitted provider directly:

- `GET /health`: 200
- `GET /v1/models`: 200
- served model: `gemma-4-E2B-it-Q4_K_M`

A deterministic diagnostic that bypassed the model entirely then isolated the failing boundary:

```text
RESEARCH=PASS authorities 53 evidence_candidates 122 unresolved 84
EVIDENCE_GRAPH=FAIL EvidenceGraphIntegrityError
canonical evidence owner is absent from the authority graph
```

The failure occurs in:

`case_evidence_graph.build_legal_research_bundle() -> _canonical_evidence_span()`

A read-only graph diagnostic over that same research result found:

- research authorities: `53`
- authority-metadata evidence refs examined: `3137`
- evidence refs whose canonical owner document was absent from the selected authority graph: `870`

Representative mismatches included evidence owned by canonical documents such as:

- `authority:DOC-e61ebd5eaa8b5b1387f920074788dc60`
- `authority:DOC-ff2f4fd3534a58f78969da109da61116`
- `authority:DOC-10ef63c1bb775fecbb295fae921ae89a`

The evidence-graph integrity check correctly refuses to fabricate/rebind the owner, but the upstream graph selection/closure is not currently sufficient to materialize a valid bundle.

Focused product defect created: **#178 — [DEFECT][CASE v4] Evidence graph rejects canonical evidence with absent owner authority**.

## Harness failure retained in the audit trail

An earlier #142 attempt failed before the first scored case because the validation harness treated Docker's published TCP port as application readiness. Docker accepted the port before #144 was serving HTTP and the first connection reset.

Evidence showed no REST request event and no case artifact/model execution. The harness was corrected in commit `a4df67ef035eeaf96509ca00ef5df04eb99f52a7` to require an actual #144 HTTP response before submitting a scored case.

The corrected run above is the scored run. The earlier failure was not hidden and was not counted as a model retry.

## Architecture-boundary observations

PASS:

- exact main source used for product containers;
- admitted #133 model/profile reachable;
- internal model can perform intake-only structuring;
- REST returns a stable sanitized error and request fingerprints rather than leaking the internal exception;
- #143 is an independent container and reached CASE only through the public REST proxy;
- #145 is an independent read-only container, reached CASE through REST, exposed exactly seven intended tools, and exposed no prompts/resources;
- MCP preserved the stable upstream error semantics instead of fabricating research;
- web and MCP had no production/backend filesystem mounts;
- production crawler was not stopped/restarted/mutated;
- no raw evidence, canonical identity, or production case state was patched.

Not reached because no LegalResearchBundle could be materialized:

- per-case independent control comparison;
- exact per-case evidence/citation/provision scoring;
- temporal/normative relationship scoring;
- deterministic evaluator/calculation scoring;
- per-case bundle regeneration/idempotency;
- real-bundle web view-model rendering;
- MCP evidence/provision projection from a successful real bundle;
- external-consumer synthesis usability.

## Remote-access efficiency

Planned: 2–3 batched runtime calls.

Actual: 14 remote calls during Phase 1.

The overrun is recorded as a validation-process defect/cost:
- the initially expected runtime checkout was stale and did not contain the validated main object;
- the expected DB path under that checkout was absent;
- the host lacked the `sqlite3` CLI, forcing a safe Python online-backup path;
- one harness readiness race required a corrected pre-execution rerun;
- the real E2E then exposed a sanitized 500, requiring bounded read-only diagnostics to distinguish provider/network failure from research/evidence-graph failure;
- final diagnostics identified the systemic #178 defect without rerunning any scored case.

No production mutation/polling loop was used. The same runtime/device/path facts were reused after discovery.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Fresh independent A/B/C controls frozen before model runs | PASS | committed input/control SHA-256 values |
| Exact #133 backend/profile used | PASS | live model/health + configured profile |
| Model acts as intake structurer, not legal authority | PARTIAL/PASS diagnostic | non-scored intake succeeds; scored bundles fail downstream |
| Platform-owned research executes independently of model prose | PASS diagnostic | deterministic research produced 53 authorities / 122 evidence candidates |
| Canonical evidence graph materializes rigorous traceable support | **FAIL** | `EvidenceGraphIntegrityError`; #178 |
| Controlling/relevant authorities can be scored against independent controls | UNRESOLVED | bundle construction fails before scoring |
| Temporal/normative state can be scored | UNRESOLVED | no bundle |
| Bounded deterministic evaluators/calculations can be scored | UNRESOLVED | no bundle |
| REST public boundary | PASS for failure contract | stable sanitized 500 + fingerprints |
| Independent web console boundary | PASS transport / UNRESOLVED successful rendering | real proxy reaches REST, but no successful bundle |
| MCP semantic boundary | PASS discovery/error mapping / FAIL successful research call | seven tools; upstream bundle not available |
| Successful citable LegalResearchBundle through MCP | **FAIL** | blocked by #178 |
| Raw/prod safety | PASS | isolated snapshot, no production corpus mount/mutation |
| Automated technical gate | **FAIL** | mandatory evidence/bundle criteria not met |
| Operator acceptance | NOT REQUESTED | Phase 1 did not pass |

## Gate decision

**AUTOMATED_TECHNICAL_GATE: FAIL**

#142 MUST remain open and MUST NOT enter `AWAITING_OPERATOR_ACCEPTANCE`.

Recovery is owned by #178. After #178 independently converges on protected `main`, #142 requires a fresh affected controlled run with new provider-reaching attempts as required by the issue. Product code must not be patched inside #142.

## Remaining limitations

This failed Phase-1 run does not establish that the legal controls themselves are satisfied. It establishes a narrower and earlier blocker: current integrated main cannot materialize a LegalResearchBundle for the tested real-corpus research because canonical evidence ownership is not closed over the selected authority graph.
