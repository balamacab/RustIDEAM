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
