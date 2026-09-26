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

Issue #90 records the #67 request and CaseInput fingerprints, the 502
`INVALID_CASE_DRAFT` result, the exact validation path, and the fact that the provider
completed generation. Inspection of the pre-change implementation confirms that
`OpenAICompatibleLLMClient.complete_case_draft()` parsed raw response bytes into a
dictionary and returned only that dictionary; `CaseStructuringService._attempt()`
then validated it without an audit-evidence sink.

## Impact

A correct fail-closed rejection can destroy the evidence needed to explain why it was
rejected. This blocks forensic diagnosis of legal-intake integrity failures and prevents
reproduction of the model/provider boundary from preserved execution artifacts.

## Root-cause hypothesis

The provider adapter and authoritative validator are separated by a lossy interface:
provider response bytes, finish reason, usage and assistant content are discarded before
the validator decides whether the candidate is acceptable.

## Proposed solution

Introduce a provider-neutral generation-evidence envelope and an immutable rejected-attempt
artifact store.

For each provider-reaching attempt that fails before an accepted CaseDraft exists:

- allocate a unique attempt identifier;
- retain the canonical CaseInput SHA-256 and provider-request SHA-256 where available;
- retain adapter/provider/model/routing identity and CASE contract/prompt/schema versions;
- preserve exact provider response bytes losslessly when returned;
- preserve exact assistant content and SHA-256 when extractable;
- preserve deterministic candidate JSON and SHA-256 when parsing succeeds;
- retain finish reason and provider usage metadata when present;
- record authoritative failure code, exact detail/path, timestamps, and failure stage;
- explicitly represent unavailable response/content bytes as absent rather than fabricating them.

The OpenAI-compatible adapter preserves response body bytes only. HTTP response/request
headers, authorization values, API keys, and other transport credentials are outside the
evidence envelope and must never be captured.

Artifacts live below the configured CASE runtime artifact root at
`_audit/rejected-structuring-attempts/<attempt-id>/`. The directory is create-once;
a retry must allocate a new attempt ID. Artifacts are non-canonical and do not write the
corpus/database.

Schema validation is classified before the existing authoritative
`validate_case_draft()` call solely to identify the failure stage. The authoritative
validator remains mandatory; no repair, coercion, prompt tuning, or validation relaxation
is introduced.

## Non-goals

This defect does not diagnose or repair the #67 quote mismatch, change generation
parameters, rerun #67, perform Phase B, redesign broad execution provenance (#11), modify
historical #65/#67 evidence, or change canonical CASE/corpus identity.

## Reprocessing plan

None. No corpus replay, production database mutation, migration, or raw-evidence rewrite
is required. The change applies prospectively to future CASE structuring attempts.

## Acceptance criteria

1. Exact rejected provider output is recoverable when the provider returned bytes.
2. Rejected output is explicitly non-canonical and cannot be mistaken for CaseDraft/CaseResult state.
3. CASE validation remains fail-closed and no repair path is introduced.
4. Failure artifacts contain failure code/path/detail, stage, timestamps, identities and reproducible hashes.
5. Failed attempts are immutable and distinct across retries.
6. Timeout/no-response records explicit absence rather than fabricated response bytes.
7. Output-ceiling failures preserve available provider response, finish reason and usage.
8. Normal HTTP errors/logs do not expose raw rejected content.
9. Authorization/API-key material is not captured.
10. Failed structuring does not mutate canonical case/corpus/database state.
11. Existing #76 structured-output/no-repair behavior remains green.
12. No immutable corpus/raw evidence is modified.

## Regression tests

`tests/test_issue0090_rejected_llm_evidence.py` covers:

- semantically invalid but schema-valid candidate with exact raw/candidate recovery;
- malformed assistant JSON;
- malformed provider envelope;
- timeout with no response;
- output ceiling metadata;
- accepted draft producing no rejected artifact;
- distinct retry artifacts;
- HTTP non-leakage and credential exclusion;
- non-canonical artifact-only failure state;
- SHA-256 reproduction from stored bytes.

The existing `tests/test_issue0076_structured_output_compatibility.py` remains the
preservation suite for schema-constrained direct output and the no-repair rule.

## Dependencies / ordering

Issue #90 is the selected implementation owner. #11 owns broader execution provenance,
#61 documents trust boundaries, #67 is the historical reproducer, and #76 owns
structured-generation/no-repair compatibility; none is replaced by this defect.

Issue #53 is concurrently active in the specification catalog. DEF-0011 registration must
therefore remain a minimal additive manifest/index edit and be reconciled against current
`main` before merge rather than overwriting #53 catalog work.
