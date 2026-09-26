# Controlled CASE failure disposition and rerun protocol

This is the durable policy for controlled CASE validations such as issues #17 and #67. It governs failed, aborted, diagnostic, amended, and post-fix attempts. It does not make retries easier to pass: historical attempts remain evidence and a later success never rewrites their meaning.

This policy is narrower than issue #11 execution provenance. A future #11 run manifest should carry or reference these attempt fields rather than creating a second competing execution identity. Rejected provider payload preservation belongs to #90/DEF-0011; source-quote behavior belongs to #91/DEF-0012; the current #67 runtime profile belongs to #92/DEF-0013. The no-repair structured-generation boundary from #76 remains mandatory.

## 1. Admission, attempt identity and lifecycle

A validation may define a separate environment/admission gate, as #95 does for #94. If that gate fails **before a controlled attempt is allocated or started**, no canonical attempt is consumed: preserve the admission evidence, fix the gate, and rerun admission without fabricating an execution attempt.

When a validation defines a separate admission manifest, the eventual controlled attempt MUST reference that admission evidence. Once an attempt ID has been allocated and execution has started, any later pre-provider failure belongs to that attempt and is preserved with `provider_contact_state=not_attempted`.

Every explicitly started controlled execution has one unique controlled-validation attempt ID and immutable artifact root. Canonical and diagnostic attempts are different designations and MUST NOT share identity or artifact roots. A retry, amended execution, post-fix rerun, or later diagnostic always creates a new attempt ID.

Allowed statuses are `running`, `failed`, `accepted`, and `aborted`. `accepted` means a structurally accepted CaseResult exists; it does **not** mean the legal result is correct. Therefore class G (`legal_semantic_quality`) may coexist with `status=accepted`. `aborted` is distinct from `failed`, uses class H (`human_abort`), and requires an explicit reason.

Every attempt also records provider-contact state:

- `not_attempted` — provider dispatch was never attempted;
- `dispatch_attempted` — the client attempted provider dispatch but no complete response was obtained;
- `response_received` — provider response bytes/envelope reached the application boundary;
- `unknown` — historical/aborted evidence cannot prove contact state.

`dispatch_attempted` does not claim that the provider actually processed the request.

The manifest records the highest accepted upstream stage as `none`, `case_draft`, or `case_result`. This is mandatory for class F so a valid accepted upstream stage is frozen rather than regenerated merely because a downstream step failed.

## 2. Failure taxonomy and disposition

| Class | Meaning | Same-envelope retry | Contract amendment | Model/backend substitution | Semantic repair |
| --- | --- | --- | --- | --- | --- |
| A — admission/preflight | dependency, frozen hash, revision/image/model/profile gate fails before canonical request consumption | after gate is fixed; this is a new attempt if execution had started | only if the contract truly changes | only when explicitly authorized | never |
| B — transient operational | demonstrable connection/provider crash/transient HTTP failure or timeout while an otherwise adequate backend is actively generating | allowed only as a bounded retry with comparable semantics | not required | no | never |
| C — runtime-envelope incompatibility | repeated timeout, output ceiling, or context envelope is demonstrably inadequate | no blind retry | explicit controller/operator amendment required | no | never |
| D — structured-generation compatibility | constrained generation unsupported, malformed envelope/output, prose/fenced/malformed structured output | only if a separate operational cause is proven; otherwise no | explicit design change if needed | separate declared run only | never |
| E — application-contract | `INVALID_CASE_DRAFT`, immutable payload change, invalid `source_quote`, graph/reference violation | no invisible retry | only an explicit authoritative contract change | no | never |
| F — downstream system | valid CaseDraft but retrieval, persistence/materialization, CaseResult, provenance or doctor fails | normally no intake regeneration | only if contract changes | no | never |
| G — legal/semantic quality | structurally valid result is unsupported, incomplete, legally incorrect, or exposes a corpus gap | no retry to improve score | no amendment to improve score | separate diagnostic only | never |
| H — human/operator abort | operator/controller explicitly stops an attempt | no automatic retry | required if purpose/contract changes | no | never |

Retry eligibility is determined from the declared class, not from the possibility that another model request might happen to succeed. Operational retries MUST be bounded by the controlling validation contract. Repeated operational failures that prove the envelope inadequate transition to class C rather than authorizing endless class-B retries.

## 3. Required evidence per attempt

The attempt manifest records, where applicable:

- parent validation issue, controlled attempt ID, immutable artifact root, status/failure or quality classification, canonical/diagnostic designation;
- start/end timestamps;
- Git/main SHA and application image identity/digest;
- admission-manifest reference when the validation defines an external admission gate;
- execution profile ID and SHA-256;
- exact request SHA-256 and CaseInput SHA-256;
- DB/corpus baseline SHA-256 and raw-evidence/provenance manifest SHA-256;
- provider/backend/model/artifact/build identity and exact generation parameters;
- provider-contact state and highest accepted upstream stage;
- provider raw-response/rejected-evidence reference when applicable;
- HTTP status/error, finish reason, token usage, timing;
- resulting CASE ID for an accepted CaseResult;
- persistence/materialization and validator/provenance/doctor state;
- `previous_attempt`, rerun kind, amendment/baseline reason and reference, child defect/spec/PR/merge reference;
- whether semantic payload was inspected before independent control.

