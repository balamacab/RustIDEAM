# CASE migration-test LLM runtime — issue #133

Issue #133 admits an operator-owned llama.cpp backend for **real-provider tests in the #130 CASE architecture-migration program**. This runtime is not a production backend decision and is not the historical CASE-0003 / #94 / #95 reference runtime.

## Committed profile

The migration-test profile is:

`config/llm/case-migration-rtx3070-v1.yaml`

It preserves the current OpenAI-compatible CASE generation envelope while giving the migration runtime a distinct identity. The profile deliberately contains no operator workstation address. The live endpoint is selected at execution time with:

`COL_TAXDATA_LLM_BASE_URL=http://<operator-host>:<port>/v1`

`tools/llm_client.py` already gives this environment variable precedence over the committed loopback default.

The profile records the verified model artifact, immutable container image identity, GPU/runtime facts needed to reproduce the admission, and the HTTP-observable backend/model identity. These fields are admission evidence only; they do not make the operator host topology an application/domain contract.

## Read-only LAN and HTTP evidence — 2026-09-27

The authorized test host `morichalserver` reached the operator backend over the LAN without changing provider, corpus, database, or CASE state.

Observed through the public llama.cpp HTTP surface:

- TCP connection succeeded with approximately 8 ms connection latency in the admission probe.
- `GET /health`: HTTP 200, `{"status":"ok"}`.
- server header: `llama.cpp`.
- build info: `b11176-f805c57a2`.
- `GET /v1/models`: exactly one served model, `gemma-4-E2B-it-Q4_K_M`.
- served format/quantization: GGUF / `Q4_K - Medium`.
- served context: 16384 tokens; training context reported as 131072.
- model metadata: 4,647,450,147 parameters.
- `GET /props`: model path `/models/gemma-4-E2B-it-Q4_K_M.gguf`, four slots.

The HTTP model `digest` field was empty, so artifact identity was not inferred from the API.

## Verified host-level identity — 2026-09-27

Read-only host evidence from SUPERBLASTER established the missing immutable identities:

- runtime: WSL2, Ubuntu 22.04.4 LTS;
- GPU: NVIDIA GeForce RTX 3070 Laptop GPU;
- GPU UUID: `GPU-a71e7801-dca9-36f4-da0a-6fc10ead8d0f`;
- NVIDIA driver: `596.36`;
- VRAM: 8192 MiB;
- live GGUF SHA-256: `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8`;
- live GGUF file size: 3,106,738,272 bytes;
- container image ID: `sha256:c5daab599318142f2b16a75d05d4c4c6763eba8b2574a9eaab85df8ffd86fce3`;
- immutable image digest: `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`;
- model bind mount is read-only in the running container;
- effective server arguments include `-c 16384`, `--n-gpu-layers 99`, alias `gemma-4-E2B-it-Q4_K_M`, and the expected GGUF path.

The host file SHA-256 exactly matches the expected admission SHA-256. The API's model-size metadata differs from the host filesystem byte count; identity is therefore established by the independently verified file SHA-256 rather than by API size metadata.

## Structured-generation smoke

A bounded synthetic intake-only JSON-Schema request was sent through the same OpenAI-compatible `/v1/chat/completions` protocol used by the current adapter. It did not contain CASE-0003 or production case data.

First smoke result:

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

A second bounded smoke used the committed 9000-token output ceiling without requesting a long response:

- HTTP 200;
- system fingerprint: `b11176-f805c57a2`;
- prompt tokens: 71;
- completion tokens: 168;
- total tokens: 239;
- finish reason: `stop`;
- backend-reported completion throughput: approximately 88.3 tokens/s;
- strict JSON object parsed successfully;
- output-ceiling truncation: false.

The generated objects contained intake semantics only for the smoke envelope. They did not need a legal conclusion to satisfy the structured-generation contract.

## Acceptance interpretation

The runtime admission evidence now establishes:

- backend/image/model identity is frozen and reproducible;
- the GGUF artifact SHA-256 matches the expected identity;
- served model identity and 16384 context are verified;
- LAN reachability from the authorized test host is verified;
- OpenAI-compatible strict structured generation succeeds;
- the committed 9000-token output envelope is accepted without ceiling truncation in the bounded smoke;
- endpoint selection remains environment-injectable and no operator LAN address is committed;
- the profile is explicitly migration-test-only and distinct from #94/#95.

Repository CI and post-merge convergence remain the final integration gates before issue #133 can be considered complete.

## Safety boundary

This admission work performs no CASE-0003 rerun, no production DB mutation, no raw-evidence mutation and no corpus reprocessing. The runtime is not promoted to a production/canonical backend by this admission. After #133 passes repository integration, #130 child implementation issues may use this backend for their real-provider acceptance tests unless the controller records a later explicit runtime amendment.
