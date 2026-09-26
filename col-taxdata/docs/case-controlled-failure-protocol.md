# Controlled CASE failure disposition and rerun protocol

Status: **Active validation/process contract**

Driver: GitHub issue #93.

This document governs controlled CASE validations such as issues #17 and #67. It defines what must happen when an execution does not produce the expected controlled result, when a retry is allowed, when the validation must block, and how a later rerun is related to preserved failed evidence.

This protocol is intentionally conservative. Its purpose is not eventual success. A failed, rejected, poor-quality, or aborted execution remains part of the validation record even when a later execution succeeds.

## 1. Scope and authority boundaries

This protocol applies to controlled CASE execution attempts and their validation lifecycle.

It does **not** replace:

- issue #11's broader code/config/runtime processing-run provenance architecture;
- the active CASE application contract under `specs/application/`;
- issue #76's provider-neutral structured-generation and no-post-response-repair contract;
- issue-specific frozen input, baseline, backend, model, or runtime requirements;
- immutable corpus/source evidence rules.

The attempt manifest defined below is a **controlled-validation overlay**. It records the fields #93 needs to decide retry/rerun comparability and points to detailed execution artifacts. A future #11 implementation may embed or reference this overlay, but must preserve its semantics rather than silently reinterpret historical attempts.

The selected validation issue remains authoritative for its frozen input and approved execution envelope. If that contract changes, the change must be explicit and versioned.

## 2. Core rules

1. Every provider-reaching or allocated controlled execution gets a unique attempt identity and a unique artifact root.
2. Terminal attempt evidence is immutable. A retry/rerun creates a successor attempt; it never overwrites, relabels, deletes, or "completes" the predecessor.
3. Failure classification is based on where and why execution failed, not on whether another model request might later succeed.
4. Only demonstrably operational failures are candidates for bounded same-envelope retry.
5. Runtime-envelope changes are contract amendments, not invisible retries.
6. Structured/application failures fail closed. No Markdown stripping, JSON substring extraction, heuristic repair, semantic field repair, fuzzy acceptance, or retry-until-pass is authorized.
7. A structurally valid but legally poor result is frozen and evaluated; it is not regenerated to improve a score.
8. A human-aborted attempt remains `aborted`, never retroactively converted to pass/fail/completed.
9. Phase B/control blindness is preserved. A Phase A that did not produce a valid accepted CaseResult cannot be represented as having reached independent comparison.
10. Unknown/unavailable evidence is recorded explicitly as unknown/unavailable; it is never guessed.

## 3. Failure taxonomy and disposition

### A — pre-execution/admission failure

Examples:

- dependency not satisfied;
- frozen input/baseline fingerprint mismatch;
- wrong code/image/model/profile;
- capability/profile verification failure.

Disposition:

- do not send/consume the canonical provider request;
- preserve admission evidence;
- fix the admission state;
- retry only after the gate is demonstrably satisfied;
- if the contract itself changes, record an explicit amendment instead of calling the next run the same frozen attempt.

### B — transport/provider operational failure

Examples:

- connection failure;
- provider process crash;
- transient HTTP failure;
- timeout while the backend is still actively generating.

Disposition:

- preserve the failed attempt;
- same-envelope retry is allowed only when the cause is operational and the retry count remains within an externally declared bound;
- preserve the input, code/image, profile, baseline, provider/model/build identity, and generation semantics that define comparability;
- every retry gets a new attempt ID and artifact root.

A repeated operational timeout may demonstrate class C rather than justify unlimited class-B retries.

### C — runtime-envelope incompatibility

Examples:

- repeated timeout showing that the frozen timeout cannot permit natural completion;
- output ceiling reached before natural completion;
- context budget incompatible with the required request.

Disposition:

- no blind same-envelope retry;
- preserve all failed attempts;
- require explicit controller/operator amendment with rationale/reference;
- update the durable machine-readable execution profile before the next canonical execution;
- the amended execution is a new canonical attempt under a new profile identity and SHA.

Historical attempts retain the profile/envelope that actually governed them.

