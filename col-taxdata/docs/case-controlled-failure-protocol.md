# Controlled CASE failure disposition and rerun protocol

This is the durable policy for controlled CASE validations such as issues #17 and #67. It governs failed, aborted, diagnostic, amended, and post-fix attempts. It does not make retries easier to pass: historical attempts remain evidence and a later success never rewrites their meaning.

This policy is narrower than issue #11 execution provenance. A future #11 run manifest should carry or reference these attempt fields rather than creating a second competing execution identity. Rejected provider payload preservation belongs to #90/DEF-0011; source-quote behavior belongs to #91/DEF-0012; the current #67 runtime profile belongs to #92/DEF-0013. The no-repair structured-generation boundary from #76 remains mandatory.

## 1. Attempt identity and immutability

Every provider-reaching or explicitly started controlled execution has a unique attempt ID and immutable artifact root. Canonical and diagnostic attempts are different designations and MUST NOT share identity or artifact roots. A retry, amended execution, or post-fix rerun always creates a new attempt ID.

An attempt is one of: `running`, `failed`, `accepted`, or `aborted`. An aborted attempt is never retroactively called completed, failed, or accepted. Historical attempt artifacts MUST NOT be overwritten by a later attempt.

A canonical attempt is the execution used by the controlled validation methodology. A diagnostic attempt may investigate runtime/provider behavior but cannot silently become the canonical completed execution.

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

- parent validation issue, attempt ID, status/failure class, canonical/diagnostic designation;
- start/end timestamps;
- Git/main SHA, image identity/digest;
- execution profile ID and SHA-256;
- exact request SHA-256 and CaseInput SHA-256;
- DB/corpus baseline SHA-256 and raw-evidence manifest SHA-256;
- provider/backend/model/artifact/build identity and generation parameters;
- provider raw-response SHA-256 plus rejected-output artifact reference when available;
- HTTP status/error, finish reason, token usage, timing;
- resulting CASE ID only when accepted;
- persistence/materialization and validator/provenance/doctor state;
- `previous_attempt`, rerun kind, amendment reason/reference, child defect/spec/PR/merge reference;
- whether semantic payload was inspected before independent control.

Unavailable evidence is recorded explicitly as unavailable; it is never guessed. Secrets and authorization material are never stored.

The attempt manifest is execution evidence, not canonical legal evidence. It does not redefine CaseDraft, CaseResult, corpus identity, or issue #11's broader processing-run architecture.

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

## 5. Post-fix rerun gate

A controlled rerun after a defect requires all of the following:

1. preserve every pre-fix attempt and artifact root;
2. link the child defect/spec/PR/merged commit;
3. independently verify the fix with regression tests;
4. verify frozen request/CaseInput has not changed unless the new run is explicitly a new contract/baseline;
5. decide whether the DB/corpus baseline remains comparable; if not, version it and classify the rerun as a new baseline;
6. verify model/runtime/profile identity and profile SHA;
7. allocate a new attempt ID and artifact root;
8. declare exactly one rerun kind: `same_contract_post_fix`, `amended_contract`, or `new_baseline`;
9. record `previous_attempt` and amendment lineage where applicable;
10. compare pre-fix and post-fix behavior directly;
11. only after the new canonical attempt is valid/frozen may the parent advance.

For `same_contract_post_fix`, request, CaseInput, baseline/raw-evidence manifest, execution profile, provider identity, and generation parameters must remain comparable. Drift blocks that classification. An amended contract must identify the predecessor and amendment. A new baseline must not be described as same-contract evidence.

## 6. Independent-control / blindness rule

Before Phase B/control is frozen, runtime and structural metadata may be inspected, but semantic Phase A content stays hidden from the independent Phase B context.

A rejected provider payload may be inspected when necessary to diagnose an application-contract failure that blocks Phase A. If that happens, record that Phase A failed before independent control. Re-establish the isolation boundary only after a valid new Phase A is frozen.

Do not claim an independent Phase B comparison against an execution that never produced a valid CaseResult. Do not expose the hidden expected answer/control to Phase A.

## 7. Parent/child issue lifecycle

A systemic defect discovered by validation belongs in a separate child issue. The parent validation remains open and records the blocker and exact attempt evidence. The child owns implementation. After the child merges, the controller verifies the post-fix rerun gate before resuming the parent.

Unknown dependency or runtime state is recorded as unknown rather than guessed. Validation issues do not absorb unrelated production fixes.

For #67 specifically, another canonical run remains gated on the live requirements recorded by #67/#90/#91/#92 and this merged protocol. This document does not itself declare those sibling issues complete.

## 8. Machine-enforced subset

`tools/case_attempt_policy.py` provides deterministic helpers for the policy subset that does not depend on runtime storage:

- failure-class disposition and retry eligibility;
- universal no-semantic-repair invariant;
- manifest lifecycle checks;
- canonical/diagnostic separation;
- abort invariants;
- amendment/predecessor requirements;
- comparability drift detection;
- post-fix rerun identity/artifact-root and regression/defect gates.

It intentionally does not persist artifacts, capture rejected provider output, mutate the corpus, implement issue #11, or execute #67.

## 9. Examples from #67

The historical states that motivated this policy remain distinct:

- a timeout at the original frozen limit is an operational failure attempt;
- a bounded repeat timeout remains a separate preserved attempt and may establish class-C envelope incompatibility;
- an operator-approved 7200/9000 execution is an amended-contract attempt under a new durable profile identity, not a continuation of the 900/6144 attempt;
- a completed generation rejected as `INVALID_CASE_DRAFT` is an application-contract failure, not a timeout;
- a diagnostic request explicitly stopped by the operator is `aborted`, not passed/failed and not retroactively canonical.

These examples explain classification; they do not rewrite #67's historical issue evidence.

## 10. Safety and non-goals

This protocol does not fix `source_quote`, select/tune a model, rerun #67, perform Phase B, repair structured output, change legal evidence semantics, mutate corpus/database state, rewrite raw evidence, or replace issue #11 execution provenance.

Historical failures are evidence. A successful future run supplements them; it never erases them.
