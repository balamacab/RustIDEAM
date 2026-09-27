from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_evidence_graph import (
    EvidenceGraphIntegrityError,
    build_legal_research_bundle,
)
from case_research import (
    PlatformResearchService,
    ResearchExecution,
    _explicit_conflict_unresolved_items,
)
from case_rest_api import validate_success_payload


NOW = "2026-09-27T10:00:00+00:00"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"
ARTICLE_592 = (
    "ARTÍCULO 592. QUIÉNES NO ESTÁN OBLIGADOS A DECLARAR. "
    "Las personas naturales deben verificar la obligación de presentar "
    "declaración de renta según los umbrales aplicables de ingresos brutos, "
    "patrimonio bruto y valores expresados en UVT."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": (
            "Una persona natural residente en Colombia obtiene ingresos por "
            "transmisiones por webcam. Pregunta si debe declarar renta."
        ),
    }


def intake() -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue138",
        "problem_text": case_input()["problem_text"],
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:person",
                "label": "Persona natural residente en Colombia",
                "value": "Actividad de transmisiones por webcam",
                "state": "user_provided",
                "source_quote": (
                    "Una persona natural residente en Colombia obtiene ingresos "
                    "por transmisiones por webcam."
                ),
                "requires_confirmation": False,
            }
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:filing",
                "text": "¿Debe declarar renta?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:person"],
            }
        ],
        "search_hints": [],
        "model_metadata": {
            "adapter": "fixture",
            "provider": "fixture",
            "model": "fixture",
            "schema_version": "4.0.0",
            "prompt_template_id": "case-intake-v4",
            "prompt_template_version": "1",
            "run_reference": "run:issue138",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
        },
    }


