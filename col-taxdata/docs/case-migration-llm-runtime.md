# CASE migration-test LLM runtime — issue #133

Issue #133 admits an operator-owned llama.cpp backend for **real-provider tests in the #130 CASE architecture-migration program**. This runtime is not a production backend decision and is not the historical CASE-0003 / #94 / #95 reference runtime.

## Committed profile

The migration-test profile is:

`config/llm/case-migration-rtx3070-v1.yaml`

It preserves the current OpenAI-compatible CASE generation envelope while giving the migration runtime a distinct identity. The profile deliberately contains no operator workstation address. The live endpoint is selected at execution time with:

`COL_TAXDATA_LLM_BASE_URL=http://<operator-host>:<port>/v1`

`tools/llm_client.py` already gives this environment variable precedence over the committed loopback default.

The profile freezes the expected model artifact SHA-256 supplied by the runtime admission contract and the HTTP-observable backend/model identity. It also marks the runtime as migration-test-only and non-production.

## Read-only live evidence — 2026-09-27

The authorized test host `morichalserver` reached the operator backend over the LAN without changing provider, corpus, database, or CASE state.

Observed through the public llama.cpp HTTP surface:

- TCP connection succeeded with approximately 8 ms connection latency in the admission probe.
- `GET /health`: HTTP 200, `{"status":"ok"}`.
- server header: `llama.cpp`.
- build info: `b11176-f805c57a2`.
- `GET /v1/models`: exactly one served model, `gemma-4-E2B-it-Q4_K_M`.
- served format/quantization: GGUF / `Q4_K - Medium`.
- served context: 16384 tokens; training context reported as 131072.
- model metadata: 4,647,450,147 parameters, 3,090,917,516-byte reported model size.
- `GET /props`: model path `/models/gemma-4-E2B-it-Q4_K_M.gguf`, four slots.

A bounded synthetic intake-only JSON-Schema request was then sent through the same OpenAI-compatible `/v1/chat/completions` protocol used by the current adapter. It did not contain CASE-0003 or production case data.

Observed smoke result:

- HTTP 200;
- served model: `gemma-4-E2B-it-Q4_K_M`;
- prompt tokens: 127;
- completion tokens: 193;
- total tokens: 320;
- finish reason: `stop`;
- backend-reported completion throughput: approximately 97.4 tokens/s;
- wall-clock completion throughput: approximately 89.6 tokens/s;
- output parsed as the requested strict JSON object;
- output-ceiling truncation: false.

The generated object contained facts, questions, missing facts and neutral search hints only; it did not need a legal conclusion to satisfy the smoke contract.

## Host-level identity gate

The HTTP API does **not** expose the GGUF file SHA-256: the model `digest` field is empty. It also does not expose the Docker image digest or GPU identity. Those facts must be verified from the operator host before #133 can be marked fully admitted.

Until that host-level verification is captured, the expected GGUF SHA-256 in the profile is a frozen **expected identity**, not a claim that the live file hash has already been independently re-read.

No attempt should substitute historical #94/#95 runtime evidence for this missing host-level proof.

## Safety boundary

This admission work performs no CASE-0003 rerun, no production DB mutation, no raw-evidence mutation and no corpus reprocessing. Later #130 child issues may use this backend for real-provider tests only after #133 reaches its complete acceptance gate.
