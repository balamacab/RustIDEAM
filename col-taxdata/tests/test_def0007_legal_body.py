from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import extract_normograma_html as extractor


BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"
C096 = BASE + "c-096_2001.htm"
NOW = "2026-09-24T00:00:00+00:00"
FIXTURE = ROOT / "tests" / "fixtures" / "def0007_c096_2001_excerpt.html"


class Def0007LegalBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.sqlite"
        self.data_root = self.root / "data"
        self._apply_migrations()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apply_migrations(self) -> None:
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def _register_html(self, url: str, html: str) -> tuple[str, Path, str]:
        raw = html.encode("utf-8")
        raw_sha = hashlib.sha256(raw).hexdigest()
        token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        source_id = "SRC-" + token
        manifestation_id = "MAN-" + token
        local_path = Path("raw") / "sha256" / raw_sha[:2] / f"{raw_sha}.html"
        raw_path = self.data_root / local_path
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, 'DIAN', 'normograma_html', NULL, ?, ?)
                """,
                (source_id, url, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (?, NULL, ?, 'text/html', ?, ?, ?, ?, 'test')
                """,
                (
                    manifestation_id,
                    source_id,
                    raw_sha,
                    len(raw),
                    NOW,
                    str(local_path),
                ),
            )
            con.commit()
        finally:
            con.close()
        return manifestation_id, raw_path, raw_sha

    @staticmethod
    def _normal_sentencia_html() -> str:
        substantive = (
            "La Corte examina la demanda y desarrolla las razones jurídicas "
            "relevantes para decidir el problema constitucional planteado. "
        ) * 12
        return f"""
        <html><body>
        <h1>SENTENCIA C-123/24</h1>
        <h2>I. ANTECEDENTES</h2>
        <p>{substantive}</p>
        <h2>VI. CONSIDERACIONES Y FUNDAMENTOS</h2>
        <p>{substantive}</p>
        <h2>VII. DECISION</h2>
        <p>R E S U E L V E:</p>
        <div>Compilación Jurídica DIAN</div>
        </body></html>
        """

    def test_c096_fixture_extracts_and_dry_run_predicts_without_mutation(self):
        html = FIXTURE.read_text(encoding="utf-8")
        manifestation_id, raw_path, raw_sha = self._register_html(C096, html)
        before_raw = raw_path.read_bytes()

        preview = extractor.extract_manifestation(
            manifestation_id=manifestation_id,
            db_path=self.db,
            data_root=self.data_root,
            dry_run=True,
        )

        self.assertTrue(preview["dry_run"])
        self.assertTrue(preview["would_insert_extraction"])
        self.assertTrue(preview["would_write_output"])
        self.assertEqual(preview["extractor_version"], "3")
        self.assertGreater(preview["char_count"], extractor.SENTENCIA_C_MIN_BODY_CHARS)
        self.assertFalse((self.data_root / preview["local_path"]).exists())

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM text_extractions").fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM extracted_segments").fetchone()[0],
                0,
            )
        finally:
            con.close()

        applied = extractor.extract_manifestation(
            manifestation_id=manifestation_id,
            db_path=self.db,
            data_root=self.data_root,
        )
        extracted_text = (self.data_root / applied["local_path"]).read_text(
            encoding="utf-8"
        )

        self.assertIn("Sentencia C-096/01", extracted_text)
        self.assertIn("I. ANTECEDENTES", extracted_text)
        self.assertIn("VI. CONSIDERACIONES Y FUNDAMENTOS", extracted_text)
        self.assertIn("VII. DECISION", extracted_text)
        self.assertNotIn("ISBN 978-958-53111-6-9", extracted_text)
        self.assertGreaterEqual(
            applied["segment_types"].get("document_heading", 0),
            1,
        )
        self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), raw_sha)
        self.assertEqual(raw_path.read_bytes(), before_raw)

        old_id = extractor.deterministic_id(
            "EXT",
            f"col-taxdata:{manifestation_id}:{extractor.EXTRACTOR_NAME}:2",
        )
        self.assertNotEqual(applied["extraction_id"], old_id)

        repeated = extractor.extract_manifestation(
            manifestation_id=manifestation_id,
            db_path=self.db,
            data_root=self.data_root,
        )
        self.assertTrue(repeated["reused"])
        self.assertEqual(repeated["extraction_id"], applied["extraction_id"])
        self.assertEqual(repeated["normalized_sha256"], applied["normalized_sha256"])

    def test_normal_sentencia_c_family_extracts(self):
        manifestation_id, _, _ = self._register_html(
            BASE + "c-123_2024.htm",
            self._normal_sentencia_html(),
        )
        result = extractor.extract_manifestation(
            manifestation_id=manifestation_id,
            db_path=self.db,
            data_root=self.data_root,
            dry_run=True,
        )
        self.assertGreater(result["segment_count"], 5)
        self.assertEqual(result["extractor_version"], "3")

    def test_sentencia_c_truncated_body_fails_safely(self):
        html = """
        <html><body>
        <h1>SENTENCIA C-999/24</h1>
        <h2>I. ANTECEDENTES</h2>
        <p>Texto truncado.</p>
        <h2>VII. DECISION</h2>
        <p>R E S U E L V E:</p>
        </body></html>
        """
        parser = extractor.VisibleBlockParser()
        parser.feed(html)
        parser.close()

        with self.assertRaisesRegex(
            RuntimeError,
            "Sentencia C body is incomplete or unexpectedly short",
        ):
            extractor.find_legal_body(
                parser.blocks,
                source_url=BASE + "c-999_2024.htm",
            )

    def test_navigation_page_is_not_promoted_to_legal_body(self):
        html = """
        <html><body>
        <h1>Índice temático</h1>
        <a href="ley_1_2000.htm">Entrada 1</a>
        <a href="decreto_2_2000.htm">Entrada 2</a>
        <a href="c-096_2001.htm">Entrada 3</a>
        </body></html>
        """
        parser = extractor.VisibleBlockParser()
        parser.feed(html)
        parser.close()

        with self.assertRaisesRegex(RuntimeError, "heading was not detected"):
            extractor.find_legal_body(
                parser.blocks,
                source_url=BASE + "indice_especial.htm",
            )

    def test_generic_short_body_guard_is_preserved(self):
        html = """
        <html><body>
        <h1>LEY 123 DE 2024</h1>
        <p>Uno.</p><p>Dos.</p><p>Tres.</p>
        </body></html>
        """
        parser = extractor.VisibleBlockParser()
        parser.feed(html)
        parser.close()

        with self.assertRaisesRegex(RuntimeError, "unexpectedly short"):
            extractor.find_legal_body(
                parser.blocks,
                source_url=BASE + "ley_123_2024.htm",
            )

    def test_generic_normative_body_remains_valid(self):
        html = """
        <html><body>
        <h1>LEY 123 DE 2024</h1>
        <p>Uno.</p><p>Dos.</p><p>Tres.</p><p>Cuatro.</p>
        </body></html>
        """
        parser = extractor.VisibleBlockParser()
        parser.feed(html)
        parser.close()

        body = extractor.find_legal_body(
            parser.blocks,
            source_url=BASE + "ley_123_2024.htm",
        )
        self.assertEqual(body[0].text, "LEY 123 DE 2024")
        self.assertEqual(len(body), 5)


if __name__ == "__main__":
    unittest.main()
