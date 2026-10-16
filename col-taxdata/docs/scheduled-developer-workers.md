# Scheduled Developer workers

Status: **operational/controller contract**

This document centralizes the repository-side execution contract for the scheduled Col-taxdata Developer workers. Worker-specific Library contracts may define worker identity, deterministic claim mechanics, one-issue-per-activation selection and report shape, but they must not weaken this lifecycle.

## Cardinality and ownership

The scheduled Developer pool has a capacity ceiling of five workers. Capacity does not imply that five issues must be active.

Each worker:

- may own at most one real active Developer claim;
- must resume its own real active claim before considering new work;
- may select at most one issue in an activation;
- must not select a second issue while its current claim is non-terminal;
- must not steal ambiguous ownership;
- must preserve the orphan-no-op claim rule defined by the current worker contract.

Elapsed time, scheduler rollover, an activation cutoff, an open PR, running CI, a merge, or a pending convergence run do **not** release ownership.


## Durable Developer backlog and candidate discovery

New-work discovery uses the machine-readable queue at:

`col-taxdata/automation/developer-backlog.json`

The backlog is a **priority/candidate registry**, not an ownership authority and not a cached replacement for GitHub. Before every claim attempt a worker MUST revalidate the referenced issue in GitHub live.

Selection order is:

1. resume the worker's own active real claim, if any;
2. read the current backlog from protected `main`;
3. discard entries whose issue is CLOSED, validation-only, controller-only, already actively claimed, dependency-blocked, or unsafe against current active work;
4. preserve backlog priority order among the remaining candidates;
5. attempt an atomic claim once for the first safe candidate;
6. if that claim race is lost, revalidate once and continue to the next safe backlog item in the same activation;
7. if no safe candidate remains, exit `NO-OP`.

Tester case `blocking_issues` are evidence/context for defect creation and case lifecycle. They are **not** the Developer queue. Stale case state must therefore never force a Developer to select a closed issue.

