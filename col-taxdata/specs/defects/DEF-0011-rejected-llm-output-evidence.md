# DEF-0011 — Rejected LLM structuring output evidence is lost

Status: implementing  
Priority: P1  
GitHub: #90

## Summary

CASE rejects invalid model-produced CaseDraft candidates correctly, but the pre-DEF-0011
runtime discards the exact provider response and rejected candidate. A failed legal-intake
structuring attempt therefore cannot be reconstructed forensically.

Rejected provider output is execution evidence only. It is never a CaseDraft, CaseResult,
canonical legal fact, corpus evidence, or permission to relax validation.

## Observed behavior

The #67 canonical Phase A request completed generation and was rejected by
`validate_case_draft()` at `$.facts[14].source_quote`, while the database remained
unchanged. The exact provider bytes/candidate that caused the rejection were not retained.

## Evidence

Issue #90 records the #67 raw HTTP request and CaseInput fingerprints, the 502
`INVALID_CASE_DRAFT` result, the exact validation path, and the fact that the provider
completed generation. Inspection of the pre-change implementation confirms that
`OpenAICompatibleLLMClient.complete_case_draft()` parsed raw response bytes into a
dictionary and returned only that dictionary; `CaseStructuringService._attempt()`
then validated it without an audit-evidence sink.

The first merged DEF-0011 candidate established the basic evidence path but a post-merge
high-rigor review found additional lifecycle gaps: non-atomic multi-file publication,
weak overwrite/concurrency tests, pre-provider errors being eligible for rejected-attempt
recording, loss of metadata from partially malformed envelopes, missing raw HTTP request
identity, and client-error detail that could echo model-produced schema values. Issue #90
was intentionally reopened to correct those gaps before lifecycle verification.

## Impact

A correct fail-closed rejection can destroy the evidence needed to explain why it was
rejected, or a partial/ambiguous artifact can falsely appear complete. This blocks forensic
diagnosis of legal-intake integrity failures and prevents reliable reconstruction of the
model/provider boundary.

## Root-cause hypothesis

The provider adapter and authoritative validator were separated by a lossy interface.
The first evidence implementation fixed that primary loss but did not fully define atomic
publication, provider-dispatch state, transport/request identity propagation, or safe
client-facing failure detail.

## Proposed solution

Introduce a provider-neutral generation-evidence envelope and an immutable
rejected-attempt artifact store.

For each provider/backend generation attempt that is actually dispatched and fails before
an accepted CaseDraft exists:

- allocate a unique attempt identifier;
- retain raw external HTTP request SHA-256 when the transport has one;
- retain canonical CaseInput SHA-256 and provider-request-body SHA-256 where available;
- record explicitly whether provider dispatch was attempted;
- retain adapter/provider/requested-model/routing identity and the served model where the
  response exposes it;
- retain CASE contract/prompt/schema version identifiers;
- preserve exact provider response body bytes losslessly when safe and returned;
- preserve exact assistant content as UTF-8 bytes/string and SHA-256 when extractable;
- preserve deterministic JSON for every successfully parsed candidate value, including
  non-object JSON roots, with SHA-256;
- retain HTTP status, finish reason and provider usage/token metadata as soon as those
  fields are available, even if later envelope extraction fails;
- record authoritative failure code, exact detail/path, timestamps, and failure stage;
- explicitly represent unavailable evidence as absent rather than fabricating it.

Pre-dispatch failures such as local context-budget rejection, incompatible local request
configuration or missing credentials are not provider-rejected-output artifacts. They
remain normal fail-closed runtime/admission failures and are not mislabeled as transport
attempt evidence. Broader classification/retry disposition remains owned by issue #93.

### Security boundary

The OpenAI-compatible adapter preserves response **body** bytes only. HTTP request/response
headers, Authorization values and transport credentials are outside the evidence model.

If the exact configured API-key value is detected inside a provider response body, payload
artifacts from that response are deliberately suppressed rather than persisting the
credential. The manifest records `payload_omission_reason=configured_api_key_material_detected`.
This security exception is explicit: exact rejected payload recovery applies when storage
does not conflict with the no-secret requirement. Provider adapters must apply the same
principle to credentials they own.

Ordinary HTTP/CLI error surfaces expose stable error codes and safe validation paths where
appropriate, not model-produced values or raw rejected payload. Exact validator detail
remains inside the protected audit artifact.

### Atomicity and immutability

Artifacts live below the configured CASE runtime artifact root at
`_audit/rejected-structuring-attempts/<attempt-id>/`.

