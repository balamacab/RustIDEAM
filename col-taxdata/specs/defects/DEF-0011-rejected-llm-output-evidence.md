# DEF-0011 — Preserve rejected LLM structuring outputs as auditable failure evidence

Status: **verified**

GitHub issue: [#90](https://github.com/balamacab/RustIDEAM/issues/90)

Priority: **P1**

## 1. Summary

CASE must reject malformed or semantically invalid model output without losing
the execution evidence that explains the rejection. A provider response that
fails CASE structuring is not a CaseDraft, CaseResult, legal fact, canonical
corpus evidence, or permission to relax validation. It is append-only execution
evidence for one failed model attempt.

This defect adds a narrow rejected-structuring-attempt evidence boundary. It
does not implement the broader run/execution provenance model owned by issue
#11.

## 2. Observed behavior

Issue #67 completed a structured-generation request and CASE correctly rejected
the resulting candidate with:

```text
INVALID_CASE_DRAFT
$.facts[14].source_quote:
user_provided quote is not present verbatim in CaseInput.problem_text
```

The provider response had already been read and parsed by
`OpenAICompatibleLLMClient.complete_case_draft()`, but that method returned
only the parsed candidate dictionary. When `CaseStructuringService` later
rejected the candidate, the exact provider response and assistant content were
no longer available.

The historical #67 attempt is not reconstructed or rerun by this defect. The
fix applies to future CASE executions.

## 3. Evidence and root cause

The clean pre-implementation code path is:

```text
provider HTTP response bytes
  -> json.loads(provider envelope)
  -> message.content
  -> json.loads(candidate)
  -> return candidate dict only
  -> add application model_metadata
  -> validate_case_draft()
  -> reject
```

The loss occurs at the adapter/service boundary: transport evidence is discarded
before authoritative application validation has decided whether the candidate
is acceptable.

The validator is not defective. The #76 provider-neutral structured-output
contract and its no-repair rule are authoritative and remain unchanged.

## 4. Impact

Without rejected-output evidence, a legal/auditable CASE failure cannot prove
exactly what the backend returned, which bytes were parsed, which candidate was
validated, or whether a reported path/detail corresponds to the actual model
output. A later retry cannot substitute for the missing failed attempt because
it may produce different output.

## 5. Required evidence model

Every model attempt that reaches the provider and fails before an accepted
CaseDraft is produced records, where available:

- immutable attempt identifier and application run reference;
- canonical CaseInput SHA-256;
- SHA-256 of the exact provider request body without storing that body;
- adapter/provider/requested-model and served-model identity;
- routing role;
- active CASE contract version;
- prompt-template identifier/version;
- deterministic response-schema SHA-256;
- exact provider HTTP response **body bytes** and SHA-256;
- HTTP status when available;
- finish reason;
- provider usage/token metadata from the response body;
- exact assistant `message.content` UTF-8 bytes/string and SHA-256;
- deterministic canonical JSON serialization of a parsed candidate and SHA-256;
- authoritative failure code;
- exact validation path when one exists;
- exact validator/error detail;
- start/end UTC timestamps;
- failure stage.

Failure stage is one of:

- `transport`;
- `provider_envelope`;
- `json_parse`;
- `output_ceiling`;
- `schema_validation`;
- `semantic_validation`.

A timeout or transport failure with no response records
`provider_response.present=false`; it must never fabricate response bytes.

## 6. Artifact layout and immutability

Runtime location:

```text
<case-root>/
  _audit/
    rejected-structuring-attempts/
      ATT-<opaque-id>/
        manifest.json
        provider-response.bin       # only when bytes exist
        assistant-content.txt       # only when content exists
        candidate.json              # only when parsing succeeded
```

`manifest.json` records SHA-256 and byte length for every optional artifact,
including explicit absence. `candidate.json` is deterministic UTF-8 canonical
JSON used for forensic hashing; it is not an accepted CaseDraft.

Each attempt directory and each file are created once. Existing attempt
directories/files are never overwritten. Every retry receives a new attempt
identifier and run reference. A later success neither rewrites nor deletes a
failed artifact.

The evidence store is outside canonical case/corpus persistence. Rejected
artifacts set `canonical_state=false` and are never consumed as legal evidence
or promoted into CaseDraft/CaseResult state.

## 7. Privacy and security boundary

The exact preserved provider payload is the **HTTP response body only**.

The evidence model deliberately excludes:

- request headers;
- response headers;
- `Authorization`;
- API keys or credential environment values;
- the full provider request body;
- full prompts as separate audit artifacts.

The provider request body is represented only by SHA-256. The response schema is
represented by SHA-256 plus its existing versioned CASE contract/template
identifiers.

Raw rejected content is never added to ordinary HTTP error bodies or ordinary
request logs. Git, issue comments, and normal application error output are not
payload stores.

Because provider response bodies may contain client-provided material, rejected
attempts live only under the CASE runtime audit tree and are created with
owner-only file permissions. Deployments must protect that runtime location at
least as strictly as other CASE execution artifacts.

## 8. Validation and #76 preservation

`validate_case_draft(case_input, draft)` remains the first and authoritative
application validation call after candidate generation.

If it rejects, CASE may run the schema-only validator **after the failure** only
to classify the recorded failure as `schema_validation` versus
`semantic_validation`. This classification must not pre-validate, repair,
coerce, rename, insert, delete, or otherwise modify candidate output.

Markdown fences, prose wrapping, malformed JSON, wrong fields and all other #76
no-repair cases remain fail-closed.

The transport evidence object is stripped before application-owned
`model_metadata` is added. It can never serialize into an accepted CaseDraft.

## 9. Reprocessing / migration / production state

**Corpus reprocessing: N/A.**

**Database migration: N/A.**

**Production DB mutation: N/A.**

DEF-0011 changes future CASE execution evidence capture only. It does not
redownload evidence, mutate raw manifestations, rewrite registered SHA-256
values, alter canonical legal identity, or rerun #67/CASE-0003.

The runtime audit write itself is intentional even when the surrounding CASE
execution later fails: preserving that failed attempt is the behavior this
defect requires. It is not canonical/corpus mutation.

## 10. Regression tests

Automated coverage must prove at minimum:

1. a schema-valid but semantically invalid candidate is rejected and exact
   provider response/content/candidate evidence is preserved;
2. malformed assistant JSON preserves exact provider bytes and content;
3. a malformed provider envelope before content extraction preserves available
   raw response bytes;
4. timeout/no-response records explicit response absence;
5. output-ceiling failure preserves available provider bytes, finish reason and
   usage;
6. schema-invalid output is classified only after authoritative validation;
7. a valid accepted CaseDraft creates no rejected-attempt artifact;
8. failed structuring creates no canonical case/corpus mutation;
9. repeated failed attempts create distinct immutable artifacts;
10. a later successful retry has a distinct run identity and leaves the failed
    artifact unchanged;
11. normal HTTP error serialization does not expose raw rejected content;
12. credential/API-key material is absent from persisted artifacts;
13. stored SHA-256 values reproduce from stored bytes;
14. the existing #76 no-repair/provider-neutral regression suite remains green.

## 11. Dependencies and ordering

- #76 is an established contract that DEF-0011 must preserve; it is not a
  blocker.
- #11 owns broader execution provenance and remains out of scope.
- #61 documents wider CASE/LLM trust boundaries and is not required for this
  functional evidence path.
- #67 is the historical reproducer. It must not be rerun by this issue.
- #53 may edit the specification catalog concurrently. DEF-0011 registration is
  additive and must be reconciled against current main rather than overwriting
  unrelated catalog work.

## 12. Acceptance criteria

DEF-0011 is verified only when:

- the specification exists and is registered consistently;
- exact rejected provider response bodies are recoverable for future invalid
  CaseDraft failures whenever the provider returned bytes;
- absent response bytes are represented explicitly rather than fabricated;
- rejected output remains non-canonical and cannot be mistaken for accepted
  CaseDraft/CaseResult state;
- CASE remains fail-closed with no repair or validation relaxation;
- failure artifacts contain exact failure code/path/detail, stage, relevant
  provider metadata and reproducible hashes;
- failed attempts are create-once, immutable and distinct across retries;
- later success does not overwrite/delete prior failure evidence;
- normal client-facing HTTP errors and ordinary logs do not expose raw rejected
  model content;
- request/response transport secrets and API-key material are not captured;
- failed structuring does not mutate corpus/canonical case state;
- no raw corpus evidence or registered SHA-256 is modified;
- semantic invalidity, malformed JSON/envelope, timeout/no-response,
  output-ceiling and successful output regressions pass;
- relevant #76 and existing CASE contract tests remain green;
- every repository content change remains inside `col-taxdata/`.

## 13. Non-goals

This defect does not:

- decide whether the historical #67 source-quote mismatch was materially
  correct or incorrect;
- relax verbatim source-quote validation;
- change T0 or generation parameters;
- tune prompts/models;
- repair rejected drafts;
- rerun #67 or CASE-0003;
- perform Phase B;
- redesign issue #11 broad execution provenance;
- modify immutable historical #65/#67 evidence.
