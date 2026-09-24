from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowStructureTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_required_ci_contexts_and_project_heavy_skip_are_durable(self):
        text = self.read("col-taxdata-ci.yml")
        for context in ("name: scope-policy", "name: project-invariants", "name: project-tests"):
            self.assertIn(context, text)
        self.assertIn("test_ci_*.py", text)
        self.assertIn("test_*.py", text)
        self.assertIn("run_heavy", text)
        self.assertNotIn("pull_request_target", text)

    def test_lifecycle_has_machine_merge_and_all_resume_states(self):
        text = self.read("col-taxdata-pr-lifecycle.yml")
        self.assertIn("workflow_run:", text)
        self.assertIn("merge_method=squash", text)
        self.assertIn("sha=", text)
        for state in (
            "CI_FAILED",
            "NEEDS_REBASE",
            "MERGE_CONFLICT",
            "SEMANTIC_REVALIDATION_REQUIRED",
        ):
            self.assertIn(state, text)
        self.assertNotIn("required_approving_review_count", text)

    def test_convergence_publishes_blocking_status_and_corrective_work(self):
        text = self.read("col-taxdata-convergence.yml")
        self.assertIn("col-taxdata-convergence", text)
        self.assertIn("state=failure", text)
        self.assertIn("integration.validation.required", text)
        self.assertIn("search/issues", text)

    def test_workflow_permissions_do_not_use_write_all(self):
        for path in WORKFLOWS.glob("col-taxdata-*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("write-all", text, path.name)
            self.assertNotIn("permissions: write", text, path.name)


if __name__ == "__main__":
    unittest.main()
