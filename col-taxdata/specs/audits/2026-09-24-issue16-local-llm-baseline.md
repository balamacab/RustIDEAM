# Issue #16 local LLM integration baseline — 2026-09-24

## Purpose

This dated audit records volatile runtime observations used while implementing issue #16.
It is evidence about the inspected host at one point in time, not an application contract
and not a request to rebuild the existing LLM platform.

## Read-only observation

Target: `morichalserver`.

Observed during the issue-admission baseline:

- NVIDIA GPU visible to the host: Quadro M620, reported 2048 MiB VRAM.
- Installed llama.cpp CUDA images include the server and full CUDA variants.
- Local model inventory contains:
  - Qwen3 1.7B-class Q4_K_M — primary policy model;
  - Qwen2.5 0.5B-class Q4_K_M — auxiliary policy model;
  - Gemma E2B-class Q4_K_M — review policy model.
- No llama.cpp/model container was resident when inspected.
- No OpenAI-compatible `/v1/models` response was active on the small set of
  expected loopback ports checked during the baseline.
- The runtime `/home/user/col-taxdata` directory contains the data mount and
  compose wrapper; it is not the repository source checkout.

The non-resident observation is compatible with the issue's required on-demand model
residency policy. It does **not** establish that the platform is unavailable; a final
bounded executable adapter validation is required after implementation.

## Durable configuration decision

Application-relevant policy is captured separately in
`config/llm/local-platform.yaml`:

- provider-neutral OpenAI-compatible adapter;
- loopback/private endpoint expectation;
- model routing roles;
- explicit retry/review policy;
- finite application context budgets;
- no silent truncation;
- on-demand residency;
- no shell/SQL authority for the model.

Image IDs, image sizes, exact model file byte sizes, VRAM observations, temperatures,
benchmark throughput and other transient measurements are intentionally not encoded as
durable application semantics.

## Safety

No container, model, driver, CUDA component, corpus row or raw evidence was changed
during this baseline inspection. No secrets or credentials were collected.


## Post-merge executable-adapter finding

After PR #36 merged and repository convergence passed, the issue-mandated real
adapter validation exercised the merged code against the installed llama.cpp
server and the configured Qwen3 primary model.

The first structured request reached the backend but failed application parsing:
llama.cpp returned an empty `message.content` while Qwen3 emitted reasoning text.
A bounded diagnostic isolated the model-template behavior:

- default request: `finish_reason=length`, empty content, non-empty
  `reasoning_content`;
- same request with
  `chat_template_kwargs.enable_thinking=false`: `finish_reason=stop`,
  JSON content present, no reasoning payload.

Issue #16 was therefore reopened instead of treating the initial merge as full
runtime acceptance. The corrective integration exposes safe adapter-level
`request_options` while forbidding those options from overriding
application-owned `model`, `messages`, `response_format`, `temperature` or
`max_tokens`. The local profile disables Qwen3 thinking for deterministic
structured intake. This remains an adapter/configuration concern and does not
change CASE domain semantics or give the model canonical authority.


### Semantic constrained-generation follow-up

With thinking disabled, the backend returned normal JSON content, but full
`CaseStructuringService` validation exposed a second compatibility detail:
llama.cpp/Qwen3 did not enforce the `CaseFact` `if/then` conditional in the
model-facing JSON Schema and emitted `requires_confirmation=true` for a
`user_provided` fact. The authoritative application validator correctly
rejected it as `INVALID_CASE_DRAFT`.

The application contract remains unchanged. The model-facing schema now
expands the same CaseFact conditions into explicit `oneOf` state variants so
constrained generation has direct constants/required fields for each state.
The system prompt states the same rules. Final CaseDraft validation continues
to run against the untouched authoritative v3 schema.
