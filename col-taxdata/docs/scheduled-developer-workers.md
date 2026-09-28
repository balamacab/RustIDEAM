# Scheduled Developer workers

Status: **operational/controller contract**

This document refines the Developer-worker portion of the scheduled stateless case-validation swarm. It governs how five independent Developer workers acquire implementation ownership without duplicating work or creating unsafe parallel changes.

It does not authorize scheduler creation by itself and does not change CASE product semantics, legal-data contracts, corpus provenance, or public APIs.

## 1. Worker identities

Exactly five stable Developer identities exist:

- `DEV-1`
- `DEV-2`
- `DEV-3`
- `DEV-4`
- `DEV-5`

A worker identity is durable task metadata, not a GitHub user account. All five workers may use the same authenticated GitHub identity, so GitHub assignee state alone is insufficient to distinguish them.

Each invocation is stateless except for durable repository/GitHub evidence.

## 2. Capacity and ownership invariants

The following invariants are mandatory:

1. one Developer worker may own at most one active implementation claim;
2. one implementation issue may have at most one active Developer claim;
3. one invocation may implement at most one issue;
4. five workers are a capacity ceiling, not a utilization target;
5. a worker with an existing active claim resumes/revalidates that issue and MUST NOT claim a second issue;
6. Developers do not mutate case-pool lifecycle state;
7. Developers do not execute Tester runs;
8. Developers do not create Generator cases;
9. a newly discovered child defect may be recorded, but is not implemented in the same invocation;
10. dependency and semantic-domain safety override throughput.

## 3. What counts as an active Developer claim

A claim is active when durable GitHub evidence shows implementation ownership has begun and has not reached a terminal state.

Applicable evidence includes:

- a Developer claim branch created under the protocol below;
- a claim metadata comment on the selected issue;
- an open implementation PR for that claim branch;
- issue development-log evidence that implementation remains in progress;
- CI/review/convergence work still owned by that implementation.

A branch or PR from historical completed work is not automatically an active claim. Completion must be demonstrated by merged/terminal PR state plus the issue-specific convergence/acceptance contract.

Time passage alone does not make a claim stale.

## 4. Worker preflight

At the beginning of every invocation the worker MUST reconstruct live state from protected `main` and GitHub.

It must determine:

- current protected-main SHA;
- its own worker identity;
- whether this worker already owns an active claim;
- all other active Developer claims;
- open defect/implementation issues relevant to the current case-validation front;
- current dependencies;
- active branches/PRs/CI;
- semantic-domain and likely-file overlap with active work.

If this worker already owns one active claim, that issue is the ONLY issue it may touch in this invocation.

If that claim is merely waiting on an external gate and no safe action is currently required, the worker reports the waiting state and terminates. It MUST NOT acquire another issue merely to stay busy.

## 5. Candidate issue eligibility

A new issue may be considered only when all applicable conditions hold:

- the issue is OPEN and requires implementation work;
- it is a product defect/gap or implementation issue, not a validation-only, Generator-only, Tester-only or controller-policy task;
- its hard dependencies are satisfied;
- no active Developer claim already owns it;
- no active implementation PR/branch already owns the same work;
- implementation does not conflict with a currently active semantically overlapping issue;
- required runtime/production mutation does not conflict with another active worker;
- the issue scope can be executed within `col-taxdata/` under the Developer template.

Priority should normally favor issues that currently block one or more case-validation cases, then other Tester-discovered product defects, while preserving dependency order and parallel safety.

If multiple candidates remain equivalent, use a deterministic order by issue number ascending.

## 6. Parallel-safety gate across different issues

Different issue numbers do not prove that work is safe in parallel.

Before claiming a candidate, compare it against every active Developer claim and implementation PR for:

- explicit dependency relation;
- shared root cause;
- semantic domain;
- expected core modules;
- likely touched files;
- schema/migration ownership;
- shared runtime or production mutation;
- same canonicalization/retrieval/intake subsystem;
- any issue text saying one must converge before the other.

