"""Regressions for fail-closed, offline developer admission (#323)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

CI = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI))
from developer_admission import SnapshotError, reconcile  # noqa: E402

OLD = "a" * 40
MAIN = "b" * 40


def issue(number: int, *, state: str = "open", priority: int = 20):
    return {
        "number": number, "state": state, "comments": [], "branches": [],
        "prs": [], "comments_complete": True, "branches_complete": True,
        "prs_complete": True, "eligible": True, "dependencies_satisfied": True,
        "parallel_safe": True, "priority": priority,
    }


def snapshot(*issues, worker="DEV-1", channel="unknown"):
    return {
        "worker_id": worker, "main_sha": MAIN, "inventory_complete": True,
        "write_channel": channel, "issues": list(issues),
    }


def claimed(number, worker, attempt, base=OLD):
    branch = f"agent/issue-{number}-claim-a{attempt}-{base[:12]}"
    return {
        "worker_id": worker, "issue": number, "attempt": attempt,
        "base_sha": base, "branch": branch, "state": "CLAIMED",
        "claim_origin": "CONTROLLER_EXPLICIT_RECOVERY",
    }


def add_claim(i, claim):
    i["comments"].append({
        "body": "<!-- col-taxdata-developer-claim: " + json.dumps(claim) + " -->"
    })
    i["branches"].append({"name": claim["branch"], "head_sha": claim["base_sha"]})


class DeveloperAdmissionTests(unittest.TestCase):
    def test_controller_handoff_resumes_even_when_write_channel_denied(self):
        a = issue(259)
        add_claim(a, claimed(259, "DEV-2", 11))
        b = issue(268, priority=1)
        r = reconcile(snapshot(b, a, worker="DEV-2", channel="denied"))
        self.assertEqual((r["decision"], r["issue"], r["attempt"]),
                         ("RESUME", 259, 11))
        self.assertEqual(r["claim_origin"], "CONTROLLER_EXPLICIT_RECOVERY")

    def test_orphan_never_reused_and_denied_write_blocks_without_new_branch(self):
        i = issue(268)
        i["branches"].append({
            "name": "agent/issue-268-claim-a1-" + MAIN[:12], "head_sha": MAIN
        })
        r = reconcile(snapshot(i, channel="denied"))
        self.assertEqual(r["decision"], "BLOCKED")
        self.assertEqual(r["reason"], "external_write_denied")
        self.assertEqual(r["next_attempt"], 2)
        self.assertEqual(len(r["orphan_noop"]), 1)

    def test_verified_channel_can_allocate_next_unused_attempt(self):
        i = issue(268)
        i["branches"] = [{"name": "agent/issue-268-claim-a2-" + OLD[:12],
                          "head_sha": OLD}]
        r = reconcile(snapshot(i, channel="verified"))
        self.assertEqual(r["decision"], "CREATE_CLAIM")
        self.assertEqual(r["attempt"], 3)
        self.assertEqual(r["base_sha"], MAIN)
        self.assertEqual(r["branch"], "agent/issue-268-claim-a3-" + MAIN[:12])

    def test_closed_done_claim_does_not_occupy_worker(self):
        done = issue(258, state="closed")
        add_claim(done, claimed(258, "DEV-1", 7))
        done["comments"].append({"body":
            '<!-- col-taxdata-agent-state: {"state":"DONE","convergence_sha":"' + OLD + '"} -->'})
        new = issue(268)
        self.assertEqual(reconcile(snapshot(done, new, channel="verified"))["issue"], 268)

    def test_unproven_closed_claim_never_becomes_new_admission(self):
        i = issue(258, state="closed")
        add_claim(i, claimed(258, "DEV-1", 7))
        with self.assertRaises(SnapshotError):
            reconcile(snapshot(i, issue(268), channel="verified"))

    def test_active_claims_on_two_issues_cannot_be_reconciled(self):
        a, b = issue(259), issue(268)
        add_claim(a, claimed(259, "DEV-2", 11))
        add_claim(b, claimed(268, "DEV-2", 2))
        with self.assertRaisesRegex(SnapshotError, "conflicting active claims"):
            reconcile(snapshot(a, b, worker="DEV-2"))

    def test_foreign_claim_protects_issue(self):
        a, b = issue(259, priority=0), issue(268, priority=1)
        add_claim(a, claimed(259, "DEV-2", 11))
        r = reconcile(snapshot(a, b, channel="verified"))
        self.assertEqual((r["decision"], r["issue"]), ("CREATE_CLAIM", 268))

    def test_incomplete_inventory_fails_closed(self):
        i = issue(268)
        i["branches_complete"] = False
        with self.assertRaisesRegex(SnapshotError, "incomplete issue branches"):
            reconcile(snapshot(i, channel="verified"))
        s = snapshot(issue(268), channel="verified")
        s["inventory_complete"] = False
        with self.assertRaises(SnapshotError):
            reconcile(s)

    def test_inconsistent_claim_identity_rejected(self):
        i = issue(259)
        bad = claimed(259, "DEV-2", 11)
        bad["branch"] = "agent/issue-258-claim-a11-" + OLD[:12]
        add_claim(i, bad)
        with self.assertRaisesRegex(SnapshotError, "branch identity mismatch"):
            reconcile(snapshot(i, worker="DEV-2"))

    def test_unclaimed_nontrivial_branch_is_not_called_orphan(self):
        i = issue(268)
        i["branches"] = [{
            "name": "agent/issue-268-claim-a1-" + OLD[:12], "head_sha": MAIN
        }]
        with self.assertRaisesRegex(SnapshotError, "unclaimed branch with implementation"):
            reconcile(snapshot(i, channel="verified"))

    def test_unknown_channel_allows_only_first_provisional_claim(self):
        r = reconcile(snapshot(issue(268), channel="unknown"))
        self.assertEqual(r["decision"], "CREATE_CLAIM")
        self.assertEqual(r["attempt"], 1)
        self.assertEqual(r["write_channel"], "unknown")
        self.assertEqual(
            r["precondition"], "atomic_branch_create_then_verified_CLAIMED_comment"
        )

    def test_unknown_channel_with_orphan_does_not_retry(self):
        i = issue(268)
        i["branches"].append({
            "name": "agent/issue-268-claim-a1-" + MAIN[:12], "head_sha": MAIN
        })
        r = reconcile(snapshot(i, channel="unknown"))
        self.assertEqual(r["decision"], "BLOCKED")
        self.assertEqual(r["reason"], "unconfirmed_claim_write_after_orphan")
        self.assertEqual(r["next_attempt"], 2)

    def test_two_claimed_workers_on_same_issue_is_corruption(self):
        i = issue(259)
        add_claim(i, claimed(259, "DEV-2", 11))
        add_claim(i, claimed(259, "DEV-1", 12))
        with self.assertRaisesRegex(SnapshotError, "conflicting active claims"):
            reconcile(snapshot(i, channel="verified"))

    def test_no_work_returns_noop(self):
        i = issue(259)
        i["eligible"] = False
        self.assertEqual(reconcile(snapshot(i))["decision"], "NO_OP")

    def test_non_durable_worker_identity_rejected(self):
        with self.assertRaises(SnapshotError):
            reconcile(snapshot(issue(268), worker="DEV-A", channel="verified"))



    def test_historical_wrong_identity_withdrawn_and_done_record_frees_worker(self):
        """Replays #53's actual a4 WITHDRAWN, a5 DONE, and live #268."""
        old = issue(53, state="closed")
        legacy = claimed(53, "DEV-A", 4)
        add_claim(old, legacy)
        old["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({**legacy, "state": "WITHDRAWN"}) + " -->"})
        latest = claimed(53, "DEV-1", 5)
        add_claim(old, latest)
        convergence = "c" * 40
        old["comments"].append({"body":
            '<!-- col-taxdata-agent-state: {"state":"DONE","convergence_sha":"' +
            convergence + '"} -->'})
        old["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({k: v for k, v in {
                **latest, "state": "DONE", "convergence_sha": convergence
            }.items() if k != "base_sha"}) + " -->"})
        current = issue(268)
        add_claim(current, claimed(268, "DEV-1", 2))
        outcome = reconcile(snapshot(old, current, worker="DEV-1", channel="denied"))
        self.assertEqual((outcome["decision"], outcome["issue"], outcome["attempt"]),
                         ("RESUME", 268, 2))

    def test_withdrawal_must_match_exact_prior_claim(self):
        i = issue(53)
        old = claimed(53, "DEV-A", 4)
        add_claim(i, old)
        i["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({**old, "worker_id": "DEV-1", "state": "WITHDRAWN"}) + " -->"})
        with self.assertRaisesRegex(SnapshotError, "terminal claim identity mismatch"):
            reconcile(snapshot(i))

    def test_legacy_wrong_identity_must_be_withdrawn(self):
        i = issue(53)
        add_claim(i, claimed(53, "DEV-A", 4))
        with self.assertRaisesRegex(SnapshotError, "unwithdrawn legacy worker identity"):
            reconcile(snapshot(i))

    def test_unpaired_done_does_not_terminate_another_claim(self):
        i = issue(53, state="closed")
        done = claimed(53, "DEV-1", 5)
        i["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({**done, "state": "DONE", "convergence_sha": "c" * 40}) + " -->"})
        with self.assertRaisesRegex(SnapshotError, "terminal claim without prior admission"):
            reconcile(snapshot(i))

    def test_done_requires_matching_repository_convergence(self):
        i = issue(53, state="closed")
        record = claimed(53, "DEV-1", 5)
        add_claim(i, record)
        i["comments"].append({"body":
            '<!-- col-taxdata-agent-state: {"state":"DONE","convergence_sha":"' +
            "d" * 40 + '"} -->'})
        i["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({**record, "state": "DONE", "convergence_sha": "c" * 40}) + " -->"})
        with self.assertRaisesRegex(SnapshotError, "DONE claim lacks matching convergence evidence"):
            reconcile(snapshot(i))

    def test_historical_withdrawal_does_not_block_unrelated_open_issue(self):
        i = issue(53)
        record = claimed(53, "DEV-A", 4)
        add_claim(i, record)
        i["comments"].append({"body":
            "<!-- col-taxdata-developer-claim: " +
            json.dumps({**record, "state": "WITHDRAWN"}) + " -->"})
        outcome = reconcile(snapshot(i, worker="DEV-1", channel="verified"))
        self.assertEqual(outcome["decision"], "CREATE_CLAIM")
        self.assertEqual(outcome["attempt"], 5)


if __name__ == "__main__":
    unittest.main()