A complete attempt is assembled in a private same-filesystem staging directory with
restrictive file creation permissions, flushed, and atomically renamed into the final
attempt path. The final path is create-once. A same-ID retry/collision fails rather than
replacing existing evidence. Failed staging writes do not publish a final attempt
directory. A retry must allocate a new attempt ID.

Artifacts are non-canonical and do not write the corpus/database.

### Validation boundary

`validate_case_draft()` remains the authoritative first application-validity gate.
Only **after** it rejects a candidate does CASE replay the schema-only check to classify
the forensic stage as `schema_validation` versus `semantic_validation`. This
classification pass cannot repair, coerce or accept model output.

The provider-neutral service can carry equivalent `GenerationEvidence` from any
CASE-compatible adapter; raw response capture is not tied to OpenAI/llama.cpp semantics.

## Non-goals

This defect does not diagnose or repair the #67 quote mismatch, change generation
parameters, rerun #67, perform Phase B, redesign broad execution provenance (#11), modify
historical #65/#67 evidence, change canonical CASE/corpus identity, or implement the
controlled retry/disposition matrix owned by #93.

Execution-profile identity, image/Git/baseline lineage and broader run manifests remain
owned by #11/#92/#93. DEF-0011 supplies the lossless rejected-output component those
protocols consume.

## Reprocessing plan

None. No corpus replay, production database mutation, migration, or raw-evidence rewrite
is required. The change applies prospectively to future CASE structuring attempts.

## Acceptance criteria

1. Exact rejected provider output is recoverable when bytes were returned and do not contain configured credential material.
2. Rejected output is explicitly non-canonical and cannot be mistaken for CaseDraft/CaseResult state.
3. CASE validation remains fail-closed and no repair path is introduced.
4. Failure artifacts contain failure code/path/detail, stage, timestamps, identities and reproducible hashes.
5. Raw HTTP request, CaseInput and provider-request fingerprints are distinguished and retained where available.
6. Provider dispatch state is explicit; pre-provider failures are not mislabeled as rejected provider attempts.
7. Failed attempts publish atomically, are create-once, remain distinct across retries and cannot overwrite one another under collision/concurrency.
8. Partial evidence-write failure does not publish a final attempt directory.
9. Timeout/no-response records explicit absence rather than fabricated response bytes.
10. Output-ceiling and partially malformed-envelope failures preserve all safe metadata already available.
11. Every successfully parsed JSON candidate value has deterministic serialized evidence, even when the root is not an object.
12. Normal HTTP/CLI/log surfaces do not expose raw rejected model values.
13. Authorization/API-key material is not captured; detected credential echo is explicitly suppressed.
14. A provider-neutral evidence-carrying adapter can use the same rejected-attempt store without OpenAI-specific logic.
15. Failed structuring does not mutate canonical case/corpus/database state.
16. Existing #76 structured-output/no-repair behavior remains green.
17. No immutable corpus/raw evidence is modified.

## Regression tests

`tests/test_issue0090_rejected_llm_evidence.py` covers:

- semantically invalid but schema-valid candidate with exact raw/candidate/request-hash recovery;
- malformed assistant JSON;
- malformed and partially malformed provider envelopes;
- parsed non-object JSON candidate evidence;
- timeout with no response;
- pre-provider context rejection producing no rejected-attempt artifact;
- output-ceiling metadata;
- accepted draft producing no rejected artifact;
- distinct retry artifacts;
- create-once overwrite refusal;
- concurrent same-ID publication;
- partial-write atomicity;
- path-escape rejection;
- provider-neutral evidence-carrying adapter behavior;
- HTTP transport propagation of raw request SHA;
- HTTP/CLI rejected-value non-leakage;
- configured API-key echo suppression;
- non-canonical artifact-only failure state;
- SHA-256 reproduction from stored bytes.

The existing `tests/test_issue0076_structured_output_compatibility.py` remains the
preservation suite for schema-constrained direct output and the no-repair rule.

## Dependencies / ordering

Issue #90 is the selected implementation owner. #11 owns broader execution provenance,
#61 documents trust boundaries, #67 is the historical reproducer, #76 owns
structured-generation/no-repair compatibility, #91 owns source-quote diagnosis, #92 owns
the durable #67 runtime envelope, #93 owns controlled failure/retry disposition, and #95
is a downstream runtime-preparation consumer.

DEF-0011 must remain compatible with those boundaries: it preserves rejected generation
evidence but does not decide whether a controlled run may retry or how a broader execution
manifest is versioned.