A candidate is NOT parallel-safe when concurrent implementation can reasonably:

- edit the same central logic;
- invalidate the other issue's baseline;
- change a schema/migration assumption used by the other;
- require mutually exclusive runtime mutation;
- make attribution of a test result ambiguous;
- duplicate a systemic fix already owned elsewhere.

If parallel safety is uncertain, do not claim the issue. Idle capacity is preferable to overlapping ownership.

## 7. Claim acquisition protocol

No product edit may occur before an exclusive claim is acquired.

### 7.1 Claim attempt number

For candidate issue `N`, inspect its existing machine-readable Developer claim comments.

Let:

`attempt = 1 + number_of_prior_CLAIMED_records_for_issue_N`

All concurrent workers observing the same live issue state therefore compute the same next attempt.

### 7.2 Deterministic claim branch

Construct the claim/work branch name:

`agent/claim-issue-N-a<attempt>-<main12>`

where `main12` is the first 12 hexadecimal characters of the exact protected-main SHA observed immediately before claiming.

The branch name MUST NOT contain the worker ID. This is deliberate: two workers racing for the same issue/main/attempt must attempt to create the exact same branch name.

GitHub branch creation is the exclusive acquisition point:

- if branch creation succeeds, that worker provisionally owns the claim;
- if branch creation fails because the branch already exists, that worker did NOT acquire the claim and MUST NOT edit that branch;
- a losing worker revalidates live state and may attempt the next eligible candidate;
- this is bounded candidate selection, not polling.

The worker MUST NOT use force update to steal a claim branch.

### 7.3 Claim metadata

Immediately after successful branch creation, post a claim comment on the selected issue:

`<!-- col-taxdata-developer-claim: {"worker_id":"DEV-X","issue":N,"attempt":K,"base_sha":"<40hex>","branch":"agent/claim-issue-N-aK-<main12>","state":"CLAIMED"} -->`

The human-readable part of the same comment should state:

- worker identity;
- exact base SHA;
- branch;
- dependency state;
- parallel-safety reasoning;
- intended scope.

If the branch was created but claim metadata cannot be persisted, make no product edits. The branch itself becomes ambiguous ownership evidence and must be surfaced for Controller recovery.

## 8. Post-claim race revalidation

After posting the claim and before the first product edit, re-read live Developer claims.

This second check exists because two workers may have claimed different issues almost concurrently.

If a newly visible earlier claim makes the selected issue semantically unsafe in parallel:

- do not implement;
- record the reason in the selected issue;
- mark the claim `WITHDRAWN`;
- leave historical claim evidence intact;
- terminate or attempt another candidate only if no product edit has occurred and the normal one-issue-per-invocation rule remains unviolated.

Once product implementation has begun, do not switch to another issue in the same invocation.

## 9. Selected issue becomes the task selector

After exclusive claim succeeds, the selected GitHub issue becomes the sole task selector for the remainder of the invocation.

The generic Developer template is then applied exactly as if its `ISSUE:` field had contained that selected issue URL from the start.

The worker must read and obey:

- the selected issue;
- authoritative specification(s);
- dependencies;
- audits;
- acceptance criteria;
- regression requirements;
- migration/reprocessing requirements;
- all safety and development-log requirements from the Developer template.

The generic template does not authorize work on a second issue.

## 10. Development branch semantics

The deterministic claim branch is also the issue implementation branch.

Protected `main` is the authoritative base; product edits occur only on the claimed branch.

Do not create a second competing implementation branch for the same claim.

When meaningful changes exist, open/update the implementation PR from that claim branch according to normal repository workflow.

The PR and issue development log must preserve the claim identity.

## 11. One active claim per worker

Before seeking new work, each worker searches for active claim metadata with its own `worker_id`.

If exactly one active claim exists:

- resume/revalidate that issue only;
- do not select another.

If more than one active claim is attributed to the same worker, this is coordination corruption:

- do not implement either blindly;
- surface to Controller Monitor;
- terminate.

