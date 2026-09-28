# Autonomous agent execution contract

This document defines the durable repository-side lifecycle for autonomous implementation work. The selected GitHub issue remains the task authority; this contract does not replace issue-specific scope, dependencies, acceptance criteria, production authorization, or architecture decisions.

Controller-side issue creation, decomposition, dependency analysis and orchestration are governed separately by [`controller-orchestration.md`](controller-orchestration.md). Controllers must define those boundaries before launching work; implementation agents execute the selected issue and report discrepancies rather than being made responsible for inventing the global project graph. Controller-thread continuity uses [`controller-handoff-template.md`](controller-handoff-template.md).

## Lifecycle

Normal implementation uses:

`issue -> admission -> dedicated branch -> implementation -> PR -> CI Gate -> automatic merge -> main -> Convergence Gate -> [post-merge acceptance when required] -> done`

An implementation agent must never develop directly on `main`. Each admitted issue owns one branch named `agent/issue-<number>-<slug>` created from the accepted current `main` revision. The base SHA is recorded in pull-request metadata.

The pull request is the integration unit and targets `main`. Ownership and completion behavior are machine-readable. Default `completion_mode=convergence` keeps exactly one closing target (`Fixes`, `Closes`, or `Resolves`) for the owning issue; successful convergence is final repository completion. `completion_mode=post_merge_acceptance` requires `issue_number` in PR metadata and forbids GitHub closing syntax so the issue remains open through merge and convergence until its explicit post-merge/runtime/provider/fresh-acceptance gate passes. Native GitHub auto-close is therefore used only when convergence is sufficient. For `post_merge_acceptance`, the owning Developer closes the issue only after recording PASS evidence for that explicit acceptance contract.

## Machine-readable PR metadata

Every col-taxdata autonomous PR carries one HTML comment with JSON:

```text
<!-- col-taxdata-agent-metadata: {"base_sha":"<40-hex-sha>","parallel_safe":false,"semantic_domains":["<domain>"],"likely_touched":["<path-or-glob>"],"depends_on":[],"completion_mode":"convergence"} -->
```

`parallel_safe` must be classified conservatively. Historical absence of concurrency metadata never implies that parallel execution is safe. `depends_on` contains GitHub issue numbers. Semantic domains are used by post-merge convergence checks; textual Git conflicts are not treated as a complete compatibility model.

`completion_mode` is optional for backward compatibility and defaults to `convergence`. Allowed values are `convergence` and `post_merge_acceptance`. The latter requires a positive `issue_number` in the same metadata object and forbids GitHub closing syntax so merge cannot prematurely close the issue. New PRs should emit `completion_mode` explicitly.

## Scope and repository invariants

The CI policy first determines whether a PR touches col-taxdata or its dedicated repository automation. Purely unrelated-project PRs receive a passing global gate without running the heavy col-taxdata suite. A PR that mixes col-taxdata changes with unrelated project changes fails scope validation.

Normal col-taxdata issues may change only `col-taxdata/**`. Dedicated `.github/workflows/col-taxdata-*.yml` and `.github/actions/col-taxdata/**` are allowed only when the selected issue explicitly authorizes repository-global automation scope.

The durable gate also rejects modification/deletion/renaming of already-present SQL migrations, committed runtime/database artifacts, and high-confidence credential material. New migrations remain append-only. Existing raw evidence and production state are outside repository-CD authority.

## CI and current-base validation

`col-taxdata CI` is started explicitly by the trusted PR-lifecycle controller through `workflow_dispatch`; it does not listen directly to `pull_request`. The workflow definition comes from the default branch, resolves the exact PR head through the GitHub API, checks that candidate SHA out separately, and runs trusted default-branch policy code against the candidate checkout. For applicable changes it always runs repository-control regression tests. It runs the complete col-taxdata suite when product, schema, test, configuration, or CI-control code changes; documentation-only changes can skip the heavy suite.

