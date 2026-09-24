# Autonomous agent execution governance

This document is the durable repository-side contract for autonomous implementation work. The selected GitHub issue is always the task authority; this document defines the lifecycle, safety invariants and machine-readable integration contract without encoding any current backlog snapshot.

## Lifecycle

Normal implementation follows:

issue admission -> dedicated issue branch -> implementation -> PR -> required CI -> autonomous merge -> main -> convergence validation -> done

Implementation agents never develop directly on main. Each admitted issue owns one branch named:

agent/issue-<number>-<short-slug>

The branch starts from the accepted main revision and records that base SHA in PR metadata. One issue owns one implementation branch; independent issues do not share branches.

The PR is the integration unit. It targets main, contains exactly one GitHub closing reference for the owning issue, and remains the same PR through stale-branch, conflict and CI recovery. The issue remains open while the PR is open or merely ready; merge closes it through the PR closing reference.

## Machine-readable execution metadata

Every autonomous implementation PR includes one HTML comment containing JSON:

<!-- agent-execution:{"base_sha":"<40-hex-sha>","parallel_safe":false,"semantic_domains":["<domain>"],"likely_touched":["<path-or-glob>"],"depends_on":[]} -->

Rules:

- base_sha is the main revision from which the issue branch started;
- parallel_safe is explicit; historical absence is never interpreted as true;
- semantic_domains identifies contracts/behavior that can overlap semantically even without textual conflicts;
- likely_touched declares expected changed paths and is enforced by CI;
- depends_on contains issue numbers whose integrated state is required.

The selected issue may explicitly authorize repository-global automation paths. Without that authority, normal col-taxdata implementation remains limited to col-taxdata/**.

## Required CI gates

Three stable required check contexts gate merge:

- scope-policy
- project-invariants
- project-tests

The scope policy verifies branch/issue ownership, the PR closing reference, metadata shape, issue-authorized writable scope, immutable migration history, forbidden runtime/raw corpus artifacts, and high-confidence credential signatures in added lines.

Project invariants run the durable CI-policy tests. Project tests run the complete col-taxdata suite when the project changed; unrelated repository changes preserve the stable required context without running the heavy suite.

Passing issue-specific tests alone is never sufficient to merge.

## Stale, conflict and CI recovery

The repository-side resume event is:

event_type: agent.resume.requested

client_payload schema version 1 contains:

- repository
- issue_number
- pull_request_number
- head_sha
- reason
- attempt
- semantic_domains
- required_action = reconcile_same_pr_against_current_main

Reasons are NEEDS_REBASE, MERGE_CONFLICT, CI_FAILED and SEMANTIC_REVALIDATION_REQUIRED.

The authorized agent orchestrator must resume the owning issue on the same PR. It must inspect current main, re-read changed contracts relevant to the semantic domains, reconcile without mechanically choosing ours/theirs, rerun applicable validation, and update the same branch/PR.

Retries are bounded per issue + reason + head SHA. A changed head gets a fresh budget; repeated no-progress failure on the same revision does not loop forever. Exhaustion creates durable corrective work and leaves unsafe merge blocked.

If reconciliation discovers a real specification/architecture contradiction not authorized by the selected issue, the agent must keep the original issue/PR open and create/link a focused blocker rather than invent a new architecture.

## Autonomous merge

Main governance requires PR integration, strict required checks, zero human approvals, and non-fast-forward protection. The lifecycle workflow performs a deterministic squash merge only when:

- required CI completed successfully;
- GitHub reports the PR clean against current main;
- current main does not have pending/failed convergence.

The merge request is SHA-locked to the validated PR head. Repository configuration deletes the issue branch after merge. No normal approval, merge click, rerun click, conflict-resolution click or manual issue closure is part of the path.

## Convergence

Every relevant change merged into main runs the complete combined-main invariant suite. Running it for every relevant merge intentionally subsumes the semantic-overlap case; overlapping semantic domains therefore cannot bypass convergence merely because Git reported no textual conflict.

The workflow publishes the col-taxdata-convergence commit status:

- pending while validation runs;
- success after combined-main invariants pass;
- failure after combined-main invariants fail.

Pending or failed convergence blocks downstream autonomous merge attempts. Failure creates one corrective issue per main SHA and emits integration.validation.required with schema_version, main_sha and corrective_issue.

Where deterministic tests are sufficient, that suite is authoritative. If the failure requires semantic architecture review, the integration-validation dispatch provides the stable external-agent handoff.

## Production boundary

Repository CD means promotion of validated repository changes into main. It does not authorize production corpus/database/runtime mutation.

Existing evidence/provenance, migration, ambiguity, dry-run/reprocessing and production-safety rules remain in force. Production mutation requires separate issue/spec authority.

## Repository governance rollout and recovery

col-taxdata/ci/repository_governance.py provides plan, apply and verify modes. Apply requires GITHUB_ADMIN_TOKEN with repository administration permission and never stores that token in the repository.

Desired governance:

- main ruleset active;
- pull requests required;
- required approving reviews = 0;
- strict required status checks;
- non-fast-forward protection;
- no bypass actors;
- squash merge enabled as the only merge strategy;
- issue branches deleted after merge.

Recovery is declarative: disable/remove the named ruleset or restore repository merge settings using an administration-authorized change. History is never force-rewritten as a rollback mechanism.