### D — structured-generation compatibility failure

Examples:

- backend cannot honor the constrained-generation requirement;
- malformed provider envelope;
- non-parseable model output;
- prose/fenced output where a direct structured object is required.

Disposition:

- preserve raw provider evidence when available;
- fail closed under issue #76;
- no post-response repair;
- if systemic, create/associate the provider/compatibility defect;
- same-envelope retry is allowed only when a separate operational cause is demonstrated;
- backend/model substitution is a separate declared diagnostic/run, never an invisible retry.

### E — application-contract failure

Examples:

- `INVALID_CASE_DRAFT`;
- immutable client payload modified;
- invalid `source_quote`;
- typed graph/reference integrity violation.

Disposition:

- preserve the exact rejected provider/candidate evidence through the applicable forensic artifact mechanism;
- classify as semantic/application failure, not transport failure;
- no invisible retry and no retry merely to obtain a lucky conforming answer;
- create/associate a defect or explicit authoritative contract change;
- parent validation remains blocked on disposition/fix;
- rerun only after the defect is resolved or the authoritative contract is explicitly amended.

### F — valid CaseDraft / invalid downstream system state

Examples:

- retrieval integrity failure;
- persistence/materialization failure;
- invalid CaseResult;
- provenance/doctor failure.

Disposition:

- preserve the accepted upstream stage and downstream failure evidence;
- identify the owning subsystem;
- do not regenerate intake merely to bypass the downstream defect;
- rerun intake only if the corrected contract actually requires it.

### G — valid structural result / poor or incorrect legal result

Examples:

- unsupported claim remains;
- relevant authority is missed;
- a material legal conclusion is incorrect;
- corpus coverage gap.

Disposition:

- the attempt is structurally **completed with findings**, not execution-failed;
- freeze and score/evaluate the original result;
- do not rerun the model to improve the score;
- independent Phase B/control may continue when the validation methodology allows;
- diagnose root cause and open follow-up issues separately.

### H — human/operator-aborted attempt

Disposition:

- preserve start metadata and all available partial runtime evidence;
- record status `aborted`, reason, and whether the request reached the provider;
- never relabel the same attempt as completed/failed/pass;
- resuming execution uses a new attempt ID;
- if purpose or contract changes, record that change explicitly.

## 4. Deterministic retry matrix

| Failure class | Same-envelope retry | Contract amendment | Model/backend substitution | Semantic repair |
| --- | --- | --- | --- | --- |
| A admission | after gate is fixed | only when contract changes | only if explicitly authorized | never |
| B operational | allowed, bounded | not required | no | never |
| C envelope incompatibility | no | required before canonical rerun | no | never |
| D structured compatibility | only for proven operational cause | explicit design change if needed | separate declared run only | never |
| E application contract | no | explicit authoritative change only | no | never |
| F downstream system | normally no intake retry | only if contract changes | no | never |
| G legal/semantic quality | no | not to improve score | separate diagnostic only | never |
| H human abort | no same-attempt retry; create a new attempt | if purpose/contract changes | no | never |

The machine-enforced subset is implemented by `tools/case_attempt_policy.py`. A validation profile/controller supplies the numeric operational retry bound; this protocol deliberately does not invent one universal retry count.

## 5. Controlled-attempt evidence overlay

Every allocated attempt records the following overlay. Values that are genuinely unavailable may be `null`/`unknown`, but the field remains present so absence is explicit.

