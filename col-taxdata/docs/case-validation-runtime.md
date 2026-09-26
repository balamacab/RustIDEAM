# CASE reference validation runtime

Issue #75 separates controlled CASE validation from the historical issue #65
three-backend benchmark. Issue #92 / DEF-0013 subsequently amends only the
canonical issue #67 runtime envelope after the original 900-second ceiling
proved operationally inadequate.

## Runtime profile versions

Normal local defaults remain in:

`config/llm/local-platform.yaml`

The original issue #75 reference profile remains unchanged at:

`config/llm/case-validation-reference.yaml`

That v1 profile retains the original 16384 context / 6144 output / 900-second
envelope. It remains useful as historical #75/#65-era reference configuration,
but it is no longer the canonical issue #67 execution profile.

The amended reference runtime is committed separately at:

`config/llm/case-validation-reference-v2.yaml`

Runtime v2 preserves the same OpenAI-compatible provider boundary, llama.cpp
provider identity, Gemma E2B model, context=16384, temperature=0 and request
options while changing only:

- `max_output_tokens=9000`;
- `request_timeout_seconds=7200`.

The issue #67-specific validation contract is:

`config/validation/issue67-reference.json`

Its validation/run identities remain specific to issue #67. The reusable
artifact is the versioned runtime profile, not the `issue67-*` execution
identity. A later controlled validation must create its own validation/admission
identity and explicitly select an authorized runtime version.

## Static verification and planning

These commands perform no model/network call and no persisted-state mutation:

```bash
python3 tools/case_validation.py verify-profile
python3 tools/case_validation.py plan
```

The verifier independently checks:

- historical #65 package/fingerprints and its exact 900/6144 envelope;
- current issue #67 exact 7200/9000 envelope;
- unchanged model/context/T0/top_p/top_k/thinking/stream/n parameters;
- clean-provider-state rules;
- the selected committed runtime profile;
- exact-byte SHA-256 for both validation and runtime profiles.

Plan output records both profile identities/versions/SHA-256 values and labels
the historical and current envelopes separately.

A validation profile may also live outside `config/validation`; repository
references resolve from an explicit project root rather than from the external
profile's directory depth:

```bash
python3 tools/case_validation.py \
  --profile /path/to/issue67-profile.json \
  --project-root /path/to/col-taxdata \
  verify-profile
```

## Clean runtime selection

No host-local generated config is needed. Runtime tooling can select the
committed canonical issue #67 runtime directly:

```bash
python3 tools/case_http.py \
  --config config/llm/case-validation-reference-v2.yaml \
  --db /path/to/isolated-state.sqlite \
  --case-root /path/to/isolated-case-root \
  --dry-run
```

The actual controlled execution remains owned by its execution issue. DEF-0013
does not start a provider, reset a provider, submit the frozen complex case, or
perform Phase A/Phase B.

## Readiness observation

A capability observation for the required reference backend uses the amended
canonical generation envelope:

```json
{
  "backends": {
    "quadro-m620-gemma-e2b-llamacpp": {
      "available": true,
      "capability_pass": true,
      "served_model": "gemma-4-E2B-it-Q4_K_M",
      "model_artifact_sha256": "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8",
      "generation": {
        "temperature": 0,
        "thinking": false,
        "context_tokens": 16384,
        "max_output_tokens": 9000,
        "provider_timeout_seconds": 7200,
        "top_p": 1,
        "top_k": 0,
        "stream": false,
        "n": 1
      }
    }
  }
}
```

Evaluate it read-only with:

```bash
python3 tools/case_validation.py readiness --capabilities /path/to/capabilities.json
```

FastFlowLM backends remain optional diagnostics. Their absence does not fail core
readiness and they may not silently substitute model or generation parameters.

## Controlled failure and Phase B gate

Runtime/profile readiness does not itself authorize a retry. Controlled execution failures, retries, amendments, aborts, post-fix reruns, validation-level disposition and independent-control isolation are governed by [`case-controlled-failure-protocol.md`](case-controlled-failure-protocol.md).

For #17/#67-style controlled runs, Phase B is eligible only after a canonical Phase A attempt is frozen as a completed, accepted, validator-passing CaseResult and its semantic content has not been exposed to the independent Phase B context. A rejected/failed attempt is preserved and classified; it is not retried ad hoc until something passes.

A systemic blocker has two distinct controller outcomes. `resume_same_validation` keeps the parent open and preserves same-parent rerun lineage. `diagnostic_complete_with_successor` may close the parent only for eligible systemic C/D/E/F failures with preserved evidence, explicit controller/operator authority, separately owned blockers, a distinct successor validation and `legal_pass=false`. Attempt `designation=diagnostic` alone never authorizes parent closure.

Issue #67 -> #94 is the historical diagnostic-successor example: #67 closed as a diagnostic milestone after its class-E Phase A blocker, while Phase B remained not started; #94 is a fresh successor. That history must not be represented as a valid final CaseResult or legal PASS for #67.

## Historical boundary

The issue #65 benchmark package remains historical evidence. DEF-0013 does not
rewrite its bytes, registered input/request/CaseInput hashes, three-backend
matrix, nine-run plan, or original generation envelope.

The amendment history is:

1. #65/#75 established the original 16384/6144/900 envelope.
2. Two canonical #67 attempts reached the 900-second timeout while generation
   remained active.
3. The operator explicitly authorized 16384/9000/7200 for #67.
4. That amended envelope allowed natural completion.
5. The later `INVALID_CASE_DRAFT` / `source_quote` rejection is an independent
   application-contract failure and is not evidence that the runtime amendment
   failed.

## Safety

The profile verifier/planner is read-only. It performs no schema migration,
corpus reprocessing, raw-evidence mutation, provider reset, model call, Phase A
execution, or Phase B execution.
