import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "automation" / "developer-backlog.json"
WORKERS = ROOT / "docs" / "scheduled-developer-workers.md"
SWARM = ROOT / "docs" / "scheduled-case-validation-swarm.md"


class DeveloperBacklogContractTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(BACKLOG.read_text(encoding="utf-8"))
        self.items = self.data["items"]

    def test_live_backlog_is_bounded_unique_and_prioritizes_p0(self):
        # The original ten low-complexity seed candidates are not a permanent
        # queue limit: #310 is a measured REST outage requiring a bounded,
        # explicit medium-complexity exception rather than a false low label.
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["kind"], "developer_backlog")
        self.assertGreaterEqual(len(self.items), 10)
        self.assertLessEqual(len(self.items), 12)
        issues = [item["issue"] for item in self.items]
        self.assertEqual(len(issues), len(set(issues)))
        self.assertEqual(issues[:2], [310, 304])
        self.assertEqual([item["priority"] for item in self.items[:2]], [0, 5])
        self.assertEqual(
            {item["issue"] for item in self.items if item["complexity"] == "medium"},
            {310},
        )
        self.assertTrue(
            all(item["complexity"] in {"low", "low-medium", "medium"}
                for item in self.items)
        )
        self.assertEqual(self.items[0]["depends_on"], [])
        self.assertEqual(self.items[0]["readiness"], "ready_if_live_eligible")
        self.assertEqual(self.items[1]["depends_on"], [58])
        priorities = [item["priority"] for item in self.items]
        self.assertEqual(priorities, sorted(priorities))

    def test_readiness_and_dependency_metadata_are_explicit(self):
        allowed = {"ready_if_live_eligible", "blocked_on_dependencies"}
        for item in self.items:
            self.assertIn(item["readiness"], allowed)
            self.assertIsInstance(item["depends_on"], list)
            self.assertTrue(all(isinstance(n, int) and n > 0 for n in item["depends_on"]))
            if item["readiness"] == "blocked_on_dependencies":
                self.assertTrue(item["depends_on"])

    def test_closed_or_retired_incident_work_is_not_seeded(self):
        issues = {item["issue"] for item in self.items}
        self.assertTrue({5, 8, 142, 168, 221}.isdisjoint(issues))

    def test_worker_contract_uses_live_filter_and_orphan_safe_attempts(self):
        text = WORKERS.read_text(encoding="utf-8")
        self.assertIn("automation/developer-backlog.json", text)
        self.assertIn("discard entries whose issue is CLOSED", text)
        self.assertIn("attempt = 1 + max(K observed in either source)", text)
        self.assertGreaterEqual(text.count("ORPHAN_NOOP"), 2)
        self.assertIn("continue to the next safe backlog item", text)

    def test_recovery_first_admission_contract_prevents_orphan_retry_storm(self):
        text = WORKERS.read_text(encoding="utf-8")
        for invariant in (
            "CONTROLLER_EXPLICIT_RECOVERY",
            "DEV-1",
            "DEV-2",
            "DEV-A",
            "DEV-B",
            "Read-after-write confirmation",
            "attempt = 1 + max(K observed in either source)",
            "ORPHAN_NOOP",
            "persistent comment-write denial",
            "ADMISSION_BLOCKED",
            "CONTRACT_DRIFT",
            "429 / 5xx",
            "no product edits",
            "Do not create yet another no-op branch",
            "GitHub through Morichal",
        ):
            self.assertIn(invariant, text)
        # The contract must distinguish a verified Controller handoff from
        # Controller-authored implementation and from a no-op branch.
        self.assertIn(
            "Controller-written code is attributed to Controller", text
        )
        self.assertIn(
            "The first successful branch creation is **provisional**", text
        )
        self.assertIn(
            "same-branch comment retry", text
        )

    def test_swarm_contract_does_not_use_case_blockers_as_dispatch_queue(self):
        text = SWARM.read_text(encoding="utf-8")
        self.assertIn("automation/developer-backlog.json", text)
        self.assertIn("Cached case-pool status alone is never a dispatch queue", text)

    def test_policy_is_explicitly_live_authoritative(self):
        policy = self.data["policy"]
        self.assertIn("GitHub live state is authoritative", policy["authority"])
        self.assertEqual(policy["tester_case_blockers"], "context_only_not_developer_dispatch")
        self.assertEqual(
            policy["claim_attempt"],
            "1 + max(K observed in claim branches or machine-readable claim records)",
        )
        self.assertIn("never reused", policy["orphan_noop"])


if __name__ == "__main__":
    unittest.main()
