# DEF-0013 — Issue #67 canonical runtime envelope drift

Status: verified  
Priority: P2  
GitHub issue: #92  
Area: validation / runtime-profile

## Summary

The controlled Phase A validation plan for issue #67 still encoded the historical/reference 900-second provider timeout and 6144-token output ceiling after the canonical #67 execution contract was explicitly amended to 7200 seconds and 9000 output tokens. This is control-plane drift: committed tooling could plan or verify a run under an envelope different from the live canonical #67 contract.

## Observed behavior

The historical issue #65 benchmark package defines 16384 context tokens, 6144 maximum output tokens and a 900-second provider timeout. Issue #75 subsequently reused those values in the first committed #67 reference validation profile and `tools/case_validation.py` hard-coded them as the expected generation envelope.

Two canonical #67 attempts later reached the 900-second provider cutoff while generation was still active. The operator amended the canonical #67 envelope to 7200 seconds and 9000 output tokens. Under that envelope the model completed naturally in 1122.799595 seconds with 6338 generated tokens and no timeout/output-ceiling failure. The resulting draft was rejected independently for a `source_quote` contract violation.

## Evidence

Historical #65/reference envelope:

```text
temperature=0
thinking=false
context_tokens=16384
max_output_tokens=6144
provider_timeout_seconds=900
top_p=1
top_k=0
stream=false
n=1
```

Current canonical #67 envelope:

```text
temperature=0
thinking=false
context_tokens=16384
max_output_tokens=9000
provider_timeout_seconds=7200
top_p=1
top_k=0
stream=false
n=1
```

The two 900-second timeout attempts remain historical evidence and MUST NOT be rewritten as if they used the amended envelope.

## Impact

A future controlled #67 run generated from repository tooling could otherwise fall back to 900/6144, invalidating interpretation of timeout/truncation behavior and making repository control-plane state disagree with the canonical issue contract.

This defect does not alter canonical legal evidence or corpus data.

## Root cause

The #67 validation plan reused a reference runtime profile whose 900/6144 values represented the historical #65/#75 preparation state, while `case_validation.py` treated those values as timeless hard-coded #67 constants. There was no versioned machine-readable distinction between the historical benchmark envelope and the amended canonical validation envelope.

## Proposed solution

1. Preserve `config/benchmarks/issue65/benchmark.json` unchanged.
2. Preserve the existing generic/reference LLM profile rather than silently changing its historical meaning.
3. Add a dedicated versioned reference runtime profile containing 7200/9000 and all unchanged generation/model parameters, without mutating the historical v1 profile.
4. Version the #67 validation profile and bind it explicitly to the versioned reference runtime while keeping #67 validation/run identity distinct from reusable runtime identity.
5. Make `verify-profile` validate the current #67 envelope while independently verifying the historical #65 envelope.
6. Make plan/verification output expose historical-versus-current envelope roles and record deterministic validation/runtime profile identities and SHA-256 values.
7. Reject fallback to 900/6144 and reject unapproved drift in model, context, T0, top-p, top-k, thinking, stream or n.

## Non-goals

- modifying #65 benchmark bytes, hashes, semantics, or historical attempts;
- fixing the independent `source_quote` defect;
- changing model, hardware, backend, T0 or context size;
- running Phase B;
- rerunning #67;
- generation-quality tuning;
- making 7200/9000 a universal application default.

## Reprocessing plan

N/A. This issue changes committed validation/control-plane configuration and deterministic planning/verification only. No corpus, canonical legal state, raw evidence, database, or derived corpus state is mutated.

## Migration

N/A. No schema changes are required.

## Dry-run / preview

The `tools/case_validation.py verify-profile` and `plan` commands are read-only previews of the selected committed validation profile. They must emit the selected profile identity/SHA and the historical/current envelope distinction without runtime/model calls or persisted-state mutation.

## Acceptance criteria

1. Historical #65 benchmark configuration and its registered evidence fingerprints remain unchanged and verify successfully.
2. Historical #65 generation remains exactly 900/6144 with all frozen generation parameters preserved.
3. The current #67 validation plan resolves exactly to context=16384, max_output=9000, timeout=7200, temperature=0, thinking=false, top_p=1, top_k=0, stream=false, n=1.
4. `verify-profile` rejects #67 fallback to 900/6144.
5. `verify-profile` rejects unapproved changes to model/context/temperature/top_p/top_k/thinking/stream/n.
6. Plan output explicitly identifies the historical #65 envelope and current canonical #67 envelope.
7. A clean invocation can select the committed canonical #67 runtime profile without host-local edits.
8. Validation and runtime profile identity plus SHA-256 are exposed for run evidence.
9. Existing #75 reference-runtime behavior remains covered under the intentionally versioned #67 plan, and #76 structured-output compatibility remains green.
10. No files outside `col-taxdata/` are changed; no production/runtime mutation or #67 rerun occurs.

