from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cleanup_unreferenced_documents import (  # noqa: E402
    RETAIN_ACTIVE,
    RETAIN_CONFLICT,
    RETAIN_PROVENANCE,
    classify_document,
    cleanup,
)


NOW = "2026-09-24T00:00:00+00:00"


class Def0009DocumentLifecycleTests(unittest.TestCase):
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

    def add_document(self, canonical_key: str, *, token: str) -> str:
        document_id = f"DOC-{token}"
        document_type = canonical_key.split(":")[-3]
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'UNKNOWN', ?, ?, NULL, NULL, ?, ?)
                """,
                (document_id, document_type, canonical_key, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES (?, ?, 'canonical_key', ?, NULL, 1)
                """,
                (f"ID-{token}", document_id, canonical_key),
            )
            con.commit()
        finally:
            con.close()
        return document_id

    def add_support_manifestation(self, token: str) -> tuple[str, str, str]:
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        source_url = f"https://example.invalid/{token}.html"
        sha = hashlib.sha256(token.encode()).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, 'TEST', 'fixture', NULL, ?, ?)
                """,
                (source_id, source_url, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (?, NULL, ?, 'text/html', ?, 10, ?, ?, 'fixture')
                """,
                (
                    manifestation_id,
                    source_id,
                    sha,
                    NOW,
                    f"raw/{token}.html",
                ),
            )
            con.commit()
        finally:
            con.close()
        return manifestation_id, source_url, sha

    def add_identifier_evidence(
        self, document_id: str, *, token: str, valid_sha: bool = True
    ) -> None:
        manifestation_id, source_url, sha = self.add_support_manifestation(token)
        evidence_id = f"EVD-{token}"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, segment_id,
                    page_number, char_start, char_end, exact_quote,
                    source_url, source_sha256, retrieved_at,
                    extraction_method, extractor_version, confidence,
                    review_status, extracted_segment_id
                ) VALUES (?, NULL, ?, NULL, NULL, 0, 10, ?, ?, ?, ?,
                          'fixture', '1', 1.0, 'unreviewed', NULL)
                """,
                (
                    evidence_id,
                    manifestation_id,
                    "identity text",
                    source_url,
                    sha if valid_sha else "0" * 64,
                    NOW,
                ),
            )
            identifier_id = con.execute(
                """
                SELECT identifier_id
                FROM document_identifiers
                WHERE document_id = ? AND is_primary = 1
                """,
                (document_id,),
            ).fetchone()[0]
            con.execute(
                """
                INSERT INTO document_identifier_evidence(
                    identifier_id, evidence_id, evidence_role, created_at
                ) VALUES (?, ?, 'identity', ?)
                """,
                (identifier_id, evidence_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def add_reference_resolution(
        self, document_id: str, canonical_key: str, *, token: str
    ) -> None:
        manifestation_id, _, _ = self.add_support_manifestation(token)
        extraction_id = f"EXT-{token}"
        segment_id = f"SEG-{token}"
        run_id = f"RDR-{token}"
        mention_id = f"REF-{token}"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size, char_count,
                    segment_count, local_path, created_at, status
                ) VALUES (?, ?, 'fixture', '1', ?, 10, 10, 1, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    hashlib.sha256((token + "-norm").encode()).hexdigest(),
                    f"normalized/{token}.txt",
                    NOW,
                ),
            )
            text = canonical_key
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
                    len(text),
                    text,
                    hashlib.sha256(text.encode()).hexdigest(),
                ),
            )
            con.execute(
                """
                INSERT INTO reference_detection_runs(
                    detection_run_id, extraction_id, detector_name,
                    detector_version, mention_count, relation_count,
                    created_at, status
                ) VALUES (?, ?, 'fixture', '1', 1, 0, ?, 'success')
                """,
                (run_id, extraction_id, NOW),
            )
            parts = canonical_key.split(":")
            con.execute(
                """
                INSERT INTO reference_mentions(
                    reference_mention_id, detection_run_id, extraction_id,
                    extracted_segment_id, mention_type, raw_text, context_text,
                    normalized_reference, target_document_key,
                    target_document_type, target_document_number,
                    target_document_year, article_designation,
                    char_start, char_end, detection_method, confidence,
                    requires_human_review, status, target_issuer
                ) VALUES (?, ?, ?, ?, 'document', ?, ?, ?, ?, ?, ?, ?, NULL,
                          0, ?, 'fixture:1', 1.0, 0, 'resolved', NULL)
                """,
                (
                    mention_id,
                    run_id,
                    extraction_id,
                    segment_id,
                    canonical_key,
                    canonical_key,
                    canonical_key,
                    canonical_key,
                    parts[-3],
                    parts[-2],
                    int(parts[-1]),
                    len(canonical_key),
                ),
            )
            con.execute(
                """
                INSERT INTO reference_resolutions(
                    reference_resolution_id, reference_mention_id,
                    target_document_id, target_provision_id,
                    resolution_method, confidence, status,
                    requires_human_review, created_at
                ) VALUES (?, ?, ?, NULL, 'fixture:1', 1.0, 'resolved', 0, ?)
                """,
                (f"RRES-{token}", mention_id, document_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def classification(self, document_id: str):
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA foreign_keys = ON")
        try:
            return classify_document(con, document_id)
        finally:
            con.close()

    def test_known_def0001_residue_is_previewed_then_cleaned_idempotently(self):
        stale_id = self.add_document(
            "CO:RESOLUCION:33933:2025",
            token="known-residue",
        )
        _, _, raw_sha = self.add_support_manifestation("unrelated-raw")

        preview = cleanup(db_path=self.db, apply=False)
        self.assertEqual(preview["candidate_delete_count"], 1)
        self.assertEqual(preview["deleted_documents"], 0)
        self.assertFalse(preview["persistent_mutation"])
        self.assertEqual(
            preview["candidate_deletes"][0]["canonical_keys"],
            ("CO:RESOLUCION:33933:2025",),
        )

        con = sqlite3.connect(self.db)
        try:
            self.assertIsNotNone(
                con.execute(
                    "SELECT 1 FROM documents WHERE document_id = ?",
                    (stale_id,),
                ).fetchone()
            )
        finally:
            con.close()

        applied = cleanup(db_path=self.db, apply=True)
        self.assertEqual(applied["deleted_documents"], 1)
        self.assertTrue(applied["hashes_unchanged"])

        con = sqlite3.connect(self.db)
        try:
            self.assertIsNone(
                con.execute(
                    "SELECT 1 FROM documents WHERE document_id = ?",
                    (stale_id,),
                ).fetchone()
            )
            self.assertEqual(
                con.execute(
                    """
                    SELECT sha256
                    FROM manifestations
                    WHERE manifestation_id = ?
                    """,
                    ("MAN-unrelated-raw",),
                ).fetchone()[0],
                raw_sha,
            )
        finally:
            con.close()

        second = cleanup(db_path=self.db, apply=True)
        self.assertEqual(second["candidate_delete_count"], 0)
        self.assertEqual(second["deleted_documents"], 0)
        self.assertFalse(second["persistent_mutation"])

    def test_explicit_identifier_evidence_allows_source_less_document(self):
        document_id = self.add_document(
            "CO:LEY:999:2026",
            token="placeholder-evidence",
        )
        self.add_identifier_evidence(
            document_id,
            token="placeholder-support",
            valid_sha=True,
        )

        classification = self.classification(document_id)
        self.assertEqual(classification.classification, RETAIN_PROVENANCE)

        applied = cleanup(db_path=self.db, apply=True)
        self.assertEqual(applied["deleted_documents"], 0)
        con = sqlite3.connect(self.db)
        try:
            self.assertIsNotNone(
                con.execute(
                    "SELECT 1 FROM documents WHERE document_id = ?",
                    (document_id,),
                ).fetchone()
            )
        finally:
            con.close()

    def test_reference_only_document_is_retained(self):
        document_id = self.add_document(
            "CO:LEY:643:2001",
            token="reference-target",
        )
        self.add_reference_resolution(
            document_id,
            "CO:LEY:643:2001",
            token="reference-source",
        )

        classification = self.classification(document_id)
        self.assertEqual(classification.classification, RETAIN_ACTIVE)
        self.assertTrue(
            any(
                reason.detail == "reference_resolutions.target_document_id"
                for reason in classification.reasons
            )
        )
        applied = cleanup(db_path=self.db, apply=True)
        self.assertEqual(applied["deleted_documents"], 0)

    def test_other_active_document_bindings_are_never_cascade_deleted(self):
        document_id = self.add_document(
            "CO:LEY:777:2026",
            token="active",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES ('PROV-active', ?, 'article', '1', '1', NULL, ?, ?)
                """,
                (document_id, NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO relationships(
                    relationship_id, source_type, source_id, relation_type,
                    target_type, target_id, scope, asserted_date,
                    effective_date, end_date, status, evidence_id,
                    confidence, requires_human_review
                ) VALUES (
                    'REL-active', 'document', ?, 'references', 'document',
                    'DOC-other', NULL, NULL, NULL, NULL, 'candidate',
                    NULL, NULL, 0
                )
                """,
                (document_id,),
            )
            con.execute(
                """
                INSERT INTO temporal_events(
                    temporal_event_id, entity_type, entity_id, event_type,
                    event_date, effective_from, effective_to, caused_by_type,
                    caused_by_id, scope, status, evidence_id, confidence,
                    requires_human_review
                ) VALUES (
                    'TEV-active', 'document', ?, 'published', NULL, NULL, NULL,
                    NULL, NULL, NULL, 'candidate', NULL, NULL, 0
                )
                """,
                (document_id,),
            )
            con.execute(
                """
                INSERT INTO cases(
                    case_id, title, query_text, as_of_date, status,
                    created_at, updated_at
                ) VALUES (
                    'CASE-active', 'Fixture', 'Fixture', NULL, 'open', ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO case_items(
                    case_id, item_type, item_id, relevance, added_at
                ) VALUES ('CASE-active', 'document', ?, 'fixture', ?)
                """,
                (document_id, NOW),
            )
            con.commit()
        finally:
            con.close()

        classification = self.classification(document_id)
        self.assertEqual(classification.classification, RETAIN_ACTIVE)
        applied = cleanup(db_path=self.db, apply=True)
        self.assertEqual(applied["deleted_documents"], 0)

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM provisions WHERE document_id = ?",
                    (document_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM case_items WHERE item_id = ?",
                    (document_id,),
                ).fetchone()[0],
                1,
            )
        finally:
            con.close()

    def test_invalid_identifier_provenance_is_retained_as_conflict(self):
        document_id = self.add_document(
            "CO:LEY:888:2026",
            token="bad-provenance",
        )
        self.add_identifier_evidence(
            document_id,
            token="bad-support",
            valid_sha=False,
        )

        classification = self.classification(document_id)
        self.assertEqual(classification.classification, RETAIN_CONFLICT)
        self.assertEqual(
            classification.reasons[0].code,
            "INVALID_IDENTIFIER_EVIDENCE_CHAIN",
        )
        applied = cleanup(db_path=self.db, apply=True)
        self.assertEqual(applied["deleted_documents"], 0)


if __name__ == "__main__":
    unittest.main()
