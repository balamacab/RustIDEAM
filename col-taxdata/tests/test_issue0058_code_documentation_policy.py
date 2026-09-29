from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_DIR))
import policy  # noqa: E402


def init_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    marker = root / "marker.txt"
    marker.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


class DocumentationPolicyTests(unittest.TestCase):
    def test_new_public_function_without_docstring_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tools/new_module.py"
            write(root, rel, "def public_api():\n    return 1\n")
            violations = policy.documentation_policy_violations(root, base, [("A", [rel])])
            self.assertEqual(
                violations,
                [f"{rel}:public_api: missing docstring for new/modified public function"],
            )

    def test_documented_public_function_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tools/new_module.py"
            write(
                root,
                rel,
                'def public_api():\n    """Return the stable public value."""\n    return 1\n',
            )
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("A", [rel])]),
                [],
            )

    def test_private_helper_is_not_mechanically_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tools/private_only.py"
            write(root, rel, "def _helper():\n    return 1\n")
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("A", [rel])]),
                [],
            )

    def test_tests_are_exempt_from_production_docstring_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tests/test_example.py"
            write(root, rel, "def public_named_test_helper():\n    return 1\n")
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("A", [rel])]),
                [],
            )

    def test_untouched_legacy_public_debt_does_not_block_private_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "col-taxdata/tools/legacy.py"
            write(
                root,
                rel,
                "def legacy_public():\n    return 1\n\n\ndef _helper():\n    return 1\n",
            )
            base = init_repo(root)
            write(
                root,
                rel,
                "def legacy_public():\n    return 1\n\n\ndef _helper():\n    return 2\n",
            )
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("M", [rel])]),
                [],
            )

    def test_modified_legacy_public_function_becomes_subject_to_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "col-taxdata/tools/legacy.py"
            write(root, rel, "def legacy_public():\n    return 1\n")
            base = init_repo(root)
            write(root, rel, "def legacy_public():\n    return 2\n")
            violations = policy.documentation_policy_violations(root, base, [("M", [rel])])
            self.assertEqual(
                violations,
                [f"{rel}:legacy_public: missing docstring for new/modified public function"],
            )

    def test_new_substantial_module_requires_module_docstring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tools/substantial.py"
            write(
                root,
                rel,
                'def first():\n    """First operation."""\n    return 1\n\n'
                'def second():\n    """Second operation."""\n    return 2\n',
            )
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("A", [rel])]),
                [f"{rel}: missing module docstring for new substantial production module"],
            )

    def test_substantial_module_with_module_docstring_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            rel = "col-taxdata/tools/substantial.py"
            write(
                root,
                rel,
                '"""Operations for the example production boundary."""\n\n'
                'def first():\n    """First operation."""\n    return 1\n\n'
                'def second():\n    """Second operation."""\n    return 2\n',
            )
            self.assertEqual(
                policy.documentation_policy_violations(root, base, [("A", [rel])]),
                [],
            )

    def test_pure_rename_preserves_legacy_transition_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = "col-taxdata/tools/legacy_name.py"
            new = "col-taxdata/tools/renamed.py"
            write(root, old, "def legacy_public():\n    return 1\n")
            base = init_repo(root)
            (root / old).rename(root / new)
            self.assertEqual(
                policy.documentation_policy_violations(
                    root,
                    base,
                    [("R100", [old, new])],
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
