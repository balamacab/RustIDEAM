# CASE reference validation runtime

Issue #75 separates the current CASE controlled-validation path from the historical issue #65 three-backend benchmark.

## Current profiles

Normal local defaults remain in:

`config/llm/local-platform.yaml`

The historical issue #75 reference-preparation profile remains unchanged at:

`config/llm/case-validation-reference.yaml`

It retains the original 16384/6144/900-second envelope and is not the current #67 canonical runtime.

The amended controlled reference runtime is versioned explicitly at:

`config/llm/case-validation-reference-v2.yaml`

That v2 runtime keeps `gemma-4-E2B-it-Q4_K_M`, context 16384, T0 and the other frozen request options, while setting the canonical amended output/timeout envelope to 9000 tokens / 7200 seconds. It uses the same OpenAI-compatible application adapter as the ordinary local path.

The #67-specific execution contract is:

`config/validation/issue67-reference.json`

Its profile/run identities are intentionally issue-specific. Other validations must not reuse `issue67-controlled-validation-v2` or `issue67-phase-a-reference` as their own execution identity. A later validation such as CASE-0003 must create its own validation/admission profile and run IDs; it may reference `case-validation-reference-v2.yaml` only if that exact runtime remains explicitly authorized for that validation.

It classifies:

- Quadro M620 + llama.cpp + Gemma E2B as the single **required reference backend**;
- Gemma E2B / Ryzen AI / FastFlowLM as **optional experimental**;
- Gemma 12B / Ryzen AI / FastFlowLM as **optional experimental**.

## Static verification

No network or model call is performed by these commands:

```bash
python3 tools/case_validation.py verify-profile
python3 tools/case_validation.py plan

# A profile may live outside config/validation; repository-relative references
# still resolve from the explicit project root.
python3 tools/case_validation.py \
  --profile /path/to/issue67-profile.json \
  --project-root /path/to/col-taxdata \
  verify-profile
```

`verify-profile` also verifies the historical #65 package and its frozen input/request/CaseInput fingerprints. It validates the selected v2 runtime profile independently, records SHA-256 over the exact selected profile bytes, and does not modify either historical package.

The required Phase A plan contains exactly one controlled E2E execution through:

`POST /v1/cases`

Optional FastFlowLM diagnostics are reported separately and never become required Phase A runs.

## Readiness input

Runtime preparation can write a small capability observation JSON outside the repository and evaluate it read-only:

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

Then:

```bash
python3 tools/case_validation.py readiness --capabilities /path/to/capabilities.json
```

Missing FastFlowLM entries are reported as unavailable experimental backends while `core_ready` remains determined solely by the strict reference backend.

An experimental backend that is available but reports a different model or generation envelope is marked ineligible for that diagnostic. It is never silently substituted and still does not fail core readiness.

## Controlled failure / rerun protocol

Before executing or resuming a controlled CASE validation, read [`case-controlled-failure-protocol.md`](case-controlled-failure-protocol.md). It is authoritative for attempt identity, provider-contact/upstream-stage evidence, retry eligibility, contract amendments, post-fix lineage, diagnostic completion, blindness, and #90/#95 evidence boundaries.

A separate preparation/admission manifest such as #95 is not an execution attempt; a failed admission gate before attempt allocation consumes no canonical attempt. Once an attempt is allocated, failures are recorded under the controlled-attempt protocol.

## Phase B gate

Phase B depends on a successful **and frozen** required Phase A result. Experimental backend availability is not a Phase B prerequisite.

## Historical benchmark boundary

The following remain historical issue #65 evidence and are not current #67 gates:

- the required three-backend matrix;
- three repetitions per backend;
- nine-run suite PASS;
- mandatory Quadro-vs-FastFlow E2B concordance;
- mandatory Gemma 12B FastFlowLM execution.

Do not modify the frozen #65 input or request to reflect the current plan.

## Safety

This profile/planner is read-only. It performs no corpus mutation, schema migration, reprocessing, provider reset, model call, Phase A execution, or Phase B execution. Runtime reset and isolated execution remain explicit operational steps owned by the executing issue.

## Cross-validation profile boundary

The reusable artifact from DEF-0013 is the versioned **reference runtime configuration** (`case-validation-reference-v2.yaml`), not the #67 validation identity. The #67 planner remains intentionally coupled to issue #67 so its evidence cannot be mistaken for CASE-0003 or another validation. New controlled validations must bind their own validation profile/run IDs to an explicitly approved runtime config and record both identities/hashes independently.
