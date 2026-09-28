from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_retrieval import CorpusRetrievalService, RetrievalIntegrityError


NOW = "2026-09-28T07:00:00+00:00"
REPEATED_TEXT = (
    "fraccion ano para obligaciones tributarias: este bloque regulatorio exacto "
    "se repite dentro de la misma extracción y debe conservar toda su evidencia "
    "sin consumir más de una posición normal de recuperación."
)
SIMILAR_TEXT = (
    "fraccion ano para obligaciones tributarias: este bloque es parecido pero "
    "contiene una regla distinta y por tanto no debe deduplicarse por similitud."
)


class Def0005RetrievalDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "retrieval.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _add_document(
        self,
        *,
        token: str,
        texts: list[str],
    ) -> list[str]:
        document_id = f"DOC-{token}"
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        source_url = f"https://example.test/{token}.htm"
        raw_sha = hashlib.sha256(f"raw:{token}".encode()).hexdigest()
        normalized = "\n".join(texts)
        normalized_sha = hashlib.sha256(normalized.encode()).hexdigest()

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'DIAN', 'RESOLUCIÓN', ?, '2026-01-01',
                          NULL, ?, ?)
                """,
                (document_id, f"Resolución fixture {token}", NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, 'DIAN', 'official_html', NULL, ?, ?)
                """,
                (source_id, source_url, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (?, ?, ?, 'text/html', ?, ?, ?, ?, 'fixture-1')
                """,
                (
                    manifestation_id,
                    document_id,
                    source_id,
                    raw_sha,
                    len(normalized.encode()),
                    NOW,
                    f"raw/{token}.html",
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size,
                    char_count, segment_count, local_path, created_at, status
                ) VALUES (?, ?, 'fixture', '1', ?, ?, ?, ?, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    normalized_sha,
                    len(normalized.encode()),
                    len(normalized),
                    len(texts),
                    f"extracted/{token}.txt",
                    NOW,
                ),
            )

            segment_ids: list[str] = []
            offset = 0
            for sequence_no, text in enumerate(texts, start=1):
                segment_id = f"SEG-{token}-{sequence_no:02d}"
                segment_ids.append(segment_id)
                text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                con.execute(
                    """
                    INSERT INTO extracted_segments(
                        extracted_segment_id, extraction_id, sequence_no,
                        segment_type, section_path, char_start, char_end,
                        text, text_sha256
                    ) VALUES (?, ?, ?, 'paragraph', NULL, ?, ?, ?, ?)
                    """,
                    (
                        segment_id,
                        extraction_id,
                        sequence_no,
                        offset,
                        offset + len(text),
                        text,
                        text_sha,
                    ),
                )
                con.execute(
                    """
                    INSERT INTO extracted_segments_fts(
                        extracted_segment_id, text, section_path
                    ) VALUES (?, ?, NULL)
                    """,
                    (segment_id, text),
                )
                offset += len(text) + 1
            con.commit()
        finally:
            con.close()
        return segment_ids

    def _search(self, *, limit: int = 3):
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            return CorpusRetrievalService(con).search("fraccion ano", limit=limit)
        finally:
            con.close()

    def test_exact_duplicates_fill_one_slot_and_preserve_alternate_provenance(self):
        repeated_ids = self._add_document(
            token="primary",
            texts=[REPEATED_TEXT] * 12 + [SIMILAR_TEXT],
        )
        other_document_ids = self._add_document(
            token="other",
            texts=[REPEATED_TEXT],
        )

        before_bytes = hashlib.sha256(self.db.read_bytes()).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            before_counts = con.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM extracted_segments),
                    (SELECT COUNT(*) FROM extracted_segments_fts)
                """
            ).fetchone()
        finally:
            con.close()

        first = self._search(limit=3)
        second = self._search(limit=3)

        after_bytes = hashlib.sha256(self.db.read_bytes()).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            after_counts = con.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM extracted_segments),
                    (SELECT COUNT(*) FROM extracted_segments_fts)
                """
            ).fetchone()
        finally:
            con.close()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(before_bytes, after_bytes)
        self.assertEqual(before_counts, after_counts)

        repeated_sha = hashlib.sha256(REPEATED_TEXT.encode("utf-8")).hexdigest()
        similar_sha = hashlib.sha256(SIMILAR_TEXT.encode("utf-8")).hexdigest()
        repeated_hits = [hit for hit in first if hit.text_sha256 == repeated_sha]
        similar_hits = [hit for hit in first if hit.text_sha256 == similar_sha]

        # The exact phrase remains independently retrievable from the other
        # document/extraction, while one extraction's 12 copies occupy one slot.
        self.assertEqual(len(repeated_hits), 2)
        self.assertEqual(len(similar_hits), 1)

        primary = next(hit for hit in repeated_hits if hit.extraction_id == "EXT-primary")
        other = next(hit for hit in repeated_hits if hit.extraction_id == "EXT-other")
        self.assertEqual(primary.extracted_segment_id, repeated_ids[0])
        self.assertEqual(primary.duplicate_count, 12)
        self.assertEqual(
            primary.alternate_segment_ids,
            tuple(repeated_ids[1:]),
        )
        self.assertEqual(other.extracted_segment_id, other_document_ids[0])
        self.assertEqual(other.duplicate_count, 1)
        self.assertEqual(other.alternate_segment_ids, ())
        self.assertEqual(similar_hits[0].duplicate_count, 1)

    def test_corrupt_alternate_row_is_not_exposed_as_equivalent_provenance(self):
        repeated_ids = self._add_document(
            token="corrupt",
            texts=[REPEATED_TEXT] * 2,
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE extracted_segments SET text = ? WHERE extracted_segment_id = ?",
                ("corrupted alternate text", repeated_ids[1]),
            )
            con.commit()
        finally:
            con.close()

        with self.assertRaises(RetrievalIntegrityError):
            self._search(limit=1)


if __name__ == "__main__":
    unittest.main()
