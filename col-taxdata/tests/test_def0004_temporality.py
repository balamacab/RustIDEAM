from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from extract_document_temporality import extract_temporality
from reprocess_temporality import reprocess


NOW = "2026-09-23T00:00:00+00:00"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"


class Def0004TemporalityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite"
        self._apply_all_migrations(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _apply_all_migrations(db_path: Path) -> None:
        con = sqlite3.connect(db_path)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def fixture(
        self,
        name: str,
        segments: list[tuple[str, str] | tuple[str, str, str | None]],
    ) -> tuple[str, str, str]:
        source_url = BASE + name
        token = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        source_id = "SRC-" + token
        manifestation_id = "MAN-" + token
        extraction_id = "EXT-" + token
        document_id = "DOC-" + token
        raw_hash = hashlib.sha256(("raw:" + source_url).encode()).hexdigest()

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'DIAN', 'DECRETO', ?, NULL, NULL, ?, ?)
                """,
                (document_id, name, NOW, NOW),
            )
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
                    raw_hash,
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
                    hashlib.sha256(("normalized:" + source_url).encode()).hexdigest(),
                    len(segments),
                    f"extracted/{token}.txt",
                    NOW,
                ),
            )
            position = 0
            for sequence_no, raw_segment in enumerate(segments, 1):
                if len(raw_segment) == 2:
                    segment_type, text = raw_segment
                    section_path = None
                else:
                    segment_type, text, section_path = raw_segment
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id, extraction_id, sequence_no,
                        segment_type, section_path, char_start, char_end,
                        text, text_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"SEG-{token}-{sequence_no}",
                        extraction_id,
                        sequence_no,
                        segment_type,
                        section_path,
                        position,
                        position + len(text),
                        text,
                        hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
                position += len(text) + 2
            con.commit()
        finally:
            con.close()
        return extraction_id, manifestation_id, document_id

    @staticmethod
    def publication(day: int = 1) -> str:
        return f"Diario Oficial No. 50.000 de {day} de enero de 2020"

    @staticmethod
    def issued(day: int = 1) -> str:
        return f"PUBLÍQUESE Y CÚMPLASE. Dado en Bogotá, {day} de enero de 2020"

    @staticmethod
    def commencement(index: int = 1) -> str:
        return (
            f"ARTÍCULO {index}. La presente disposición rige a partir de la "
            "fecha de su publicación."
        )

    def test_zero_publication_date_completes_as_unresolved(self):
        extraction_id, _, _ = self.fixture(
            "decreto_0001_2020.htm",
            [
                ("closing", self.issued()),
                ("article", self.commencement()),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["roles"]["publication_date"]["status"], "unresolved")
        self.assertEqual(result["roles"]["publication_date"]["candidate_count"], 0)
        self.assertIsNone(result["publication_date"])
        self.assertIsNone(result["effective_date"])

    def test_exactly_one_publication_date_is_promoted(self):
        extraction_id, _, _ = self.fixture(
            "decreto_0002_2020.htm",
            [
                ("text", self.publication()),
                ("closing", self.issued()),
                ("article", self.commencement()),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        publication = result["roles"]["publication_date"]
        self.assertEqual(publication["status"], "resolved")
        self.assertEqual(publication["candidate_count"], 1)
        self.assertEqual(publication["trusted_candidate_count"], 1)
        self.assertEqual(result["publication_date"], "2020-01-01")
        self.assertEqual(result["effective_date"], "2020-01-01")

    def test_two_publication_dates_are_ambiguous_not_failure(self):
        extraction_id, _, _ = self.fixture(
            "decreto_0003_2020.htm",
            [
                ("text", self.publication(1)),
                ("text", self.publication(2)),
                ("closing", self.issued()),
                ("article", self.commencement()),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        publication = result["roles"]["publication_date"]
        self.assertEqual(publication["status"], "ambiguous")
        self.assertEqual(publication["candidate_count"], 2)
        self.assertEqual(publication["trusted_candidate_count"], 2)
        self.assertIsNone(result["publication_date"])
        con = sqlite3.connect(self.db)
        try:
            reason = con.execute(
                """
                SELECT rq.reason_code
                FROM review_queue rq
                JOIN temporal_role_resolutions tr
                  ON rq.entity_id=tr.temporal_resolution_id
                WHERE tr.extraction_id=? AND tr.role='publication_date'
                  AND rq.resolved_at IS NULL
                """,
                (extraction_id,),
            ).fetchone()[0]
            self.assertEqual(reason, "TEMPORAL_ROLE_AMBIGUOUS")
        finally:
            con.close()

    def test_one_issued_date_wins_over_multiple_quoted_dates(self):
        quoted_a = "DECRETO 99 DE 2010. Dado en Medellín, 2 de febrero de 2010"
        quoted_b = "LEY 100 DE 2011. Dada en Cali, 3 de marzo de 2011"
        extraction_id, _, _ = self.fixture(
            "decreto_0004_2020.htm",
            [
                ("text", self.publication()),
                ("text", quoted_a),
                ("text", quoted_b),
                ("article", "ARTÍCULO 1. Objeto."),
                ("text", "Texto intermedio uno."),
                ("text", "Texto intermedio dos."),
                ("text", "Texto intermedio tres."),
                ("closing", self.issued()),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        issued = result["roles"]["issued_date"]
        self.assertEqual(issued["status"], "resolved")
        self.assertEqual(issued["candidate_count"], 3)
        self.assertEqual(issued["trusted_candidate_count"], 1)
        self.assertEqual(result["issued_date"], "2020-01-01")
        con = sqlite3.connect(self.db)
        try:
            contexts = con.execute(
                """
                SELECT context_type, is_trusted_structure
                FROM temporal_candidates
                WHERE extraction_id=? AND role='issued_date'
                ORDER BY char_start
                """,
                (extraction_id,),
            ).fetchall()
            self.assertEqual(
                contexts,
                [
                    ("quoted_cited_norm", 0),
                    ("quoted_cited_norm", 0),
                    ("primary_document_date", 1),
                ],
            )
        finally:
            con.close()

    def test_quoted_publication_metadata_is_not_promoted(self):
        quoted = (
            "DECRETO 99 DE 2010 fue publicado en "
            "Diario Oficial No. 47.000 de 2 de febrero de 2010"
        )
        extraction_id, _, _ = self.fixture(
            "decreto_0005_2020.htm",
            [
                ("text", quoted),
                ("text", self.publication()),
                ("article", "ARTÍCULO 1. Objeto."),
                ("closing", self.issued()),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        publication = result["roles"]["publication_date"]
        self.assertEqual(publication["candidate_count"], 2)
        self.assertEqual(publication["trusted_candidate_count"], 1)
        self.assertEqual(publication["status"], "resolved")
        self.assertEqual(result["publication_date"], "2020-01-01")

    def test_no_commencement_clause_stays_unresolved_without_effective_event(self):
        extraction_id, _, document_id = self.fixture(
            "decreto_0006_2020.htm",
            [("text", self.publication()), ("closing", self.issued())],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["roles"]["commencement_rule"]["status"], "unresolved")
        self.assertIsNone(result["effective_date"])
        con = sqlite3.connect(self.db)
        try:
            count = con.execute(
                """
                SELECT COUNT(*) FROM temporal_events
                WHERE entity_id=? AND event_type='enters_into_force'
                  AND status='validated'
                """,
                (document_id,),
            ).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            con.close()

    def test_multiple_commencement_clauses_are_ambiguous(self):
        extraction_id, _, _ = self.fixture(
            "decreto_0007_2020.htm",
            [
                ("text", self.publication()),
                ("closing", self.issued()),
                ("article", self.commencement(1)),
                ("article", self.commencement(2)),
            ],
        )
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        role = result["roles"]["commencement_rule"]
        self.assertEqual(role["status"], "ambiguous")
        self.assertEqual(role["candidate_count"], 2)
        self.assertIsNone(result["effective_date"])

    def test_decreto_1625_like_seventy_commencement_clauses_do_not_guess(self):
        segments: list[tuple[str, str]] = [
            ("text", self.publication()),
            ("closing", self.issued()),
        ]
        segments.extend(("article", self.commencement(i)) for i in range(1, 71))
        extraction_id, _, _ = self.fixture("decreto_1625_2016.htm", segments)
        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        role = result["roles"]["commencement_rule"]
        self.assertEqual(role["status"], "ambiguous")
        self.assertEqual(role["candidate_count"], 70)
        self.assertEqual(role["trusted_candidate_count"], 70)
        self.assertIsNone(role["promoted_candidate_id"])
        self.assertIsNone(result["effective_date"])

    def test_generated_event_retains_exact_segment_evidence(self):
        prefix = "METADATO: "
        suffix = " / FIN"
        publication_text = prefix + self.publication(5) + suffix
        extraction_id, _, document_id = self.fixture(
            "decreto_0008_2020.htm",
            [
                ("text", publication_text),
                ("closing", self.issued()),
                ("article", self.commencement()),
            ],
        )
        extract_temporality(extraction_id=extraction_id, db_path=self.db)
        con = sqlite3.connect(self.db)
        try:
            row = con.execute(
                """
                SELECT e.exact_quote, e.char_start, e.char_end,
                       es.char_start, e.extracted_segment_id, es.extracted_segment_id
                FROM temporal_events te
                JOIN temporal_event_evidence tee
                  ON tee.temporal_event_id=te.temporal_event_id
                 AND tee.evidence_role='publication_date_source'
                JOIN evidence e ON e.evidence_id=tee.evidence_id
                JOIN extracted_segments es
                  ON es.extracted_segment_id=e.extracted_segment_id
                WHERE te.entity_id=? AND te.event_type='published'
                  AND te.status='validated'
                """,
                (document_id,),
            ).fetchone()
            self.assertEqual(row[0], self.publication(5))
            self.assertEqual(row[1], row[3] + len(prefix))
            self.assertEqual(row[2] - row[1], len(self.publication(5)))
            self.assertEqual(row[4], row[5])
        finally:
            con.close()

    def test_dry_run_predicts_apply_is_idempotent_and_preserves_raw_hash(self):
        extraction_id, manifestation_id, _ = self.fixture(
            "decreto_0009_2020.htm",
            [
                ("text", self.publication()),
                ("closing", self.issued()),
                ("article", self.commencement()),
            ],
        )
        con = sqlite3.connect(self.db)
        try:
            before_rows = {
                table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "temporal_candidates",
                    "temporal_role_resolutions",
                    "temporal_events",
                    "review_queue",
                )
            }
            raw_before = con.execute(
                "SELECT sha256 FROM manifestations WHERE manifestation_id=?",
                (manifestation_id,),
            ).fetchone()[0]
        finally:
            con.close()

        preview = reprocess(
            db_path=self.db,
            apply=False,
            extraction_ids=[extraction_id],
        )
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["persistent_mutation"])
        self.assertEqual(preview["error_count"], 0)
        self.assertTrue(preview["raw_hash_registry_unchanged"])

        con = sqlite3.connect(self.db)
        try:
            after_preview_rows = {
                table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before_rows
            }
            raw_after_preview = con.execute(
                "SELECT sha256 FROM manifestations WHERE manifestation_id=?",
                (manifestation_id,),
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(after_preview_rows, before_rows)
        self.assertEqual(raw_after_preview, raw_before)

        applied = reprocess(
            db_path=self.db,
            apply=True,
            extraction_ids=[extraction_id],
        )
        self.assertEqual(applied["delta"], preview["delta"])
        self.assertTrue(applied["raw_hash_registry_unchanged"])

        second = reprocess(
            db_path=self.db,
            apply=True,
            extraction_ids=[extraction_id],
        )
        self.assertEqual(sum(second["delta"].values()), 0)
        self.assertFalse(second["persistent_mutation"])
        self.assertTrue(second["raw_hash_registry_unchanged"])

    def test_v2_events_are_superseded_without_deleting_evidence(self):
        extraction_id, manifestation_id, document_id = self.fixture(
            "decreto_0010_2020.htm",
            [
                ("text", self.publication()),
                ("closing", self.issued()),
                ("article", self.commencement(1)),
                ("article", self.commencement(2)),
            ],
        )
        con = sqlite3.connect(self.db)
        try:
            segment_id = con.execute(
                """
                SELECT extracted_segment_id FROM extracted_segments
                WHERE extraction_id=? ORDER BY sequence_no LIMIT 1
                """,
                (extraction_id,),
            ).fetchone()[0]
            source_url, raw_hash, retrieved_at = con.execute(
                """
                SELECT s.source_url, m.sha256, m.retrieved_at
                FROM manifestations m JOIN sources s ON s.source_id=m.source_id
                WHERE m.manifestation_id=?
                """,
                (manifestation_id,),
            ).fetchone()
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, segment_id,
                    page_number, char_start, char_end, exact_quote, source_url,
                    source_sha256, retrieved_at, extraction_method,
                    extractor_version, confidence, review_status,
                    extracted_segment_id
                ) VALUES ('EVD-v2', NULL, ?, NULL, NULL, 0, 10, 'legacy', ?, ?, ?,
                          'document_temporality_regex:2:effective_on_publication',
                          '2', 1.0, 'machine_validated', ?)
                """,
                (manifestation_id, source_url, raw_hash, retrieved_at, segment_id),
            )
            con.execute(
                """
                INSERT INTO temporal_events(
                    temporal_event_id, entity_type, entity_id, event_type,
                    event_date, effective_from, effective_to, caused_by_type,
                    caused_by_id, scope, status, evidence_id, confidence,
                    requires_human_review
                ) VALUES ('TEV-v2', 'document', ?, 'enters_into_force',
                          '2020-01-01', '2020-01-01', NULL, NULL, NULL,
                          'document', 'validated', 'EVD-v2', 1.0, 0)
                """,
                (document_id,),
            )
            con.execute(
                """
                INSERT INTO temporal_event_evidence(
                    temporal_event_id, evidence_id, evidence_role, created_at
                ) VALUES ('TEV-v2', 'EVD-v2', 'commencement_rule', ?)
                """,
                (NOW,),
            )
            con.execute(
                """
                INSERT INTO relationships(
                    relationship_id, source_type, source_id, relation_type,
                    target_type, target_id, scope, asserted_date, effective_date,
                    end_date, status, evidence_id, confidence,
                    requires_human_review
                ) VALUES ('REL-v2', 'document', ?, 'modifies', 'document',
                          'DOC-target', 'document', NULL, '2020-01-01', NULL,
                          'validated', NULL, 1.0, 0)
                """,
                (document_id,),
            )
            con.execute(
                """
                INSERT INTO relationship_temporal_basis(
                    relationship_id, temporal_event_id, basis_role, created_at
                ) VALUES ('REL-v2', 'TEV-v2', 'effective_date', ?)
                """,
                (NOW,),
            )
            con.commit()
        finally:
            con.close()

        result = extract_temporality(extraction_id=extraction_id, db_path=self.db)
        self.assertEqual(result["roles"]["commencement_rule"]["status"], "ambiguous")
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT status FROM temporal_events WHERE temporal_event_id='TEV-v2'"
                ).fetchone()[0],
                "superseded",
            )
            self.assertIsNotNone(
                con.execute(
                    "SELECT evidence_id FROM evidence WHERE evidence_id='EVD-v2'"
                ).fetchone()
            )
            self.assertIsNone(
                con.execute(
                    "SELECT effective_date FROM relationships WHERE relationship_id='REL-v2'"
                ).fetchone()[0]
            )
            self.assertIsNone(
                con.execute(
                    """
                    SELECT 1 FROM relationship_temporal_basis
                    WHERE relationship_id='REL-v2' AND basis_role='effective_date'
                    """
                ).fetchone()
            )
        finally:
            con.close()

    def test_schema_upgrade_from_013_to_014_and_fresh_init(self):
        upgrade_db = Path(self.tmp.name) / "upgrade.sqlite"
        con = sqlite3.connect(upgrade_db)
        try:
            migrations = sorted((ROOT / "schema").glob("*.sql"))
            for migration in migrations:
                if migration.name >= "014_":
                    break
                con.executescript(migration.read_text(encoding="utf-8"))
            con.executescript(
                (ROOT / "schema" / "014_temporal_candidates.sql").read_text(
                    encoding="utf-8"
                )
            )
            for table in ("temporal_candidates", "temporal_role_resolutions"):
                self.assertIsNotNone(
                    con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                )
        finally:
            con.close()

        con = sqlite3.connect(self.db)
        try:
            self.assertIsNotNone(
                con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='temporal_candidates'"
                ).fetchone()
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
