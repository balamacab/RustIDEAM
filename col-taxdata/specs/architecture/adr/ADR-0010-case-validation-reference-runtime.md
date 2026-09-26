# ADR-0010 — CASE controlled validation uses one reference runtime and optional experimental backends

## Status

Accepted.

## Context

Issue #65 froze a historical comparative benchmark package containing three backend configurations, three repetitions per backend, a nine-run suite gate, and cross-platform Gemma E2B concordance. Those files are valid historical evidence and remain immutable as a benchmark package.

Runtime preparation in issue #73 subsequently established that the Quadro M620 + llama.cpp + Gemma E2B path can satisfy the current CASE HTTP and structured-output flow, while FastFlowLM on Ryzen AI remained unreliable as a mandatory dependency. Issue #75 therefore separates current controlled CASE validation from the historical #65 comparative benchmark.

The generalized provider-neutral structured-output compatibility contract is intentionally owned by issue #76 and is not changed by this ADR.

Issue #92 / DEF-0013 later amends only the runtime envelope used by the canonical issue #67 execution after two preserved 900-second timeout attempts demonstrated that the original #75 limits were operationally inadequate. This amendment does not reverse the reference-backend decision or rewrite #65/#75 history.

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

The machine-readable contracts are versioned:

- `config/llm/case-validation-reference.yaml` — original reference-runtime v1 retained with its #75-era 6144/900 semantics;
- `config/llm/case-validation-reference-v2.yaml` — amended reference-runtime v2 used by the canonical issue #67 plan, preserving model/context/request semantics while using 9000/7200;
- `config/validation/issue67-reference.json` — issue #67-specific validation profile distinguishing the required reference backend from optional experimental backends and recording the envelope amendment lineage;
- `tools/case_validation.py` — read-only profile verification, planning, readiness evaluation, and exact selected-profile identity/SHA reporting.

The existing `config/llm/local-platform.yaml` remains the ordinary local default and is not silently repurposed.

## Versioned generation envelope

The original issue #75 reference-runtime v1 and historical #65 package retain exactly:

- temperature = 0;
- thinking = false;
- context = 16384 tokens;
- max output = 6144 tokens;
- provider timeout = 900 seconds;
- top_p = 1;
- top_k = 0;
- stream = false;
- n = 1.

For the canonical issue #67 execution, issue #92 / DEF-0013 supersedes only the output/timeout limits with an explicitly versioned v2 envelope:

- temperature = 0;
- thinking = false;
- context = 16384 tokens;
- max output = 9000 tokens;
- provider timeout = 7200 seconds;
- top_p = 1;
- top_k = 0;
- stream = false;
- n = 1.

The amendment was authorized after two canonical #67 attempts timed out at 900 seconds while generation was still active. The amended envelope subsequently allowed natural completion; the later `INVALID_CASE_DRAFT` / `source_quote` rejection is an independent application-contract failure.

Controlled validation still requires a clean provider state before the run, does not allow warm-session reuse, and discards capability-probe state. The v1 envelope remains historical evidence and is not rewritten as if it had been v2.

## Issue #67 execution contract

The current required sequence is:

1. one controlled Phase A E2E execution on Quadro M620 / llama.cpp / Gemma E2B through `POST /v1/cases`;
2. freeze the successful Phase A result and its baseline;
3. run isolated Phase B official-source control;
4. perform post-freeze claim-by-claim comparison.

FastFlowLM runs may be added as separate supplemental diagnostic observations. They are not members of required Phase A and do not gate Phase B.

No complex #67 input is executed by issue #75 or issue #92. The #67 validation/run identifiers remain issue-specific; another controlled validation may select the reusable runtime v2 only under its own explicit validation/admission identity.

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
- Versioned reference-runtime profiles avoid changing ordinary `local-platform.yaml` behavior or rewriting the original v1 meaning.
- The #67 amendment is explicit and machine-checkable rather than a host-local override.
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
- #92 / DEF-0013 — versioned amendment of the canonical #67 runtime envelope.
