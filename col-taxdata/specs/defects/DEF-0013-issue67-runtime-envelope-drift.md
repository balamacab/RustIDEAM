# DEF-0013 — Issue #67 canonical runtime envelope drift

Status: implementing  
Priority: P2  
GitHub issue: #92  
Area: validation / runtime-profile

## Summary

The controlled Phase A plan for issue #67 still encoded the original
900-second provider timeout and 6144-token output ceiling after the canonical
#67 execution contract was explicitly amended to 7200 seconds and 9000 output
tokens. Repository tooling therefore planned and verified a different envelope
from the live canonical validation contract.

## Observed behavior

Issue #65 froze a historical comparative benchmark at context=16384,
max_output=6144 and timeout=900. Issue #75 then created the first #67 reference
validation profile using the same envelope and ADR-0010 recorded it.

Two canonical #67 attempts later reached the 900-second provider cutoff while
generation remained active. The operator explicitly amended #67 to
context=16384, max_output=9000 and timeout=7200, leaving all other generation
and model parameters unchanged. That envelope completed naturally in
1122.799595 seconds with 6338 generated tokens and no timeout/output-ceiling
failure. The resulting draft was subsequently rejected for an independent
`source_quote` application-contract violation.

The clean repository baseline before DEF-0013 still had:

- `config/validation/issue67-reference.json` at 6144/900;
- `config/llm/case-validation-reference.yaml` at 6144/900;
- `tools/case_validation.py` hard-coding 6144/900 as one timeless expected
  envelope;
- ADR-0010 and runtime documentation describing 6144/900 as current.

## Evidence

Historical issue #65 / reference-v1 envelope:

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

Current canonical issue #67 envelope:

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

The two 900-second attempts remain historical evidence. They must not be
rewritten or described as executions under the amended envelope.

## Impact

Without a durable current profile, a later #67 controlled run could silently
fall back to 900/6144. That would invalidate timeout/truncation interpretation
and make profile evidence disagree with the contract under which the run was
claimed.

This defect affects validation/control-plane correctness only. It does not
change canonical legal evidence, corpus data, legal identity, or provenance.

## Root cause

The first #67 validation profile reused the original #75 reference envelope and
`case_validation.py` represented it with one hard-coded
`EXPECTED_GENERATION`. Historical benchmark/reference semantics and the
later canonical #67 execution semantics therefore had no versioned
machine-readable separation.

## Architecture decision / proposed solution

1. Preserve `config/benchmarks/issue65/benchmark.json` and all of its
   historical input/request/CaseInput fingerprints unchanged.
2. Preserve `config/llm/case-validation-reference.yaml` as reference-runtime
   v1 with its original 6144/900 meaning.
3. Add `config/llm/case-validation-reference-v2.yaml` with the same
   OpenAI-compatible provider, model, context and request parameters, changing
   only output=9000 and timeout=7200.
4. Version the #67-specific validation profile to v2, bind it explicitly to
   runtime v2, and record the historical/current envelope lineage.
5. Keep historical #65 and current #67 envelope constants separate in
   `tools/case_validation.py`; fail closed if either side drifts.
6. Verify the selected runtime profile independently from the validation
   profile so changing one cannot hide drift in the other.
7. Resolve repository-relative references from an explicit project root rather
   than deriving the root from the validation profile's filesystem depth.
8. Expose validation/runtime profile ID, version/path and exact-byte SHA-256 in
   verification and plan/run evidence.
9. Amend ADR-0010 narrowly: retain its original #75 decision and reference
   backend, while recording #92 as the versioned runtime-envelope supersession
   for canonical #67 execution.

The runtime v2 configuration is reusable only as an explicitly selected
runtime. The validation profile and `issue67-*` run IDs remain specific to
#67 and must not be reused as another validation's execution identity.

## Non-goals

- modifying #65 benchmark bytes, hashes, historical attempts, or scoring;
- changing ordinary `local-platform.yaml` defaults;
- fixing the independent `source_quote` defect;
- changing model, hardware, backend, T0, context, top_p, top_k, thinking,
  stream, or n;
- running or rerunning #67;
- running Phase B;
- tuning generation quality;
- making 7200/9000 a universal application default.

## Reprocessing plan

N/A. No corpus, canonical legal state, raw evidence, database, retrieval index,
or other derived corpus state changes.

## Migration

N/A. No schema change is required and no applied migration is modified.

## Dry-run / preview

`tools/case_validation.py verify-profile` and `plan` are the read-only
preview mechanisms for this control-plane change. They execute the same profile
decision rules used by readiness/planning, perform no provider/model call and
perform no persistent mutation.

## Acceptance criteria

1. Historical #65 benchmark configuration remains untouched and its frozen
   input/request/CaseInput fingerprints still verify.
2. Historical #65 generation remains exactly 16384/6144/900 with all other
   frozen generation parameters unchanged.
3. Reference runtime v1 remains version 1 at 16384/6144/900.
4. Current #67 resolves exactly to 16384/9000/7200 with temperature=0,
   thinking=false, top_p=1, top_k=0, stream=false and n=1.
5. `verify-profile` rejects fallback to the historical 6144/900 envelope.
6. `verify-profile` rejects unapproved drift in model, context, temperature,
   top_p, top_k, thinking, stream, n, output ceiling or timeout.
7. Selected-runtime-profile drift is checked independently from validation
   profile drift.
8. Plan output distinguishes historical #65 from current canonical #67 and
   records the full generation envelope for each.
9. Validation and runtime profile identity/version/path and exact-byte SHA-256
   are recordable in plan/run evidence.
10. A clean runtime invocation can select the committed v2 profile without
    generating or editing a host-local config.
11. Clean-provider-state semantics remain strict.
12. Existing #75 required/optional reference-runtime behavior and #76
    provider-neutral structured-output compatibility remain green.
13. ADR-0010 and runtime documentation no longer describe 6144/900 as the
    current canonical #67 envelope.
14. No production/runtime/corpus/raw-evidence mutation and no #67 execution
    occurs.
15. All repository content changes remain under `col-taxdata/`.

## Regression tests

Focused DEF-0013 tests cover:

- exact historical #65 envelope and frozen fingerprints;
- unchanged reference-runtime v1;
- exact amended #67 envelope;
- complete historical/current plan labeling;
- validation/runtime profile identity and exact-byte SHA-256;
- external validation-profile location with explicit project-root resolution;
- fallback to v1 / 6144/900 rejection;
- validation-profile generation/model/version drift;
- envelope-lineage drift;
- selected runtime model/context/output/timeout/options/version drift;
- actual OpenAI-compatible request materialization at T0/max_tokens=9000 and
  timeout=7200;
- direct selection of the committed v2 profile by CASE runtime construction;
- clean-provider-state drift.

The existing issue #75 and issue #76 suites remain preservation coverage.

## Dependencies / ordering

No blocking implementation dependency is required for DEF-0013 itself. The next
canonical #67 Phase A rerun is gated on this change being integrated so that
the amended plan is produced directly from committed repository configuration.

## Provenance / integrity

This issue changes only control-plane configuration, verification/planning,
tests and documentation. Immutable raw evidence and corpus SHA-256 provenance
are outside the changed path. The final diff must confirm the historical #65
benchmark file and reference-v1 profile are not modified.
