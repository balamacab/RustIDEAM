# Issue #142 — Fresh affected Phase-1 recovery report

## Gate

**AUTOMATED_TECHNICAL_GATE: FAIL**

Operator acceptance was **not requested**.

This is the fresh affected validation required after #178/#180 converged. The earlier failed A/B/C executions remain historical evidence and were not reused as PASS evidence.

## Exact validated identities

- protected product main: `98495aa39fe97049449cbebca8708db924c5a8d2`
- CASE contract: `4.0.0`
- REST API: `1.0.0`
- selected exact-main repository suite: **189/189 PASS**
- internal intake profile: `case-migration-rtx3070-v1`
- provider: `operator-llama-cpp-migration-test`
- served model: `gemma-4-E2B-it-Q4_K_M`
- admitted model SHA-256: `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8`
- provider context: 16384
- provider GPU layers: 99
- provider image lineage: `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`
- recovery backend image ID: `sha256:daa8cd9b3d3ac7050bcac6aa6348b37b6ce5b28bff7d567d9d40a86c0c2f166a`
- recovery web image ID: `sha256:bd0e1b688915009a454528c2f9069d07de5c8d8fd95223888d380a5231b036b1`
- recovery MCP image ID: `sha256:e8884300063e63cce7b6fc1090196bccb665ced468a6934668002fa1740ea733`
- validation root: `/home/user/col-taxdata-validation-142-rerun3-98495`
- isolated manifestation count after the run: 1,984

The backend used a validation-only Docker network to reach the admitted provider by container identity rather than host loopback. A probe from inside the CASE backend returned HTTP 200, exact model alias, and `n_ctx=16384`.

## Scored executions

Exactly one corrected provider-reaching execution was retained for each case. No retry-until-pass occurred.

### A — direct REST

- case-input SHA-256: `c0502cd7f19ed2ffa2ac1b3b56cb3bd0fdfab98c1767f81997160d26b4cd8117`
- raw-request SHA-256: `9417a8a251271018c0a7775127ba6e1e32f55469047455b83a6aa3e8986b4589`
- model run: `run:1209561e9368443f8da27bd3f525c390`
- bundle ref: `bundle:6a9cf007b1f75901fbc2095abfd3ee16`
- canonical bundle SHA-256: `eeb4121f47886f0b1557f5e10f8596781f36717687a2803389162bdf238081b7`
- bundle status: `partial`
- authorities: 286
- evidence spans: 3,606
- normative relationships: 2,844
- rules: 36
- deterministic evaluations: 0
- calculations: 0

Control-positive evidence includes Article-592-family material and exact evidence stating the 1,400 UVT gross-income and 4,500 UVT gross-patrimony thresholds.

**Failure:** 4/4 selected facts were emitted as `ambiguous`, including the client-stated 1,100 UVT income and 3,900 UVT patrimony. None retained an exact client source quote. The bounded natural-person evaluator therefore had no confirmed structured inputs and produced no evaluation/calculation.

Owned defect: **#188**.

### B — independent web console proxy -> REST

- case-input SHA-256: `5fdd697a0924d9c6aca90b711b701256f1ea8d774cd7c79eaf716724eb6495b2`
- raw-request SHA-256: `7d1eea276a6719a75ff7156eb86a803b45fddcf3a68eb2de14e7b26bba5290c3`
- model run: `run:dbf2d2e208314b9ca562e1bbd01957ca`
- bundle ref: `bundle:d6dadcc4ee460e1c62b1845079553623`
- canonical bundle SHA-256: `669eeae06fcbf28a7f795ac4ad798dba32f8e3060e55db4e5dff4f9fff6823c3`
- bundle status: `partial`
- authorities: 277
- evidence spans: 3,913

Control-positive evidence includes Article-481/export-of-services material and exact support for services used exclusively abroad.

**Failure:** all 9 selected facts were emitted as `missing`, with 0 exact source quotes, despite the client text explicitly stating the Colombian SAS, Bogotá execution, Canadian customer, absence of Colombian presence, exclusive foreign use, retained supporting documents and August-2026 invoicing/payment.

The real B response successfully rendered through the same pure view-model used by the independent #143 console before case C executed.

Owned defect: **#188**.

### C — MCP Streamable HTTP -> REST

- case-input SHA-256: `21f055a11992c7fb8ba2a21414cd0920c017b59958c61764ea4c1629dd06b9a4`
- raw-request SHA-256: `ccc50b7742bee28be37caefe99a27721cdced5a430f665a8abd0f11dad0927d0`
- model run: `run:81d87a5e6d1f4945aede1658665abf41`
- bundle ref: `bundle:fb05735049119932d65d4b00f38a035f`
- canonical bundle SHA-256: `ca2a9a81f5d13a925fc373e63f998c570a17735d380084094e4a5f804bb22c3f`
- bundle status: `partial`
- authorities: 297
- evidence spans: 3,837
- normative relationships: 3,001
- rules: 54

MCP discovery was exactly:

`research_case`, `get_case_research`, `get_authority`, `get_provision`, `get_evidence`, `get_normative_relationships`, `get_calculation`

Prompts: `[]`. Resources: `[]`.

The MCP follow-up bundle matched the research bundle exactly and the first evidence projection matched the bundle evidence exactly.

**Failure 1:** the explicit IVA component question was categorized `temporal` instead of `legal`, so the platform planner — which intentionally creates mandatory tasks only for open legal questions — created no research task for that substantive IVA question.

Owned defect: **#188**.

**Failure 2:** the treaty question was correctly legal and did receive platform-required research. The bundle found Colombia–Spain treaty identity/promulgation and permanent-establishment material, but contained zero exact evidence for `beneficios empresariales` and zero exact evidence for `cánones o regalías`.

