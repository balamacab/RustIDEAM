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


### Final merged-runtime acceptance failure and recovery

A bounded validation of the final PR #40 merge
`b7f40353776d6f44ad9afe17f2d04cf7489bb997` reached the real
llama.cpp/Qwen3 backend with thinking disabled and the model-facing CaseFact
constraints in place, but the accepted CaseDraft still failed because the model
omitted an immutable client-owned optional field:

```text
INVALID_CASE_DRAFT: $.as_of_date: client field presence/absence was not preserved
```

This is an application-boundary defect, not a reason to weaken the v3 contract.
The recovery makes `problem_text`, `as_of_date` and `client_reference`
application-owned during model generation: they remain visible to the model as
input context, are excluded from the model-facing output schema, and are copied
exactly from the retained CaseInput into the final CaseDraft before authoritative
v3 validation. A model that nevertheless echoes one of these fields with a
different/manufactured value is rejected.

The OpenAI-compatible adapter also verifies the backend response's `model`
identifier against the requested route before the application records
`model_metadata.model`. This prevents review/primary routing metadata from
claiming a configured model that the selected backend did not actually serve.

The historical failing observations above remain preserved. Final runtime PASS
evidence must be appended only after the recovery branch passes repository CI
and the merged-code-equivalent primary-model validation succeeds.


### Recovery design correction after contract re-read

The first recovery patch experimentally moved immutable client fields outside the
model output and re-injected them afterward. That approach was rejected before
merge because CASE v3 §5.1 and issue #23 explicitly require an omitted supplied
optional field to remain an `INVALID_CASE_DRAFT`; the application must not
repair a missing model value after the fact.

The recovery now keeps the complete CaseDraft contract intact. For each
CaseInput, the model-facing JSON Schema pins `problem_text` and each present
optional client field with an exact `const`, requires supplied optional fields,
and removes absent optional properties so constrained generation cannot
manufacture them. The authoritative post-generation validator remains unchanged
and still rejects any mismatch.

A second bounded Qwen3 diagnostic identified the next primary-output failure:
the model treated `as_of_date` and `client_reference` metadata as
`user_provided` CaseFact values and used those metadata strings as
`source_quote`, although they were not verbatim substrings of
`problem_text`. The validator correctly rejected the draft. The prompt/model
context now distinguishes `problem_text` as the only client fact-source text,
passes `as_of_date` only as temporal analysis context, and does not expose
`client_reference` as analytical model context.

The same runtime phase also proved that automatic review escalation cannot be
truthfully executed through the current single-model llama.cpp endpoint: when
the configured review route requested Gemma, the endpoint continued serving
Qwen3. The adapter's served-model integrity check rejected the mismatch. The
local profile therefore disables automatic review-on-invalid-output while
retaining the configured review route for an environment/runtime router that can
actually make that model resident. This avoids false review metadata and does
not require simultaneous model residency.


### Final recovery runtime acceptance

The recovery code at commit
`348edecd0fe5658a165a722de9cd0e970da6885c` passed the required real local
adapter validation against the installed llama.cpp CUDA server and
`Qwen3-1.7B-Q4_K_M`.

A direct full `CaseStructuringService` execution completed successfully with
the real primary model and therefore passed the authoritative v3 CaseDraft
schema/semantic validation, including exact immutable client-payload
preservation. It advanced to the CLI phase without review escalation.

The first CLI dry-run attempt exposed an unrelated host-capacity condition:
`/tmp` had only about 101 MiB available while the runtime SQLite database was
about 824 MiB, so SQLite backup failed with `database or disk is full`. A
second candidate temporary path under `data/tmp` was not writable by the
runtime user; permissions/ownership were intentionally not changed. The final
validation used a new disposable directory under `/home/user`, on the same
filesystem that had about 65 GiB available, and removed it after completion.

The exact natural-language CLI path then passed:

```text
tools/analyze_case.py
  --input <natural-language-file>
  --as-of-date 2026-09-24
  --client-reference issue16-pr47-cli
  --db /home/user/col-taxdata/data/state/taxdata.sqlite
  --dry-run
```

Observed result:

- adapter: `openai-compatible`;
- provider: `local-llama-cpp`;
- model: `Qwen3-1.7B-Q4_K_M`;
- routing role: `primary`;
- prompt template version: `3`;
- persistence mode: `dry-run`;
- generated bundle validation: `true`;
- analysis status: `partial`;
- facts: 2;
- questions: 2;
- supported claims: 0;
- remaining candidate claims: 1;
- unresolved items: 2;
- evidence objects: 0.

The unsupported legal conclusion remained candidate/unresolved rather than being
promoted without canonical evidence.

Non-mutation checks passed:

- source SQLite SHA-256 before/after: unchanged;
- canonical `cases` row count before/after: 1 -> 1;
- requested case-root remained absent after dry-run.

No production corpus row, raw manifestation, registered hash, permission,
ownership, model file, driver, or persistent service configuration was changed.

Remote validation required more status reads than the original two-phase budget
because Desktop Commander returned control while the bounded inference process
was still running and two environment-only dry-run attempts were needed
(`/tmp` capacity, then a non-writable existing temp directory). The actual
runtime actions remained bounded and non-destructive: one primary diagnostic
phase, one corrected full service/CLI validation phase, and one environment-only
CLI rerun using a disposable writable home-directory temp area.
