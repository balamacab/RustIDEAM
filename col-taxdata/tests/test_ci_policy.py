from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))

from policy import (
    PolicyError,
    issue_authorizes_global_automation,
    parse_metadata,
    validate_issue_linkage,
    validate_migration_immutability,
    validate_runtime_artifacts,
    validate_scope,
)


BASE_SHA = "1" * 40


def body(metadata: dict) -> str:
    return (
        "Fixes #28\n\n"
        "<!-- agent-execution:"
        + json.dumps(metadata, separators=(",", ":"))
        + " -->"
    )


def metadata(**overrides) -> dict:
    value = {
        "base_sha": BASE_SHA,
        "parallel_safe": False,
        "semantic_domains": ["repository-automation"],
        "likely_touched": ["col-taxdata/**"],
        "depends_on": [],
    }
    value.update(overrides)
    return value


class PolicyPureTests(unittest.TestCase):
    def test_metadata_and_issue_branch_linkage(self):
        parsed = parse_metadata(body(metadata()))
        self.assertFalse(parsed["parallel_safe"])
        self.assertEqual(
            validate_issue_linkage("agent/issue-28-autonomous-ci", body(metadata())),
            28,
        )

    def test_wrong_closing_issue_rejected(self):
        with self.assertRaises(PolicyError):
            validate_issue_linkage(
                "agent/issue-28-autonomous-ci",
                body(metadata()).replace("Fixes #28", "Fixes #27"),
            )

    def test_global_paths_require_explicit_issue_authority(self):
        meta = metadata(likely_touched=[".github/workflows/**"])
        with self.assertRaises(PolicyError):
            validate_scope([".github/workflows/x.yml"], meta, "ordinary project issue")
        authority = (
            "Writable scope explicitly authorizes .github/workflows/ "
            "and .github/actions/ for repository automation."
        )
        validate_scope([".github/workflows/x.yml"], meta, authority)
        self.assertTrue(issue_authorizes_global_automation(authority))

    def test_unrelated_repository_path_rejected_even_when_declared(self):
        meta = metadata(likely_touched=["docs/**"])
        with self.assertRaises(PolicyError):
            validate_scope(["docs/unrelated.md"], meta, "allowed")

    def test_changed_path_must_be_declared_in_metadata(self):
        with self.assertRaises(PolicyError):
            validate_scope(
                ["col-taxdata/ci/policy.py"],
                metadata(likely_touched=["col-taxdata/docs/**"]),
                "",
            )

    def test_runtime_database_and_raw_evidence_rejected(self):
        for path in (
            "col-taxdata/data/corpus.sqlite",
            "col-taxdata/raw/source.html",
            "col-taxdata/cache/test.db",
        ):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                validate_runtime_artifacts([path])


class MigrationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        schema = self.root / "col-taxdata" / "schema"
        schema.mkdir(parents=True)
        (schema / "001_initial.sql").write_text("select 1;\n")
        (schema / "002_fetches.sql").write_text("select 2;\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)
        self.base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, message="change"):
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=self.root, check=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()

    def test_existing_migration_edit_is_rejected(self):
        path = self.root / "col-taxdata" / "schema" / "001_initial.sql"
        path.write_text("select 999;\n")
        head = self._commit()
        with self.assertRaises(PolicyError):
            validate_migration_immutability(self.root, self.base, head)

    def test_next_contiguous_migration_is_allowed(self):
        path = self.root / "col-taxdata" / "schema" / "003_next.sql"
        path.write_text("select 3;\n")
        head = self._commit()
        validate_migration_immutability(self.root, self.base, head)

    def test_skipped_migration_number_is_rejected(self):
        path = self.root / "col-taxdata" / "schema" / "004_skip.sql"
        path.write_text("select 4;\n")
        head = self._commit()
        with self.assertRaises(PolicyError):
            validate_migration_immutability(self.root, self.base, head)


if __name__ == "__main__":
    unittest.main()
