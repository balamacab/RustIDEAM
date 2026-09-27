from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_research import (
    PlatformResearchService,
    build_research_plan,
)
from case_retrieval import RetrievalIntegrityError


NOW = "2026-09-27T05:00:00+00:00"
AS_OF = "2026-09-26"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"

GENERAL_RULE = (
    "Las personas naturales deben verificar la obligación de presentar "
    "declaración de renta según los umbrales aplicables de ingresos brutos "
    "y patrimonio."
)
ARTICLE_592_THRESHOLD_RULE = (
    "ARTÍCULO 592. QUIÉNES NO ESTÁN OBLIGADOS A DECLARAR. "
    "Para las personas naturales la obligación de presentar declaración de renta "
    "se determina, entre otros supuestos legales, con umbrales de patrimonio bruto, "
    "ingresos brutos y valores expresados en UVT."
)
REFERENCE_RULE = (
    "LEY 999 DE 2020 contiene una disposición general expresamente referenciada."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": (
            "Una persona natural residente en Colombia obtiene ingresos por "
            "transmisiones por webcam. Pregunta si debe declarar renta y cómo "
            "determinar la obligación."
        ),
        "as_of_date": AS_OF,
    }


def intake(*, hints: list[dict] | None = None) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue137",
        "problem_text": case_input()["problem_text"],
        "as_of_date": AS_OF,
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
                "text": "¿Debe declarar renta y cómo determinar la obligación?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:person"],
            }
        ],
        "search_hints": [] if hints is None else hints,
        "model_metadata": {
            "adapter": "fixture",
            "provider": "fixture",
            "model": "fixture",
            "schema_version": "4.0.0",
            "prompt_template_id": "case-intake-v4",
            "prompt_template_version": "1",
            "run_reference": "run:issue137",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
        },
    }


