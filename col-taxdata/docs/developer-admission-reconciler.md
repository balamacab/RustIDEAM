# Executable Developer admission reconciler

Issue: #323. The worker IDs are **DEV-1** (Desarrollo A) and **DEV-2**
(Desarrollo B). There are no identities `DEV-A` or `DEV-B`.

`ci/developer_admission.py` is a **pure, offline decision engine** for a
GitHub-connector-derived inventory. It is not a GitHub API client, a credential
holder, a worker scheduler, or an alternative writer. Its output is a proposed
decision subject to the existing GitHub transaction and lifecycle rules.

## Required snapshot

Supply JSON via stdin from complete LIVE GitHub connector reads:

```json
{
  "worker_id": "DEV-2",
  "main_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "inventory_complete": true,
  "write_channel": "denied",
  "issues": [
    {
      "number": 259,
      "state": "open",
      "comments_complete": true,
      "branches_complete": true,
      "prs_complete": true,
      "comments": [
        {
          "body": "<!-- col-taxdata-developer-claim: {\"worker_id\":\"DEV-2\",\"issue\":259,\"attempt\":11,\"base_sha\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"branch\":\"agent/issue-259-claim-a11-aaaaaaaaaaaa\",\"state\":\"CLAIMED\",\"claim_origin\":\"CONTROLLER_EXPLICIT_RECOVERY\"} -->"
        }
      ],
      "branches": [
        {
          "name": "agent/issue-259-claim-a11-aaaaaaaaaaaa",
          "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
      ],
      "prs": [],
      "eligible": true,
      "dependencies_satisfied": true,
      "parallel_safe": true,
      "priority": 30
    }
  ]
}
```

The sample SHAs are placeholders, **never use them as facts**. For a real run:
- `issues` must include every potentially active claim for the worker,
  every relevant competing worker claim and all eligible work considered;
  `inventory_complete=true` must not be asserted on a truncated search.
- Each issue includes the **complete** comments, issue-related claim branches
  and implementation PRs; search pagination must be exhausted, with per-issue
  `*_complete=true` flags only once evidence is actually complete.
- Candidate `priority` may originate from the backlog, but open state,
  dependency completion, `eligible`, and `parallel_safe` require separate
  live semantic evaluation. Missing evidence must produce a blocked outcome,
  not a guessed yes.
- `write_channel=verified` requires a **successful authorized write in the
  same effective worker execution context**, not the repository `push`
  permission, another agent's success or a healthcheck. `denied` records an
  explicit refusal. `unknown` allows exactly ONE provisional atomic branch
  attempt when the chosen issue has no prior orphan. Its immediately following
  `CLAIMED` comment must succeed and be read back; a failure leaves
  `ORPHAN_NOOP`, and another unverified attempt is forbidden.
- For a closed claimed issue, a `DONE` marker with convergence SHA must
  exist before the claim can be discarded as terminal. `WITHDRAWN` must
  be a real machine-readable terminal claim record.
- If the worker is resuming an existing valid claim, `RESUME` is returned
  regardless of write-channel status. This recognizes **ownership only**;
  any subsequent source write still requires its own authorized permission.
  Refusal must not be retried through an alternative GitHub writer.

Run:

```bash
python3 col-taxdata/ci/developer_admission.py < complete-live-snapshot.json
python3 -m unittest discover -s col-taxdata/tests -p 'test_issue0323_developer_admission.py' -v
```

## Decision application

| Outcome | Next allowed action |
| --- | --- |
| `RESUME` | Keep exact own issue/attempt/branch; verify HEAD and scope, then continue implementation using GitHub connector. |
| `CREATE_CLAIM` | Revalidate main/ownership immediately, attempt one atomic branch creation, post machine-readable `CLAIMED` to same issue and confirm read-after-write before product edits. |
| `BLOCKED` | Do not create an extra branch, fake a claim, switch worker ID, or use another GitHub writer; retain exact refusal and recover through authorized coordination. |
| `NO_OP` | No safe eligible issue; do not manufacture work. |
| Invalid snapshot (exit 2) | Re-fetch incomplete/contradictory GitHub evidence; no write authorized. |

The helper does not itself verify secrets, actual GitHub write availability,
post-merge acceptance or empirical worker activity. These remain independent
requirements. A Controller-authored implementation is always attributed to
Controller even when it uses an issue historically assigned to a Developer.

## Current, observed recovery state

At 2026-10-16 during issue #323 recovery, DEV-2 has an exclusive recovered
claim on #259/a11; DEV-1's #258 was merged by Controller; a branch
`agent/issue-268-claim-a1-c5767b9d3f53` existed without a claim comment
or commits and is `ORPHAN_NOOP`, not evidence of Developer progress.
These are **historical observations**, not a replacement for LIVE preflight.

A GitHub docs or tool commit does not update a scheduler prompt, pinned hash or
external Library worker contract. Proven worker recovery requires a worker's
own source changes, PR, CI and convergence. Keep #323 open until that evidence
exists. Do not modify scheduled tasks to test this helper.

The Controller subsequently published an explicit DEV-1 handoff for
#268/a2 on `agent/issue-268-claim-a2-c5767b9d3f53`, leaving a1 as a
historical `ORPHAN_NOOP`. Neither worker's implementation is proved by those
handoffs; all main drift must be reconciled on the original claim branch.
