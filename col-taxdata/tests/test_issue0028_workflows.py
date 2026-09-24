from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowStructureTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_ci_exposes_stable_required_gate_and_skips_heavy_when_unrelated(self):
        text = self.read("col-taxdata-ci.yml")
        self.assertIn("name: CI Gate", text)
        self.assertIn("run_heavy", text)
        self.assertIn("if: needs.policy.outputs.applicable == 'true' && needs.policy.outputs.run_heavy == 'true'", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("  pull_request:\n", text)

    def test_dispatched_revalidation_reenters_lifecycle_from_trusted_main(self):
        text = self.read("col-taxdata-ci.yml")
        self.assertIn("name: Complete dispatched lifecycle", text)
        self.assertIn(
            "if: needs.gate.result == 'success' && needs.policy.outputs.applicable == 'true'",
            text,
        )
        self.assertIn("pr_number: ${{ steps.resolve.outputs.pr_number }}", text)
        self.assertIn("head_sha: ${{ steps.resolve.outputs.head_sha }}", text)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", text)
        self.assertIn("path: trusted", text)
        self.assertIn("path: candidate", text)
        self.assertIn("ref: ${{ steps.resolve.outputs.head_sha }}", text)
        self.assertIn("python3 trusted/col-taxdata/ci/policy.py", text)
        self.assertIn("CI_HEAD_SHA: ${{ needs.policy.outputs.head_sha }}", text)
        self.assertIn("--ci-conclusion success", text)
        self.assertIn("--ci-head-sha \"$CI_HEAD_SHA\"", text)
        self.assertIn("contents: write", text)
        self.assertIn("issues: write", text)
        self.assertIn("pull-requests: write", text)

    def test_pull_request_target_never_checks_out_pr_code(self):
        text = self.read("col-taxdata-pr-lifecycle.yml")
        self.assertIn("pull_request_target:", text)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", text)
        self.assertNotIn("github.event.pull_request.head", text)
        self.assertNotIn("write-all", text)

    def test_convergence_publishes_commit_status_and_corrective_path(self):
        text = self.read("col-taxdata-convergence.yml")
        self.assertIn("repository_dispatch:", text)
        self.assertIn("types: [col-taxdata-convergence]", text)
        self.assertIn("statuses: write", text)
        self.assertIn("name: Convergence Gate", text)

    def test_required_workflows_do_not_hide_failures(self):
        for path in WORKFLOWS.glob("col-taxdata-*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("|| true", text, path.name)
            self.assertNotIn("continue-on-error: true", text, path.name)


if __name__ == "__main__":
    unittest.main()
