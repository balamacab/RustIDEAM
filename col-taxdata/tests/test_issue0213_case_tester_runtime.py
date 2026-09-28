from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Issue0213CaseTesterRuntimeTests(unittest.TestCase):
    def test_case_tester_dependencies_are_exactly_pinned(self):
        lines = [
            line.strip()
            for line in (ROOT / "requirements-case-tester.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            lines,
            [
                "PyYAML==6.0.2",
                "jsonschema==4.23.0",
                "requests==2.32.3",
            ],
        )

    def test_default_runtime_and_case_tester_targets_are_separate(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM base AS case-tester", dockerfile)
        self.assertIn("FROM base AS runtime", dockerfile)
        self.assertLess(
            dockerfile.index("FROM base AS case-tester"),
            dockerfile.index("FROM base AS runtime"),
        )
        self.assertIn("-r requirements-case-tester.txt", dockerfile)

    def test_compose_uses_runtime_target_for_normal_service(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("  taxdata:\n", compose)
        self.assertIn("      target: runtime\n", compose)
        self.assertIn("  case-tester:\n", compose)
        self.assertIn("      target: case-tester\n", compose)
        self.assertIn("    image: col-taxdata-case-tester:local\n", compose)

    def test_preflight_contract_is_importable_without_harness_dependencies(self):
        path = ROOT / "tools" / "case_tester_preflight.py"
        spec = importlib.util.spec_from_file_location("case_tester_preflight", path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.EXPECTED_CASE_CONTRACT, "4.0.0")
        self.assertEqual(module.EXPECTED_REST_CONTRACT, "1.0.0")
        self.assertEqual(module.EXPECTED_REST_ENDPOINT, "/v1/cases")
        self.assertEqual(
            module.REQUIRED_MODULES,
            {
                "yaml": "PyYAML",
                "jsonschema": "jsonschema",
                "requests": "requests",
            },
        )


if __name__ == "__main__":
    unittest.main()
