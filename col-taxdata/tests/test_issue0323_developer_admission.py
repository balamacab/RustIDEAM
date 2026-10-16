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

    def test_unknown_channel_cannot_create_claim(self):
        r = reconcile(snapshot(issue(268), channel="unknown"))
        self.assertEqual(r["decision"], "BLOCKED")
        self.assertEqual(r["reason"], "write_channel_unverified")

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


if __name__ == "__main__":
    unittest.main()
