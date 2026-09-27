from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_evidence_graph import build_legal_research_bundle
from case_research import PlatformResearchService
import test_issue0138_citable_evidence_graph as issue138

ARTICLE_592 = issue138.ARTICLE_592
NOW = issue138.NOW
case_input = issue138.case_input
intake = issue138.intake


class Issue0180EvidenceOwnerClosureTests(unittest.TestCase):
    """Regression coverage for bounded canonical evidence-owner materialization."""

    # Reuse the small #138 SQLite corpus builder without inheriting its test
    # methods. This keeps #180 fixtures aligned with the established evidence
    # and provenance contract instead of creating a second fixture model.
    setUp = issue138.Issue0138CitableEvidenceGraphTests.setUp
    tearDown = issue138.Issue0138CitableEvidenceGraphTests.tearDown
    add_provision_document = (
        issue138.Issue0138CitableEvidenceGraphTests.add_provision_document
    )

    def add_relationship(
        self,
        *,
        relationship_id: str,
        source_document_id: str,
        target_document_id: str,
        evidence_id: str,
        relation_type: str = "implements",
    ) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO relationships(
                    relationship_id, source_type, source_id, relation_type,
                    target_type, target_id, scope, asserted_date,
                    effective_date, end_date, status, evidence_id, confidence,
                    requires_human_review
                )
                VALUES (
                    ?, 'document', ?, ?, 'document', ?, 'issue180_test',
                    NULL, NULL, NULL, 'validated', ?, 1.0, 0
                )
                """,
                (
                    relationship_id,
                    source_document_id,
                    relation_type,
                    target_document_id,
                    evidence_id,
                ),
            )
            con.commit()
        finally:
            con.close()

    def link_identity_evidence(
        self,
        *,
        identifier_token: str,
        evidence_id: str,
    ) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO document_identifier_evidence(
                    identifier_id, evidence_id, evidence_role, created_at
                )
                VALUES (?, ?, 'identity', ?)
                """,
                (f"ID-{identifier_token}", evidence_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def add_distinct_evidence(
        self,
        *,
        fixture: dict[str, str],
        evidence_id: str,
        exact_quote: str,
    ) -> None:
        offset = fixture["text"].index(exact_quote)
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
                    page_number, ?, ?, ?,
                    source_url, source_sha256, retrieved_at,
                    extraction_method, extractor_version, confidence,
                    review_status, extracted_segment_id
                FROM evidence
                WHERE evidence_id = ?
                """,
                (
                    evidence_id,
                    offset,
                    offset + len(exact_quote),
                    exact_quote,
                    fixture["evidence_id"],
                ),
            )
            con.commit()
        finally:
            con.close()

    def research(self, *, draft: dict | None = None):
        return PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=draft or intake(),
            generated_at=NOW,
        )

    def build(self, research, *, draft: dict | None = None):
        return build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=draft or intake(),
            research=research,
            db_path=self.db,
        )

    def add_primary_and_supporting_documents(self):
        primary = self.add_provision_document(
            token="primary",
            document_id="DOC-primary",
            document_type="LEY",
            number="1",
            year=2026,
            filename="ley_0001_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        supporting = self.add_provision_document(
            token="support",
            document_id="DOC-support",
            document_type="LEY",
            number="2",
            year=2026,
            filename="ley_0002_2026.htm",
            text=(
                "DOCUMENTO DE SOPORTE CANÓNICO. Texto independiente que no "
                "contiene los términos de la pregunta de investigación."
            ),
            designation="Artículo 1",
        )
        return primary, supporting

    def test_metadata_evidence_owned_by_selected_authority_stays_self_owned(self):
        primary = self.add_provision_document(
            token="selected",
            document_id="DOC-selected",
            document_type="LEY",
            number="10",
            year=2026,
            filename="ley_0010_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        research = self.research()
        bundle = self.build(research)

        ref = f"evidence:{primary['evidence_id']}"
        span = next(item for item in bundle["evidence_spans"] if item["evidence_ref"] == ref)
        self.assertEqual(span["authority_ref"], "authority:DOC-selected")
        self.assertIn(
            "authority:DOC-selected",
            {item["authority_ref"] for item in bundle["authorities"]},
        )

    def test_valid_cross_document_owner_is_added_as_supporting_authority(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )

        research = self.research()
        self.assertNotIn("authority:DOC-support", research.result["authority_refs"])
        bundle = self.build(research)

        authority_refs = {item["authority_ref"] for item in bundle["authorities"]}
        self.assertIn("authority:DOC-support", authority_refs)
        span = next(
            item
            for item in bundle["evidence_spans"]
            if item["evidence_ref"] == f"evidence:{supporting['evidence_id']}"
        )
        self.assertEqual(span["authority_ref"], "authority:DOC-support")
        self.assertEqual(span["source_sha256"], supporting["raw_sha"])
        self.assertEqual(
            span["text_sha256"],
            hashlib.sha256(supporting["text"].encode("utf-8")).hexdigest(),
        )

    def test_multiple_refs_share_one_supporting_owner_without_duplicate_authority(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        extra_id = "EVD-support-extra"
        self.add_distinct_evidence(
            fixture=supporting,
            evidence_id=extra_id,
            exact_quote="Texto independiente",
        )
        for evidence_id in (supporting["evidence_id"], extra_id):
            self.link_identity_evidence(
                identifier_token="primary",
                evidence_id=evidence_id,
            )

        research = self.research()
        bundle = self.build(research)

        support_authorities = [
            item
            for item in bundle["authorities"]
            if item["authority_ref"] == "authority:DOC-support"
        ]
        self.assertEqual(len(support_authorities), 1)
        support_spans = [
            item
            for item in bundle["evidence_spans"]
            if item["evidence_ref"]
            in {
                f"evidence:{supporting['evidence_id']}",
                f"evidence:{extra_id}",
            }
        ]
        self.assertEqual(len(support_spans), 2)
        self.assertEqual(
            {item["authority_ref"] for item in support_spans},
            {"authority:DOC-support"},
        )

    def test_relationship_endpoint_and_owner_closure_do_not_import_second_degree_graph(self):
        primary = self.add_provision_document(
            token="chain-a",
            document_id="DOC-chain-a",
            document_type="LEY",
            number="20",
            year=2026,
            filename="ley_0020_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        endpoint = self.add_provision_document(
            token="chain-b",
            document_id="DOC-chain-b",
            document_type="DECRETO",
            number="21",
            year=2026,
            filename="decreto_0021_2026.htm",
            text="Documento endpoint sin vocabulario de la consulta.",
            designation="Artículo 1",
        )
        second_degree = self.add_provision_document(
            token="chain-c",
            document_id="DOC-chain-c",
            document_type="RESOLUCION",
            number="22",
            year=2026,
            filename="resolucion_0022_2026.htm",
            text="Documento de segundo grado no investigado.",
            designation="Artículo 1",
        )
        self.add_relationship(
            relationship_id="REL-chain-ab",
            source_document_id=primary["document_id"],
            target_document_id=endpoint["document_id"],
            evidence_id=primary["evidence_id"],
        )
        self.add_relationship(
            relationship_id="REL-chain-bc",
            source_document_id=endpoint["document_id"],
            target_document_id=second_degree["document_id"],
            evidence_id=second_degree["evidence_id"],
        )

        research = self.research()
        self.assertIn("relationship:REL-chain-ab", {
            item["relationship_ref"] for item in research.relationships
        })
        self.assertNotIn("authority:DOC-chain-b", research.result["authority_refs"])
        bundle = self.build(research)

        authority_refs = {item["authority_ref"] for item in bundle["authorities"]}
        relationship_refs = {
            item["relationship_ref"] for item in bundle["normative_relationships"]
        }
        evidence_refs = {item["evidence_ref"] for item in bundle["evidence_spans"]}
        self.assertIn("authority:DOC-chain-b", authority_refs)
        self.assertNotIn("authority:DOC-chain-c", authority_refs)
        self.assertEqual(relationship_refs, {"relationship:REL-chain-ab"})
        self.assertNotIn("relationship:REL-chain-bc", relationship_refs)
        self.assertNotIn(
            f"evidence:{second_degree['evidence_id']}",
            evidence_refs,
        )

    def test_unresolved_owner_identity_becomes_explicit_partial_state(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                (supporting["manifestation_id"],),
            )
            con.commit()
        finally:
            con.close()

        research = self.research()
        bundle = self.build(research)

        self.assertEqual(bundle["status"], "partial")
        self.assertNotIn(
            f"evidence:{supporting['evidence_id']}",
            {item["evidence_ref"] for item in bundle["evidence_spans"]},
        )
        self.assertTrue(
            any(
                item["stage"] == "evidence"
                and item["category"] == "unresolved_identity"
                for item in bundle["unresolved"]
            )
        )

    def test_ambiguous_supporting_owner_keeps_classification_ambiguity(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                UPDATE document_identifiers
                SET issuer = 'BANREP_JD'
                WHERE identifier_id = 'ID-support'
                """
            )
            con.commit()
        finally:
            con.close()

        research = self.research()
        bundle = self.build(research)

        support = next(
            item
            for item in bundle["authorities"]
            if item["authority_ref"] == "authority:DOC-support"
        )
        self.assertEqual(support["classification_state"], "ambiguous")
        self.assertTrue(
            any(
                item["category"] == "conflicting_authority"
                and "authority:DOC-support"
                in item.get("related_authority_refs", [])
                for item in bundle["unresolved"]
            )
        )

    def test_supporting_owner_does_not_recursively_expand_its_relationships(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        unrelated = self.add_provision_document(
            token="unrelated",
            document_id="DOC-unrelated",
            document_type="DECRETO",
            number="99",
            year=2026,
            filename="decreto_0099_2026.htm",
            text="Contenido ajeno a la investigación.",
            designation="Artículo 1",
        )
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )
        self.add_relationship(
            relationship_id="REL-support-unrelated",
            source_document_id=supporting["document_id"],
            target_document_id=unrelated["document_id"],
            evidence_id=unrelated["evidence_id"],
        )

        research = self.research()
        bundle = self.build(research)

        self.assertIn(
            "authority:DOC-support",
            {item["authority_ref"] for item in bundle["authorities"]},
        )
        self.assertNotIn(
            "authority:DOC-unrelated",
            {item["authority_ref"] for item in bundle["authorities"]},
        )
        self.assertNotIn(
            "relationship:REL-support-unrelated",
            {
                item["relationship_ref"]
                for item in bundle["normative_relationships"]
            },
        )

    def test_supporting_owner_does_not_satisfy_research_question(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )
        research = self.research()
        original_result_refs = deepcopy(research.result["authority_refs"])
        bundle = self.build(research)

        self.assertEqual(
            bundle["research_result"]["authority_refs"],
            original_result_refs,
        )
        self.assertNotIn(
            "authority:DOC-support",
            bundle["research_result"]["authority_refs"],
        )
        self.assertFalse(
            any(
                "authority:DOC-support" in item["authority_refs"]
                for item in bundle["rule_fragments"]
            )
        )

    def test_natural_person_path_reproduces_absent_owner_regression(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )

        research = self.research()
        self.assertNotIn(
            "authority:DOC-support",
            research.result["authority_refs"],
        )
        bundle = self.build(research)

        self.assertIn(
            "authority:DOC-support",
            {item["authority_ref"] for item in bundle["authorities"]},
        )
        self.assertIn(
            f"evidence:{supporting['evidence_id']}",
            {item["evidence_ref"] for item in bundle["evidence_spans"]},
        )

    def test_basic_and_multi_question_paths_remain_materializable(self):
        self.add_provision_document(
            token="regression",
            document_id="DOC-regression",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        basic_research = self.research()
        basic = self.build(basic_research)
        self.assertTrue(basic["evidence_spans"])

        complex_draft = deepcopy(intake())
        complex_draft["questions"].append(
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:filing-support",
                "text": "¿Qué evidencia canónica soporta los umbrales aplicables?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:person"],
            }
        )
        complex_research = self.research(draft=complex_draft)
        complex_bundle = self.build(complex_research, draft=complex_draft)
        self.assertEqual(
            len(complex_bundle["research_plan"]["tasks"]),
            2,
        )
        self.assertTrue(complex_bundle["evidence_spans"])

    def test_bundle_regeneration_is_deterministic_and_read_only_with_support_owner(self):
        _primary, supporting = self.add_primary_and_supporting_documents()
        self.link_identity_evidence(
            identifier_token="primary",
            evidence_id=supporting["evidence_id"],
        )
        research = self.research()
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        first = self.build(research)
        second = self.build(research)
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(first["bundle_ref"], second["bundle_ref"])
        self.assertEqual(
            first["research_result"]["result_ref"],
            research.result["result_ref"],
        )


if __name__ == "__main__":
    unittest.main()