## Regression tests

- historical #65 envelope/package verification;
- exact amended #67 envelope;
- historical/current plan labeling;
- committed profile selection and SHA recording;
- rejection of historical-envelope fallback;
- rejection of generation/model drift in both the validation profile and the selected LLM runtime profile;
- external validation-profile path resolution from an explicit project root;
- exact-byte profile SHA sensitivity;
- clean-provider-state drift rejection;
- issue #75 reference-runtime suite;
- issue #76 structured-output compatibility suite.

## Cross-validation identity boundary

DEF-0013 makes the amended **reference runtime** durable, but the `issue67-controlled-validation-v2` profile and `issue67-phase-a-reference` run ID remain intentionally specific to issue #67. CASE-0003/#95 must not reuse those identifiers as its execution identity. It must create its own validation/admission profile and run IDs, while it may reference `config/llm/case-validation-reference-v2.yaml` if #95 confirms that runtime is still the explicitly authorized reference envelope.

This boundary avoids turning an observation from #67 into a universal application default and satisfies #93's requirement that amended/controlled attempts record truthful profile identity and SHA.

## Dependencies / ordering

No blocking implementation dependency is required. The next canonical #67 Phase A rerun is gated on this defect being integrated so repository tooling can produce the amended plan directly from committed configuration.

## Verification evidence from initial implementation

- Implementation PR: #96, merged as `1cb053042b90b1035ba2fd9d7585f81166a7cbab`.
- Candidate `CI Gate`: passed.
- Post-merge col-taxdata suite: 280 tests passed, including issue #75 reference-runtime and issue #76 structured-output compatibility coverage.
- Post-merge `Convergence Gate`: passed.
- Historical #65 benchmark blob SHA remained `3e9da9c37eed8abfd036d7ccb722a6c6d4459f27` across the #92 implementation.
- Generic `config/llm/case-validation-reference.yaml` blob SHA remained `36a814481fe0540e0f28d8b18cc27c9e7747f613` across the #92 implementation.
- Reprocessing, schema migration, production mutation, runtime access, and raw-evidence changes: N/A.
- A later high-rigor review reopened #92 before final verification because external profile-path resolution, selected-runtime-profile drift coverage, and runtime documentation required correction. This section is therefore historical evidence for PR #96, not the final DEF-0013 verification state.

## Final high-rigor verification

DEF-0013 was re-reviewed after the initial implementation and corrected through PR #100.

Final evidence:

- corrected implementation PR #100 merged as `7f6dd922d1ba7dc25815c7d4b1ad7fd450237f29`;
- exact candidate `e6fa376970b67a830d5b876f8a5447ae2dddb362` was selected by trusted CI for PR #100;
- the complete col-taxdata suite passed: 319 tests, including the DEF-0013, issue #75, issue #76, issue #90, and issue #93 coverage present on the integrated base;
- candidate `CI Gate` passed;
- merged-state `Main integration invariants` passed;
- merged-state `Convergence Gate` passed;
- historical #65 benchmark content remained separate at 900/6144;
- historical `config/llm/case-validation-reference.yaml` remained the v1 reference-preparation profile rather than being silently repurposed;
- current reusable runtime is `config/llm/case-validation-reference-v2.yaml` with 7200/9000 and unchanged model/context/T0/request semantics;
- the #67 validation plan/run identity remains explicitly #67-specific and is not a reusable CASE-0003 execution identity;
- external validation-profile paths resolve repository-relative references from an explicit project root;
- validation/runtime profile SHA-256 values cover exact selected bytes;
- independent validation-profile and selected-runtime-profile drift is rejected;
- actual OpenAI-compatible request construction was verified to materialize T0 and the frozen request options;
- clean-provider-state drift is rejected;
- no schema migration, corpus reprocessing, production mutation, raw-evidence mutation, #67 rerun, Phase B run, or #94 execution was performed.

All mandatory acceptance criteria are PASS. Status is therefore `verified`.