class Issue0138CitableEvidenceGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "case138.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_provision_document(
        self,
        *,
        token: str,
        document_id: str,
        document_type: str,
        number: str,
        year: int,
        filename: str,
        text: str,
        designation: str,
        issuer: str = "CONGRESO",
        bind_identity_evidence: bool = True,
    ) -> dict[str, str]:
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        segment_id = f"SEG-{token}"
        provision_id = f"PROV-{token}"
        observation_id = f"PO-{token}"
        identifier_id = f"ID-{token}"
        source_url = BASE + filename
        raw_sha = hashlib.sha256(f"raw:{source_url}".encode()).hexdigest()
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    document_id,
                    issuer,
                    document_type,
                    f"{document_type} {number} DE {year}",
                    f"{year}-01-01",
                    NOW,
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES (?, ?, 'canonical_key', ?, ?, 1)
                """,
                (
                    identifier_id,
                    document_id,
                    f"CO:{document_type}:{number}:{year}",
                    issuer,
                ),
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
                    len(text.encode()),
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
                ) VALUES (?, ?, 'fixture', '1', ?, ?, ?, 1, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    hashlib.sha256(("normalized:" + text).encode()).hexdigest(),
                    len(text.encode()),
                    len(text),
                    f"extracted/{token}.txt",
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
                (segment_id, extraction_id, len(text), text, text_sha),
            )
            con.execute(
                """
                INSERT INTO extracted_segments_fts(
                    extracted_segment_id, text, section_path
                ) VALUES (?, ?, NULL)
                """,
                (segment_id, text),
            )
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES (?, ?, 'article', ?, ?, NULL, ?, ?)
                """,
                (
                    provision_id,
                    document_id,
                    designation,
                    designation.casefold(),
                    NOW,
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO provision_observations(
                    provision_observation_id, provision_id, extraction_id,
                    extracted_segment_id, observed_text, normative_text,
                    editorial_note, observed_text_sha256, normative_text_sha256,
                    observed_at, parser_name, parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'fixture', '1')
                """,
                (
                    observation_id,
                    provision_id,
                    extraction_id,
                    segment_id,
                    text,
                    text,
                    text_sha,
                    text_sha,
                    NOW,
                ),
            )
            evidence_id = f"EVD-{token}"
            if bind_identity_evidence:
                con.execute(
                    """
                    INSERT INTO evidence(
                        evidence_id, claim_id, manifestation_id, segment_id,
                        page_number, char_start, char_end, exact_quote,
                        source_url, source_sha256, retrieved_at,
                        extraction_method, extractor_version, confidence,
                        review_status, extracted_segment_id
                    ) VALUES (
                        ?, NULL, ?, NULL, NULL, 0, ?, ?, ?, ?, ?,
                        'fixture', '1', 1.0, 'machine_validated', ?
                    )
                    """,
                    (
                        evidence_id,
                        manifestation_id,
                        len(text),
                        text,
                        source_url,
                        raw_sha,
                        NOW,
                        segment_id,
                    ),
                )
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

        return {
            "document_id": document_id,
            "source_id": source_id,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "segment_id": segment_id,
            "provision_id": provision_id,
            "evidence_id": evidence_id,
            "raw_sha": raw_sha,
            "text_sha": text_sha,
            "text": text,
        }

    def add_resolved_provision_reference(
        self,
        *,
        source: dict[str, str],
        target: dict[str, str],
        normalized_reference: str,
    ) -> None:
        suffix = source["segment_id"].replace("-", "").lower()
        detection_id = f"RDR-{suffix}"
        mention_id = f"RM-{suffix}"
        resolution_id = f"RR-{suffix}"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO reference_detection_runs(
                    detection_run_id, extraction_id, detector_name,
                    detector_version, mention_count, relation_count,
                    created_at, status
                ) VALUES (?, ?, 'fixture', '1', 1, 0, ?, 'success')
                """,
                (detection_id, source["extraction_id"], NOW),
            )
            con.execute(
                """
                INSERT INTO reference_mentions(
                    reference_mention_id, detection_run_id, extraction_id,
                    extracted_segment_id, mention_type, raw_text, context_text,
                    normalized_reference, target_document_key,
                    target_document_type, target_document_number,
                    target_document_year, article_designation, char_start,
                    char_end, detection_method, confidence,
                    requires_human_review, status
                ) VALUES (
                    ?, ?, ?, ?, 'article', ?, ?, ?,
                    ?, 'LEY', '999', 2020, 'Artículo 2', 0, ?,
                    'fixture', 1.0, 0, 'candidate'
                )
                """,
                (
                    mention_id,
                    detection_id,
                    source["extraction_id"],
                    source["segment_id"],
                    normalized_reference,
                    source["text"],
                    normalized_reference,
                    "FIXTURE:" + target["document_id"],
                    len(normalized_reference),
                ),
            )
            con.execute(
                """
                INSERT INTO reference_resolutions(
                    reference_resolution_id, reference_mention_id,
                    target_document_id, target_provision_id,
                    resolution_method, confidence, status,
                    requires_human_review, created_at
                ) VALUES (?, ?, ?, ?, 'fixture_exact', 1.0, 'resolved', 0, ?)
                """,
                (
                    resolution_id,
                    mention_id,
                    target["document_id"],
                    target["provision_id"],
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()

    def research_and_bundle(self) -> tuple[ResearchExecution, dict]:
        research = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        bundle = build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=intake(),
            research=research,
            db_path=self.db,
        )
        return research, bundle

    def test_canonical_provision_becomes_exact_citable_span_and_rule(self):
        fixture = self.add_provision_document(
            token="592",
            document_id="DOC-statute-592",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        research, bundle = self.research_and_bundle()

        self.assertNotIn("webcam", ARTICLE_592.casefold())
        self.assertIn(
            f"authority:{fixture['document_id']}",
            research.result["authority_refs"],
        )
        provision_spans = [
            item for item in bundle["evidence_spans"]
            if item.get("provision_ref")
            == f"provision:{fixture['provision_id']}"
            and item["evidence_ref"] != f"evidence:{fixture['evidence_id']}"
        ]
        self.assertEqual(len(provision_spans), 1)
        span = provision_spans[0]
        self.assertEqual(span["exact_text"], ARTICLE_592)
        self.assertEqual(span["source_sha256"], fixture["raw_sha"])
        self.assertEqual(span["text_sha256"], fixture["text_sha"])
        self.assertEqual(
            span["source_ref"],
            f"source:{fixture['source_id']}",
        )

        canonical = [
            item for item in bundle["evidence_spans"]
            if item["evidence_ref"] == f"evidence:{fixture['evidence_id']}"
        ]
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0]["source_sha256"], fixture["raw_sha"])

        rules = [
            item for item in bundle["rule_fragments"]
            if item["rule_type"] == "canonical_source_statement"
            and item["evidence_refs"] == [span["evidence_ref"]]
        ]
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(
            rule["structured_data"]["statement_scope"],
            "canonical_provision",
        )
        self.assertEqual(
            rule["structured_data"]["provision_ref"],
            f"provision:{fixture['provision_id']}",
        )
        self.assertEqual(
            rule["derivation"]["method"],
            "extractive_normalization",
        )
        self.assertNotIn(
            "webcam",
            json.dumps(
                bundle["rule_fragments"],
                ensure_ascii=False,
            ).casefold(),
        )

        validate_success_payload(
            {
                "api_version": "1.0.0",
                "request_fingerprints": {
                    "raw_request_sha256": "a" * 64,
                    "case_input_sha256": "b" * 64,
                },
                "bundle": bundle,
            }
        )

    def test_retrieval_similarity_without_canonical_provision_yields_evidence_not_rule(self):
        fixture = self.add_provision_document(
            token="segment-only",
            document_id="DOC-segment-only",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989_segment.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "DELETE FROM provision_observations WHERE provision_id = ?",
                (fixture["provision_id"],),
            )
            con.execute(
                "DELETE FROM provisions WHERE provision_id = ?",
                (fixture["provision_id"],),
            )
            con.commit()
        finally:
            con.close()

        research, bundle = self.research_and_bundle()
        candidate = next(
            item
            for item in research.evidence_candidates
            if item["document_ref"] == f"document:{fixture['document_id']}"
        )
        self.assertNotIn("provision_ref", candidate)

        segment_spans = [
            item for item in bundle["evidence_spans"]
            if item["document_ref"] == f"document:{fixture['document_id']}"
            and item["evidence_ref"] != f"evidence:{fixture['evidence_id']}"
        ]
        self.assertEqual(len(segment_spans), 1)
        self.assertEqual(segment_spans[0]["exact_text"], ARTICLE_592)
        self.assertFalse(
            any(
                item["rule_type"] == "canonical_source_statement"
                and f"authority:{fixture['document_id']}" in item["authority_refs"]
                for item in bundle["rule_fragments"]
            ),
            "FTS/research relevance alone must never promote document text to a rule",
        )

    def test_resolved_cross_provision_reference_composes_all_evidence(self):
        source = self.add_provision_document(
            token="source",
            document_id="DOC-source",
            document_type="LEY",
            number="1",
            year=2026,
            filename="ley_0001_2026.htm",
            text=ARTICLE_592 + " Véase LEY 999 DE 2020 ARTÍCULO 2.",
            designation="Artículo 592",
        )
        target = self.add_provision_document(
            token="target",
            document_id="DOC-target",
            document_type="LEY",
            number="999",
            year=2020,
            filename="ley_0999_2020.htm",
            text=(
                "LEY 999 DE 2020. ARTÍCULO 2. Para determinar la obligación "
                "tributaria se aplica también esta disposición de referencia."
            ),
            designation="Artículo 2",
        )
        self.add_resolved_provision_reference(
            source=source,
            target=target,
            normalized_reference="LEY 999 DE 2020 ARTÍCULO 2",
        )

        _research, bundle = self.research_and_bundle()
        compositions = [
            item for item in bundle["rule_fragments"]
            if item["rule_type"] == "resolved_provision_reference"
        ]
        self.assertEqual(len(compositions), 1)
        composed = compositions[0]
        self.assertEqual(
            composed["derivation"]["method"],
            "deterministic_composition",
        )
        self.assertEqual(len(composed["authority_refs"]), 2)
        self.assertEqual(len(composed["evidence_refs"]), 2)
        self.assertEqual(
            {
                composed["structured_data"]["source"]["provision_ref"],
                composed["structured_data"]["target"]["provision_ref"],
            },
            {
                f"provision:{source['provision_id']}",
                f"provision:{target['provision_id']}",
            },
        )

    def test_unresolved_identity_never_becomes_evidence_or_rule(self):
        fixture = self.add_provision_document(
            token="unbound",
            document_id="DOC-unbound",
            document_type="LEY",
            number="5",
            year=2026,
            filename="ley_0005_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
            bind_identity_evidence=False,
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                (fixture["manifestation_id"],),
            )
            con.commit()
        finally:
            con.close()

        research, bundle = self.research_and_bundle()
        self.assertEqual(research.result["authority_refs"], [])
        self.assertEqual(bundle["evidence_spans"], [])
        self.assertEqual(bundle["rule_fragments"], [])
        self.assertTrue(
            any(
                item["category"] == "unresolved_identity"
                for item in bundle["unresolved"]
            )
        )

    def test_conflict_stays_unresolved_while_source_statements_remain_citable(self):
        a = self.add_provision_document(
            token="a",
            document_id="DOC-a",
            document_type="LEY",
            number="10",
            year=2025,
            filename="ley_0010_2025.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        b = self.add_provision_document(
            token="b",
            document_id="DOC-b",
            document_type="LEY",
            number="11",
            year=2025,
            filename="ley_0011_2025.htm",
            text=(
                "Las personas naturales deben presentar declaración de renta "
                "bajo los supuestos de ingresos brutos y patrimonio aplicables."
            ),
            designation="Artículo 1",
        )
        research = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        conflict = _explicit_conflict_unresolved_items(
            [
                {
                    "kind": "normative_relationship",
                    "contract_version": "4.0.0",
                    "relationship_ref": "relationship:test-conflict",
                    "relationship_type": "conflicts_with",
                    "source_authority_ref": f"authority:{a['document_id']}",
                    "target_authority_ref": f"authority:{b['document_id']}",
                    "evidence_refs": ["evidence:synthetic"],
                    "provenance_ref": "provenance:synthetic",
                    "status": "resolved",
                }
            ],
            research.result["authority_refs"],
        )
        self.assertEqual(len(conflict), 1)

        result = deepcopy(research.result)
        result["status"] = "partial"
        result["unresolved_refs"] = sorted(
            [*result["unresolved_refs"], conflict[0]["unresolved_ref"]]
        )
        with_conflict = ResearchExecution(
            plan=research.plan,
            result=result,
            evidence_candidates=research.evidence_candidates,
            authorities=research.authorities,
            relationships=research.relationships,
            unresolved=tuple([*research.unresolved, *conflict]),
        )
        bundle = build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=intake(),
            research=with_conflict,
            db_path=self.db,
        )
        self.assertTrue(bundle["rule_fragments"])
        self.assertTrue(
            any(
                item["category"] == "conflicting_authority"
                for item in bundle["unresolved"]
            )
        )
        self.assertEqual(bundle["status"], "partial")

    def test_quote_or_hash_mismatch_is_integrity_failure_not_repair(self):
        self.add_provision_document(
            token="mismatch",
            document_id="DOC-mismatch",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        research = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        candidate = deepcopy(research.evidence_candidates[0])
        candidate["text"] = candidate["text"].replace(
            "ingresos brutos",
            "ingresos supuestamente equivalentes",
        )
        tampered = ResearchExecution(
            plan=research.plan,
            result=research.result,
            evidence_candidates=(
                candidate,
                *research.evidence_candidates[1:],
            ),
            authorities=research.authorities,
            relationships=research.relationships,
            unresolved=research.unresolved,
        )
        with self.assertRaises(EvidenceGraphIntegrityError):
            build_legal_research_bundle(
                case_input=case_input(),
                intake_draft=intake(),
                research=tampered,
                db_path=self.db,
            )

    def test_same_research_result_builds_identical_read_only_graph(self):
        self.add_provision_document(
            token="stable",
            document_id="DOC-stable",
            document_type="DECRETO",
            number="624",
            year=1989,
            filename="decreto_0624_1989.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        research = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        first = build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=intake(),
            research=research,
            db_path=self.db,
        )
        second = build_legal_research_bundle(
            case_input=case_input(),
            intake_draft=intake(),
            research=research,
            db_path=self.db,
        )
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(
            first["research_result"]["result_ref"],
            research.result["result_ref"],
        )


if __name__ == "__main__":
    unittest.main()
