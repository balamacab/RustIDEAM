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