Because a default-branch `workflow_dispatch` run is itself attached to the default-branch commit, the trusted gate explicitly publishes a GitHub Actions check run named `CI Gate` on the exact candidate head SHA after validation. The check is emitted with `checks: write` only by trusted workflow code; candidate jobs remain read-only. The required `CI Gate` context on the PR head is therefore tied to the exact candidate SHA that was validated.

The required `CI Gate` check is stable and is the branch-rule status context. The main ruleset requires strict/current-base status checks, PR integration, zero approving reviews, and non-fast-forward protection. No bypass actor is configured; automation merges through a validated PR rather than bypassing the PR requirement.

## Stale branch, conflict, and CI recovery

The lifecycle controller handles safe stale-branch updates through GitHub's update-branch API. GitHub-token-authored branch updates can create a non-runnable `pull_request` check suite with conclusion `action_required`, so `col-taxdata CI` no longer has a direct `pull_request` trigger. Instead, trusted `pull_request_target` controller code explicitly dispatches CI for a PR head, both at initial validation and after automated branch reconciliation.

Every dispatched CI uses the workflow definition from the default branch, not the candidate branch. The workflow resolves the current PR head SHA, checks that candidate code out separately with read-only permissions, and applies trusted default-branch policy code to the candidate checkout. After `CI Gate` succeeds, the write-capable completion job again checks out default-branch controller code and re-enters the lifecycle with the exact tested candidate head SHA. This avoids GitHub anti-recursion ghost suites while preventing candidate code from defining its own write-capable integration workflow.

When reconciliation requires implementation judgment, the controller emits `repository_dispatch` event type `col-taxdata-agent-resume` and writes the same request durably to the owning issue. The payload contract is:

```json
{
  "schema_version": 2,
  "repository": "owner/repository",
  "issue_number": 123,
  "pr_number": 456,
  "branch": "agent/issue-123-short-slug",
  "head_sha": "<sha>",
  "base_sha": "<sha>",
  "reason": "NEEDS_REBASE | MERGE_CONFLICT | CI_FAILED | CHECKS_OUTDATED | SEMANTIC_REVALIDATION_REQUIRED",
  "semantic_domains": ["domain"],
  "retry": {
    "attempt": 1,
    "max_attempts": 3,
    "automatic_update": false
  }
}
```

GitHub repository-dispatch accepts at most 10 top-level `client_payload` properties. Resume schema v2 therefore keeps retry/update metadata under the nested `retry` object without dropping any recovery/audit fields. Durable v1 issue markers remain valid historical retry evidence because retry counting is scoped by `reason` and `head_sha`.

An authorized external agent orchestrator may consume that event directly. It must resume the same issue and PR, inspect current `main`, preserve unrelated merged work, re-read changed contracts in relevant semantic domains, resolve conflicts semantically rather than choosing blanket ours/theirs, rerun applicable checks, and update the same branch/PR.

Retries are bounded per `(reason, head_sha)`. After three recorded resume requests, another request creates a focused blocker issue, records `BLOCKED`, and does not continue an infinite retry loop.

## Agent states

Normal states are represented by issue/PR/check state and durable lifecycle comments: `ADMITTED`, `WORKING`, `PR_OPEN`, `CI_VALIDATING`, `READY_FOR_MERGE`, `MERGED`, `POST_MERGE_ACCEPTANCE_PENDING`, and `DONE`. `PR_OPEN`, `CI_VALIDATING`, `READY_FOR_MERGE`, `MERGED`, pending convergence, and `POST_MERGE_ACCEPTANCE_PENDING` are non-terminal. Exceptional states include `NEEDS_REBASE`, `MERGE_CONFLICT`, `CI_FAILED`, `CHECKS_OUTDATED`, `SEMANTIC_REVALIDATION_REQUIRED`, and `BLOCKED`.

