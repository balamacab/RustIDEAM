from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from register_document_identity import register_document_identity
from register_simple_normative_act import register_simple_act
from source_identity import classify_source_url


NOW = "2026-09-22T00:00:00+00:00"


class Def0001IdentityTests(unittest.TestCase):
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

    def fixture(self, filename: str, heading: str, article: str | None = None) -> str:
        source_url = f"https://normograma.dian.gov.co/dian/compilacion/docs/{filename}"
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
                ) VALUES (?, NULL, ?, 'text/html', ?, 1, ?, ?, 'test')
                """,
                (manifestation_id, source_id, "a" * 64, NOW, f"raw/{token}.html"),
            )
            segments = [("document_heading", heading)]
            if article is not None:
                segments.append(("article", article))
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
            pos = 0
            for seq, (kind, text) in enumerate(segments, 1):
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id, extraction_id, sequence_no,
                        segment_type, section_path, char_start, char_end,
                        text, text_sha256
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        f"SEG-{token}-{seq}",
                        extraction_id,
                        seq,
                        kind,
                        pos,
                        pos + len(text),
                        text,
                        hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
                pos += len(text) + 1
            con.commit()
        finally:
            con.close()
        return extraction_id

    def assert_unresolved(self, filename: str, heading: str) -> None:
        extraction_id = self.fixture(filename, heading, "ARTÍCULO 1. Texto")
        simple = register_simple_act(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(simple["status"], "unresolved")
        self.assertEqual(simple["reason_code"], "SOURCE_IDENTITY_CONFLICT")

        fallback = register_document_identity(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(fallback["status"], "unresolved")
        self.assertIsNone(fallback["document_id"])

        con = sqlite3.connect(self.db)
        try:
            document_id = con.execute(
                """
                SELECT m.document_id
                FROM manifestations m JOIN text_extractions te
                  ON te.manifestation_id=m.manifestation_id
                WHERE te.extraction_id=?
                """,
                (extraction_id,),
            ).fetchone()[0]
            self.assertIsNone(document_id)
            reasons = con.execute(
                """
                SELECT reason_code FROM review_queue
                WHERE entity_id=(
                    SELECT manifestation_id FROM text_extractions WHERE extraction_id=?
                ) AND resolved_at IS NULL
                """,
                (extraction_id,),
            ).fetchall()
            self.assertIn(("SOURCE_IDENTITY_CONFLICT",), reasons)
            signals = con.execute(
                "SELECT signal_origin FROM document_identity_signals WHERE extraction_id=?",
                (extraction_id,),
            ).fetchall()
            self.assertEqual({x[0] for x in signals}, {"source_url", "document_heading"})
        finally:
            con.close()

    def test_c621_cannot_become_ley_1450(self):
        self.assert_unresolved("c-621_2013.htm", "LEY 1450 DE 2011")

    def test_c833_cannot_become_ley_1607(self):
        self.assert_unresolved("c-833_2013.htm", "LEY 1607 DE 2012")

    def test_concepto_aduanero_cannot_become_quoted_decreto(self):
        self.assert_unresolved(
            "concepto_aduanero_dian_0001465_2019.htm",
            "DECRETO 2685 DE 1999. ARTICULO 231 . RESCATE.",
        )

    def test_constitucion_cannot_become_resolucion(self):
        self.assert_unresolved(
            "constitucion_politica_1991.htm",
            "RESOLUCIÓN 33933 DE 2025",
        )

    def assert_valid_norm(self, filename: str, heading: str, expected_key: str):
        extraction_id = self.fixture(filename, heading, "ARTÍCULO 1. Texto válido.")
        result = register_simple_act(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["canonical_key"], expected_key)
        self.assertIsNotNone(result["document_id"])
        con = sqlite3.connect(self.db)
        try:
            stored = con.execute(
                """
                SELECT di.identifier_value
                FROM text_extractions te
                JOIN manifestations m ON m.manifestation_id=te.manifestation_id
                JOIN document_identifiers di ON di.document_id=m.document_id
                WHERE te.extraction_id=? AND di.identifier_type='canonical_key'
                """,
                (extraction_id,),
            ).fetchone()[0]
            self.assertEqual(stored, expected_key)
        finally:
            con.close()

    def test_normative_url_number_conflict_is_unresolved(self):
        extraction_id = self.fixture(
            "ley_1450_2011.htm",
            "LEY 1607 DE 2012",
            "ARTÍCULO 1. Texto",
        )
        result = register_simple_act(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason_code"], "SOURCE_IDENTITY_CONFLICT")

    def test_unknown_family_is_not_guessed_from_quoted_norm(self):
        extraction_id = self.fixture(
            "documento_sin_identidad.htm",
            "LEY 1450 DE 2011",
            "ARTÍCULO 1. Texto",
        )
        result = register_simple_act(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason_code"], "SOURCE_IDENTITY_UNRESOLVED")

    def test_existing_zero_padded_canonical_identity_is_preserved(self):
        extraction_id = self.fixture(
            "resolucion_dian_0180_2024.htm",
            "RESOLUCIÓN 000180 DE 2024",
            "ARTÍCULO 1. Texto",
        )
        old_key = "CO:RESOLUCION:000180:2024"
        old_document_id = "DOC-existing-zero-padded"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'DIAN', 'RESOLUCION', ?, NULL, NULL, ?, ?)
                """,
                (old_document_id, "RESOLUCIÓN 000180 DE 2024", NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES ('ID-existing-zero-padded', ?, 'canonical_key', ?, 'DIAN', 1)
                """,
                (old_document_id, old_key),
            )
            con.execute(
                """
                UPDATE manifestations
                SET document_id=?
                WHERE manifestation_id=(
                    SELECT manifestation_id FROM text_extractions WHERE extraction_id=?
                )
                """,
                (old_document_id, extraction_id),
            )
            con.commit()
        finally:
            con.close()

        result = register_document_identity(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["document_id"], old_document_id)
        self.assertEqual(result["canonical_key"], old_key)
        self.assertTrue(result["reused"])

    def test_valid_ley_stable(self):
        self.assert_valid_norm("ley_1450_2011.htm", "LEY 1450 DE 2011", "CO:LEY:1450:2011")

    def test_valid_decreto_stable(self):
        self.assert_valid_norm("decreto_1165_2019.htm", "DECRETO 1165 DE 2019", "CO:DECRETO:1165:2019")

    def test_valid_resolucion_stable(self):
        self.assert_valid_norm(
            "resolucion_dian_0227_2025.htm",
            "RESOLUCIÓN 227 DE 2025",
            "CO:RESOLUCION:227:2025",
        )

    def test_valid_circular_stable(self):
        self.assert_valid_norm(
            "circular_dian_0010_2022.htm",
            "CIRCULAR 10 DE 2022",
            "CO:CIRCULAR:10:2022",
        )

    def test_source_family_classifier(self):
        self.assertEqual(classify_source_url("https://x/docs/c-621_2013.htm").family, "CORTE_CONSTITUCIONAL_SENTENCIA_C")
        self.assertEqual(classify_source_url("https://x/docs/conpes_dnp_3995_2020.htm").family, "CONPES")
        self.assertEqual(classify_source_url("https://x/docs/constitucion_politica_1991.htm").family, "CONSTITUCION_POLITICA")


if __name__ == "__main__":
    unittest.main()