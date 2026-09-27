from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import test_issue0138_citable_evidence_graph as issue138

from case_evidence_graph import (
    ANCHOR_VERSION,
    _stable_ref,
    build_legal_research_bundle,
)
from case_research import PlatformResearchService


NOW = issue138.NOW
ARTICLE_592 = issue138.ARTICLE_592
case_input = issue138.case_input
intake = issue138.intake


class Issue0186CanonicalSpanIdentityTests(unittest.TestCase):
    setUp = issue138.Issue0138CitableEvidenceGraphTests.setUp
    tearDown = issue138.Issue0138CitableEvidenceGraphTests.tearDown
    add_provision_document = (
        issue138.Issue0138CitableEvidenceGraphTests.add_provision_document
    )

    def add_duplicate_canonical_evidence(
        self,
        *,
        token: str,
        source_evidence_id: str,
        duplicate_evidence_id: str,
    ) -> None:
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
                )
                SELECT
                    ?, claim_id, manifestation_id, segment_id,
                    page_number, char_start, char_end, exact_quote,
                    source_url, source_sha256, retrieved_at,
                    extraction_method, extractor_version, confidence,
                    review_status, extracted_segment_id
                FROM evidence
                WHERE evidence_id = ?
                """,
                (duplicate_evidence_id, source_evidence_id),
            )
            con.execute(
                """
                INSERT INTO document_identifier_evidence(
                    identifier_id, evidence_id, evidence_role, created_at
                ) VALUES (?, ?, 'identity', ?)
                """,
                (f"ID-{token}", duplicate_evidence_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def research(self):
        return PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

    def build(self, research):
        return build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=intake(),
            research=research,
            db_path=self.db,
        )

    def test_duplicate_physical_anchor_keeps_both_canonical_evidence_objects(self):
        fixture = self.add_provision_document(
            token="duplicate",
            document_id="DOC-duplicate",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989_duplicate.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        duplicate_id = "EVD-duplicate-second"
        self.add_duplicate_canonical_evidence(
            token="duplicate",
            source_evidence_id=fixture["evidence_id"],
            duplicate_evidence_id=duplicate_id,
        )

        research = self.research()
        first = self.build(research)
        second = self.build(research)

        wanted = {
            f"evidence:{fixture['evidence_id']}",
            f"evidence:{duplicate_id}",
        }
        spans = [
            item for item in first["evidence_spans"]
            if item["evidence_ref"] in wanted
        ]
        self.assertEqual(len(spans), 2)
        self.assertEqual({item["evidence_ref"] for item in spans}, wanted)
        self.assertEqual(len({item["span_ref"] for item in spans}), 2)

        self.assertEqual(
            {item["authority_ref"] for item in spans},
            {"authority:DOC-duplicate"},
        )
        self.assertEqual(
            {item["document_ref"] for item in spans},
            {"document:DOC-duplicate"},
        )
        self.assertEqual(
            {item["source_ref"] for item in spans},
            {f"source:{fixture['source_id']}"},
        )
        self.assertEqual(
            {item["source_sha256"] for item in spans},
            {fixture["raw_sha"]},
        )
        self.assertEqual(
            {item["text_sha256"] for item in spans},
            {fixture["text_sha"]},
        )
        self.assertEqual(
            {item["exact_text"] for item in spans},
            {ARTICLE_592},
        )

        self.assertEqual(first, second)
        self.assertEqual(first["bundle_ref"], second["bundle_ref"])

    def test_research_derived_span_identity_formula_is_unchanged(self):
        fixture = self.add_provision_document(
            token="research",
            document_id="DOC-research",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989_research.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        research = self.research()
        bundle = self.build(research)

        derived = next(
            item
            for item in bundle["evidence_spans"]
            if item["evidence_ref"] != f"evidence:{fixture['evidence_id']}"
            and item["document_ref"] == "document:DOC-research"
        )
        expected = _stable_ref(
            "span",
            ANCHOR_VERSION,
            fixture["manifestation_id"],
            fixture["segment_id"],
            0,
            len(ARTICLE_592),
            fixture["text_sha"],
        )
        self.assertEqual(derived["span_ref"], expected)


if __name__ == "__main__":
    unittest.main()
