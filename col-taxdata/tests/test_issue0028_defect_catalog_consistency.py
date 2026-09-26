from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))

import defect_catalog  # noqa: E402


DEF0013_FILENAME = "DEF-0013-issue67-runtime-envelope-drift.md"
DEF0013_TITLE = "Issue #67 canonical runtime envelope drift"
DEF0013_ROW = (
    f"| [DEF-0013]({DEF0013_FILENAME}) | P2 | {DEF0013_TITLE} | "
    "[#92](https://github.com/balamacab/RustIDEAM/issues/92) | verified |"
)


class DefectCatalogConsistencyTests(unittest.TestCase):
    """Issue #114 regression coverage in the always-run repository-control family."""

    def _fixture(
        self,
        *,
        defect_rows: list[str] | None = None,
        spec_status: str = "verified",
        spec_id: str = "DEF-0013",
    ) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        defects = root / "specs" / "defects"
        defects.mkdir(parents=True)
        (root / "specs" / "gaps").mkdir(parents=True)

        (root / "specs" / "manifest.yaml").write_text(
            """version: 1
project: col-taxdata
items:
  - id: DEF-0013
    type: defect
    priority: P2
    status: verified
    area: validation
    spec: specs/defects/DEF-0013-issue67-runtime-envelope-drift.md
    github_issue: 92
    depends_on: []

  - id: GAP-0001
    type: coverage-gap
    priority: P2
    status: specified
    area: corpus-coverage
    spec: specs/gaps/GAP-0001-referenced-documents-outside-current-corpus.md
    github_issue: 8
    depends_on: []
implementation_order:
  - DEF-0013
""",
            encoding="utf-8",
        )
        (defects / DEF0013_FILENAME).write_text(
            f"# {spec_id} — {DEF0013_TITLE}\n\n"
            f"Status: {spec_status}  \n"
            "Priority: P2  \n"
            "GitHub issue: #92  \n",
            encoding="utf-8",
        )
        rows = defect_rows if defect_rows is not None else [DEF0013_ROW]
        (defects / "README.md").write_text(
            "# Defect index\n\n"
            "| ID | Priority | Title | GitHub | Status |\n"
            "|---|---|---|---|---|\n"
            + "".join(f"{row}\n" for row in rows),
            encoding="utf-8",
        )
        return temp, root

    def test_current_catalog_passes_and_def0013_row_is_exact(self) -> None:
        self.assertEqual(defect_catalog.validate_defect_catalog(ROOT), [])
        rows = defect_catalog.parse_index_rows(
            (ROOT / "specs" / "defects" / "README.md").read_text(encoding="utf-8")
        )
        def0013 = [row for row in rows if row.item_id == "DEF-0013"]
        self.assertEqual(len(def0013), 1)
        row = def0013[0]
        self.assertEqual(row.spec_link, DEF0013_FILENAME)
        self.assertEqual(row.priority, "P2")
        self.assertEqual(row.title, DEF0013_TITLE)
        self.assertEqual(
            row.github,
            "[#92](https://github.com/balamacab/RustIDEAM/issues/92)",
        )
        self.assertEqual(row.status, "verified")

    def test_manifest_defect_missing_from_readme_fails(self) -> None:
        temp, root = self._fixture(defect_rows=[])
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("DEF-0013" in error and "found 0" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_duplicate_defect_row_fails(self) -> None:
        temp, root = self._fixture(defect_rows=[DEF0013_ROW, DEF0013_ROW])
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("DEF-0013" in error and "found 2" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_wrong_spec_link_fails(self) -> None:
        wrong = DEF0013_ROW.replace(DEF0013_FILENAME, "DEF-0013-wrong.md")
        temp, root = self._fixture(defect_rows=[wrong])
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("does not resolve to manifest spec" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_index_status_disagreement_fails(self) -> None:
        wrong = DEF0013_ROW.replace("| verified |", "| specified |")
        temp, root = self._fixture(defect_rows=[wrong])
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("index status" in error and "does not match" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_spec_status_disagreement_fails(self) -> None:
        temp, root = self._fixture(spec_status="specified")
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("spec status" in error and "does not match" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_spec_header_identity_disagreement_fails(self) -> None:
        temp, root = self._fixture(spec_id="DEF-9999")
        try:
            errors = defect_catalog.validate_defect_catalog(root)
            self.assertTrue(
                any("spec header id is DEF-9999" in error for error in errors),
                errors,
            )
        finally:
            temp.cleanup()

    def test_coverage_gap_is_not_required_in_defect_index(self) -> None:
        temp, root = self._fixture()
        try:
            self.assertEqual(defect_catalog.validate_defect_catalog(root), [])
        finally:
            temp.cleanup()

    def test_manifest_remains_parseable_for_catalog_check(self) -> None:
        items = defect_catalog.parse_manifest_items(
            (ROOT / "specs" / "manifest.yaml").read_text(encoding="utf-8")
        )
        by_id = {item.item_id: item for item in items}
        self.assertEqual(by_id["DEF-0013"].item_type, "defect")
        self.assertEqual(by_id["DEF-0013"].status, "verified")
        self.assertEqual(by_id["GAP-0001"].item_type, "coverage-gap")


if __name__ == "__main__":
    unittest.main()