class Issue0137EvidenceFirstResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_document_with_segment(
        self,
        *,
        document_id: str,
        number: str,
        year: int,
        text: str,
        filename: str,
        document_type: str = "LEY",
        issuer: str = "CONGRESO",
    ) -> dict[str, str]:
        token = document_id.replace("DOC-", "").lower()
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        segment_id = f"SEG-{token}"
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
                    f"ID-{token}",
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
                ) VALUES (?, ?, ?, 'text/html', ?, ?, ?, ?, 'fixture-1')
                """,
                (
                    manifestation_id,
                    document_id,
                    source_id,
                    raw_sha,
                    len(text.encode("utf-8")),
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
                ) VALUES (
                    ?, ?, 'fixture', '1', ?, ?, ?, 1, ?, ?, 'success'
                )
                """,
                (
                    extraction_id,
                    manifestation_id,
                    hashlib.sha256(("normalized:" + text).encode()).hexdigest(),
                    len(text.encode("utf-8")),
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
            con.commit()
        finally:
            con.close()

        return {
            "document_id": document_id,
            "source_id": source_id,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "segment_id": segment_id,
            "raw_sha": raw_sha,
            "text_sha": text_sha,
        }

    def add_resolved_reference(
        self,
        *,
        source: dict[str, str],
        target: dict[str, str],
        normalized_reference: str,
    ) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO reference_detection_runs(
                    detection_run_id, extraction_id, detector_name,
                    detector_version, mention_count, relation_count,
                    created_at, status
                ) VALUES ('RDR-issue137', ?, 'fixture', '1', 1, 0, ?, 'success')
                """,
                (source["extraction_id"], NOW),
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
                    'RM-issue137', 'RDR-issue137', ?, ?, 'document',
                    ?, ?, ?, 'CO:LEY:999:2020', 'LEY', '999', 2020,
                    NULL, 0, ?, 'fixture', 1.0, 0, 'candidate'
                )
                """,
                (
                    source["extraction_id"],
                    source["segment_id"],
                    normalized_reference,
                    normalized_reference,
                    normalized_reference,
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
                ) VALUES (
                    'RR-issue137', 'RM-issue137', ?, NULL,
                    'fixture', 1.0, 'resolved', 0, ?
                )
                """,
                (target["document_id"], NOW),
            )
            con.commit()
        finally:
            con.close()

    def test_plan_is_deterministic_and_hint_free_platform_query_is_neutral(self):
        first = build_research_plan(
            case_input(),
            intake(),
            generated_at=NOW,
        )
        second = build_research_plan(
            case_input(),
            intake(),
            generated_at=NOW,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first["tasks"]), 1)
        required = first["tasks"][0]
        self.assertEqual(required["origin"], "platform_required")
        self.assertIn("ingresos brutos", required["query_text"])
        self.assertIn("patrimonio", required["query_text"])
        self.assertNotIn("hint_refs", required)

    def test_misleading_hint_cannot_suppress_platform_required_query(self):
        bad_hint = {
            "kind": "search_hint",
            "contract_version": "4.0.0",
            "hint_ref": "hint:bad",
            "terms": ["webcam plataforma creador digital irrelevante"],
            "origin": "internal_intake_model",
            "related_question_refs": ["question:filing"],
        }
        no_hint = build_research_plan(
            case_input(),
            intake(),
            generated_at=NOW,
        )
        with_hint = build_research_plan(
            case_input(),
            intake(hints=[bad_hint]),
            generated_at=NOW,
        )

        required_without = [
            task for task in no_hint["tasks"]
            if task["origin"] == "platform_required"
        ]
        required_with = [
            task for task in with_hint["tasks"]
            if task["origin"] == "platform_required"
        ]
        self.assertEqual(required_without, required_with)
        self.assertTrue(
            any(task["origin"] == "intake_hint_expansion" for task in with_hint["tasks"])
        )

    def test_domain_word_mismatch_discovers_general_filing_authority(self):
        primary = self.add_document_with_segment(
            document_id="DOC-tax-statute-592",
            number="624",
            year=1989,
            text=ARTICLE_592_THRESHOLD_RULE,
            filename="decreto_0624_1989.htm",
            document_type="DECRETO",
        )
        self.assertNotIn("webcam", ARTICLE_592_THRESHOLD_RULE.casefold())

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        self.assertIn(
            f"authority:{primary['document_id']}",
            execution.result["authority_refs"],
        )
        self.assertEqual(len(execution.evidence_candidates), 1)
        candidate = execution.evidence_candidates[0]
        self.assertEqual(candidate["extracted_segment_id"], primary["segment_id"])
        self.assertEqual(candidate["manifestation_sha256"], primary["raw_sha"])
        self.assertEqual(candidate["text_sha256"], primary["text_sha"])
        self.assertEqual(
            candidate["document_ref"],
            f"document:{primary['document_id']}",
        )
        self.assertIn("ARTÍCULO 592", candidate["text"])
        self.assertIn("ingresos brutos", candidate["text"].casefold())
        self.assertIn("patrimonio bruto", candidate["text"].casefold())
        self.assertTrue(candidate["task_refs"])
        self.assertTrue(candidate["query_texts"])
        self.assertTrue(
            any("ingresos brutos" in query.casefold() for query in candidate["query_texts"])
        )
        self.assertTrue(
            all("592" not in query for query in candidate["query_texts"]),
            "platform research must discover Article 592-family material without "
            "hardcoding the article number into the query",
        )

    def test_resolved_reference_expands_within_bounds(self):
        source_text = GENERAL_RULE + " Véase LEY 999 DE 2020."
        source = self.add_document_with_segment(
            document_id="DOC-source",
            number="1",
            year=2026,
            text=source_text,
            filename="ley_0001_2026.htm",
        )
        target = self.add_document_with_segment(
            document_id="DOC-target",
            number="999",
            year=2020,
            text=REFERENCE_RULE,
            filename="ley_0999_2020.htm",
        )
        self.add_resolved_reference(
            source=source,
            target=target,
            normalized_reference="LEY 999 DE 2020",
        )

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        reference_tasks = [
            task for task in execution.plan["tasks"]
            if task["origin"] == "reference_expansion"
        ]
        self.assertTrue(reference_tasks)
        self.assertIn(
            f"authority:{target['document_id']}",
            execution.result["authority_refs"],
        )
        self.assertLessEqual(
            len(execution.result["trace"]),
            execution.plan["bounds"]["max_queries_per_question"],
        )

    def test_temporal_ambiguity_remains_explicitly_unresolved(self):
        primary = self.add_document_with_segment(
            document_id="DOC-temporal",
            number="2",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_0002_2026.htm",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO temporal_role_resolutions(
                    temporal_resolution_id, extraction_id, document_id, role,
                    status, candidate_count, trusted_candidate_count,
                    promoted_candidate_id, processor_name, processor_version,
                    created_at, updated_at
                ) VALUES (
                    'TRR-issue137', ?, ?, 'commencement_rule',
                    'ambiguous', 2, 2, NULL,
                    'document_temporality_regex', '3', ?, ?
                )
                """,
                (
                    primary["extraction_id"],
                    primary["document_id"],
                    NOW,
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        temporal = [
            item for item in execution.unresolved
            if item["category"] == "temporal_uncertainty"
        ]
        self.assertTrue(temporal)
        authority = next(
            item for item in execution.authorities
            if item["authority_ref"] == "authority:DOC-temporal"
        )
        self.assertEqual(
            authority["temporal_state"]["resolution_state"],
            "ambiguous",
        )
        self.assertIsNone(authority["temporal_state"]["effective"])

    def test_non_effective_authority_does_not_satisfy_current_question(self):
        primary = self.add_document_with_segment(
            document_id="DOC-expired",
            number="8",
            year=2020,
            text=GENERAL_RULE,
            filename="ley_0008_2020.htm",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO temporal_events(
                    temporal_event_id, entity_type, entity_id, event_type,
                    event_date, effective_from, effective_to, caused_by_type,
                    caused_by_id, scope, status, evidence_id, confidence,
                    requires_human_review
                ) VALUES (
                    'TEV-issue137-expired', 'document', ?, 'enters_into_force',
                    '2020-01-01', '2020-01-01', '2021-01-01',
                    NULL, NULL, 'document', 'validated', NULL, 1.0, 0
                )
                """,
                (primary["document_id"],),
            )
            con.commit()
        finally:
            con.close()

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        self.assertIn("authority:DOC-expired", execution.result["authority_refs"])
        authority = next(
            item for item in execution.authorities
            if item["authority_ref"] == "authority:DOC-expired"
        )
        self.assertFalse(authority["temporal_state"]["effective"])
        self.assertEqual(execution.result["status"], "partial")
        self.assertNotEqual(
            execution.result["trace"][-1].get("stop_reason"),
            "questions_satisfied",
        )
        self.assertTrue(
            any(
                "not effective" in item["description"]
                for item in execution.unresolved
            )
        )

    def test_missing_client_fact_blocks_research_without_guessing(self):
        blocked = intake()
        blocked["facts"].append(
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:tax-year",
                "label": "Periodo gravable",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Indicar el periodo gravable consultado.",
            }
        )
        blocked["questions"][0]["status"] = "blocked"
        blocked["questions"][0]["depends_on_fact_refs"] = [
            "fact:person",
            "fact:tax-year",
        ]

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=blocked,
            generated_at=NOW,
        )

        self.assertEqual(execution.plan["tasks"], [])
        self.assertEqual(execution.result["trace"], [])
        self.assertEqual(execution.result["status"], "blocked")
        self.assertEqual(execution.result["authority_refs"], [])
        self.assertTrue(
            any(
                item["category"] == "missing_fact"
                and item["related_fact_refs"] == ["fact:tax-year"]
                and item["next_action"] == "ask_client"
                for item in execution.unresolved
            )
        )

    def test_duplicate_hits_are_stable_and_repeated_research_is_idempotent(self):
        self.add_document_with_segment(
            document_id="DOC-dedupe",
            number="3",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_0003_2026.htm",
        )
        hint = {
            "kind": "search_hint",
            "contract_version": "4.0.0",
            "hint_ref": "hint:secondary",
            "terms": ["ingresos brutos patrimonio"],
            "origin": "internal_intake_model",
            "related_question_refs": ["question:filing"],
        }
        service = PlatformResearchService(self.db)
        before_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()
        first = service.research(
            case_input=case_input(),
            intake_draft=intake(hints=[hint]),
            generated_at=NOW,
        )
        second = service.research(
            case_input=case_input(),
            intake_draft=intake(hints=[hint]),
            generated_at=NOW,
        )
        after_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            claim_count = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        finally:
            con.close()

        self.assertEqual(before_sha, after_sha)
        self.assertEqual(claim_count, 0)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.result, second.result)
        self.assertEqual(first.evidence_candidates, second.evidence_candidates)
        self.assertEqual(len(first.evidence_candidates), 1)
        self.assertEqual(len(first.evidence_candidates[0]["task_refs"]), 2)

    def test_query_bounds_stop_reference_loop(self):
        source = self.add_document_with_segment(
            document_id="DOC-bounded-source",
            number="4",
            year=2026,
            text=GENERAL_RULE + " Véase LEY 999 DE 2020.",
            filename="ley_0004_2026.htm",
        )
        target = self.add_document_with_segment(
            document_id="DOC-bounded-target",
            number="999",
            year=2020,
            text=REFERENCE_RULE,
            filename="ley_0999_2020.htm",
        )
        self.add_resolved_reference(
            source=source,
            target=target,
            normalized_reference="LEY 999 DE 2020",
        )

        execution = PlatformResearchService(
            self.db,
            bounds={"max_queries_per_question": 1},
        ).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        self.assertEqual(len(execution.result["trace"]), 1)
        self.assertEqual(
            execution.result["trace"][-1]["stop_reason"],
            "bounds_exhausted",
        )
        self.assertNotIn(
            f"authority:{target['document_id']}",
            execution.result["authority_refs"],
        )

    def test_unresolved_document_identity_is_not_guessed(self):
        primary = self.add_document_with_segment(
            document_id="DOC-unbound",
            number="5",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_0005_2026.htm",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE manifestations SET document_id = NULL WHERE manifestation_id = ?",
                (primary["manifestation_id"],),
            )
            con.commit()
        finally:
            con.close()

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )

        self.assertEqual(execution.result["authority_refs"], [])
        self.assertTrue(
            any(item["category"] == "unresolved_identity" for item in execution.unresolved)
        )
        self.assertNotIn("document_ref", execution.evidence_candidates[0])

    def test_segment_hash_mismatch_fails_closed(self):
        primary = self.add_document_with_segment(
            document_id="DOC-corrupt",
            number="6",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_0006_2026.htm",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                UPDATE extracted_segments
                SET text_sha256 = ?
                WHERE extracted_segment_id = ?
                """,
                ("0" * 64, primary["segment_id"]),
            )
            con.commit()
        finally:
            con.close()

        with self.assertRaises(RetrievalIntegrityError):
            PlatformResearchService(self.db).research(
                case_input=case_input(),
                intake_draft=intake(),
                generated_at=NOW,
            )

    def test_research_context_marks_unavailable_migration_metadata_explicitly(self):
        self.add_document_with_segment(
            document_id="DOC-context",
            number="7",
            year=2026,
            text=GENERAL_RULE,
            filename="ley_0007_2026.htm",
        )

        execution = PlatformResearchService(self.db).research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        context = execution.result["research_context"]

        self.assertEqual(len(context["corpus_snapshot_sha256"]), 64)
        self.assertEqual(len(context["retrieval_config_sha256"]), 64)
        self.assertIsNone(context["schema_migration_fingerprint"])
        self.assertIn(
            "schema_migration_fingerprint",
            context["unavailable_fields"],
        )
        self.assertEqual(context["as_of_date"], AS_OF)


if __name__ == "__main__":
    unittest.main()
