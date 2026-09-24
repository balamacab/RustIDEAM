from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_DIR))
import convergence  # noqa: E402
import repository_governance  # noqa: E402


def body(domains):
    metadata = {
        "base_sha": "1" * 40,
        "parallel_safe": False,
        "semantic_domains": domains,
        "likely_touched": ["col-taxdata/**"],
        "depends_on": [],
    }
    return "Fixes #1\n<!-- col-taxdata-agent-metadata: " + json.dumps(metadata) + " -->"


class GovernanceTests(unittest.TestCase):
    def test_desired_ruleset_has_pr_only_zero_approval_strict_ci(self):
        ruleset = repository_governance.desired_ruleset()
        self.assertEqual(repository_governance.verify_ruleset(ruleset), [])
        self.assertEqual(ruleset["bypass_actors"], [])

    def test_ruleset_verifier_detects_weakened_status_policy(self):
        ruleset = repository_governance.desired_ruleset()
        status = next(r for r in ruleset["rules"] if r["type"] == "required_status_checks")
        status["parameters"]["strict_required_status_checks_policy"] = False
        self.assertIn("required status checks are not strict/current-base", repository_governance.verify_ruleset(ruleset))

    def test_semantic_overlap_is_detected(self):
        prs = [
            {"number": 10, "merged_at": "2026-09-23T00:00:00Z", "body": body(["document-identity", "ci-governance"])},
            {"number": 11, "merged_at": "2026-09-23T00:01:00Z", "body": body(["unrelated-domain"])},
        ]
        overlap = convergence.overlap_with_prs(["ci-governance"], prs, current_pr=12)
        self.assertEqual(overlap, [{"pr_number": 10, "semantic_domains": ["ci-governance"]}])

    def test_unmerged_pr_does_not_count_as_overlap(self):
        prs = [{"number": 10, "merged_at": None, "body": body(["ci-governance"])}]
        self.assertEqual(convergence.overlap_with_prs(["ci-governance"], prs, current_pr=12), [])


if __name__ == "__main__":
    unittest.main()