```json
{
  "schema_version": 1,
  "parent_validation_issue": 67,
  "attempt_id": "ATT-...",
  "designation": "canonical | diagnostic",
  "status": "failed | aborted | completed | completed_with_findings",
  "failure_class": "A_... | B_... | ... | H_... | null",
  "artifact_root": "...",
  "timestamps": {
    "started_at": "...",
    "ended_at": "..."
  },
  "code": {
    "git_sha": "...",
    "image_identity": "..."
  },
  "profile": {
    "id": "...",
    "sha256": "..."
  },
  "input": {
    "request_sha256": "...",
    "case_input_sha256": "...",
    "db_baseline_sha256": "...",
    "raw_evidence_manifest_sha256": "..."
  },
  "provider": {
    "provider": "...",
    "backend": "...",
    "model": "...",
    "model_artifact_identity": "...",
    "backend_build_identity": "...",
    "generation_parameters": {},
    "request_reached_provider": true,
    "raw_response_sha256": null,
    "rejected_output_artifact": null,
    "http_status": null,
    "error": null,
    "finish_reason": null,
    "usage": null,
    "timing": null
  },
  "outcome": {
    "case_id": null,
    "case_result_state": "not_produced | accepted | rejected",
    "persistence_state": "...",
    "materialization_state": "...",
    "validator_state": "...",
    "provenance_state": "...",
    "doctor_state": "..."
  },
  "lineage": {
    "kind": "initial | same_envelope_retry | same_contract_post_fix | amended_contract_rerun | new_baseline_rerun | diagnostic",
    "previous_attempt": null,
    "previous_artifact_root": null,
    "previous_evidence_preserved": false,
    "reason": null,
    "amendment_reference": null,
    "fix_reference": null,
    "baseline_reference": null,
    "retry_number": null
  },
  "control": {
    "semantic_payload_inspected_before_independent_control": false,
    "semantic_repair_applied": false
  }
}
```

This overlay covers the minimum #93 decision evidence:

- parent validation and attempt identity;
- canonical/diagnostic designation;
- start/end time;
- Git/image identity;
- execution-profile identity and SHA;
- exact request and CaseInput SHA;
- database/corpus baseline and raw-evidence-manifest SHA;
- provider/backend/model/artifact/build identity and generation parameters;
- provider response/rejected-output references where available;
- HTTP/error/finish/usage/timing metadata;
- resulting CASE ID and persistence/materialization state;
- validator/provenance/doctor state;
- predecessor/retry/amendment lineage;
- whether semantic Phase A payload was inspected before independent control.

Detailed raw provider payloads remain runtime execution evidence and must not be placed in GitHub comments or normal client errors. The overlay references their artifact and hashes when available.

## 6. Artifact immutability and identity

For every successor attempt:

- `attempt_id` must differ from its predecessor;
- `artifact_root` must differ from its predecessor;
- predecessor attempt ID and artifact root are linked explicitly;
- predecessor evidence must remain preserved and accessible;
- the successor may not replace files under the predecessor artifact root.

A successful later run does not erase an earlier timeout, rejection, abort, or poor legal result.

The attempt ID is execution identity. It is not a CASE/domain identifier and does not redefine deterministic `CASE-*` identity.

## 7. Same-envelope operational retry

A same-envelope retry is valid only when:

1. the predecessor class permits it;
2. any required admission gate is fixed or operational cause is demonstrated;
3. the declared retry number is within the caller/profile retry bound;
4. predecessor evidence is preserved;
5. attempt ID/artifact root are new;
6. no comparability drift exists in:
   - Git SHA;
   - image identity;
   - profile ID/SHA;
   - request SHA;
   - CaseInput SHA;
   - DB baseline SHA;
   - raw-evidence manifest SHA;
   - provider/backend/model/artifact/build identity;
   - generation parameters.

If any of those values must change, the controller must choose the appropriate declared rerun type rather than labeling the action a same-envelope retry.

## 8. Post-fix rerun protocol

When a controlled validation exposes a defect and the defect is fixed:

1. preserve every pre-fix attempt;
2. link the child defect/spec/PR/merge SHA in `fix_reference`;
3. verify the fix independently with regression tests;
4. verify frozen request and CaseInput have not changed;
5. decide explicitly whether the DB/corpus baseline remains comparable;
6. verify model/runtime/profile identity;
7. allocate a new attempt ID and artifact root;
8. declare exactly one rerun kind;
9. execute without overwriting historical artifacts;
10. compare pre-fix and post-fix behavior directly;
11. when the controller selects `resume_same_validation`, continue the same parent to its next phase only after the rerun gate passes; when it selects diagnostic milestone completion, the original parent does not resume.