GitHub's native issue state remains only OPEN/CLOSED, so Col-taxdata projects the operational `BLOCKED` state into one visible/filterable issue label: `status:blocked`. The source of truth is the durable machine-readable lifecycle marker, not the label and not free-form prose:

```text
<!-- col-taxdata-agent-state: {"state":"BLOCKED","reason":"<why>","blocker":"<issue/ref when known>"} -->
Agent state: `BLOCKED`.
```

A real `BLOCKED` transition adds `status:blocked` idempotently and leaves the issue OPEN. A later machine-readable non-blocked lifecycle state removes the label idempotently. Arbitrary text such as `State: BLOCKED` without the marker is diagnostic prose only and must not mutate GitHub metadata.

Trusted repository workflows project states directly because comments created with GitHub's workflow token are not relied upon to recursively launch another workflow. Developer/operator lifecycle comments created outside that trusted workflow path are synchronized by the dedicated `col-taxdata Issue State` issue-comment workflow. Both paths use the same `issue_state_sync.py` projection rules.
A clean merge is not sufficient evidence of semantic compatibility. Agents must refresh `main` before final integration and rerun validation after relevant concurrent changes.

## Merge and convergence

After a successful `CI Gate`, the lifecycle controller re-reads live PR mergeability and head SHA and performs a deterministic squash merge. GitHub can transiently report `mergeable_state=blocked` while a just-completed required check is still propagating. For the exact CI-tested current head, the controller therefore performs a small bounded mergeability recheck. A head change becomes `NEEDS_REBASE`; a persistently blocked state becomes bounded `CHECKS_OUTDATED` recovery instead of a silent terminal wait. Required checks are never bypassed. It then emits `col-taxdata-convergence`; a normal authenticated merge to `main` also triggers convergence through `push`.

Convergence marks the merged SHA with `Convergence Gate`, detects overlapping semantic domains among recent merged autonomous PRs, and runs the complete col-taxdata integration/invariant suite on the resulting `main`. Repository-dispatch semantic-domain metadata is normalized to compact JSON before it is exported through GitHub Actions outputs. The test suite runs for every applicable merge, so semantic overlap cannot bypass convergence validation.

On convergence success, completion depends on the PR declared mode. For `completion_mode=convergence`, the controller closes the owning issue if GitHub did not already do so. For `completion_mode=post_merge_acceptance`, convergence records `POST_MERGE_ACCEPTANCE_PENDING` and deliberately leaves the issue open. The owning Developer then executes the explicit acceptance contract on the converged `main`; only PASS evidence permits final `DONE` and issue closure. Stranded-issue reconciliation never closes a `post_merge_acceptance` issue. For normal convergence-complete PRs it only reconciles recent stranded autonomous merged issues when their merge commit is contained in the successfully validated current history and the issue was not explicitly reopened after that merge. Historical failed convergence statuses are not rewritten; recovery is recorded against the newer validated main state.

A convergence failure sets the commit status to failure, leaves downstream readiness blocked, and automatically creates a focused corrective issue. Merged histories are preserved; revert or forward-fix is an explicit, separately validated action.

## Production boundary

Repository CD means promotion of validated repository changes into `main`. It does not authorize production corpus/database/runtime mutation, data reprocessing, destructive infrastructure operations, secret changes, or deployment. Those actions require their own issue authorization and the project's existing preview, migration, provenance, ambiguity, evidence-immutability, and recovery rules.

## Governance apply and recovery

`ci/repository_governance.py` plans, applies, verifies, or deletes the named `col-taxdata-autonomous-main` ruleset. Mutating commands require an administrator token supplied only through `GITHUB_ADMIN_TOKEN` or `GH_TOKEN`; no credential is stored in the repository.

Before applying the ruleset, the repository CI workflow must already exist on `main`, because `CI Gate` becomes required immediately. Rollback deletes only the named ruleset and does not rewrite history, weaken project tests, or modify production data. A rollback is an administrative recovery action, not a normal development path.