A worker becomes free only after its prior claim reaches a terminal state.

## 12. Claim terminal states

Claim history is append-only. Do not edit an old `CLAIMED` comment into another state.

Add a new machine-readable terminal comment when appropriate.

### DONE

Use `DONE` only when the issue's implementation lifecycle has satisfied its required completion/convergence/acceptance contract.

Example:

`<!-- col-taxdata-developer-claim: {"worker_id":"DEV-X","issue":N,"attempt":K,"branch":"...","state":"DONE","convergence_sha":"<40hex>"} -->`

Issue closure alone is insufficient if issue-specific provider/runtime acceptance or post-merge convergence is still required.

### WITHDRAWN

Use `WITHDRAWN` when the claim is abandoned before implementation because ownership/dependency/parallel-safety assumptions proved invalid.

Record the reason. Do not delete the claim branch or historical comment as evidence.

### BLOCKED

If implementation legitimately began but further work is blocked by an external dependency, the claim remains owned by that worker. Record the blocker in the issue, but do not free the worker to claim another issue unless the project explicitly transfers/releases ownership.

## 13. Stale and abandoned claim recovery

A scheduled worker MUST NOT declare another worker's claim stale based only on age.

A claim may be treated as terminal/released only with affirmative durable evidence such as:

- explicit terminal claim metadata;
- merged implementation plus required convergence/acceptance and a matching completion record;
- explicit Controller recovery/transfer decision.

If branch/PR/comment evidence conflicts or ownership cannot be resolved, do not claim that issue.

Escalate to Controller Monitor.

## 14. Bounded candidate selection

A worker that has no active personal claim may construct the deterministic list of eligible candidates.

For each candidate in order:

1. revalidate issue/dependencies;
2. revalidate active claims;
3. revalidate parallel safety;
4. compute deterministic claim attempt/branch;
5. attempt branch creation once.

If branch creation loses a race, move to the next candidate after one live revalidation.

Do not repeatedly retry the same issue.

If no candidate can be safely claimed, report NO-OP and terminate.

## 15. Staggered scheduled starts

The five workers should normally be scheduled at different minute offsets so earlier claims become visible before later workers select work.

Recommended hourly offsets in `America/Bogota`:

- DEV-1: `:20`
- DEV-2: `:22`
- DEV-3: `:24`
- DEV-4: `:26`
- DEV-5: `:28`

The stagger is a race-reduction mechanism, not the ownership mechanism.

Developer implementations MAY overlap in wall-clock time **only after** distinct, parallel-safe issue claims have been acquired.

The workers MUST NOT overlap on the same issue, claim branch, or unsafe semantic domain.

If the intended deployment requires strictly no concurrent Developer execution at all, use one Developer worker instead of five; five workers exist specifically to allow safe parallel implementation.

## 16. Interaction with Tester and Generator

Developers do not directly write:

- `TestCasePool.yaml`;
- case lifecycle `state.yaml`;
- Tester sweep records;
- Tester run records.

The Tester owns case lifecycle and later observes live issue/PR/convergence state to decide whether blocked cases become runnable.

The Generator owns case creation/inventory.

Developers communicate their work through GitHub issue/branch/PR/CI/convergence state.

## 17. Child issues and unexpected defects

If the selected issue exposes a separate defect:

- preserve evidence;
- create/recommend the correct child/new issue when authorized;
- establish dependency/ownership clearly;
- do not switch to implementing that new issue in the current invocation.

The current worker remains bound to its claimed issue.

## 18. Invocation completion report

At the end of each invocation report:

- worker ID;
- protected main observed;
- prior active claim for this worker, if any;
- candidate issues considered;
- issue selected or NO-OP;
- claim attempt/branch;
- parallel-safety decision;
- selected issue dependencies;
- implementation/PR/CI/convergence state;
- whether claim is `CLAIMED`, `BLOCKED`, `WITHDRAWN` or `DONE`;
- any Controller intervention required.

Then terminate.

Do not wait for the next hour and do not poll.
