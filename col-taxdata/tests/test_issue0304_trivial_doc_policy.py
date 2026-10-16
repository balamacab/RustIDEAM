from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))
import policy  # noqa: E402


class TrivialReasonPolicyTests(unittest.TestCase):
    def check(self, source: str, expected: list[str], *, module: str = "one.py") -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            (root / "base.txt").write_text("baseline")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            rel = f"col-taxdata/tools/{module}"
            target = root / rel
            target.parent.mkdir(parents=True)
            target.write_text(source)
            violations = policy.documentation_policy_violations(root, base, [("A", [rel])])
            self.assertEqual(violations, sorted([f"{rel}:{part}" for part in expected]))

    def test_reasoned_trivial_delegate_is_allowed(self):
        self.check("# doc-policy: trivial - delegates unchanged to adapter\ndef adapter_passthrough(v):\n    return delegate(v)\n", [])

    def test_reasoned_getter_and_decorated_method_are_allowed(self):
        self.check('''"""Documented module."""
class Example:
    """Documented public class."""
    # doc-policy: trivial - expose unchanged stored value
    @property
    def value(self):
        return self._value
''', [])

    def test_empty_or_malformed_reason_is_rejected(self):
        for marker in ("# doc-policy: trivial - ", "# doc-policy: trivial", "# doc-policy: trivial -   ", "# doc-policy: none - exempt"):
            with self.subTest(marker=marker):
                self.check(f"{marker}\ndef f():\n    return 1\n", [
                    "f: trivial suppression needs a non-empty reason",
                    "f: missing docstring for new/modified public function"
                ])

    def test_nontrivial_computation_cannot_be_suppressed(self):
        self.check("# doc-policy: trivial - allegedly simple\ndef calculate(v):\n    return v + 1\n", [
            "calculate: trivial suppression cannot exempt non-trivial implementation",
            "calculate: missing docstring for new/modified public function"
        ])

    def test_class_and_substantial_module_cannot_be_exempted(self):
        self.check('''# doc-policy: trivial - allegedly exempt class
class Example:
    # doc-policy: trivial - unchanged value
    def value(self):
        return 1
''', [
            "Example: trivial suppression cannot exempt a class",
            "Example: missing docstring for new/modified public class",
            " missing module docstring for new substantial production module",
        ])

    def test_regular_undocumented_function_still_rejected(self):
        self.check("def calculate(v):\n    return v * 2\n", [
            "calculate: missing docstring for new/modified public function"
        ])

    def test_misplaced_marker_does_not_suppress(self):
        self.check("# doc-policy: trivial - old unrelated line\n\ndef f():\n    return 1\n", [
            "f: missing docstring for new/modified public function"
        ])


if __name__ == "__main__":
    unittest.main()