The same isolated canonical snapshot contains directly relevant official-source treaty text, including:
- `SEG-bb72b5e66da5516281fe477615033bb7` — treaty structure identifying art. 7 business profits and art. 12 royalties;
- `SEG-2733d6bd613956d996274dbb68ab3771` — article-12 royalty taxation text;
- `SEG-42b3e92ab3af53a19b62482f7f2ca032` — article-12 definition including technical assistance/services/consulting;
- `SEG-a04cffb206bf5c62a019a7ec8a5ab048` — article-12 PE linkage to article 7.

This is a research-coverage defect, not a corpus gap.

Owned defect: **#189**.

## Evidence/provenance invariants

Direct checks over each frozen bundle found:

| invariant | A | B | C |
|---|---:|---:|---:|
| missing EvidenceSpan owner authority | 0 | 0 | 0 |
| EvidenceSpan document/authority mismatch | 0 | 0 | 0 |
| recomputed exact-text SHA mismatch | 0 | 0 | 0 |
| missing EvidenceSpan source | 0 | 0 | 0 |
| dangling RuleFragment evidence refs | 0 | 0 | 0 |

Each ResearchResult records a populated research context with:
- `as_of_date=2026-09-27`;
- corpus-snapshot SHA-256;
- schema/migration fingerprint;
- retrieval configuration SHA-256;
- planner/retrieval versions;
- `unavailable_fields=[]`.

#180/#178 owner-closure regressions therefore remain fixed in this run.

## Independent lifecycle and boundary validation

The scored A/B/C artifacts had already been frozen when the recovery runner hit a separate validation-harness startup race while checking web health immediately after a restart. The scored cases were **not** rerun.

The lifecycle test was completed afterward using actual HTTP readiness:

1. restart web independently -> `/healthz` returns `ok`;
2. restart backend independently -> GET `/v1/cases` reaches the expected HTTP 405 readiness contract;
3. web remains healthy after backend restart;
4. MCP `/readyz` returns ready with gateway/API contract `1.0.0`;
5. backend still reaches the exact #133 provider after restart.

Mount boundary:
- backend mounts only isolated validation state/runtime harness plus its anonymous `/app/data` volume;
- web has no mounts;
- MCP has no mounts and a read-only root filesystem.

No production corpus or production CASE state is mounted into web/MCP.

## Harness incidents retained for audit

Two recovery-harness failures occurred **before/after** the scored model outputs and are not reinterpreted as scored results:

1. recovery r2 used host loopback from inside the backend container, producing `CASE_STRUCTURING_UNAVAILABLE` before the model executed; those rejected attempts remain separately attributable;
2. recovery r3 completed A/B/C, then the runner used TCP-only readiness after restarting web and hit a connection reset before writing its final summary.

Both are validation-harness defects only. Product code was not patched. The corrected r3 network/provider precondition was proven before the retained A/B/C, and lifecycle was completed afterward without rerunning them.

## Acceptance matrix

| criterion | status |
|---|---|
| controls committed before runs | PASS |
| exact admitted #133 runtime/profile | PASS |
| REST / web / MCP independent boundaries | PASS |
| successful LegalResearchBundle through all three surfaces | PASS |
| evidence owner/source/hash graph | PASS |
| research-context fingerprint present | PASS |
| MCP seven-tool/no-prompts/no-resources surface | PASS |
| independent web/backend restart | PASS |
| A explicit-fact fidelity / bounded evaluator path | **FAIL — #188** |
| B explicit-fact fidelity | **FAIL — #188** |
| C IVA-question research branch | **FAIL — #188** |
| C material Colombia–Spain treaty provision coverage | **FAIL — #189** |
| automated technical gate | **FAIL** |
| operator acceptance | NOT REQUESTED |

## Recovery

#142 remains open and blocked.

Product fixes must remain outside this validation branch:

1. #188 independently converges on protected main;
2. #189 independently converges on protected main;
3. #142 performs another fresh affected A/B/C Phase-1 execution against the converged main;
4. only an explicit `AUTOMATED_TECHNICAL_GATE: PASS` may transition #142 to `AWAITING_OPERATOR_ACCEPTANCE`.

The current post-#178 A/B/C artifacts are frozen historical FAIL evidence and must not be retried until they pass.

## Teardown after failed gate

Because Phase 1 remained FAIL, the isolated r3 stack was **not** left available for operator testing.

After all scored artifacts, lifecycle evidence and hashes were frozen:
- removed only `col-taxdata-issue142-r3-backend`, `col-taxdata-issue142-r3-web` and `col-taxdata-issue142-r3-mcp`;
- removed the validation-only network `col-taxdata-issue142-r3-net`;
- left `col-taxdata-llm-gemma4-e2b` running and healthy;
- left `col-taxdata-crawler` running and untouched;
- preserved the full validation root `/home/user/col-taxdata-validation-142-rerun3-98495` including isolated DB/logs/artifacts.

Frozen scored artifact SHA-256 values after teardown:
- A: `24c629ec7104869de14651fcd1b202197c696ffd28fac4c7680eb63497986c5c`
- B: `d7b63c24dc15b96e28faece9507c19ac88968735a8820e385341b22f71e72b4d`
- C: `9b854f5bcba990db1316fbf67752e41983573571e1c81a07269d95e6dd427312`

The corrected recovery harness — dedicated provider network/preflight plus HTTP readiness rather than TCP-only readiness — is preserved separately as:
`col-taxdata/validation/issue-0142/phase1-recovery-runner.py`.

This does not alter or reinterpret the scored A/B/C outputs; it prevents the already-observed validation-harness wiring/readiness defects from recurring in the next affected run.
