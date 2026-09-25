from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_DIR))
import policy  # noqa: E402


def metadata_body(issue: int = 28) -> str:
    metadata = {
        "base_sha": "1" * 40,
        "parallel_safe": False,
        "semantic_domains": ["repository-automation"],
        "likely_touched": ["col-taxdata/ci/**"],
        "depends_on": [],
    }
    return f"Fixes #{issue}\n\n<!-- col-taxdata-agent-metadata: {json.dumps(metadata)} -->"


class PolicyTests(unittest.TestCase):
    def test_metadata_and_issue_are_deterministic(self):
        body = metadata_body()
        self.assertEqual(policy.closing_issue_number(body), 28)
        self.assertEqual(policy.parse_metadata(body)["semantic_domains"], ["repository-automation"])
        policy.validate_branch("agent/issue-28-autonomous-ci", 28)

    def test_branch_issue_mismatch_fails(self):
        with self.assertRaises(policy.PolicyError):
            policy.validate_branch("agent/issue-27-autonomous-ci", 28)

    def test_scope_rejects_unrelated_project(self):
        issue = "Writable-scope exception: `.github/workflows/` and `.github/actions/`."
        bad = policy.validate_scope(["col-taxdata/ci/policy.py", "other-project/app.py"], issue)
        self.assertEqual(bad, ["other-project/app.py"])

    def test_global_scope_requires_explicit_issue_authorization(self):
        path = ".github/workflows/col-taxdata-ci.yml"
        self.assertEqual(policy.validate_scope([path], "ordinary issue"), [path])
        issue = "## Writable-scope exception\n`.github/workflows/` is explicitly authorized."
        self.assertEqual(policy.validate_scope([path], issue), [])

    def test_only_dedicated_global_automation_is_allowed(self):
        issue = "Writable-scope exception: `.github/workflows/` and `.github/actions/`."
        bad = policy.validate_scope([".github/workflows/unrelated.yml"], issue)
        self.assertEqual(bad, [".github/workflows/unrelated.yml"])

    def test_migration_addition_allowed_but_mutation_rejected(self):
        added = [("A", ["col-taxdata/schema/015_new.sql"])]
        modified = [("M", ["col-taxdata/schema/014_temporal_candidates.sql"])]
        self.assertEqual(policy.validate_migration_immutability(added), [])
        self.assertTrue(policy.validate_migration_immutability(modified))

    def test_controller_memory_sessions_are_append_only(self):
        added = [("A", ["col-taxdata/controller-memory/sessions/C260925T181700Z00.cm"])]
        modified = [("M", ["col-taxdata/controller-memory/sessions/C260925T181700Z00.cm"])]
        deleted = [("D", ["col-taxdata/controller-memory/sessions/C260925T181700Z00.cm"])]
        renamed = [
            (
                "R100",
                [
                    "col-taxdata/controller-memory/sessions/C260925T181700Z00.cm",
                    "col-taxdata/controller-memory/sessions/C260925T181800Z00.cm",
                ],
            )
        ]
        self.assertEqual(policy.validate_controller_session_immutability(added), [])
        self.assertTrue(policy.validate_controller_session_immutability(modified))
        self.assertTrue(policy.validate_controller_session_immutability(deleted))
        self.assertEqual(len(policy.validate_controller_session_immutability(renamed)), 2)

    def test_controller_memory_index_remains_rebuildable(self):
        changed = [("M", ["col-taxdata/controller-memory/INDEX.cm"])]
        self.assertEqual(policy.validate_controller_session_immutability(changed), [])

    def test_runtime_database_and_raw_artifacts_are_rejected(self):
        paths = [
            "col-taxdata/data/state/taxdata.sqlite",
            "col-taxdata/tests/fixture.db",
            "col-taxdata/raw/source.html",
        ]
        self.assertEqual(policy.forbidden_artifacts(paths), paths)

    def test_likely_touched_metadata_must_cover_actual_diff(self):
        paths = ["col-taxdata/ci/policy.py", ".github/workflows/col-taxdata-ci.yml"]
        declared = ["col-taxdata/ci/**", ".github/workflows/col-taxdata-*.yml"]
        self.assertEqual(policy.undeclared_paths(paths, declared), [])
        self.assertEqual(policy.undeclared_paths(paths, ["col-taxdata/docs/**"]), paths)

    def test_new_migrations_must_be_contiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            schema = root / "col-taxdata" / "schema"
            schema.mkdir(parents=True)
            (schema / "001_initial.sql").write_text("select 1;\n", encoding="utf-8")
            (schema / "002_second.sql").write_text("select 2;\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            good = [("A", ["col-taxdata/schema/003_next.sql"])]
            bad = [("A", ["col-taxdata/schema/004_skip.sql"])]
            self.assertEqual(policy.migration_sequence_violations(root, base, good), [])
            self.assertTrue(policy.migration_sequence_violations(root, base, bad))

    def test_unrelated_pr_skips_col_taxdata_heavy_ci(self):
        self.assertEqual(policy.classify_paths(["another-project/README.md"]), (False, False))
        self.assertEqual(policy.classify_paths(["col-taxdata/docs/note.md"]), (True, False))
        self.assertEqual(policy.classify_paths(["col-taxdata/tools/x.py"]), (True, True))

    def test_high_confidence_secret_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "col-taxdata" / "x.txt"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("credential=" + "ghp_" + "A" * 36, encoding="utf-8")
            findings = policy.scan_secrets(root, ["col-taxdata/x.txt"])
            self.assertEqual(findings, ["col-taxdata/x.txt:github-token"])


if __name__ == "__main__":
    unittest.main()