### Same-contract post-fix rerun

Use when the defect fix changes implementation but not the controlled contract.

Required stable values include:

- request and CaseInput SHA;
- DB baseline and raw-evidence-manifest SHA;
- profile ID/SHA;
- provider/backend/model/artifact/build identity;
- generation parameters.

Git/image/build identity may legitimately change because the defect fix changed executable code. The fix reference explains that change.

### Amended-contract rerun

Use when the meaning or runtime envelope of the controlled execution changed.

Requirements:

- predecessor and failed evidence preserved;
- explicit amendment reason/reference;
- frozen request/CaseInput and baseline remain stable unless separately versioned;
- provider/model identity remains stable unless a separate run is explicitly authorized;
- new durable execution-profile **ID and SHA**;
- generation/profile differences are represented as the amendment, not hidden drift.

The rerun must never be described as having used the original profile.

### New baseline/version

Use when corpus/database baseline comparability intentionally changes.

Requirements:

- explicit baseline reason/reference;
- changed DB baseline SHA;
- same frozen request/CaseInput unless the validation itself is versioned;
- stable profile/provider/model/generation semantics unless separately amended;
- comparison report distinguishes baseline change from implementation defect correction.

## 9. Independent control / blindness

For #17/#67-style methodology:

- structural/runtime metadata may be inspected before Phase B;
- semantic Phase A content remains hidden from the independent Phase B context;
- a rejected payload may be inspected only when necessary to diagnose a blocking application-contract failure;
- if that happens, record that Phase A failed before independent control;
- after the defect is fixed, freeze a new valid Phase A and re-establish the isolation boundary;
- do not claim a Phase B comparison against an attempt that never produced an accepted, validator-passing CaseResult.

`tools/case_attempt_policy.py::independent_control_ready()` enforces the machine-checkable subset of this gate.

## 10. Validation-level disposition and parent/child issue state

Attempt lifecycle and validation lifecycle are separate concepts. In particular,
an attempt with `designation=diagnostic` does **not** authorize closing its
parent validation. Parent closure requires an explicit validation-level
controller/operator disposition.

After a systemic validation failure, the controller chooses exactly one of these
two dispositions.

### A. `resume_same_validation`

Use this when the same frozen validation case/methodology is intended to
continue after the blocker is corrected.

Requirements:

- the parent validation remains open;
- the failed/aborted attempt and its artifact evidence remain preserved;
- systemic C/D/E/F blockers are owned by at least one separate child
  defect/architecture/operations issue;
- no successor validation issue is named;
- future rerun lineage remains owned by the same parent validation issue;
- any post-fix attempt still follows the retry/rerun rules in sections 7–8;
- Phase B is not represented as executed or completed unless a valid Phase A
  exists.

This disposition does not make a failure retryable. Retry eligibility continues
to come from the attempt-level failure taxonomy and declared rerun kind.

### B. `diagnostic_complete_with_successor`

Use this only when the controller/operator explicitly determines that the
validation has fulfilled its diagnostic purpose and the next meaningful
validation should be a distinct successor case/milestone.

Requirements:

- only systemic failure classes C, D, E, or F qualify;
- the blocking attempt/artifact evidence is preserved and referenced;
- the original parent closes with explicit **diagnostic completion** language;
- an explicit controller/operator decision reference is recorded;
- at least one separately owned blocker/fix issue is recorded;
- the distinct successor validation issue is recorded and cannot be the parent
  or one of the blocker/fix issues;
- the reason for not resuming the same validation is recorded;
- `legal_pass=false`; diagnostic completion is never CaseResult/legal PASS;
- the original parent owns no future rerun lineage;
- Phase A and Phase B truthfully record what actually executed/completed;
- if Phase A was not valid, Phase B must be recorded as not executed and not
  completed;
- the blocking attempt itself remains failed/aborted/completed-with-findings as
  originally classified and is never relabeled successful merely because the
  parent issue closes.

Diagnostic milestone completion is deliberately unavailable for:

