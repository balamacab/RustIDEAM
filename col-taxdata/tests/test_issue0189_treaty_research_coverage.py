from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_research import PlatformResearchService, build_research_plan


NOW = "2026-09-28T02:00:00+00:00"
AS_OF = "2026-09-27"
BASE = "https://www.corteconstitucional.gov.co/relatoria/2008/"

PROBLEM = (
    "Una SAS colombiana contrató con una sociedad residente fiscal en España "
    "una solución empresarial con acceso SaaS, implementación remota, soporte "
    "técnico y capacitación. A 27 de septiembre de 2026 pregunta qué efecto "
    "puede tener el convenio para evitar la doble imposición entre Colombia y "
    "España, sin asumir de antemano la caracterización tributaria de cada pago."
)
QUESTION = (
    "¿Qué efecto puede tener el convenio para evitar la doble imposición entre "
    "Colombia y España?"
)
FACT_QUOTE = (
    "Una SAS colombiana contrató con una sociedad residente fiscal en España "
    "una solución empresarial con acceso SaaS, implementación remota, soporte "
    "técnico y capacitación."
)

TREATY_OVERVIEW = (
    "CONVENIO PARA EVITAR LA DOBLE IMPOSICIÓN ENTRE COLOMBIA Y ESPAÑA. "
    "La Corte revisa la aprobación y el alcance general del convenio."
)
BUSINESS_PROFITS = (
    "ARTÍCULO 7. BENEFICIOS EMPRESARIALES. Los beneficios de una empresa de "
    "un Estado contratante se someten a imposición conforme a las reglas del "
    "convenio, sin prejuzgar la caracterización de un pago concreto."
)
ROYALTIES = (
    "ARTÍCULO 12. CÁNONES O REGALÍAS. La definición comprende, en los términos "
    "del convenio, referencias a asistencia técnica, servicios técnicos y "
    "consultoría, junto con las reglas de tributación en la fuente."
)
PERMANENT_ESTABLISHMENT = (
    "ESTABLECIMIENTO PERMANENTE. El convenio contiene reglas específicas sobre "
    "establecimiento permanente y la conexión de determinados rendimientos con "
    "ese establecimiento."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": PROBLEM,
        "as_of_date": AS_OF,
    }


def intake(*, hints: list[dict] | None = None) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue189",
        "problem_text": PROBLEM,
        "as_of_date": AS_OF,
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:transaction",
                "label": "SAS colombiana contrata solución empresarial con sociedad española",
                "value": "SaaS, implementación, soporte técnico y capacitación",
                "state": "user_provided",
                "source_quote": FACT_QUOTE,
                "requires_confirmation": False,
            }
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:treaty",
                "text": QUESTION,
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:transaction"],
            }
        ],
        "search_hints": [] if hints is None else hints,
        "model_metadata": {
            "adapter": "fixture",
            "provider": "fixture",
            "model": "fixture",
            "schema_version": "4.0.0",
            "prompt_template_id": "case-intake-v4",
            "prompt_template_version": "2",
            "run_reference": "run:issue189",
            "generated_at": NOW,
            "routing_role": "intake_structuring",
        },
    }


