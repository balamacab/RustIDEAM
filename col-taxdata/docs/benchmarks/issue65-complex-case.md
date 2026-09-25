# Issue #65 — comparative complex-case benchmark

## Boundary

This package freezes the benchmark protocol for issue #67. It does **not** execute or authorize the complex benchmark. Execution waits until #63, #64, #65 and #66 are closed/verified.

It exercises the existing CASE v3 application service; it does not change legal identity, provenance, schema, migrations, corpus data or canonical promotion rules.

## Frozen CaseInput and request

Exact `problem_text`: `config/benchmarks/issue65/complex-case.txt`. Its final LF is significant.

| Item | Frozen value |
| --- | --- |
| problem bytes | 7,684 |
| problem SHA-256 | `ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1` |
| `as_of_date` | `2026-09-24` |
| `client_reference` | omitted |
| canonical CaseInput SHA-256 | `9a88c7d1f818e22ef310ef52a4185d2795d3e51ddd374d22b25e713b522171d4` |
| expected CASE ID | `CASE-31fdda05d776558393b16095880202d7` |
| HTTP request SHA-256 | `b0b36bf6ab5c5d46572aee434933b4a87f830c953ef26ee17c78734c82a9b763` |

Canonical identity uses the current v3 compact JSON contract: UTF-8, sorted keys, compact separators, no trailing LF. `request.json` is also byte-frozen, has no trailing LF, and contains only `problem_text` and `as_of_date`. No CASE/DOC/PROV/SEG/EVD IDs, source hints, expected conclusions or evidence bindings may be added by the caller.

Issue #66 is now part of the integration baseline. Every measured request must use `POST /v1/cases` through `tools/case_http.py`. A successful response must expose both `raw_request_sha256` and `case_input_sha256`. The frozen failure categories are `CASE_PROVIDER_TIMEOUT`, `CASE_OUTPUT_LIMIT`, `CASE_CONTEXT_LIMIT` and `INVALID_CASE_DRAFT`; in particular, the merged provider adapter independently raises `CASE_OUTPUT_LIMIT` when `completion_tokens >= max_output_tokens`, even if a provider reports another finish reason.

## Matrix and generation policy

Exactly three configurations:

1. Gemma E2B / Quadro M620 / llama.cpp.
2. Gemma E2B / Ryzen AI NPU / FastFlowLM.
3. Gemma 12B / Ryzen AI NPU / FastFlowLM.

The E2B pair is compared semantically across platforms. Generated-output or model-artifact byte/hash identity is not required.

Every measured request uses:

```text
temperature=0
thinking=false
context_tokens=16384
max_output_tokens=6144
provider_timeout_seconds=900
top_p=1.0
top_k=0
stream=false
n=1
```

No temperature sweep, extra model or extra request-side generation parameter is allowed.

Before measurement, a **non-benchmark** probe must bind the exact served model/artifact and backend/build identity and confirm the backend honors the frozen context, output, sampling, thinking-disabled and structured-output semantics. A backend that cannot honor them blocks execution; limits or models must not be silently substituted. Probe traffic is not a measured run.

## Nine-run plan and state isolation

There are 3 runs per configuration, 9 total. `python3 tools/case_benchmark.py plan` expands the authoritative run plan.

Issue #67 freezes one baseline before run 1 and records:

- current validated `main` SHA;
- database SHA-256;
- raw-evidence manifest/integrity SHA-256;
- runtime image/build identity per backend.

Raw evidence may be shared read-only. Mutable state may not be shared. Every measured run gets an independent writable SQLite copy and case directory cloned from that same baseline:

```text
benchmark-runs/<backend-id>/run-1/{state.sqlite,cases/}
benchmark-runs/<backend-id>/run-2/{state.sqlite,cases/}
benchmark-runs/<backend-id>/run-3/{state.sqlite,cases/}
```

Per-run isolation is intentional: this CaseInput deterministically creates the same CASE ID, so shared writable CASE state would turn later repetitions into reuse/idempotency measurements instead of independent E2E runs. No acquisition, corpus refresh, migration, repair or reprocessing may occur during the nine-run set.

## Clean model/server state

Before each measured run:

1. confirm no prior measured request is active;
2. use a fresh backend process or documented equivalent full model/session/KV reset;
3. load only the declared model;
4. wait for readiness and record served-model/backend identities;
5. discard readiness/probe conversation state;
6. submit the measured request without prior chat/session continuation.

