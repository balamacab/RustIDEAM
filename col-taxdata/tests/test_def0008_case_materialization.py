from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from rematerialize_case import refresh_case_materializations
from validate_case_bundle import validate_case


NOW = "2026-09-24T00:00:00+00:00"
RAW_SHA = "a" * 64


class Def0008CaseMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "test.sqlite"
        self.case_dir = root / "CASE-TEST"
        (self.case_dir / "sources").mkdir(parents=True)
        (self.case_dir / "unresolved.json").write_text(
            '{"items": []}\n',
            encoding="utf-8",
        )
        self._apply_all_migrations()
        self._seed_case()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apply_all_migrations(self) -> None:
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def _seed_case(self) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (
                    'DOC-TEST', 'CO', 'DIAN', 'DECRETO', 'Documento de prueba',
                    NULL, NULL, ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (
                    'SRC-TEST', 'https://example.test/decreto.htm', 'DIAN',
                    'normograma_html', NULL, ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (
                    'MAN-TEST', 'DOC-TEST', 'SRC-TEST', 'text/html',
                    ?, 12, ?, 'raw/test.html', 'test'
                )
                """,
                (RAW_SHA, NOW),
            )
            con.execute(
                """
                INSERT INTO cases(
                    case_id, title, query_text, as_of_date, status,
                    created_at, updated_at
                ) VALUES (
                    'CASE-TEST', 'Caso de prueba', 'Consulta', '2026-09-24',
                    'open', ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO claims(
                    claim_id, subject_type, subject_id, predicate,
                    object_type, object_id, object_literal, claim_type, status,
                    extraction_method, confidence_extraction,
                    requires_human_review, created_at
                ) VALUES (
                    'CLM-TEST', 'case', 'CASE-TEST', 'conclusion',
                    'literal', NULL, 'Conclusión soportada',
                    'case_legal_conclusion', 'validated', 'test', 1.0, 0, ?
                )
                """,
                (NOW,),
            )
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, exact_quote,
                    source_url, source_sha256, retrieved_at, extraction_method,
                    extractor_version, confidence, review_status
                ) VALUES (
                    'EVD-OLD', 'CLM-TEST', 'MAN-TEST', 'Soporte del claim',
                    'https://example.test/decreto.htm', ?, ?, 'test', '1',
                    1.0, 'validated'
                )
                """,
                (RAW_SHA, NOW),
            )
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, exact_quote,
                    source_url, source_sha256, retrieved_at, extraction_method,
                    extractor_version, confidence, review_status
                ) VALUES (
                    'EVD-NEW', NULL, 'MAN-TEST', 'Soporte de la relación',
                    'https://example.test/decreto.htm', ?, ?, 'test', '2',
                    1.0, 'validated'
                )
                """,
                (RAW_SHA, NOW),
            )
            con.execute(
                """
                INSERT INTO relationships(
                    relationship_id, source_type, source_id, relation_type,
                    target_type, target_id, scope, asserted_date,
                    effective_date, end_date, status, evidence_id, confidence,
                    requires_human_review
                ) VALUES (
                    'REL-TEST', 'document', 'DOC-TEST', 'modifies',
                    'document', 'DOC-TEST', NULL, NULL, NULL, NULL,
                    'validated', 'EVD-OLD', 1.0, 0
                )
                """
            )
            for item_type, item_id in (
                ("claim", "CLM-TEST"),
                ("relationship", "REL-TEST"),
                ("source", "SRC-TEST"),
            ):
                con.execute(
                    """
                    INSERT INTO case_items(
                        case_id, item_type, item_id, relevance, added_at
                    ) VALUES ('CASE-TEST', ?, ?, 'test', ?)
                    """,
                    (item_type, item_id, NOW),
                )
            con.commit()
            refresh_case_materializations(
                con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
                write=True,
            )
        finally:
            con.close()

    def test_existing_healthy_case_validation_is_preserved(self):
        con = sqlite3.connect(self.db)
        try:
            result = validate_case(
                con=con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
            )
        finally:
            con.close()

        self.assertTrue(result["valid"])
        self.assertTrue(result["manifest_matches_sqlite"])
        self.assertTrue(result["source_manifest_matches_materializer"])
        self.assertTrue(result["report_matches_materializer"])

    def test_source_kind_drift_is_detected_with_same_source_ids(self):
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE sources SET source_kind='decreto' WHERE source_id='SRC-TEST'"
            )
            con.commit()
            result = validate_case(
                con=con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
            )
        finally:
            con.close()

        self.assertTrue(result["manifest_matches_sqlite"])
        self.assertFalse(result["source_manifest_matches_materializer"])
        self.assertFalse(result["report_matches_materializer"])
        self.assertIn(
            "source_manifest_not_materialized_from_canonical_state",
            result["errors"],
        )

    def test_report_is_stale_when_relationship_evidence_changes_only(self):
        report_before = (self.case_dir / "report.md").read_text(encoding="utf-8")
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                UPDATE relationships
                SET evidence_id='EVD-NEW'
                WHERE relationship_id='REL-TEST'
                """
            )
            con.commit()
            claim_count = con.execute(
                "SELECT COUNT(*) FROM claims WHERE claim_id='CLM-TEST'"
            ).fetchone()[0]
            result = validate_case(
                con=con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
            )
        finally:
            con.close()

        self.assertEqual(claim_count, 1)
        self.assertTrue(result["source_manifest_matches_materializer"])
        self.assertFalse(result["report_matches_materializer"])
        self.assertIn(
            "report_not_materialized_from_canonical_state",
            result["errors"],
        )
        self.assertEqual(
            report_before,
            (self.case_dir / "report.md").read_text(encoding="utf-8"),
        )

    def test_preview_refresh_and_second_refresh_are_deterministic(self):
        manifest_path = self.case_dir / "sources" / "manifest.json"
        report_path = self.case_dir / "report.md"
        before_files = (
            manifest_path.read_bytes(),
            report_path.read_bytes(),
        )

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE sources SET source_kind='decreto' WHERE source_id='SRC-TEST'"
            )
            con.execute(
                """
                UPDATE relationships
                SET evidence_id='EVD-NEW'
                WHERE relationship_id='REL-TEST'
                """
            )
            con.commit()
            raw_sha_before = con.execute(
                """
                SELECT sha256 FROM manifestations
                WHERE manifestation_id='MAN-TEST'
                """
            ).fetchone()[0]

            preview = refresh_case_materializations(
                con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
                write=False,
                include_diff=True,
            )
            self.assertEqual(preview["mode"], "preview")
            self.assertEqual(preview["updated_count"], 0)
            self.assertEqual(preview["before"]["stale_count"], 2)
            self.assertEqual(preview["before"]["would_write_count"], 2)
            self.assertTrue(
                all(
                    artifact.get("diff")
                    for artifact in preview["before"]["artifacts"]
                )
            )
            self.assertEqual(
                before_files,
                (manifest_path.read_bytes(), report_path.read_bytes()),
            )

            applied = refresh_case_materializations(
                con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
                write=True,
            )
            self.assertEqual(applied["updated_count"], 2)
            self.assertEqual(applied["after"]["would_write_count"], 0)

            validated = validate_case(
                con=con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
            )
            self.assertTrue(validated["valid"])
            self.assertIn('"type": "decreto"', manifest_path.read_text(encoding="utf-8"))
            self.assertIn("EVD-NEW", report_path.read_text(encoding="utf-8"))

            files_after_first_write = (
                manifest_path.read_bytes(),
                report_path.read_bytes(),
            )
            second = refresh_case_materializations(
                con,
                case_id="CASE-TEST",
                case_dir=self.case_dir,
                write=True,
            )
            self.assertEqual(second["updated_count"], 0)
            self.assertEqual(second["after"]["would_write_count"], 0)
            self.assertEqual(
                files_after_first_write,
                (manifest_path.read_bytes(), report_path.read_bytes()),
            )
            raw_sha_after = con.execute(
                """
                SELECT sha256 FROM manifestations
                WHERE manifestation_id='MAN-TEST'
                """
            ).fetchone()[0]
        finally:
            con.close()

        self.assertEqual(raw_sha_before, raw_sha_after)


if __name__ == "__main__":
    unittest.main()
