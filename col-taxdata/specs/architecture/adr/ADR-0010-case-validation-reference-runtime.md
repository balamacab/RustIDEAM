# ADR-0010 — CASE controlled validation uses one reference runtime and optional experimental backends

## Status

Accepted.

## Context

Issue #65 froze a historical comparative benchmark package containing three backend configurations, three repetitions per backend, a nine-run suite gate, and cross-platform Gemma E2B concordance. Those files are valid historical evidence and remain immutable as a benchmark package.

Runtime preparation in issue #73 subsequently established that the Quadro M620 + llama.cpp + Gemma E2B path can satisfy the current CASE HTTP and structured-output flow, while FastFlowLM on Ryzen AI remained unreliable as a mandatory dependency. Issue #75 therefore separates current controlled CASE validation from the historical #65 comparative benchmark.

The generalized provider-neutral structured-output compatibility contract is intentionally owned by issue #76 and is not changed by this ADR.

## Decision

The supported **reference development and controlled-validation runtime** is:

- hardware: NVIDIA Quadro M620;
- backend: llama.cpp;
- logical model: Gemma E2B;
- artifact: `gemma-4-E2B-it-Q4_K_M.gguf`;
- artifact SHA-256: `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8`;
- transport: the existing OpenAI-compatible application boundary;
- external CASE entry point: `POST /v1/cases`.

The application remains backend-neutral. Selecting a reference validation runtime is an operational validation decision, not a vendor-specific domain contract.

Ryzen AI / FastFlowLM backends are **optional experimental diagnostics**. Their absence, capability failure, or incompatibility does not fail core CASE readiness and does not gate issue #67 Phase A, Phase B, or closure. If an experimental diagnostic is run, its declared model and generation envelope may not be silently substituted.

The current machine-readable contracts are:

- `config/llm/case-validation-reference.yaml` — dedicated LLM platform profile with Gemma E2B as the actual primary structuring model;
- `config/validation/issue67-reference.json` — current validation profile distinguishing the required reference backend from optional experimental backends;
- `tools/case_validation.py` — read-only profile verification, planning, and readiness evaluation.

The existing `config/llm/local-platform.yaml` remains the ordinary local default and is not silently repurposed.

## Frozen generation envelope

Controlled validation requires exactly:

- temperature = 0;
- thinking = false;
- context = 16384 tokens;
- max output = 6144 tokens;
- provider timeout = 900 seconds;
- top_p = 1;
- top_k = 0;
- stream = false;
- n = 1.

Controlled validation requires a clean provider state before the run, does not allow warm-session reuse, and discards capability-probe state.

## Issue #67 execution contract

The current required sequence is:

1. one controlled Phase A E2E execution on Quadro M620 / llama.cpp / Gemma E2B through `POST /v1/cases`;
2. freeze the successful Phase A result and its baseline;
3. run isolated Phase B official-source control;
4. perform post-freeze claim-by-claim comparison.

FastFlowLM runs may be added as separate supplemental diagnostic observations. They are not members of required Phase A and do not gate Phase B.

No complex #67 input is executed by issue #75.

## Historical #65 benchmark

The #65 benchmark package is not rewritten. In particular, its:

- problem bytes and SHA-256;
- raw request bytes and SHA-256;
- canonical CaseInput SHA-256;
- deterministic CASE ID;
- three-backend matrix;
- nine-run plan;
- concordance rules;
- suite scoring

remain historical comparative-benchmark evidence. Current #67 planning is represented separately instead of redefining those files.

## Issue #73 completion semantics

The required runtime evidence from #73 is the validated CASE image/baseline, current migration state, raw-evidence integrity/provenance checks, Quadro capability, HTTP CASE path, and clean/reset procedure. FastFlowLM probe outcomes remain recorded as optional POC diagnostics and are not acceptance blockers after ADR-0010.

No prior #73 observation is deleted or reinterpreted as a successful FastFlowLM capability result.

## Consequences / trade-offs

- Normal CASE development and #67 controlled validation no longer depend on FastFlowLM availability.
- The historical benchmark remains reproducible without becoming the current validation gate.
- The dedicated validation profile avoids changing ordinary `local-platform.yaml` behavior.
- A single reference runtime reduces platform-comparison coverage in the required validation path; experimental runs can still provide supplemental evidence.
- Provider-neutral application behavior and all canonical evidence/provenance rules remain unchanged.

## Related issues

- #17 — validation methodology.
- #65 — frozen historical comparative benchmark.
- #66 — external HTTP CASE endpoint.
- #67 — controlled complex-case validation.
- #73 — runtime/baseline preparation.
- #75 — this decision and implementation.
- #76 — generalized structured-output compatibility contract.
