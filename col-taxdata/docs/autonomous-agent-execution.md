# Autonomous agent execution contract

This document defines the durable repository-side lifecycle for autonomous implementation work. The selected GitHub issue remains the task authority; this contract does not replace issue-specific scope, dependencies, acceptance criteria, production authorization, or architecture decisions.

## Lifecycle

Normal implementation uses:

`issue -> admission -> dedicated branch -> implementation -> PR -> CI Gate -> automatic merge -> main -> Convergence Gate -> done`

An implementation agent must never develop directly on `main`. Each admitted issue owns one branch named `agent/issue-<number>-<slug>` created from the accepted current `main` revision. The base SHA is recorded in pull-request metadata.

The pull request is the integration unit. It targets `main`, contains exactly one closing target (`Fixes`, `Closes`, or `Resolves`), and keeps the issue open until GitHub closes it after the PR is merged. Human approval, a manual merge click, manual rerun, manual conflict resolution, and manual issue closure are not normal lifecycle steps.

## Machine-readable PR metadata

Every col-taxdata autonomous PR carries one HTML comment with JSON:

```text
<!-- col-taxdata-agent-metadata: {"base_sha":"<40-hex-sha>","parallel_safe":false,"semantic_domains":["<domain>"],"likely_touched":["<path-or-glob>"],"depends_on":[]} -->
```

`parallel_safe` must be classified conservatively. Historical absence of concurrency metadata never implies that parallel execution is safe. `depends_on` contains GitHub issue numbers. Semantic domains are used by post-merge convergence checks; textual Git conflicts are not treated as a complete compatibility model.

## Scope and repository invariants

The CI policy first determines whether a PR touches col-taxdata or its dedicated repository automation. Purely unrelated-project PRs receive a passing global gate without running the heavy col-taxdata suite. A PR that mixes col-taxdata changes with unrelated project changes fails scope validation.

Normal col-taxdata issues may change only `col-taxdata/**`. Dedicated `.github/workflows/col-taxdata-*.yml` and `.github/actions/col-taxdata/**` are allowed only when the selected issue explicitly authorizes repository-global automation scope.

The durable gate also rejects modification/deletion/renaming of already-present SQL migrations, committed runtime/database artifacts, and high-confidence credential material. New migrations remain append-only. Existing raw evidence and production state are outside repository-CD authority.

## CI and current-base validation

`col-taxdata CI` runs the scope/policy gate on every PR to `main`. For applicable changes it always runs repository-control regression tests. It runs the complete col-taxdata suite when product, schema, test, configuration, or CI-control code changes; documentation-only changes can skip the heavy suite.

The required `CI Gate` job is stable and is the branch-rule status context. The main ruleset requires strict/current-base status checks, PR integration, zero approving reviews, and non-fast-forward protection. No bypass actor is configured; automation merges through a validated PR rather than bypassing the PR requirement.

## Stale branch, conflict, and CI recovery

The lifecycle controller handles safe stale-branch updates through GitHub's update-branch API. Because GitHub-token-authored changes do not reliably generate a fresh CI event, the controller explicitly dispatches `col-taxdata CI` against the updated branch.

When reconciliation requires implementation judgment, the controller emits `repository_dispatch` event type `col-taxdata-agent-resume` and writes the same request durably to the owning issue. The payload contract is:

```json
{
  "schema_version": 1,
  "repository": "owner/repository",
  "issue_number": 123,
  "pr_number": 456,
  "branch": "agent/issue-123-short-slug",
  "head_sha": "<sha>",
  "base_sha": "<sha>",
  "reason": "NEEDS_REBASE | MERGE_CONFLICT | CI_FAILED | SEMANTIC_REVALIDATION_REQUIRED",
  "semantic_domains": ["domain"],
  "attempt": 1,
  "max_attempts": 3,
  "automatic_update": false
}
```

An authorized external agent orchestrator may consume that event directly. It must resume the same issue and PR, inspect current `main`, preserve unrelated merged work, re-read changed contracts in relevant semantic domains, resolve conflicts semantically rather than choosing blanket ours/theirs, rerun applicable checks, and update the same branch/PR.

Retries are bounded per `(reason, head_sha)`. After three recorded resume requests, another request creates a focused blocker issue, records `BLOCKED`, and does not continue an infinite retry loop.

## Agent states

Normal states are represented by issue/PR/check state and durable lifecycle comments: `ADMITTED`, `WORKING`, `PR_OPEN`, `CI_VALIDATING`, `READY_FOR_MERGE`, `MERGED`, and `DONE`. Exceptional states include `NEEDS_REBASE`, `MERGE_CONFLICT`, `CI_FAILED`, `SEMANTIC_REVALIDATION_REQUIRED`, and `BLOCKED`.

A clean merge is not sufficient evidence of semantic compatibility. Agents must refresh `main` before final integration and rerun validation after relevant concurrent changes.

## Merge and convergence

After a successful `CI Gate`, the lifecycle controller re-reads live PR mergeability and head SHA and performs a deterministic squash merge. It then emits `col-taxdata-convergence`; a normal authenticated merge to `main` also triggers convergence through `push`.

Convergence marks the merged SHA with `Convergence Gate`, detects overlapping semantic domains among recent merged autonomous PRs, and runs the complete col-taxdata integration/invariant suite on the resulting `main`. The test suite runs for every applicable merge, so semantic overlap cannot bypass convergence validation.

A convergence failure sets the commit status to failure, leaves downstream readiness blocked, and automatically creates a focused corrective issue. Merged histories are preserved; revert or forward-fix is an explicit, separately validated action.

## Production boundary

Repository CD means promotion of validated repository changes into `main`. It does not authorize production corpus/database/runtime mutation, data reprocessing, destructive infrastructure operations, secret changes, or deployment. Those actions require their own issue authorization and the project's existing preview, migration, provenance, ambiguity, evidence-immutability, and recovery rules.

## Governance apply and recovery

`ci/repository_governance.py` plans, applies, verifies, or deletes the named `col-taxdata-autonomous-main` ruleset. Mutating commands require an administrator token supplied only through `GITHUB_ADMIN_TOKEN` or `GH_TOKEN`; no credential is stored in the repository.

Before applying the ruleset, the repository CI workflow must already exist on `main`, because `CI Gate` becomes required immediately. Rollback deletes only the named ruleset and does not rewrite history, weaken project tests, or modify production data. A rollback is an administrative recovery action, not a normal development path.

[executed on device: morichalserver (2bfaa62f-23ff-40e5-9fc7-7c1a7d28b1fc)]