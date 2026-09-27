from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_evidence_graph import (  # noqa: E402
    ANCHOR_VERSION,
    EvidenceGraphIntegrityError,
    _candidate_span,
    _stable_ref,
)
from case_retrieval import (  # noqa: E402
    CorpusRetrievalService,
    RetrievalIntegrityError,
)


NOW = "2026-09-27T12:00:00+00:00"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Issue0183EmptyNormativeTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "issue183.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_observation(
        self,
        *,
        segment_text: str,
        normative_text: str,
        normative_sha256: str | None = None,
    ) -> dict[str, str]:
        document_id = "DOC-issue183"
        source_id = "SRC-issue183"
        manifestation_id = "MAN-issue183"
        extraction_id = "EXT-issue183"
        segment_id = "SEG-issue183"
        provision_id = "PROV-issue183"
        observation_id = "POBS-issue183"
        source_url = "https://normograma.dian.gov.co/issue183.htm"
        raw_sha = sha256_text("raw:" + source_url)
        segment_sha = sha256_text(segment_text)
        normative_sha = normative_sha256 or sha256_text(normative_text)

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'CONGRESO', 'LEY', 'LEY 183 DE 2026',
                          '2026-01-01', NULL, ?, ?)
                """,
                (document_id, NOW, NOW),
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
                ) VALUES (?, ?, ?, 'text/html', ?, ?, ?, ?, 'fixture')
                """,
                (
                    manifestation_id,
                    document_id,
                    source_id,
                    raw_sha,
                    len(segment_text.encode("utf-8")),
                    NOW,
                    "raw/issue183.html",
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size,
                    char_count, segment_count, local_path, created_at, status
                ) VALUES (?, ?, 'fixture', '1', ?, ?, ?, 1, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    sha256_text("normalized:" + segment_text),
                    len(segment_text.encode("utf-8")),
                    len(segment_text),
                    "extracted/issue183.txt",
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
                    segment_id,
                    extraction_id,
                    len(segment_text),
                    segment_text,
                    segment_sha,
                ),
            )
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES (?, ?, 'article', 'Artículo 1', 'articulo 1',
                          NULL, ?, ?)
                """,
                (provision_id, document_id, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO provision_observations(
                    provision_observation_id, provision_id, extraction_id,
                    extracted_segment_id, observed_text, normative_text,
                    editorial_note, observed_text_sha256,
                    normative_text_sha256, observed_at,
                    parser_name, parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?,
                          'fixture', '1')
                """,
                (
                    observation_id,
                    provision_id,
                    extraction_id,
                    segment_id,
                    segment_text,
                    normative_text,
                    segment_sha,
                    normative_sha,
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()

        return {
            "document_id": document_id,
            "source_id": source_id,
            "source_url": source_url,
            "manifestation_id": manifestation_id,
            "manifestation_sha256": raw_sha,
            "extraction_id": extraction_id,
            "segment_id": segment_id,
            "segment_text": segment_text,
            "segment_sha256": segment_sha,
            "provision_id": provision_id,
            "observation_id": observation_id,
            "normative_text": normative_text,
            "normative_sha256": normative_sha,
        }

    def candidate(self, fixture: dict[str, str], *, with_provision: bool) -> dict:
        candidate = {
            "extracted_segment_id": fixture["segment_id"],
            "extraction_id": fixture["extraction_id"],
            "sequence_no": 1,
            "text": fixture["segment_text"],
            "text_sha256": fixture["segment_sha256"],
            "manifestation_id": fixture["manifestation_id"],
            "manifestation_sha256": fixture["manifestation_sha256"],
            "source_ref": f"source:{fixture['source_id']}",
            "source_url": fixture["source_url"],
            "document_ref": f"document:{fixture['document_id']}",
            "authority_ref": f"authority:{fixture['document_id']}",
        }
        if with_provision:
            candidate["provision_ref"] = f"provision:{fixture['provision_id']}"
        return candidate

    def test_empty_normative_text_is_not_retrieval_eligible(self) -> None:
        fixture = self.add_observation(
            segment_text=(
                "ARTÍCULO 1. La persona natural debe declarar renta cuando "
                "se cumplan los supuestos legales."
            ),
            normative_text="",
        )
        con = sqlite3.connect(self.db)
        try:
            retrieval = CorpusRetrievalService(con)
            self.assertIsNone(
                retrieval.provision_for_segment(fixture["segment_id"])
            )
        finally:
            con.close()

    def test_stale_empty_provision_candidate_becomes_segment_only_evidence(self) -> None:
        fixture = self.add_observation(
            segment_text=(
                "ARTÍCULO 1. La persona natural debe declarar renta cuando "
                "se cumplan los supuestos legales."
            ),
            normative_text="",
        )
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            span, statement = _candidate_span(
                con,
                self.candidate(fixture, with_provision=True),
            )
        finally:
            con.close()

        self.assertIsNotNone(span)
        self.assertIsNotNone(statement)
        assert span is not None
        assert statement is not None
        self.assertNotIn("provision_ref", span)
        self.assertEqual(span["exact_text"], fixture["segment_text"])
        self.assertEqual(span["text_sha256"], fixture["segment_sha256"])
        self.assertIsNone(statement["provision"])
        self.assertEqual(
            span["evidence_ref"],
            _stable_ref(
                "evidence",
                "research",
                fixture["manifestation_id"],
                fixture["segment_id"],
                None,
                fixture["segment_sha256"],
                ANCHOR_VERSION,
            ),
        )

    def test_repeated_normative_text_never_uses_a_guessed_anchor(self) -> None:
        normative = "debe declarar renta"
        fixture = self.add_observation(
            segment_text=(
                "La persona debe declarar renta en el supuesto A y también "
                "debe declarar renta en el supuesto B."
            ),
            normative_text=normative,
        )
        con = sqlite3.connect(self.db)
        try:
            retrieval = CorpusRetrievalService(con)
            self.assertIsNone(
                retrieval.provision_for_segment(fixture["segment_id"])
            )
        finally:
            con.close()

        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            span, statement = _candidate_span(
                con,
                self.candidate(fixture, with_provision=True),
            )
        finally:
            con.close()

        assert span is not None
        assert statement is not None
        self.assertNotIn("provision_ref", span)
        self.assertEqual(span["exact_text"], fixture["segment_text"])
        self.assertIsNone(statement["provision"])

    def test_valid_exact_provision_preserves_hash_and_provenance_contract(self) -> None:
        normative = "La persona natural debe declarar renta."
        fixture = self.add_observation(
            segment_text=f"ARTÍCULO 1. {normative} Fin.",
            normative_text=normative,
        )

        con = sqlite3.connect(self.db)
        try:
            retrieval = CorpusRetrievalService(con)
            provision = retrieval.provision_for_segment(fixture["segment_id"])
        finally:
            con.close()
        self.assertEqual(provision["provision_id"], fixture["provision_id"])

        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            span, statement = _candidate_span(
                con,
                self.candidate(fixture, with_provision=True),
            )
        finally:
            con.close()

        assert span is not None
        assert statement is not None
        provision_ref = f"provision:{fixture['provision_id']}"
        self.assertEqual(span["provision_ref"], provision_ref)
        self.assertEqual(span["exact_text"], normative)
        self.assertEqual(span["text_sha256"], sha256_text(normative))
        self.assertEqual(
            span["evidence_ref"],
            _stable_ref(
                "evidence",
                "research",
                fixture["manifestation_id"],
                fixture["segment_id"],
                provision_ref,
                sha256_text(normative),
                ANCHOR_VERSION,
            ),
        )
        self.assertEqual(
            span["provenance_ref"],
            _stable_ref(
                "provenance",
                "provision_observation",
                fixture["observation_id"],
                "fixture",
                "1",
                fixture["manifestation_id"],
                fixture["segment_id"],
                sha256_text(normative),
            ),
        )
        self.assertEqual(
            statement["provision"]["provision_ref"],
            provision_ref,
        )

    def test_normative_hash_mismatch_remains_integrity_failure(self) -> None:
        fixture = self.add_observation(
            segment_text="ARTÍCULO 1. La persona natural debe declarar renta.",
            normative_text="La persona natural debe declarar renta.",
            normative_sha256="0" * 64,
        )
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(RetrievalIntegrityError):
                CorpusRetrievalService(con).provision_for_segment(
                    fixture["segment_id"]
                )
        finally:
            con.close()

        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            with self.assertRaises(EvidenceGraphIntegrityError):
                _candidate_span(
                    con,
                    self.candidate(fixture, with_provision=True),
                )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
