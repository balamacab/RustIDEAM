# DEF-0012 — user-provided source_quote fidelity

Status: verified  
Priority: P1  
GitHub: #91  
Area: CASE structuring / application validation

## Problem

The historical #67 controlled CASE run completed model generation and was rejected
by the authoritative validator at:

`$.facts[14].source_quote: user_provided quote is not present verbatim in CaseInput.problem_text`.

That rejection was correct. At that time the rejected provider payload was not
preserved, so the exact bad quote cannot be reconstructed without inventing
evidence. DEF-0011 (#90) and DEF-0014 (#113) subsequently added rejected-output
capture and credential-safe crash-atomic publication.

The systemic defect is upstream of the literal validator: the model-facing schema
required `source_quote` to be a non-empty string but did not constrain the model
to source-owned bytes. A schema-constrained backend could therefore return a
syntactically valid string that paraphrased, normalized, concatenated, shortened,
expanded, or otherwise altered the client text. Temperature zero does not turn
free-string generation into an exact-copy guarantee.

## Diagnostic evidence

Historical immutable input identities remain:

- raw HTTP request SHA-256:
  `b0b36bf6ab5c5d46572aee434933b4a87f830c953ef26ee17c78734c82a9b763`;
- canonical CaseInput SHA-256:
  `9a88c7d1f818e22ef310ef52a4185d2795d3e51ddd374d22b25e713b522171d4`;
- problem_text SHA-256:
  `ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1`.

A #91-owned diagnostic reproduction used those exact input fingerprints, Gemma E2B
on the llama.cpp reference backend, and the amended #67 envelope
(context 16384, max output 9000, timeout 7200, temperature 0, thinking false,
top_p 1, top_k 0, stream false, n 1). The run completed with provider HTTP 200 and
an application-valid CaseDraft:

- provider response SHA-256:
  `2c74d4245bd72c9974b62084a21c5f7f3f0514cd83d942c9201c0ea0e02c2125`;
- assistant content SHA-256:
  `cd16f07113a1d2f6811ba50486aed448a9015b1feba1446131eb8272a15d5f26`;
- parsed candidate SHA-256:
  `a67de3c777b1fae5ff4e4c7ff4c5b28781c0a2b0f6d5b2b2c753523d81cc2be5`.

Therefore the exact historical #67 malformed quote remains unavailable. The
regression suite MUST preserve the historical failure path and frozen input identity
while using synthetic minimal examples for mismatch classes that were not captured
byte-for-byte. It MUST NOT fabricate a historical quote.

## Classification

The defect is classified as a **prompt/schema expressiveness limitation and exact-copy
reliability defect**.

It is not a validator-normalization defect. The authoritative v3 rule remains:

`user_provided.source_quote in CaseInput.problem_text`

using exact Python string/code-point substring semantics. No Unicode, whitespace,
punctuation, lexical, or semantic normalization is permitted to turn a non-literal
quote into a literal one.

## Required design

### Exact generated quote candidates

For constrained model generation, derive a deterministic list of exact contiguous
paragraph spans from the exact validated `CaseInput.problem_text`.

Paragraph boundaries are blank-line separators. Candidate text:

- is copied exactly from the client string;
- preserves code points and internal newlines;
- is always one contiguous substring;
- is never normalized;
- is deduplicated by exact string value while preserving first-seen order.

The model-facing `user_provided.source_quote` field MUST be an enum of those exact
candidate strings. Non-`user_provided` model-facing fact variants MUST NOT expose
`source_quote`.

This prevents a conforming constrained backend from generating a paraphrased,
Unicode-normalized, whitespace-modified, punctuation-modified, or non-contiguously
merged literal quote.

### Client-owned root materialization

The model has no authority over `problem_text`, `as_of_date`, or
`client_reference`. To keep the source-quote enum within the existing runtime
context envelope, those client-owned root fields are omitted from the model-facing
generation schema.

After structured JSON parsing, the adapter MAY copy an omitted client-owned field
from the exact already-validated CaseInput into the candidate. It MUST:

- copy the exact parsed value;
- copy only a field present in CaseInput;
- never overwrite a value emitted by a backend;
- never rewrite model-authored facts, values, states, questions, claims, unresolved
  items, or source_quote;
- preserve the exact provider candidate separately in generation/rejection evidence;
- still run the complete authoritative `validate_case_draft()` afterwards.

This is deterministic client-payload materialization, not post-response semantic or
JSON repair.

### Versioning and compatibility

The public serialized CASE contract remains `3.0.0`. Existing valid CaseDraft v3
consumers remain compatible:

- final CaseDraft still contains exact `problem_text` and optional client fields;
- final `user_provided.source_quote` remains a string;
- existing exact literal substrings remain valid under authoritative validation,
  including shorter substrings that need not equal one generated paragraph;
- no persisted CASE schema changes.

The model-facing generation contract changes and therefore the prompt template
version MUST advance from v4 to v5.

A new public span/reference field was considered but is not required for this fix.
CaseDraft v3 stores quote text rather than occurrence identity, so identical duplicate
paragraphs intentionally collapse to the same generated quote string. A future
contract may add positional evidence identity if occurrence-level provenance becomes
a requirement.

## Rejection semantics

The following remain invalid and MUST fail closed when supplied to the authoritative
v3 validator unless the changed text still happens to be an exact contiguous
substring:

- lexical or semantic paraphrase;
- deleted/added negation that changes the literal text;
- changed number, date, or entity;
- non-contiguous fragments concatenated into one quote;
- Unicode normalization that changes code points;
- whitespace changes;
- punctuation changes that produce a non-substring;
- empty source_quote.

Removing terminal punctuation is not itself invalid when the resulting text remains
an exact literal substring. Literal-substring semantics, not sentence equality, is
authoritative.

## Provenance and evidence

No raw corpus evidence, canonical legal identity, canonical evidence, database schema,
or persisted CASE record is changed by this defect.

Rejected provider output remains governed by DEF-0011 and DEF-0014. The exact parsed
provider candidate MUST remain the candidate artifact; deterministic client-owned
field materialization does not replace or rewrite that evidence.

## Migration / reprocessing

N/A.

No DB migration, corpus reprocessing, canonical rebind, raw-evidence rewrite, or
production mutation is required.

## Required regression coverage

Tests MUST cover:

1. exact literal user-provided quote accepted;
2. lexical and semantic paraphrase rejected;
3. deleted negation rejected when no longer literal;
4. changed number/date/entity rejected;
5. merged non-contiguous text rejected;
6. punctuation, whitespace, and Unicode behavior explicitly defined;
7. duplicate source paragraphs produce deterministic text-only candidates;
8. empty quote rejected;
9. model-facing normalized/inferred variants cannot emit literal source_quote;
10. historical #67 frozen input/failure metadata retained without inventing the lost quote;
11. existing shorter exact v3 source_quote remains accepted;
12. generated schema omits model authority over client-owned root fields;
13. adapter copies only missing client-owned fields and never overwrites drift;
14. final authoritative CaseDraft validation remains mandatory;
15. #76 no-repair compatibility behavior remains protected;
16. #90/#113 rejected-output evidence behavior remains protected.

## Acceptance criteria

- [ ] A #91-owned diagnostic run is preserved with the historical frozen input fingerprints.
- [ ] The historical failure is not silently reconstructed or guessed.
- [ ] Root cause/classification is recorded.
- [ ] Literal substring validation remains strict and fail-closed.
- [ ] Model-facing user-provided source_quote is constrained to exact contiguous client spans.
- [ ] No normalization/fuzzy/semantic quote comparator is introduced.
- [ ] Client-owned root materialization is exact, non-overwriting, deterministic, and documented as distinct from semantic repair.
- [ ] Public CaseDraft v3 compatibility is preserved.
- [ ] Prompt/generation contract is versioned.
- [ ] Mandatory regression and preservation tests pass.
- [ ] DEF-0011 / DEF-0014 rejected-evidence guarantees remain green.
- [ ] No DB migration, corpus reprocessing, canonical mutation, or raw-evidence rewrite occurs.
- [ ] Current-main/branch reconciliation and repository CI pass before merge.
