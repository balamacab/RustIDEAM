from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_research import PlatformResearchService
from case_retrieval import CorpusRetrievalService


NOW = "2026-09-28T20:30:00+00:00"
BASE = "https://example.test/"
GENERAL_RULE = (
    "Las personas naturales deben verificar la obligación de presentar "
    "declaración de renta según los umbrales aplicables de ingresos brutos "
    "y patrimonio."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": "Persona natural pregunta si debe declarar renta.",
    }


def intake() -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue276",
        "problem_text": case_input()["problem_text"],
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:person",
                "label": "Persona natural en Colombia",
                "value": "ingresos y patrimonio",
                "state": "user_provided",
                "source_quote": "Persona natural pregunta si debe declarar renta.",
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
            "run_reference": "run:issue276",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
        },
    }


class Issue0276ExactReferenceExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "issue276.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_document(
        self,
        *,
        token: str,
        document_type: str,
        number: str,
        year: int,
        issuer: str,
        texts: list[str],
    ) -> dict[str, object]:
        document_id = f"DOC-{token}"
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        source_url = f"{BASE}{token}.htm"
        joined = "\n".join(texts)
        raw_sha = hashlib.sha256(f"raw:{source_url}".encode()).hexdigest()
        normalized_sha = hashlib.sha256(joined.encode()).hexdigest()

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
                    f"ID-{token}",
                    document_id,
                    f"CO:{issuer}:{document_type}:{number}:{year}",
                    issuer,
                ),
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, 'official_html', NULL, ?, ?)
                """,
                (source_id, source_url, issuer, NOW, NOW),
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
                    len(joined.encode()),
                    NOW,
                    f"raw/{token}.htm",
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
                    len(joined.encode()),
                    len(joined),
                    len(texts),
                    f"extracted/{token}.txt",
                    NOW,
                ),
            )

            segment_ids: list[str] = []
            offset = 0
            for sequence_no, text in enumerate(texts, start=1):
                segment_id = f"SEG-{token}-{sequence_no}"
                segment_ids.append(segment_id)
                text_sha = hashlib.sha256(text.encode()).hexdigest()
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

        return {
            "document_id": document_id,
            "source_id": source_id,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "segment_ids": segment_ids,
            "raw_sha": raw_sha,
        }

    def add_provision(
        self,
        *,
        token: str,
        document: dict[str, object],
        segment_id: str,
        designation: str,
        normative_text: str,
    ) -> str:
        provision_id = f"PROV-{token}"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES (?, ?, 'article', ?, ?, NULL, ?, ?)
                """,
                (
                    provision_id,
                    document["document_id"],
                    designation,
                    designation.casefold(),
                    NOW,
                    NOW,
                ),
            )
            text_sha = hashlib.sha256(normative_text.encode()).hexdigest()
            con.execute(
                """
                INSERT INTO provision_observations(
                    provision_observation_id, provision_id, extraction_id,
                    extracted_segment_id, observed_text, normative_text,
                    editorial_note, observed_text_sha256,
                    normative_text_sha256, observed_at, parser_name,
                    parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'fixture', '1')
                """,
                (
                    f"PO-{token}",
                    provision_id,
                    document["extraction_id"],
                    segment_id,
                    normative_text,
                    normative_text,
                    text_sha,
                    text_sha,
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()
        return provision_id

    def add_reference(
        self,
        *,
        token: str,
        source: dict[str, object],
        normalized_reference: str,
        target_document_id: str | None = None,
        target_provision_id: str | None = None,
        resolution_status: str | None = "resolved",
        requires_review: bool = False,
    ) -> None:
        segment_id = str(source["segment_ids"][0])
        detection_run_id = f"RDR-{token}"
        mention_id = f"RM-{token}"
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
                (detection_run_id, source["extraction_id"], NOW),
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
                    requires_human_review, status, target_issuer
                ) VALUES (
                    ?, ?, ?, ?, 'document', ?, ?, ?, ?, 'LEY', '42', 2020,
                    NULL, 0, ?, 'fixture', 1.0, ?, 'candidate', NULL
                )
                """,
                (
                    mention_id,
                    detection_run_id,
                    source["extraction_id"],
                    segment_id,
                    normalized_reference,
                    normalized_reference,
                    normalized_reference,
                    f"CO:LEY:42:2020:{token}",
                    len(normalized_reference),
                    1 if requires_review else 0,
                ),
            )
            if resolution_status is not None:
                con.execute(
                    """
                    INSERT INTO reference_resolutions(
                        reference_resolution_id, reference_mention_id,
                        target_document_id, target_provision_id,
                        resolution_method, confidence, status,
                        requires_human_review, created_at
                    ) VALUES (?, ?, ?, ?, 'fixture', 1.0, ?, ?, ?)
                    """,
                    (
                        f"RR-{token}",
                        mention_id,
                        target_document_id,
                        target_provision_id,
                        resolution_status,
                        1 if requires_review else 0,
                        NOW,
                    ),
                )
            con.commit()
        finally:
            con.close()

    def test_exact_document_target_excludes_same_label_other_issuer_on_reference_path(self):
        source = self.add_document(
            token="source",
            document_type="LEY",
            number="1",
            year=2026,
            issuer="CONGRESO",
            texts=[GENERAL_RULE + " Véase LEY 42 DE 2020."],
        )
        selected = self.add_document(
            token="selected",
            document_type="LEY",
            number="42",
            year=2020,
            issuer="CONGRESO",
            texts=["LEY 42 DE 2020 regla seleccionada sobre ingresos brutos."],
        )
        distractor = self.add_document(
            token="distractor",
            document_type="LEY",
            number="42",
            year=2020,
            issuer="ASAMBLEA",
            texts=["LEY 42 DE 2020 regla distractora sobre ingresos brutos."],
        )
        self.add_reference(
            token="selected",
            source=source,
            normalized_reference="LEY 42 DE 2020",
            target_document_id=str(selected["document_id"]),
        )

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        exact_candidates = [
            item for item in execution.evidence_candidates
            if item.get("reference_paths")
        ]
        self.assertTrue(exact_candidates)
        self.assertTrue(
            all(
                item["document_ref"] == f"document:{selected['document_id']}"
                for item in exact_candidates
            )
        )
        self.assertFalse(
            any(
                item["document_ref"] == f"document:{distractor['document_id']}"
                and item.get("reference_paths")
                for item in execution.evidence_candidates
            )
        )
        path = exact_candidates[0]["reference_paths"][0]
        self.assertEqual(path["strategy"], "canonical_document_target")
        self.assertEqual(
            path["target_document_ref"],
            f"document:{selected['document_id']}",
        )

        # Thematic retrieval remains independent: the distractor is allowed to
        # exist in ordinary search results, but it cannot leak into exact target
        # expansion.
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            thematic = CorpusRetrievalService(con).search("LEY 42 DE 2020", limit=20)
        finally:
            con.close()
        self.assertIn(
            str(distractor["document_id"]),
            {hit.document_id for hit in thematic},
        )

    def test_provision_target_preserves_one_digit_designation_and_document_scope(self):
        source = self.add_document(
            token="source-provision",
            document_type="LEY",
            number="1",
            year=2026,
            issuer="CONGRESO",
            texts=[GENERAL_RULE + " Véase ARTÍCULO 2 DE LA LEY 7 DE 2020."],
        )
        target_text = "ARTÍCULO 2. Regla exacta de la Ley 7 de 2020 sobre patrimonio."
        target = self.add_document(
            token="target-provision",
            document_type="LEY",
            number="7",
            year=2020,
            issuer="CONGRESO",
            texts=[target_text, "ARTÍCULO 20. Regla distinta."],
        )
        other = self.add_document(
            token="other-provision",
            document_type="LEY",
            number="7",
            year=2020,
            issuer="ASAMBLEA",
            texts=["ARTÍCULO 2. Regla distractora de otra autoridad."],
        )
        provision_id = self.add_provision(
            token="article-2",
            document=target,
            segment_id=str(target["segment_ids"][0]),
            designation="ARTÍCULO 2",
            normative_text=target_text,
        )
        self.add_provision(
            token="other-article-2",
            document=other,
            segment_id=str(other["segment_ids"][0]),
            designation="ARTÍCULO 2",
            normative_text="ARTÍCULO 2. Regla distractora de otra autoridad.",
        )
        self.add_reference(
            token="article-2",
            source=source,
            normalized_reference="LEY 7 DE 2020",
            target_document_id=str(target["document_id"]),
            target_provision_id=provision_id,
        )

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        exact = [
            item for item in execution.evidence_candidates
            if any(
                path.get("target_provision_ref") == f"provision:{provision_id}"
                for path in item.get("reference_paths", [])
            )
        ]
        self.assertEqual([item["extracted_segment_id"] for item in exact], [target["segment_ids"][0]])
        self.assertEqual(exact[0]["document_ref"], f"document:{target['document_id']}")
        self.assertEqual(exact[0]["provision_ref"], f"provision:{provision_id}")
        self.assertEqual(
            exact[0]["reference_paths"][0]["strategy"],
            "canonical_provision_target",
        )
        self.assertIn("ARTÍCULO 2", exact[0]["text"])

    def test_unresolved_review_and_inconsistent_targets_never_fallback_to_fts(self):
        source_missing = self.add_document(
            token="source-missing",
            document_type="LEY",
            number="1",
            year=2026,
            issuer="CONGRESO",
            texts=[GENERAL_RULE + " Véase LEY 42 DE 2020 sin resolución."],
        )
        source_ambiguous = self.add_document(
            token="source-ambiguous",
            document_type="LEY",
            number="2",
            year=2026,
            issuer="CONGRESO",
            texts=[GENERAL_RULE + " Véase LEY 42 DE 2020 ambigua."],
        )
        source_review = self.add_document(
            token="source-review",
            document_type="LEY",
            number="3",
            year=2026,
            issuer="CONGRESO",
            texts=[GENERAL_RULE + " Véase LEY 42 DE 2020 por revisar."],
        )
        target = self.add_document(
            token="target-inconsistent",
            document_type="LEY",
            number="42",
            year=2020,
            issuer="CONGRESO",
            texts=["LEY 42 DE 2020 objetivo exacto."],
        )
        other = self.add_document(
            token="other-owner",
            document_type="LEY",
            number="9",
            year=2020,
            issuer="CONGRESO",
            texts=["ARTÍCULO 1. pertenece a otro documento."],
        )
        other_provision = self.add_provision(
            token="wrong-owner",
            document=other,
            segment_id=str(other["segment_ids"][0]),
            designation="ARTÍCULO 1",
            normative_text="ARTÍCULO 1. pertenece a otro documento.",
        )

        self.add_reference(
            token="missing",
            source=source_missing,
            normalized_reference="LEY 42 DE 2020",
            resolution_status=None,
        )
        self.add_reference(
            token="ambiguous",
            source=source_ambiguous,
            normalized_reference="LEY 42 DE 2020",
            target_document_id=str(target["document_id"]),
            resolution_status="ambiguous",
        )
        self.add_reference(
            token="review",
            source=source_review,
            normalized_reference="LEY 42 DE 2020",
            target_document_id=str(target["document_id"]),
            requires_review=True,
        )

        # Direct lookup proves an inconsistent provision/document pair is
        # rejected before any segment search can occur.
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            lookup = CorpusRetrievalService(con).lookup_canonical_target(
                str(target["document_id"]),
                target_provision_id=other_provision,
                limit=10,
            )
        finally:
            con.close()
        self.assertEqual(lookup.status, "inconsistent_provision")
        self.assertEqual(lookup.hits, ())

        execution = PlatformResearchService(
            self.db,
            bounds={
                "max_queries_per_question": 10,
                "max_total_authorities": 64,
            },
        ).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        unresolved_descriptions = [
            item["description"] for item in execution.unresolved
            if item["category"] == "unresolved_identity"
        ]
        self.assertTrue(any("missing_resolution" in text for text in unresolved_descriptions))
        self.assertTrue(any("ambiguous" in text for text in unresolved_descriptions))
        self.assertTrue(any("requires_review" in text for text in unresolved_descriptions))

    def test_repeated_exact_lookup_is_stable_read_only_and_preserves_duplicate_provenance(self):
        target = self.add_document(
            token="duplicates",
            document_type="DECRETO",
            number="6",
            year=2020,
            issuer="PRESIDENCIA",
            texts=[
                "DECRETO 6 DE 2020 texto exacto repetido.",
                "DECRETO 6 DE 2020 texto exacto repetido.",
                "DECRETO 6 DE 2020 texto distinto.",
            ],
        )
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()

        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            service = CorpusRetrievalService(con)
            first = service.lookup_canonical_target(
                str(target["document_id"]),
                limit=10,
            )
            second = service.lookup_canonical_target(
                str(target["document_id"]),
                limit=10,
            )
        finally:
            con.close()

        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "resolved")
        self.assertEqual(len(first.hits), 2)
        repeated = first.hits[0]
        self.assertEqual(repeated.duplicate_count, 2)
        self.assertEqual(len(repeated.alternate_segment_ids), 1)


if __name__ == "__main__":
    unittest.main()