Warm session reuse across measured runs is prohibited. #67 records backend-specific reset commands before run 1.

## What each run must record

A run record contains:

- backend ID and repetition;
- problem/request/CaseInput fingerprints and CASE ID;
- CASE contract + prompt-template identity;
- exact frozen generation parameters;
- frozen baseline identifiers;
- served model/artifact/backend identity and clean-state confirmation;
- prompt/completion tokens, total time, model-load time and finish reason;
- malformed-output, contract-failure, timeout, crash, context-rejection and truncation flags;
- all mandatory PASS gates;
- every semantic-rubric item with PASS/FAIL and evidence references.

No post-response semantic repair is permitted.

## Truncation/error rule

A run fails on any of:

- `completion_tokens >= 6144` (the required equality-at-ceiling case is therefore a failure);
- malformed/incomplete structured output;
- CaseDraft contract failure;
- timeout;
- backend crash;
- context-budget rejection;
- independently detected truncation.

`finish_reason=stop` never overrides these failures.

## Semantic rubric

`benchmark.json` freezes 32 auditable items:

- `FACT-01..10`: explicit intake fact groups and known/unknown boundaries;
- `QUESTION-01..08`: all eight client questions preserved and not duplicated as missing facts;
- `UNC-01..06`: implementation/training allocations, affiliate facts, provider representations and legal-vs-factual uncertainty;
- `CLAIM-01..08`: meaningful candidate coverage for IVA, component separation, withholding, CDI, PE, timing, verification needs and supporting documents.

All items are mandatory. Each assessment must include `status=pass` and non-empty evidence references to pass. The benchmark does not use another LLM as judge. Semantic evaluation is an auditable reviewer/controller assessment against these frozen definitions; deterministic checks remain deterministic.

For `user_provided` facts, source quotes must be verbatim substrings of the exact problem text. Evaluation-only comparison may use Unicode NFC, outer trimming and whitespace collapse; these never alter stored bytes or repair output.

## Minimum run PASS

All machine gates in `benchmark.json` must pass, including:

- external HTTP accepted through the production application path;
- exact fingerprints;
- valid CaseDraft;
- explicit fact fidelity and verbatim quotes;
- all questions preserved;
- no question duplicated as missing;
- legal uncertainty not mislabeled as missing client data;
- meaningful candidate claims;
- CaseResult generated;
- persisted `requires_human_review` semantics consistent;
- validator and provenance PASS;
- unsupported claims not promoted;
- current materialization;
- no output ceiling/truncation/error.

Structural validity alone is not a semantic PASS.

## E2B cross-platform concordance

Quadro/llama.cpp vs Ryzen AI/FastFlowLM must PASS all eight dimensions:

`explicit_facts`, `missing_ambiguous_states`, `questions`, `candidate_claims`, `unresolved_items`, `retrieval_document_coverage`, `evidence`, `claim_disposition`.

Each dimension requires evidence. Semantic concordance is required; byte/hash identity is not.

## Suite PASS

The suite passes only if:

1. all nine declared run slots exist;
2. all nine runs pass;
3. all nine use the same `main`/database/raw-evidence baseline;
4. E2B cross-platform concordance passes.

Gemma 12B differences are reported independently; they are not folded into E2B concordance.

## Repository-only commands

These commands perform no model or network calls:

```bash
python3 tools/case_benchmark.py verify-package
python3 tools/case_benchmark.py plan
python3 tools/case_benchmark.py score-run --record /path/to/run.json
python3 tools/case_benchmark.py score-suite --record /path/to/suite.json
```

`verify-package` protects frozen bytes, canonical fingerprint, CASE identity, matrix, generation policy and isolation plan.

## #67 execution sequence

After all prerequisites close/verify:

1. reconcile to validated `main`;
2. run `verify-package`;
3. bind model/backend identities with non-benchmark capability probes;
4. freeze database/raw-evidence/runtime baseline;
5. clone nine isolated writable run stores;
6. establish clean backend state;
7. send exact `request.json` bytes to `POST /v1/cases` through the #66 HTTP adapter;
8. capture each run record before the next repetition;
9. preserve failures without parameter repair;
10. score each run, then the suite and E2B concordance;
11. publish run summaries/evidence in #67.

The complex benchmark must not be executed in #65.