class Issue0189TreatyResearchCoverageTests(unittest.TestCase):
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

    def add_document(
        self,
        *,
        document_id: str,
        number: str,
        year: int,
        texts: list[str],
        filename: str,
        document_type: str = "SENTENCIA",
        issuer: str = "CORTE CONSTITUCIONAL",
    ) -> list[str]:
        token = document_id.replace("DOC-", "").lower()
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        source_url = BASE + filename
        raw_sha = hashlib.sha256(f"raw:{source_url}".encode()).hexdigest()
        normalized_sha = hashlib.sha256(
            ("normalized:" + "\n".join(texts)).encode()
        ).hexdigest()

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
                ) VALUES (?, ?, 'CORTE_CONSTITUCIONAL', 'official_html', NULL, ?, ?)
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
                    len("\n".join(texts).encode()),
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
                    len("\n".join(texts).encode()),
                    len("\n".join(texts)),
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

    def test_treaty_plan_adds_bounded_platform_topic_tasks_deterministically(self):
        misleading_hint = {
            "kind": "search_hint",
            "contract_version": "4.0.0",
            "hint_ref": "hint:model",
            "terms": ["software internacional"],
            "origin": "internal_intake_model",
            "related_question_refs": ["question:treaty"],
        }
        first = build_research_plan(
            case_input(),
            intake(hints=[misleading_hint]),
            generated_at=NOW,
        )
        second = build_research_plan(
            case_input(),
            intake(hints=[misleading_hint]),
            generated_at=NOW,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["planner_version"], "2")

        platform_queries = [
            task["query_text"]
            for task in first["tasks"]
            if task["origin"] == "platform_required"
        ]
        self.assertEqual(len(platform_queries), 4)
        self.assertIn("beneficios empresariales", platform_queries)
        self.assertIn("cánones regalías", platform_queries)
        self.assertIn("establecimiento permanente", platform_queries)
        self.assertLessEqual(
            len(first["tasks"]),
            first["bounds"]["max_queries_per_question"],
        )
        self.assertTrue(
            all(
                task["purpose"] == "primary_research"
                for task in first["tasks"]
                if task["origin"] == "platform_required"
            )
        )
        self.assertTrue(
            any(task["origin"] == "intake_hint_expansion" for task in first["tasks"])
        )

    def test_crowded_generic_hits_cannot_hide_material_treaty_topics(self):
        treaty_segments = self.add_document(
            document_id="DOC-treaty-review",
            number="C-383",
            year=2008,
            texts=[
                TREATY_OVERVIEW,
                BUSINESS_PROFITS,
                ROYALTIES,
                PERMANENT_ESTABLISHMENT,
            ],
            filename="C-383-08.htm",
        )

        # Fill the generic treaty-query window with material that matches the
        # broad question very well but does not contain the provision topics.
        # The issue #189 fix must not depend on increasing max_hits_per_query.
        for index in range(30):
            self.add_document(
                document_id=f"DOC-noise-{index:02d}",
                number=str(1000 + index),
                year=2020,
                texts=[
                    (
                        "Convenio para evitar la doble imposición entre Colombia "
                        "y España: comentario tributario general sobre el efecto "
                        f"del convenio, referencia {index}."
                    )
                ],
                filename=f"noise-{index:02d}.htm",
                document_type="CONCEPTO",
                issuer="DIAN",
            )

        before_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()
        service = PlatformResearchService(self.db)
        first = service.research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        second = service.research(
            case_input=case_input(),
            intake_draft=intake(),
            generated_at=NOW,
        )
        after_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(before_sha, after_sha)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.result, second.result)
        self.assertEqual(first.evidence_candidates, second.evidence_candidates)

        candidates = {
            item["extracted_segment_id"]: item for item in first.evidence_candidates
        }
        for segment_id in treaty_segments[1:]:
            self.assertIn(segment_id, candidates)

        self.assertTrue(
            any(
                "beneficios empresariales" in item["text"].casefold()
                and "beneficios empresariales" in item["query_texts"]
                for item in first.evidence_candidates
            )
        )
        self.assertTrue(
            any(
                "cánones o regalías" in item["text"].casefold()
                and "cánones regalías" in item["query_texts"]
                for item in first.evidence_candidates
            )
        )
        self.assertTrue(
            any(
                "establecimiento permanente" in item["text"].casefold()
                and "establecimiento permanente" in item["query_texts"]
                for item in first.evidence_candidates
            )
        )
        self.assertLessEqual(
            len(first.result["trace"]),
            first.plan["bounds"]["max_queries_per_question"],
        )
        self.assertIn(
            "authority:DOC-treaty-review",
            first.result["authority_refs"],
        )

        # The planner researches possible treaty provision families only. It
        # must not turn the client's components into an asserted legal outcome.
        joined_queries = " ".join(
            task["query_text"] for task in first.plan["tasks"]
        ).casefold()
        self.assertNotIn("saas es regal", joined_queries)
        self.assertNotIn("soporte es regal", joined_queries)
        self.assertNotIn("capacitación es regal", joined_queries)


if __name__ == "__main__":
    unittest.main()