- class A admission/preflight failures that should be corrected at the gate;
- class B operational failures while bounded operational retry remains the
  correct disposition;
- class G structurally valid legal-quality findings, which must be frozen and
  evaluated rather than escaped through diagnostic closure;
- class H operator aborts. An abort requires a separate explicit controller
  disposition appropriate to the validation; it is not automatically a
  diagnostic milestone completion;
- convenience, issue cleanup, or avoidance of scoring a poor legal result.

### Machine-checkable validation disposition

`tools/case_attempt_policy.py::validate_validation_disposition()` validates a
separate record such as:

```json
{
  "schema_version": 1,
  "disposition": "resume_same_validation | diagnostic_complete_with_successor",
  "parent_validation_issue": 67,
  "parent_issue_open": false,
  "blocking_failure_class": "E_APPLICATION_CONTRACT",
  "blocking_attempt_id": "ATT-...",
  "blocking_artifact_reference": "artifacts/ATT-...",
  "blocking_attempt_status": "failed",
  "blocking_evidence_preserved": true,
  "controller_decision_reference": "issue#67-final-closeout",
  "blocker_issue_references": [90, 91, 92, 93],
  "successor_validation_issue": 94,
  "future_rerun_parent_issue": null,
  "legal_pass": false,
  "phase_a_valid": false,
  "phase_b_executed": false,
  "phase_b_completed": false,
  "reason": "diagnostic purpose fulfilled; fresh successor required"
}
```

The helper may also be given the referenced attempt manifest. When supplied, it
verifies that parent issue, failure class, terminal status, attempt identity and
artifact reference agree with the preserved attempt. This prevents validation
closure metadata from silently relabeling the attempt itself.

`validation_parent_may_close()` returns true only for a fully valid
`diagnostic_complete_with_successor` record. It never infers closure from an
attempt's `designation`.

Unknown dependency state is recorded as unknown rather than inferred.

### Historical #67 -> #94 example

Issue #67 is the concrete historical example of
`diagnostic_complete_with_successor`:

- the amended canonical Phase A completed model generation but failed the
  authoritative CaseDraft contract (class E);
- the failed Phase A evidence remained historical evidence;
- Phase A never produced a valid final CaseResult;
- Phase B was not started;
- #90, #91, #92 and #93 separately owned the discovered blockers/fixes;
- the controller explicitly closed #67 as a **completed diagnostic validation
  milestone**, not a legal/CaseResult PASS;
- #94 / CASE-0003 is a distinct fresh successor validation.

Nothing in this representation retroactively completes #67's unexecuted Phase B
or rewrites #67 history.

## 11. Relationship to current CASE work

- **#11** owns broader execution/provenance manifests. #93 only supplies the controlled-attempt overlay and transition rules.
- **#76** owns provider-neutral structured-generation compatibility and fail-closed/no-repair semantics. #93 cannot authorize a repair path that #76 forbids.
- **#90 / DEF-0011** owns preservation of rejected provider output for future invalid structuring attempts. #93 references that evidence; it does not duplicate the payload store.
- **#91 / DEF-0012** owns the concrete `source_quote` fidelity defect exposed by #67.
- **#92 / DEF-0013** owns the durable amended #67 runtime profile. #93 defines why that change must be represented as an amended-contract successor.
- **#67** remains the parent controlled validation and must not be rerun by implementing #93.

Before another canonical #67 run, the parent controller must verify the current issue-level resume gate, including the required #90/#91/#92 state, this protocol, a new attempt ID, and explicit post-fix/amended lineage.

## 12. What this protocol does not authorize

This protocol does not authorize:

- retry-until-pass;
- post-response semantic or JSON repair;
- model/backend substitution disguised as retry;
- rewriting historical attempt artifacts;
- changing frozen input to make a result pass;
- rerunning intake to hide a downstream defect;
- regenerating a structurally valid legal result to improve score;
- executing CASE-0003 as part of issue #93;
- corpus/database mutation or reprocessing;
- replacement of issue #11's broader execution provenance architecture.
