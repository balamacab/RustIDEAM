# CASE reference validation runtime

Issue #75 separates the current CASE controlled-validation path from the historical issue #65 three-backend benchmark.

## Current profiles

Normal local defaults remain in:

`config/llm/local-platform.yaml`

Controlled validation uses the dedicated profile:

`config/llm/case-validation-reference.yaml`

That profile makes `gemma-4-E2B-it-Q4_K_M` the actual primary structuring model with the frozen 16384/6144/900-second envelope. It uses the same OpenAI-compatible application adapter as the ordinary local path.

The execution contract is:

`config/validation/issue67-reference.json`

It classifies:

- Quadro M620 + llama.cpp + Gemma E2B as the single **required reference backend**;
- Gemma E2B / Ryzen AI / FastFlowLM as **optional experimental**;
- Gemma 12B / Ryzen AI / FastFlowLM as **optional experimental**.

## Static verification

No network or model call is performed by these commands:

```bash
python3 tools/case_validation.py verify-profile
python3 tools/case_validation.py plan
```

`verify-profile` also verifies the historical #65 package and its frozen input/request/CaseInput fingerprints. It does not modify that package.

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
        "max_output_tokens": 6144,
        "provider_timeout_seconds": 900,
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
