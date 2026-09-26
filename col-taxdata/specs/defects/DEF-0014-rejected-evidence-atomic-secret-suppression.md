# DEF-0014 — Harden rejected CASE evidence against credential echo and partial publication

Status: **implementing**

GitHub issue: [#113](https://github.com/balamacab/RustIDEAM/issues/113)

Priority: **not assigned by issue #113**

## 1. Summary

Rejected CASE structuring output is forensic execution evidence, but the verified
DEF-0011 implementation has two residual risks at the same persistence boundary:

1. a provider can echo a configured runtime credential in its response body,
   contradicting DEF-0011's simultaneous exact-response and no-credential goals;
2. the store creates the final `ATT-*` directory before all files are durable, so
   an interrupted write can expose a partial directory as though it were a
   published attempt.

This defect is a narrow corrective hardening follow-up. It does not weaken
CaseDraft validation, alter #76 no-repair semantics, or rewrite historical #90
artifacts.

## 2. Normative clarification of DEF-0011

This specification amends DEF-0011's exact-response retention rule for future
attempts with one explicit precedence rule:

> **Configured credential secrecy overrides exact raw-response retention.**

The DEF-0011 requirement to preserve exact provider response bytes therefore
continues to apply only when those bytes do **not** contain an exact credential
value that CASE actually resolved for the outbound request.

When exact configured credential bytes are present in an observed provider
response, CASE must not persist those bytes. Instead the artifact record must
prove the observation without content by recording at least:

- `present=true`;
- exact byte length;
- SHA-256 computed over the exact in-memory response bytes;
- `persisted=false`;
- `suppressed=true`;
- suppression reason `credential_material_detected`.

The same rule applies independently to assistant content and canonical candidate
JSON when those derivative bytes contain the configured credential. A derivative
that does not contain the credential need not be suppressed merely because some
other response field was contaminated.

The manifest itself must not contain the configured credential value. Metadata
that contains the exact configured credential must be replaced by an explicit
suppression marker rather than copied verbatim.

This is not generic DLP. Detection is deterministic substring matching against
non-empty exact credential values actually resolved by the adapter at runtime.
Absent configured credential material must not suppress ordinary legal/client
text.

## 3. Observed behavior and evidence

The current DEF-0011 store performs the effective sequence:

```text
mkdir ATT-<id>
write provider response
write assistant content
write candidate
write manifest last
```

Files use create-once mode and owner-only permissions, but the final directory is
visible throughout that sequence. A failure after any earlier file therefore
leaves a partial final attempt.

`GenerationEvidence` also carries the exact provider response body to the store
without a suppression decision based on the API key resolved for the outbound
request. Existing #90 coverage proves the request credential is not copied from
headers into artifacts, but it does not protect against a provider echoing that
credential in returned content.

## 4. Root cause

DEF-0011 correctly established an immutable rejected-attempt evidence boundary,
but it did not distinguish:

- observed bytes from bytes eligible for persistence; or
- in-progress persistence from published evidence.

The store therefore has no explicit representation for "response existed but
content was suppressed", and its final namespace doubles as its staging
namespace.

## 5. Required implementation

### 5.1 Evidence schema

Advance the rejected-attempt evidence schema for new attempts. Each optional
artifact records observation and persistence independently, including:

- `present`;
- `persisted`;
- `path` only when persisted;
- encoding;
- exact SHA-256 and byte length when present;
- `suppressed`;
- suppression reason.

Configured secret values used for matching are in-memory decision inputs only.
They must not be serialized, logged, added to exception detail, or written into
the evidence tree.

Ordinary non-contaminated output remains byte-for-byte preserved.

### 5.2 Crash-atomic publication

Persist a rejected attempt under an owner-only staging directory whose name
cannot be mistaken for canonical `ATT-*` evidence.

The required sequence is:

```text
create .staging-<opaque> with mode 0700
write each eligible artifact create-once, flush and fsync
write manifest last after suppression decisions are final
fsync staging directory metadata where supported
atomically rename staging -> ATT-<id> on the same filesystem
fsync the parent directory where supported
```

Publication must serialize competing writers for the same attempt ID and must
never replace an existing final attempt. Stale `.staging-*` state is
non-canonical and may be retained conservatively for diagnosis. No cleanup path
may delete an already published attempt.

### 5.3 Persistence failure

If a provider-backed structuring attempt is rejected and its configured evidence
store fails, CASE must not continue as though forensic preservation succeeded.

It must surface deterministic error code
`CASE_EVIDENCE_PERSISTENCE_FAILED`, remain non-retryable at the structuring
policy boundary, and preserve the original structuring failure as causal context
where practical. The invalid candidate must never be accepted because audit
persistence failed.

## 6. Security and provenance properties

- no credential value or reversible encoding is persisted;
- a suppressed provider response retains exact in-memory SHA-256 and byte length;
- ordinary output is not sanitized, paraphrased, or rewritten;
- request bodies remain hash-only under DEF-0011;
- rejected evidence remains `canonical_state=false`;
- immutable corpus/raw evidence is outside this change;
- no LLM decision becomes canonical legal state.

## 7. Reprocessing / migration / production state

**Database migration: N/A.** No schema/database change is required.

**Corpus reprocessing: N/A.** This affects future rejected CASE attempts only.

**Historical evidence rewrite: N/A / prohibited.** Existing #90/#67 evidence is
not rewritten.

**Production mutation: N/A.** Validation uses fixtures/fault injection; no
production runtime is required.

## 8. Regression tests

Automated coverage must prove at minimum:

1. ordinary rejected provider response remains byte-for-byte preserved;
2. configured API key present only in the outbound request is not persisted;
3. configured API key echoed in provider response suppresses raw response bytes;
4. contaminated assistant content/candidate artifacts are also suppressed;
5. suppressed response records exact in-memory SHA-256 and byte length;
6. suppression manifest contains no credential value;
7. absent configured secret does not suppress arbitrary legal/client text;
8. failure after the first staged artifact but before manifest publishes no
   final `ATT-*` directory;
9. failure after manifest staging but before rename publishes no final attempt;
10. successful publication exposes one complete final attempt at rename;
11. an existing final attempt ID cannot be overwritten;
12. concurrent writers cannot publish the same final attempt ID;
13. a later attempt leaves a prior published failed attempt unchanged;
14. evidence-persistence failure remains fail-closed and does not accept the
    rejected draft;
15. #90 / DEF-0011 and #76 structured-output/no-repair regressions remain green.

Fault injection/mocking is sufficient; a production host is not required.

## 9. Dependencies / ordering

- DEF-0011 / issue #90 owns the original rejected-output evidence model and is a
  required established dependency.
- Issue #76 remains authoritative for provider-neutral structured generation and
  no-repair validation semantics.
- Issue #11 continues to own broader execution provenance and is out of scope.
- Issue #91 may continue using the rejected-attempt path for source-quote
  diagnosis; this defect does not change source-quote semantics.
- Issue #95 final admission remains downstream and must not pass until this
  defect is merged and verified.

## 10. Acceptance criteria

DEF-0014 is verified only when:

- credential secrecy versus exact response retention has the explicit precedence
  defined in this specification;
- contaminated provider response bytes are never persisted;
- non-contaminated provider response bytes remain exact;
- suppressed response existence is proven by exact SHA-256 and byte length;
- contaminated derivative artifacts are suppressed independently;
- no configured credential value occurs in the persisted manifest/evidence;
- final `ATT-*` publication is same-filesystem crash-atomic after durable
  staging;
- partial/stale staging is distinguishable from published evidence;
- final attempt IDs remain create-once and immutable under concurrency;
- evidence persistence failure surfaces deterministically and remains fail-closed;
- the required secret-echo, fault-injection, concurrency, retry and ordinary
  exact-preservation regressions pass;
- relevant #90 and #76 regression suites remain green;
- no database/corpus migration or reprocessing occurs;
- no historical raw/runtime evidence is rewritten;
- every repository content change remains under `col-taxdata/`.

## 11. Non-goals

This defect does not:

- relax CaseDraft validation;
- change source_quote semantics;
- tune model prompts or generation parameters;
- add heuristic secret scanning or generic DLP;
- encrypt the entire CASE evidence store;
- redesign issue #11 execution provenance;
- rerun #67 or CASE-0003;
- rewrite prior DEF-0011 evidence.
