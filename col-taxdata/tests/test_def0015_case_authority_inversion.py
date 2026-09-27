from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_retrieval import CorpusRetrievalService


NOW = "2026-09-27T05:00:00+00:00"
SOURCE_SHA256 = "a" * 64
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "def0015_webcam_authority_inversion.json"


class Def0015AuthorityInversionCharacterizationTests(unittest.TestCase):
    """Freeze the current v3 research dependency without treating it as correct."""

    def setUp(self) -> None:
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "state.sqlite"
        self._apply_migrations()
        self._seed_canonical_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apply_migrations(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def _seed_canonical_fixture(self) -> None:
        canonical = self.fixture["canonical_segment"]
        text = canonical["text"]
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type,
                    title, issued_date, publication_date,
                    created_at, updated_at
                ) VALUES (?, 'CO', 'TEST', 'DECRETO',
                          'DEF-0015 synthetic canonical document',
                          '2026-01-01', NULL, ?, ?)
                """,
                (canonical["document_id"], NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES (
                    'ID-DEF0015', ?, 'number', 'DEF0015', 'TEST', 1
                )
                """,
                (canonical["document_id"],),
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (
                    ?, 'https://example.test/def0015', 'fixture',
                    'normograma_html', NULL, ?, ?
                )
                """,
                (canonical["source_id"], NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (
                    ?, ?, ?, 'text/html', ?, ?, ?,
                    'raw/def0015-fixture', 'fixture-1'
                )
                """,
                (
                    canonical["manifestation_id"],
                    canonical["document_id"],
                    canonical["source_id"],
                    SOURCE_SHA256,
                    len(text.encode("utf-8")),
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size,
                    char_count, segment_count, local_path, created_at, status
                ) VALUES (
                    ?, ?, 'fixture', '1', ?, ?, ?, 1,
                    'extracted/def0015-fixture', ?, 'success'
                )
                """,
                (
                    canonical["extraction_id"],
                    canonical["manifestation_id"],
                    hashlib.sha256(("normalized:" + text).encode("utf-8")).hexdigest(),
                    len(text.encode("utf-8")),
                    len(text),
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO extracted_segments(
                    extracted_segment_id, extraction_id, sequence_no,
                    segment_type, section_path, char_start, char_end,
                    text, text_sha256
                ) VALUES (?, ?, 1, 'paragraph', NULL, 0, ?, ?, ?)
                """,
                (
                    canonical["extracted_segment_id"],
                    canonical["extraction_id"],
                    len(text),
                    text,
                    text_sha256,
                ),
            )
            con.execute(
                """
                INSERT INTO extracted_segments_fts(
                    extracted_segment_id, text, section_path
                ) VALUES (?, ?, NULL)
                """,
                (canonical["extracted_segment_id"], text),
            )
            con.commit()
        finally:
            con.close()

    def _service(self) -> tuple[sqlite3.Connection, CorpusRetrievalService]:
        con = sqlite3.connect(self.db_path)
        return con, CorpusRetrievalService(con)

    def test_domain_word_is_absent_from_general_rule_fixture(self) -> None:
        problem = self.fixture["case_input"]["problem_text"].casefold()
        rule = self.fixture["canonical_segment"]["text"].casefold()

        self.assertIn("webcam", problem)
        self.assertNotIn("webcam", rule)

    def test_current_candidate_query_is_model_text_plus_model_hints(self) -> None:
        candidate = self.fixture["model_candidate"]
        expected_query = " ".join(
            [candidate["text"], *candidate["target_hints"]]
        )
        con, retrieval = self._service()
        try:
            with mock.patch.object(
                retrieval,
                "search",
                wraps=retrieval.search,
            ) as search:
                hits = retrieval.search_candidate(candidate)

            self.assertEqual(search.call_args.args[0], expected_query)
            self.assertEqual(hits, [])
        finally:
            con.close()

    def test_neutral_legal_terms_retrieve_relevant_canonical_segment(self) -> None:
        canonical = self.fixture["canonical_segment"]
        con, retrieval = self._service()
        try:
            hits = retrieval.search(self.fixture["neutral_query"])
        finally:
            con.close()

        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.extracted_segment_id, canonical["extracted_segment_id"])
        self.assertEqual(hit.extraction_id, canonical["extraction_id"])
        self.assertEqual(hit.manifestation_id, canonical["manifestation_id"])
        self.assertEqual(hit.source_id, canonical["source_id"])
        self.assertEqual(hit.document_id, canonical["document_id"])
        self.assertEqual(hit.manifestation_sha256, SOURCE_SHA256)
        self.assertEqual(
            hit.text_sha256,
            hashlib.sha256(canonical["text"].encode("utf-8")).hexdigest(),
        )

    def test_relevant_evidence_does_not_promote_unrelated_model_prose(self) -> None:
        candidate = self.fixture["model_candidate"]
        con, retrieval = self._service()
        try:
            neutral_hits = retrieval.search(self.fixture["neutral_query"])
            supports = retrieval.exact_canonical_support(candidate, neutral_hits)
        finally:
            con.close()

        self.assertEqual(len(neutral_hits), 1)
        self.assertEqual(supports, [])


if __name__ == "__main__":
    unittest.main()
