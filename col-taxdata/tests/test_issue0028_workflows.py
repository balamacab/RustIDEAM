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