The initial backlog was seeded with ten low/low-medium candidate issues (#257). That initial seed count is not a permanent dispatch limit: Controller may add a small, explicitly bounded urgent candidate when live defects justify it (for example, a medium-complexity P0 REST transport defect). Repository tests must validate the new known priority/exception explicitly rather than mislabeling complexity or bypassing CI. The backlog still grants no Developer ownership; every claim requires live eligibility checks and atomic persistence.

The backlog may include future items with explicit dependencies. Such an entry is not eligible until GitHub live proves those dependencies satisfied. Backlog metadata such as complexity or semantic domains is a scheduling hint; issue/spec/live GitHub state remains authoritative.

Closed issues #5, #8 and #221 are historical completed work and must not re-enter the active backlog unless GitHub contains an explicit regression/reopen.

## Atomic claim attempts and orphan branches

For issue `N`, inspect both:

- machine-readable Developer claim records for issue `N`; and
- existing branches matching `agent/issue-N-claim-aK-*`.

The next attempt is:

`attempt = 1 + max(K observed in either source)`

If no prior attempt exists, `attempt = 1`.

A branch matching the claim pattern that has **no** machine-readable `CLAIMED` metadata, **no** implementation PR/development log, and whose HEAD is exactly its creation/base commit is `ORPHAN_NOOP`.

An `ORPHAN_NOOP`:

- consumes its observed attempt number `K`;
- is never reused or force-updated;
- is not active ownership;
- does not block another worker from using the next attempt number;
- remains historical evidence unless separately cleaned by an explicit administrative policy.

Workers competing for the same issue/attempt/main SHA must construct the same branch name. Branch creation is the atomic ownership race. A worker that loses that race MUST NOT retry the same attempt or write to the winner's branch; it proceeds to the next eligible backlog candidate after one live revalidation.

After winning branch creation, the worker must immediately publish the machine-readable Developer claim comment before product edits. Failure to persist that metadata prevents implementation and leaves the branch as non-owning/orphan evidence.

## Controller-authorized emergency claim handoff

Normal workers acquire claims themselves through unique atomic branch creation
followed by the machine-readable `CLAIMED` issue comment. This remains the
default and cannot be replaced by an informal issue assignment.

When repeated attempts have demonstrably failed **after creating the branch but
before persisting the claim comment**, Controller may explicitly recover the
coordination deadlock on behalf of one named worker **only** when:

1. Live GitHub verifies the issue is OPEN, dependencies are satisfied, and no
   conflicting active claims or implementation PRs exist. Each historical
   no-op branch consumes its attempt number; no prior branch is adopted.
2. Controller creates exactly the next issue/attempt/main12 branch **atomically**
   from the exact current protected-main SHA; a lost race cannot be reclaimed.
3. Controller immediately writes the normal
   `col-taxdata-developer-claim` record to the **same issue** with exact
   `worker_id`, issue, attempt, base SHA, branch and state `CLAIMED`,
   plus `claim_origin=CONTROLLER_EXPLICIT_RECOVERY`. The prose explicitly
   identifies Controller as the assigning actor, not the implementing worker.
4. The worker, on its next activation, recognizes this as **its own active,
   nonterminal assigned claim** and resumes only that exact issue/branch.
   It **must not** create another attempt, adopt another worker's assignment,
   or assert it personally created the already-persisted claim.
5. Before product edits, it revalidates the branch, issue, claim, main drift,
   parallel safety, issue scope and selected tests/CI. It then does the
   implementation and produces its own commits/PR and completion evidence.
   If handoff metadata or any GitHub read/write is unavailable, it reports
   the precise blocker and does not invent a completed implementation.

The recovery comment and branch prove exclusive handoff, **not** that the
worker has executed code or that CI, merge, convergence or acceptance passed.
Controller verifies actual progress through implementation commits and
normal lifecycle evidence; it cannot declare delivery merely from the handoff.

## Admission resilience and recovery for scheduled DEV-1 / DEV-2

The human-facing labels Desarrollo A / Desarrollo B map **only** to durable
worker IDs `DEV-1` / `DEV-2`. Neither `DEV-A` nor `DEV-B` may appear as
a `worker_id` in a machine-readable claim. These rules apply independently
of the scheduler and are part of each worker's required protected-main
preflight. They supersede older Library contract text that infers work solely
from cached Tester blockers or computes attempts from comment counts only.
An effective scheduled prompt may additionally pin a Library-file hash;
modifying repository documentation does **not** silently update that pin.

### Recovery-first decision table

Every activation must reconstruct **GitHub live** (not last chat output)
before allocating a claim:

| Observation | Mandatory next action |
| --- | --- |
| One verified nonterminal `CLAIMED` by own durable worker ID (including `claim_origin=CONTROLLER_EXPLICIT_RECOVERY`) and matching branch / OPEN issue | Resume that issue and branch; verify current head, dependencies, PR/checks, and semantic overlap; do **not** create another attempt |
| Own prior claim has true terminal `DONE` / `WITHDRAWN` evidence, or the issue has documented merge + convergence + any required post-merge acceptance and is CLOSED | Release that claim for selection purposes without changing historical comments; never reopen automatically |
| A branch matching claim naming has no durable claim comment, no implementation PR/log, and HEAD equals its observed base | Classify `ORPHAN_NOOP`; consume attempt number; do not reuse, adopt or erase the branch |
| An unclaimed candidate has open issue + converged dependencies + no competing claim + parallel-safe scope | Compute next attempt from **both** branch and comment histories: `attempt = 1 + max(K observed in either source)`; perform the one atomic branch-create attempt |
| Branch creation returns a provable already-exists conflict (e.g. GitHub 422) | Lost race; do not write to winner's branch; revalidate once and consider the next safe candidate |
| Branch created, but `CLAIMED` comment outcome is unknown (timeout/connection loss) | Read the target issue's comments and exact branch HEAD first. If the exact comment exists, resume it; if absent, one bounded same-branch comment retry is allowed **only** for a demonstrably transient transport / 429 / 5xx failure |
| Branch created, but GitHub rejects the comment because of explicit security/policy denial, missing write permission, or repeated verified failure | Do not bypass or reformat to evade a safety refusal; no product edits and no other GitHub writer. Mark the local outcome `ADMISSION_BLOCKED` with operation + denial class, preserve `ORPHAN_NOOP`, and request Controller's exceptional documented recovery |
| One or more consecutive `ORPHAN_NOOP` attempts exist for a candidate on unchanged main with persistent comment-write denial | Do not create yet another no-op branch on each scheduled activation. Revalidate the live state; prioritize a valid own Controller handoff or a different independently safe candidate if its write path is verified. Otherwise report the precise external admission blocker |
| Own claimed issue encounters stale HEAD / rebase conflict / failed CI / pending convergence | Keep the same issue/claim, use existing bounded GitHub-native recovery; do not confuse these recoverable lifecycle states with `ADMISSION_BLOCKED` |
| Contradictory claims, differing durable identities, or an issue with unresolved ownership | Stop only conflicting work, preserve evidence, and report coordination corruption; never steal another worker's claim |

The first successful branch creation is **provisional**, not full admission.
Admission is the exact branch **plus** the machine-readable `CLAIMED` issue
comment. The comment may be short: the full validated
`col-taxdata-developer-claim` JSON marker suffices; do not add unrelated
requests or raw sensitive data. Read-after-write confirmation must match
`worker_id`, issue, attempt, base SHA, branch and state exactly. Once admitted,
resume normal implementation rather than repeatedly diagnosing GitHub.

The retry ceiling is about attempts **on the same provisional branch**, not
permission to create newer branch numbers after each scheduled failure. For
unknown writes, inspect live comments **before** retrying, so delayed success
does not create duplicate claims. A persistent safety denial cannot be repaired
by a repository documentation change, and must not be bypassed by changing
tools or writing GitHub through Morichal.

### External contract drift and progress evidence

At bootstrap read this file from exact protected main. If a pinned worker
Library file or scheduler-facing prompt conflicts (for example, DEV-2's old
`attempt=1+number_of_CLAIMED` or cached Tester blockers as primary queue),
report `CONTRACT_DRIFT` and use the newer authoritative repository rule only
when the effective worker contract permits that precedence. Never claim that
the external prompt or pinned hash was changed by a repository commit.

A successful Controller handoff is a **recovery of admission**, not an
implementation. Only actual code commits authored/executed by the worker,
its issue-specific regression tests, PR, CI, merge, and acceptance demonstrate
Developer progress. Controller-written code is attributed to Controller,
even when carried on a branch historically owned by DEV-1 or DEV-2.

No part of this recovery procedure changes scheduling, scheduled tasks,
worker identities, Tester admission, the requirement for GitHub connector
writes, protected-main CI rules, or permission to operate on production.

## One issue through the complete lifecycle

Once a Developer claims issue `N`, that issue remains the sole task through:

```text
CLAIMED
  -> WORKING
  -> PR_OPEN
  -> CI_VALIDATING
  -> READY_FOR_MERGE
  -> MERGED
  -> convergence
  -> POST_MERGE_ACCEPTANCE_PENDING when required
  -> DONE
```

The following are non-terminal:

- `PR_OPEN`;
- `CI_VALIDATING`;
- `READY_FOR_MERGE`;
- `MERGED`;
- pending Convergence Gate;
- `POST_MERGE_ACCEPTANCE_PENDING`.

A Developer must not voluntarily terminate merely because a GitHub gate is asynchronous. It should use GitHub-native check/workflow state and bounded, reasonable revalidation for the same claimed issue. This does not authorize aggressive polling of GitHub or polling of remote hosts/runtime state.

If the execution environment itself ends before a terminal state, the exact non-terminal state remains durable. The next activation resumes that same claim before considering another issue.

## Completion modes

The autonomous PR metadata supports two generic completion modes.

### `completion_mode=convergence`

Use when merge plus successful Convergence Gate satisfies the issue's repository completion contract.

The PR:

- carries exactly one GitHub closing target such as `Fixes #N`;
- may omit `completion_mode` only for backward compatibility; new PRs should emit it explicitly.

Successful convergence is sufficient for normal `DONE`/closure.

### `completion_mode=post_merge_acceptance`

Use when the selected issue/spec explicitly requires a provider, runtime, fresh-validation, or other mandatory acceptance step **after** merge and convergence.

The PR metadata must contain:

- `completion_mode: "post_merge_acceptance"`;
- `issue_number: N`.

The PR must **not** contain `Fixes`, `Closes`, or `Resolves` for the owning issue. Neutral linkage such as `Tracks #N` is appropriate.

After successful convergence, repository automation records `POST_MERGE_ACCEPTANCE_PENDING` and deliberately leaves the issue open. The owning Developer retains the claim and executes the issue-specific acceptance against the converged protected `main`.

Only PASS evidence for that explicit acceptance contract permits final `DONE` and issue closure. A failed acceptance is preserved as evidence; retry-until-pass is prohibited.

The mechanism is generic. Worker contracts and repository automation must not hard-code issue numbers, case IDs, providers, or one historical defect.

## Waiting, recovery and blockers

GitHub lifecycle waiting for the currently claimed issue is not "future work." Developers should prefer GitHub-native status/check/workflow evidence and follow the existing bounded autonomous recovery contract for:

- `NEEDS_REBASE`;
- `MERGE_CONFLICT`;
- `CI_FAILED`;
- `CHECKS_OUTDATED`;
- `SEMANTIC_REVALIDATION_REQUIRED`.

A genuine external dependency with no safe current action may produce `BLOCKED`. The claim remains owned unless terminal metadata or an explicit Controller transfer/release says otherwise.

When a Developer records a real `BLOCKED` transition in GitHub, it MUST publish the standard machine-readable lifecycle marker in the same issue comment; prose alone is insufficient control state:

```text
<!-- col-taxdata-agent-state: {"state":"BLOCKED","reason":"<why>","blocker":"<issue/ref when known>"} -->
Agent state: `BLOCKED`.
```

The repository projects that marker to the visible `status:blocked` label while leaving the issue OPEN. When work resumes, the Developer MUST publish the next real non-blocked lifecycle marker (for example `WORKING`); the projection then removes `status:blocked`. Developers must not add/remove the label as an independent source of truth.

For post-merge/runtime/provider acceptance failures, the BLOCKED marker should also include the relevant converged/main identity when available. This makes #237-style failures visible without parsing narrative development logs.

## Role boundaries

Developer workers do not:

- run the Case Tester or Case Generator;
- directly mutate Tester case lifecycle state;
- use production as a development sandbox;
- take a second issue merely to utilize capacity;
- bypass required CI/checks;
- weaken tests/specification to obtain a pass;
- force-push protected integration history.

The selected issue, protected `main`, the current repository contracts, and GitHub live state remain authoritative.


## Executable admission decision gate — issue #323 recovery

For scheduled workers whose effective contract allows it, use
[`developer-admission-reconciler.md`](developer-admission-reconciler.md)
and the pure `col-taxdata/ci/developer_admission.py` helper before new claim
allocation. The helper requires a COMPLETE GitHub connector snapshot,
recognizes current `CONTROLLER_EXPLICIT_RECOVERY` handoffs, distinguishes
terminal `DONE` from implementation, and prevents `ORPHAN_NOOP` retry storms.

Its output is advisory and cannot grant GitHub permissions, authorize writing
through a different client, supersede a denied security operation, or modify
the effective scheduled prompt/pinned Library contract. In particular, only
a successful authorized write in the **same worker execution context** counts
as `write_channel=verified`; Controller success does not verify Developer
permission. No work or branch may be created from incomplete snapshots.

If a valid own claim exists, immediately resume the exact branch without
creating another claim, regardless of write-channel status. If the subsequent
implementation write is denied, preserve the claim and report the denial
distinctly as `IMPLEMENTATION_WRITE_BLOCKED`, **not** `ADMISSION_BLOCKED`.
The Controller may perform an explicitly attributed implementation fallback,
but must never count those commits toward empirical autonomous worker recovery.

This implementation does not update the scheduler and requires acceptance on
actual DEV-1 and DEV-2 executions before issue #323 can be closed.
