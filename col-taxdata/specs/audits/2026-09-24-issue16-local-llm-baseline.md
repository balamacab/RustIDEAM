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
