# Generic autonomous implementation template

Use this template for repository implementation work when the selected issue does not define a stricter workflow.

Controller governance is defined in [`controller-orchestration.md`](controller-orchestration.md). The controller owns issue decomposition, global dependency/blocker analysis, concurrency decisions and authorization before this implementation template begins. An implementation agent should report materially incorrect/stale controller assumptions, but it is not responsible for reconstructing the global project graph omitted by the controller.

## Admission

Read the selected issue, current repository contracts, dependencies, blockers, environment/authority requirements, and writable scope. Record the accepted `main` SHA and classify `parallel_safe`, `semantic_domains`, `likely_touched`, and `depends_on`. Stop unsafe or unauthorized portions rather than inventing approval.

## Branch and implementation

Create or reuse `agent/issue-<number>-<slug>` from the accepted current `main`. One issue owns one branch. Use an isolated checkout/worktree when local execution is required. Do not develop directly on `main`, force-push `main`, rewrite applied migrations, rewrite immutable evidence, or widen scope for convenience.

## Pull request

Open or update one PR targeting `main`. Record the owning issue in the machine-readable PR metadata. For normal `completion_mode=convergence`, include exactly one GitHub closing target (`Fixes`, `Closes`, or `Resolves`). If the selected issue has an explicit mandatory post-merge/runtime/provider/fresh-acceptance gate, use `completion_mode=post_merge_acceptance`, include `issue_number` in metadata, and do **not** use GitHub closing syntax; this deliberately keeps the issue open through merge/convergence until acceptance passes. Always include base SHA, scope summary, validation evidence, concurrency metadata, semantic domains, and likely touched paths.

## Validation and recovery

Run issue-specific tests plus durable project invariants. Before merge, refresh current `main`, review relevant concurrent changes, reconcile safely, re-read changed contracts, and rerun applicable validation. Stale branches, conflicts, and fixable CI failures use the autonomous resume contract and update the same PR. Retry loops are bounded and auditable.

Textual conflict resolution must preserve unrelated merged work. A real architecture/specification contradiction blocks merge and creates focused corrective/blocking work rather than silently inventing architecture.

## Integration and completion

Machine-verifiable required checks determine merge eligibility; normal work requires zero human approvals. Merge through the repository lifecycle, not a direct push. `PR_OPEN`, `CI_VALIDATING`, `READY_FOR_MERGE`, `MERGED`, and pending convergence are non-terminal. Normal completion is `merged + required convergence validation`; `completion_mode=post_merge_acceptance` additionally requires the selected issue explicit post-merge acceptance contract to pass. The Developer keeps ownership of the same issue through these non-terminal states and does not select another issue merely because GitHub Actions is still running. Use GitHub-native check/workflow state for bounded waiting and revalidation. If the execution environment ends before a terminal state, persist the non-terminal state and resume the same claim on the next activation; timeout is not release or completion.

Production/runtime mutation is separate from repository integration and requires explicit authorization, preview/recovery controls, and the project's production-safety invariants.

Repository automation exceptions must be explicitly authorized by the selected issue and remain limited to the minimum required automation paths.