Unavailable evidence is recorded explicitly as unavailable/unknown; it is never guessed. Secrets and authorization material are never stored.

The attempt manifest is execution evidence, not canonical legal evidence. It does not redefine CaseDraft, CaseResult, corpus identity, or issue #11's broader processing-run architecture.

### #90 rejected-output evidence boundary

The controlled-validation attempt ID and a #90 rejected-structuring evidence attempt ID are different namespaces. When #90 captures a provider failure, the #93 attempt manifest references the immutable #90 manifest/artifact; it MUST NOT assume the nested #90 `attempt_id` equals the controlled-validation `attempt_id`.

Under the current architecture, structured-generation and application-contract failures after provider response require a #90 evidence reference. Historical pre-#90 attempts remain valid historical evidence but must record that the nested forensic evidence was unavailable at the time.

The #90 artifact remains non-canonical forensic execution evidence. Referencing it never promotes rejected output to CaseDraft, CaseResult, or legal evidence.

## 4. Failure-specific rules

### Admission/preflight

No canonical request is consumed when the gate fails before execution. Preserve the failed admission evidence, correct the gate, and start only after admission passes. If an execution had already started, it has its own attempt identity and cannot be erased as “preflight”.

### Operational failure

Preserve the attempt. A bounded same-envelope retry is permitted only when the failure is demonstrably operational and request/input/profile/baseline/model semantics remain comparable. A retry does not reuse the previous attempt ID or artifact root.

### Runtime-envelope incompatibility

Do not silently increase timeout/context/output limits. Preserve all failed attempts. The controller/operator must approve an explicit amendment with rationale, update the durable machine-readable profile, and create a new canonical attempt under the new profile identity/SHA. The amended run is not represented as having used the original contract.

### Structured-generation compatibility

Preserve raw provider evidence when available and fail closed. No Markdown stripping, JSON substring extraction, malformed-JSON repair, field coercion, semantic insertion/deletion, or lucky-answer retry is permitted. Systemic incompatibility belongs in its own provider/compatibility issue.

### Application-contract failure

Preserve the exact rejected candidate/provider evidence through the #90 mechanism when available. This is a semantic/application failure, not a transport failure. There is no invisible retry. Associate a focused defect; the parent validation remains blocked until the defect is resolved or an authoritative contract change is approved.

### Downstream system failure

Freeze the accepted upstream stage and the downstream failure evidence. Identify the owning subsystem. Do not regenerate intake merely to obtain a different upstream answer unless the corrected contract explicitly requires it.

### Legal/semantic quality failure

Freeze and score/evaluate the original result. Do not rerun the model to improve the score. Independent Phase B/control may continue when the validation methodology allows it. Diagnose the cause and create focused follow-up work.

### Human/operator abort

Preserve start metadata and partial runtime evidence, record whether the request reached the provider, and record the reason. Status remains `aborted`. A later run is a new attempt.

## 5. Retry, amendment and post-fix rerun gates

### Bounded same-envelope operational retry

A class-B retry is allowed only when the previous attempt is preserved, the previous status is `failed` with class B, the new attempt has a new ID/artifact root and predecessor link, the retry remains within the controlling validation's explicit bound, and no contract amendment is attached.

For a same-envelope operational retry, Git revision, image identity, request/CaseInput, baseline/raw fingerprint, profile identity/SHA, provider identity, and generation parameters must remain comparable. If those semantics change, it is not a same-envelope operational retry.

Class-A failure in a separate admission gate does not consume a controlled attempt. If an attempt had already started but provider dispatch was not attempted, preserve that failed attempt and allocate a new one after correcting the gate.

### Contract amendment

An `amended_contract` rerun requires all of the following:

- previous attempt and preserved prior evidence;
- explicit controller/operator rationale and durable reference;
- new attempt ID and artifact root;
- new durable execution-profile identity and profile SHA;
- explicit amended-contract lineage.

Do not silently change timeout, output ceiling, context, model, backend, or other execution semantics and call the new execution the old frozen attempt.

### New baseline

A `new_baseline` rerun requires a previous attempt, preserved prior evidence, explicit baseline-change rationale/reference, and a baseline SHA different from the predecessor. It must be declared as a new baseline/version rather than represented as same-baseline evidence.

### Same-validation post-fix rerun

When the same validation will resume after a defect fix:

1. preserve every pre-fix attempt and artifact root;
2. link the child defect/spec/PR/merged commit;
3. verify the fix independently with regression tests;
4. verify frozen request/CaseInput identity;
5. decide whether baseline remains comparable or must be versioned;
6. verify model/runtime/profile identity and SHA;
7. allocate a new attempt ID/artifact root;
8. declare exactly one rerun kind: `same_contract_post_fix`, `amended_contract`, or `new_baseline`;
9. record predecessor and applicable amendment/baseline lineage;
10. compare pre-fix and post-fix behavior directly;
11. only after the new canonical attempt is valid/frozen may the parent advance.

