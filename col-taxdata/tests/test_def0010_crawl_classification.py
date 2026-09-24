from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from crawl_dian_normograma import status_payload
from crawl_page_classification import (
    AMBIGUOUS,
    CONFIRMED_INDEX,
    LEGAL_EXTRACTION_FAILURE,
    classify_heading_failure,
)
from reclassify_crawl_queue import reclassify


NOW = "2026-09-24T00:00:00+00:00"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"
C096 = BASE + "c-096_2001.htm"


class Def0010CrawlerClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.sqlite"
        self.data_root = self.root / "data"
        self._apply_migrations(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _apply_migrations(
        db_path: Path,
        *,
        through: str | None = None,
    ) -> None:
        con = sqlite3.connect(db_path)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                if through is not None and migration.name > through:
                    break
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def _queue_fixture(
        self,
        *,
        url: str,
        html: str,
        item_type: str = "index",
        status: str = "done",
        classification_state: str = "unclassified",
    ) -> tuple[str, Path]:
        token = hashlib.sha256(url.encode()).hexdigest()[:16]
        source_id = "SRC-" + token
        manifestation_id = "MAN-" + token
        raw = html.encode("utf-8")
        raw_sha = hashlib.sha256(raw).hexdigest()
        local_path = Path("raw") / (raw_sha + ".html")
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
            con.execute(
                """
                INSERT INTO dian_crawl_queue(
                    url, item_type, scope, depth, discovered_from, status,
                    attempts, source_id, manifestation_id, extraction_id,
                    content_sha256, processing_json, last_error,
                    first_seen_at, last_attempt_at, completed_at,
                    next_attempt_at, classification_state
                ) VALUES (?, ?, 'all', 1, ?, ?, 15, ?, ?, NULL, ?, '{}',
                          NULL, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    item_type,
                    BASE + "oficio_dian_34755_2015.htm",
                    status,
                    source_id,
                    manifestation_id,
                    raw_sha,
                    NOW,
                    NOW,
                    NOW,
                    NOW,
                    classification_state,
                ),
            )
            con.commit()
        finally:
            con.close()
        return raw_sha, raw_path

    def test_c096_source_family_cannot_be_confirmed_as_index(self):
        html = """
        <html><body>
        <h1>SENTENCIA C-096/01</h1>
        <p>CORTE CONSTITUCIONAL</p>
        <p>ARTÍCULO 1. Texto sustantivo de la decisión.</p>
        <a href="ley_1_2000.htm">Ley citada</a>
        <a href="decreto_2_2000.htm">Decreto citado</a>
        <a href="resolucion_3_2000.htm">Resolución citada</a>
        <a href="circular_4_2000.htm">Circular citada</a>
        </body></html>
        """
        decision = classify_heading_failure(source_url=C096, html=html)
        self.assertEqual(decision.state, LEGAL_EXTRACTION_FAILURE)
        self.assertEqual(
            decision.reason_code,
            "KNOWN_LEGAL_SOURCE_HEADING_NOT_DETECTED",
        )

    def test_genuine_navigation_page_requires_positive_link_structure(self):
        url = BASE + "indice_especial.htm"
        html = """
        <html><body><h1>Índice temático</h1>
        <a href="ley_1_2000.htm">Entrada 1</a>
        <a href="decreto_2_2000.htm">Entrada 2</a>
        <a href="resolucion_3_2000.htm">Entrada 3</a>
        <a href="circular_4_2000.htm">Entrada 4</a>
        <a href="oficio_dian_5_2000.htm">Entrada 5</a>
        </body></html>
        """
        decision = classify_heading_failure(source_url=url, html=html)
        self.assertEqual(decision.state, CONFIRMED_INDEX)
        self.assertGreaterEqual(decision.document_link_count, 4)

    def test_truncated_known_legal_page_remains_extraction_failure(self):
        url = BASE + "ley_123_2024.htm"
        decision = classify_heading_failure(
            source_url=url,
            html="<html><body><h1>LEY</h1><p>truncado</p></body></html>",
        )
        self.assertEqual(decision.state, LEGAL_EXTRACTION_FAILURE)

    def test_legal_looking_unknown_page_is_explicitly_ambiguous(self):
        url = BASE + "tema_especial.htm"
        html = """
        <html><body>
        <p>La CORTE CONSTITUCIONAL estudió el ARTÍCULO 1 de la norma.</p>
        <a href="ley_1_2000.htm">Referencia</a>
        </body></html>
        """
        decision = classify_heading_failure(source_url=url, html=html)
        self.assertEqual(decision.state, AMBIGUOUS)
        self.assertEqual(
            decision.reason_code,
            "LEGAL_CUES_WITHOUT_TRUSTED_SOURCE_IDENTITY",
        )

    def test_status_surfaces_legacy_index_done_legal_candidate(self):
        self._queue_fixture(
            url=C096,
            html="<html><body><h1>SENTENCIA C-096/01</h1></body></html>",
        )
        con = sqlite3.connect(self.db)
        try:
            payload = status_payload(con)
        finally:
            con.close()

        self.assertEqual(payload["review_required"]["count"], 1)
        self.assertEqual(payload["review_required"]["items"][0]["url"], C096)
        self.assertGreaterEqual(payload["meaningful_failure_count"], 1)

    def test_reclassification_preview_is_non_mutating_and_apply_is_idempotent(self):
        html = """
        <html><body>
        <h1>SENTENCIA C-096/01</h1>
        <p>CORTE CONSTITUCIONAL</p>
        <p>ARTÍCULO 1. Texto sustantivo.</p>
        </body></html>
        """
        raw_sha, raw_path = self._queue_fixture(url=C096, html=html)
        before_bytes = raw_path.read_bytes()

        preview = reclassify(
            db_path=self.db,
            data_root=self.data_root,
            apply=False,
            url=C096,
        )
        self.assertEqual(preview["changed_rows"], 0)
        self.assertFalse(preview["mutated"])
        self.assertEqual(
            preview["items"][0]["after"]["classification_state"],
            LEGAL_EXTRACTION_FAILURE,
        )

        con = sqlite3.connect(self.db)
        try:
            unchanged = con.execute(
                """
                SELECT item_type, status, classification_state
                FROM dian_crawl_queue WHERE url=?
                """,
                (C096,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(unchanged, ("index", "done", "unclassified"))

        applied = reclassify(
            db_path=self.db,
            data_root=self.data_root,
            apply=True,
            url=C096,
        )
        self.assertEqual(applied["changed_rows"], 1)

        second = reclassify(
            db_path=self.db,
            data_root=self.data_root,
            apply=True,
            url=C096,
        )
        self.assertEqual(second["changed_rows"], 0)

        con = sqlite3.connect(self.db)
        try:
            after = con.execute(
                """
                SELECT item_type, status, classification_state, extraction_id
                FROM dian_crawl_queue WHERE url=?
                """,
                (C096,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(
            after,
            ("document", "error", LEGAL_EXTRACTION_FAILURE, None),
        )
        self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), raw_sha)
        self.assertEqual(raw_path.read_bytes(), before_bytes)

    def test_confirmed_navigation_is_not_bulk_converted_to_document(self):
        url = BASE + "indice_especial.htm"
        html = """
        <html><body><h1>Índice temático</h1>
        <a href="ley_1_2000.htm">Entrada 1</a>
        <a href="decreto_2_2000.htm">Entrada 2</a>
        <a href="resolucion_3_2000.htm">Entrada 3</a>
        <a href="circular_4_2000.htm">Entrada 4</a>
        </body></html>
        """
        self._queue_fixture(url=url, html=html)
        result = reclassify(
            db_path=self.db,
            data_root=self.data_root,
            apply=True,
            url=url,
        )
        self.assertEqual(result["changed_rows"], 1)
        con = sqlite3.connect(self.db)
        try:
            row = con.execute(
                """
                SELECT item_type, status, classification_state
                FROM dian_crawl_queue WHERE url=?
                """,
                (url,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("index", "done", CONFIRMED_INDEX))

    def test_migration_upgrades_existing_queue_rows_without_reclassification(self):
        upgrade_db = self.root / "upgrade.sqlite"
        self._apply_migrations(upgrade_db, through="014_temporal_candidates.sql")
        con = sqlite3.connect(upgrade_db)
        try:
            con.execute(
                """
                INSERT INTO dian_crawl_queue(
                    url, item_type, scope, depth, status, attempts,
                    first_seen_at, next_attempt_at
                ) VALUES (?, 'index', 'all', 0, 'done', 1, ?, ?)
                """,
                (C096, NOW, NOW),
            )
            con.commit()
            migration = ROOT / "schema" / "015_crawl_page_classification.sql"
            con.executescript(migration.read_text(encoding="utf-8"))
            row = con.execute(
                """
                SELECT item_type, status, classification_state, classification_json
                FROM dian_crawl_queue WHERE url=?
                """,
                (C096,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("index", "done", "unclassified", None))


if __name__ == "__main__":
    unittest.main()
