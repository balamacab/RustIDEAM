from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))

from repository_governance import (
    REQUIRED_CHECKS,
    desired_repository_settings,
    desired_ruleset,
)


class GovernanceTests(unittest.TestCase):
    def test_main_ruleset_requires_pr_zero_human_approvals_and_strict_checks(self):
        ruleset = desired_ruleset()
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        rules = {rule["type"]: rule for rule in ruleset["rules"]}
        self.assertIn("non_fast_forward", rules)
        self.assertEqual(
            rules["pull_request"]["parameters"]["required_approving_review_count"], 0
        )
        statuses = rules["required_status_checks"]["parameters"]
        self.assertTrue(statuses["strict_required_status_checks_policy"])
        self.assertEqual(
            [entry["context"] for entry in statuses["required_status_checks"]],
            list(REQUIRED_CHECKS),
        )
        self.assertEqual(ruleset["bypass_actors"], [])

    def test_repository_uses_deterministic_squash_and_branch_cleanup(self):
        settings = desired_repository_settings()
        self.assertTrue(settings["allow_squash_merge"])
        self.assertFalse(settings["allow_merge_commit"])
        self.assertFalse(settings["allow_rebase_merge"])
        self.assertTrue(settings["delete_branch_on_merge"])


if __name__ == "__main__":
    unittest.main()
