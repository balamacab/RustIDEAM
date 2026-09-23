from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from promote_operational_relationships import promote as promote_operational
from register_dian_doctrine import register_doctrine
from register_document_identity import register_document_identity
from reprocess_supported_document_families import reprocess
from resolve_references import RESOLUTION_METHOD


NOW = "2026-09-22T00:00:00+00:00"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"


class Def0003DocumentFamilyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fixture(
        self,
        filename: str,
        segments: list[tuple[str, str]],
        *,
        document_id: str | None = None,
    ) -> tuple[str, str]:
        source_url = BASE + filename
        token = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        source_id = "SRC-" + token
        manifestation_id = "MAN-" + token
        extraction_id = "EXT-" + token

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, 'DIAN', 'normograma_html', NULL, ?, ?)
                """,
                (source_id, source_url, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (?, ?, ?, 'text/html', ?, 1, ?, ?, 'test')
                """,
                (
                    manifestation_id,
                    document_id,
                    source_id,
                    hashlib.sha256(source_url.encode()).hexdigest(),
                    NOW,
                    f"raw/{token}.html",
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size, char_count,
                    segment_count, local_path, created_at, status
                ) VALUES (?, ?, 'test', '1', ?, 1, 1, ?, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    "b" * 64,
                    len(segments),
                    f"normalized/{token}.txt",
                    NOW,
                ),
            )
            position = 0
            for sequence_no, (segment_type, text) in enumerate(segments, 1):
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id, extraction_id, sequence_no,
                        segment_type, section_path, char_start, char_end,
                        text, text_sha256
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        f"SEG-{token}-{sequence_no}",
                        extraction_id,
                        sequence_no,
                        segment_type,
                        position,
                        position + len(text),
                        text,
                        hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
                position += len(text) + 1
            con.commit()
        finally:
            con.close()
        return extraction_id, manifestation_id

    def assert_registered(
        self,
        filename: str,
        segments: list[tuple[str, str]],
        expected_key: str,
        expected_type: str,
    ) -> dict[str, object]:
        extraction_id, _ = self.fixture(filename, segments)
        result = register_document_identity(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["canonical_key"], expected_key)
        self.assertEqual(result["document_type"], expected_type)
        return result

    def test_historic_oficio_uses_trusted_source_not_quoted_ley(self):
        result = self.assert_registered(
            "oficio_dian_68070_1998.htm",
            [("document_heading", "LEY 223 DE 1995")],
            "CO:DIAN:OFICIO:68070:1998",
            "OFICIO",
        )
        self.assertEqual(result["issuer_key"], "DIAN")

    def test_modern_oficio_preserves_explicit_matching_concepto_title(self):
        result = self.assert_registered(
            "oficio_dian_001169_2024.htm",
            [("document_heading", "CONCEPTO 001169 int 25 DE 2024")],
            "CO:DIAN:CONCEPTO:1169:2024",
            "CONCEPTO",
        )
        self.assertEqual(result["family_metadata"]["internal_number"], "25")

    def test_concepto_tributario_source_identity(self):
        self.assert_registered(
            "concepto_tributario_dian_0000001_2003.htm",
            [("document_heading", "DECRETO 624 DE 1989")],
            "CO:DIAN:CONCEPTO:1:2003",
            "CONCEPTO",
        )

    def test_concepto_aduanero_source_identity(self):
        self.assert_registered(
            "concepto_aduanero_dian_0001465_2019.htm",
            [("document_heading", "DECRETO 2685 DE 1999")],
            "CO:DIAN:CONCEPTO:1465:2019",
            "CONCEPTO",
        )

    def test_concepto_cambiario_source_identity(self):
        self.assert_registered(
            "concepto_cambiario_dian_0000046_2007.htm",
            [("document_heading", "RESOLUCIÓN 1 DE 2007")],
            "CO:DIAN:CONCEPTO:46:2007",
            "CONCEPTO",
        )

    def test_sentencia_c_ignores_quoted_normative_heading(self):
        self.assert_registered(
            "c-621_2013.htm",
            [("document_heading", "LEY 1450 DE 2011")],
            "CO:CORTE_CONSTITUCIONAL:SENTENCIA_C:621:2013",
            "SENTENCIA_C",
        )

    def test_sentencia_c_family_heading_conflict_is_unresolved(self):
        extraction_id, manifestation_id = self.fixture(
            "c-621_2013.htm",
            [("document_heading", "SENTENCIA C-833 DE 2013")],
        )
        result = register_document_identity(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason_code"], "SOURCE_IDENTITY_CONFLICT")
        con = sqlite3.connect(self.db)
        try:
            self.assertIsNone(
                con.execute(
                    "SELECT document_id FROM manifestations "
                    "WHERE manifestation_id=?",
                    (manifestation_id,),
                ).fetchone()[0]
            )
        finally:
            con.close()

    def test_conpes_has_issuer_aware_identity(self):
        self.assert_registered(
            "conpes_dnp_3701_2011.htm",
            [("document_heading", "DOCUMENTO CONPES 3701")],
            "CO:CONPES:CONPES:3701:2011",
            "CONPES",
        )

    def test_constitucion_has_own_identity(self):
        self.assert_registered(
            "constitucion_politica_1991.htm",
            [("document_heading", "RESOLUCIÓN 33933 DE 2025")],
            "CO:ASAMBLEA_CONSTITUYENTE:CONSTITUCION_POLITICA:1991:1991",
            "CONSTITUCION_POLITICA",
        )

    def test_incomplete_concept_source_stays_explicitly_unresolved(self):
        extraction_id, _ = self.fixture(
            "concepto_dian_c0000148.htm",
            [("document_heading", "DECRETO 624 DE 1989")],
        )
        result = register_document_identity(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason_code"], "SOURCE_IDENTITY_UNRESOLVED")

    def test_legacy_modern_concept_document_is_reused_and_upgraded(self):
        legacy_document_id = "DOC-legacy-concept-1169-2024"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'DIAN', 'CONCEPTO', ?, NULL, NULL, ?, ?)
                """,
                (
                    legacy_document_id,
                    "CONCEPTO 001169 int 25 DE 2024",
                    NOW,
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES ('ID-legacy-concept', ?, 'canonical_key',
                          'CO:CONCEPTO:1169:2024', 'DIAN', 1)
                """,
                (legacy_document_id,),
            )
            con.commit()
        finally:
            con.close()

        extraction_id, manifestation_id = self.fixture(
            "oficio_dian_001169_2024.htm",
            [("document_heading", "CONCEPTO 001169 int 25 DE 2024")],
            document_id=legacy_document_id,
        )
        result = register_document_identity(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["document_id"], legacy_document_id)
        self.assertEqual(
            result["canonical_key"],
            "CO:DIAN:CONCEPTO:1169:2024",
        )

        con = sqlite3.connect(self.db)
        try:
            identifiers = con.execute(
                """
                SELECT identifier_value, issuer, is_primary
                FROM document_identifiers
                WHERE document_id=? AND identifier_type='canonical_key'
                ORDER BY is_primary DESC, identifier_value
                """,
                (legacy_document_id,),
            ).fetchall()
            self.assertEqual(
                identifiers,
                [
                    ("CO:DIAN:CONCEPTO:1169:2024", "DIAN", 1),
                    ("CO:CONCEPTO:1169:2024", "DIAN", 0),
                ],
            )
            self.assertEqual(
                con.execute(
                    "SELECT document_id FROM manifestations "
                    "WHERE manifestation_id=?",
                    (manifestation_id,),
                ).fetchone()[0],
                legacy_document_id,
            )
        finally:
            con.close()

    def test_doctrine_registry_identity_survives_absent_modern_metadata(self):
        extraction_id, _ = self.fixture(
            "oficio_dian_0054_2023.htm",
            [("document_heading", "LEY 2277 DE 2022")],
        )
        result = register_doctrine(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["document_type"], "OFICIO")
        self.assertEqual(
            result["doctrine_metadata_status"],
            "not_applicable",
        )

    def test_modern_doctrine_metadata_still_registers(self):
        extraction_id, _ = self.fixture(
            "oficio_dian_001169_2024.htm",
            [
                ("document_heading", "CONCEPTO 001169 int 25 DE 2024"),
                ("paragraph", "(enero 5)"),
                (
                    "paragraph",
                    "Publicado en la página web de la DIAN: "
                    "6 de enero de 2024",
                ),
            ],
        )
        result = register_doctrine(
            extraction_id=extraction_id,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "registered")
        self.assertEqual(
            result["canonical_key"],
            "CO:DIAN:CONCEPTO:1169:2024",
        )
        self.assertEqual(result["doctrine_metadata_status"], "registered")

    def test_promoter_skips_unresolved_source_instead_of_failing(self):
        extraction_id, _ = self.fixture(
            "concepto_dian_c0000148.htm",
            [("document_heading", "DECRETO 624 DE 1989")],
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO reference_detection_runs(
                    detection_run_id, extraction_id, detector_name,
                    detector_version, mention_count, relation_count,
                    created_at, status
                ) VALUES ('RDR-test', ?, 'test', '1', 0, 0, ?, 'success')
                """,
                (extraction_id, NOW),
            )
            con.commit()
        finally:
            con.close()

        result = promote_operational(
            detection_run_id="RDR-test",
            resolution_method=RESOLUTION_METHOD,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(
            result["reason_code"],
            "SOURCE_DOCUMENT_ID_UNRESOLVED",
        )

    def test_dry_run_predicts_apply_preserves_hashes_and_is_idempotent(self):
        _, manifestation_id = self.fixture(
            "c-072_2025.htm",
            [("document_heading", "SENTENCIA C-072 DE 2025")],
        )
        con = sqlite3.connect(self.db)
        try:
            before = con.execute(
                "SELECT document_id, sha256 FROM manifestations "
                "WHERE manifestation_id=?",
                (manifestation_id,),
            ).fetchone()
        finally:
            con.close()

        preview = reprocess(
            db_path=self.db,
            apply=False,
            only_unidentified=True,
        )
        self.assertFalse(preview["persistent_mutation"])
        self.assertEqual(preview["registered_count"], 1)
        self.assertEqual(preview["delta"]["manifestation_rebindings"], 1)
        self.assertTrue(preview["hashes_unchanged"])

        con = sqlite3.connect(self.db)
        try:
            after_preview = con.execute(
                "SELECT document_id, sha256 FROM manifestations "
                "WHERE manifestation_id=?",
                (manifestation_id,),
            ).fetchone()
            self.assertEqual(before, after_preview)
        finally:
            con.close()

        applied = reprocess(
            db_path=self.db,
            apply=True,
            only_unidentified=True,
        )
        self.assertEqual(applied["delta"], preview["delta"])
        self.assertTrue(applied["hashes_unchanged"])

        second = reprocess(
            db_path=self.db,
            apply=False,
            only_unidentified=False,
        )
        self.assertEqual(second["delta"]["documents_inserted"], 0)
        self.assertEqual(second["delta"]["identifiers_inserted"], 0)
        self.assertEqual(second["delta"]["manifestation_rebindings"], 0)
        self.assertTrue(second["hashes_unchanged"])

    def test_generic_normative_identity_stays_stable(self):
        result = self.assert_registered(
            "resolucion_dian_0227_2025.htm",
            [("document_heading", "RESOLUCIÓN 227 DE 2025")],
            "CO:DIAN:RESOLUCION:227:2025",
            "RESOLUCION",
        )
        self.assertEqual(result["source_family"], "NORMATIVE_ACT")


if __name__ == "__main__":
    unittest.main()