For `same_contract_post_fix`, request, CaseInput, baseline/raw fingerprint, execution profile, provider identity, and generation parameters cannot drift. Code/image may intentionally change because the defect was fixed; their changed identities must still be recorded.

## 6. Independent-control / blindness rule

Before Phase B/control is frozen, runtime and structural metadata may be inspected, but semantic Phase A content stays hidden from the independent Phase B context.

A rejected provider payload may be inspected when necessary to diagnose an application-contract failure that blocks Phase A. If that happens, record that Phase A failed before independent control. Re-establish the isolation boundary only after a valid new Phase A is frozen.

Do not claim an independent Phase B comparison against an execution that never produced a valid CaseResult. Do not expose the hidden expected answer/control to Phase A.

## 7. Parent/child issue lifecycle

A systemic defect does **not** have one universal parent-issue disposition. The controller/operator must explicitly choose one of two paths.

### Same-validation resume — parent MUST remain open

Use this path when the methodology still intends to complete the **same validation case** after the blocker is fixed.

Requirements:

- failed/aborted attempts remain preserved;
- child defect(s) own implementation;
- parent remains open/blocked;
- after child completion, the post-fix rerun gate is verified;
- the same case reruns under explicit lineage;
- the parent advances only after the new valid frozen attempt permits it.

### Diagnostic completion — parent MAY close

A validation may close as a **diagnostic blocker completion** instead of resuming the same case only when all are true:

- controller/operator makes an explicit recorded decision;
- every failed/aborted attempt remains preserved;
- the blocker is systemic and belongs to class C, D, E, or F;
- every unresolved blocker has separately owned child issue(s);
- the parent records exact blocker evidence;
- a distinct successor validation issue is explicitly identified;
- the successor validates the repaired system rather than silently inheriting the failed result;
- the closeout outcome is explicitly `diagnostic_blocker`;
- the closeout explicitly states that it is **not** a CaseResult/legal PASS;
- the old failed case is not rerun invisibly after closure.

Diagnostic completion is not an escape hatch. It is not permitted merely for transient operational failure, admission/preflight failure, human abort, or poor legal/semantic quality of an otherwise executable CaseResult.

Issue #67 is the historical example: it may remain a completed diagnostic milestone because failed attempts were preserved, blockers were split into child issues, and #94 is the fresh successor validation. If #94 later uses diagnostic completion, it must satisfy the same gates and identify another distinct successor.

Unknown dependency or runtime state is recorded as unknown rather than guessed. Validation issues do not absorb unrelated production fixes.

### #95 admission-manifest relationship

For #94-style validation, #95 prepares/finalizes environment admission and records `case0003_consumed=false`. That #95 manifest is not a #94 attempt manifest. A #95 failure before #94 allocates an attempt consumes no canonical #94 attempt. The first #94 attempt references the passing #95 admission manifest. After #94 allocates/starts an attempt, a pre-provider failure belongs to that attempt and records `provider_contact_state=not_attempted`.

## 8. Machine-enforced subset

`tools/case_attempt_policy.py` provides deterministic helpers for the policy subset that does not depend on runtime storage:

- failure-class disposition and universal no-semantic-repair behavior;
- status/classification compatibility, including structurally accepted class-G findings;
- provider-contact and accepted-upstream-stage semantics;
- terminal/abort invariants;
- admission-manifest references when required;
- canonical/diagnostic consistency;
- #90 rejected-evidence references for structuring/application failures;
- bounded same-envelope operational retries and retry drift;
- post-fix rerun identity, prior-evidence preservation, and regression gates;
- strict amended-profile and new-baseline requirements;
- parent-resolution validation for same-validation resume versus diagnostic completion.

It intentionally does not persist artifacts, capture provider output, mutate the corpus, implement issue #11, execute a CASE validation, or decide legal correctness.

## 9. Examples from #67

The historical states that motivated this policy remain distinct:

- a timeout at the original frozen limit is a class-B operational attempt;
- a bounded repeat timeout is a second preserved attempt and may establish class-C envelope incompatibility;
- an operator-approved 7200/9000 execution is an amended-contract attempt under a new durable profile identity, not a continuation of 900/6144;
- a completed generation rejected as `INVALID_CASE_DRAFT` is class E, not transport failure;
- a diagnostic request explicitly stopped by the operator is status `aborted`, class H, never retroactively canonical;
- #67 closeout is diagnostic completion, not CaseResult/legal PASS, with child blockers and successor #94.

These examples explain classification; they do not rewrite #67's historical evidence.

## 10. Safety and non-goals

This protocol does not fix `source_quote`, select/tune a model, rerun #67 or #94, perform Phase B, repair structured output, change legal evidence semantics, mutate corpus/database state, rewrite raw evidence, replace #90 forensic capture, or replace issue #11 execution provenance.

Historical failures are evidence. A successful future run supplements them; it never erases them.
