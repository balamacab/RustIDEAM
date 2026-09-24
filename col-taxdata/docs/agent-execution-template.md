# Generic autonomous implementation template

Use this template for repository implementation work when the selected issue does not define a stricter workflow.

## Admission

Read the selected issue, current repository contracts, dependencies, blockers, environment/authority requirements, and writable scope. Record the accepted `main` SHA and classify `parallel_safe`, `semantic_domains`, `likely_touched`, and `depends_on`. Stop unsafe or unauthorized portions rather than inventing approval.

## Branch and implementation

Create or reuse `agent/issue-<number>-<slug>` from the accepted current `main`. One issue owns one branch. Use an isolated checkout/worktree when local execution is required. Do not develop directly on `main`, force-push `main`, rewrite applied migrations, rewrite immutable evidence, or widen scope for convenience.

## Pull request

Open or update one PR targeting `main`. Include the selected issue using GitHub closing syntax, base SHA, scope summary, validation evidence, concurrency metadata, semantic domains, and likely touched paths. Keep the issue open until merge.

## Validation and recovery

Run issue-specific tests plus durable project invariants. Before merge, refresh current `main`, review relevant concurrent changes, reconcile safely, re-read changed contracts, and rerun applicable validation. Stale branches, conflicts, and fixable CI failures use the autonomous resume contract and update the same PR. Retry loops are bounded and auditable.

Textual conflict resolution must preserve unrelated merged work. A real architecture/specification contradiction blocks merge and creates focused corrective/blocking work rather than silently inventing architecture.

## Integration and completion

Machine-verifiable required checks determine merge eligibility; normal work requires zero human approvals. Merge through the repository lifecycle, not a direct push. Completion is `merged + required convergence validation`, not merely `implementation complete` or `PR ready`.

Production/runtime mutation is separate from repository integration and requires explicit authorization, preview/recovery controls, and the project's production-safety invariants.

[executed on device: morichalserver (2bfaa62f-23ff-40e5-9fc7-7c1a7d28b1fc)]