from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from case_research import RETRIEVAL_VERSION, retrieval_config_sha256
from case_retrieval import (
    CorpusRetrievalService,
    build_thematic_query_plan,
)
from test_issue0189_treaty_research_coverage import (
    Issue0189TreatyResearchCoverageTests,
)


SIMPLE_QUERY = (
    "¿Qué efecto puede tener el régimen simple de tributación "
    "sobre declaración y anticipos?"
)
SIMPLE_RELEVANT = (
    "El régimen simple de tributación establece reglas propias para anticipos "
    "y consolida obligaciones dentro del impuesto unificado."
)
SIMPLE_DISTRACTOR = (
    "Qué efecto puede tener el régimen tributario sobre otros temas: la "
    "tributación simple regula declaración con anticipos en este comentario "
    "general, sin describir esos términos como un concepto conjunto."
)

PENALTY_QUERY = "declaración tardía"
PENALTY_PARAPHRASE = (
    "La declaración extemporánea puede generar una sanción tributaria conforme "
    "a los supuestos y reducciones legalmente aplicables."
)

NUMERIC_QUERY = "artículo 7 beneficios empresariales"
NUMERIC_RELEVANT = (
    "ARTÍCULO 7. BENEFICIOS EMPRESARIALES. La disposición regula los beneficios "
    "de una empresa bajo los supuestos previstos por el instrumento."
)
NUMERIC_DISTRACTOR = (
    "ARTÍCULO 70. BENEFICIOS EMPRESARIALES se menciona aquí únicamente como "
    "distractor numérico para comprobar que 70 no equivale a 7."
)


class Issue0278ThematicRetrievalTests(unittest.TestCase):
    # Reuse only the deterministic isolated-corpus fixture helpers. Do not
    # inherit the #189 unittest class because that would duplicate its suite.
    setUp = Issue0189TreatyResearchCoverageTests.setUp
    tearDown = Issue0189TreatyResearchCoverageTests.tearDown
    add_document = Issue0189TreatyResearchCoverageTests.add_document

    def _service(self) -> CorpusRetrievalService:
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        self.addCleanup(con.close)
        return CorpusRetrievalService(con)

    def _legacy_search_ids(self, query: str, *, limit: int) -> list[str]:
        """Reproduce the pre-#278 max-18, >=3-char blanket-OR baseline."""
        terms: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"[^\W_]{3,}", query.casefold(), re.UNICODE):
            term = match.group(0)
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 18:
                break
        if not terms:
            return []
        fts_query = " OR ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"'
            for term in terms
        )
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """
                SELECT es.extracted_segment_id
                FROM extracted_segments_fts
                JOIN extracted_segments es
                  ON es.rowid = extracted_segments_fts.rowid
                WHERE extracted_segments_fts MATCH ?
                ORDER BY bm25(extracted_segments_fts), extracted_segments_fts.rowid
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        finally:
            con.close()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _quality(ids: list[str], relevant: set[str]) -> tuple[float, float]:
        if not ids:
            return 0.0, 0.0
        relevant_hits = len(set(ids) & relevant)
        coverage = relevant_hits / len(relevant)
        distractor_proportion = (len(ids) - relevant_hits) / len(ids)
        return coverage, distractor_proportion

    def test_simple_fixture_improves_coverage_and_distractor_proportion_same_budget(self):
        # Distractors deliberately contain almost every old OR token while
        # separating/reordering the actual multiword concept.
        for index in range(12):
            self.add_document(
                document_id=f"DOC-simple-noise-{index:02d}",
                number=str(100 + index),
                year=2026,
                texts=[f"{SIMPLE_DISTRACTOR} Muestra {index}."],
                filename=f"simple-noise-{index:02d}.htm",
                document_type="CONCEPTO",
                issuer="DIAN",
            )
        relevant_ids = self.add_document(
            document_id="DOC-simple-relevant",
            number="SIMPLE",
            year=2026,
            texts=[SIMPLE_RELEVANT],
            filename="simple-relevant.htm",
            document_type="DECRETO",
            issuer="PRESIDENCIA",
        )
        relevant = {relevant_ids[0]}
        limit = 6

        before_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()
        legacy_ids = self._legacy_search_ids(SIMPLE_QUERY, limit=limit)

        service = self._service()
        first = service.search_detailed(SIMPLE_QUERY, limit=limit)
        second = service.search_detailed(SIMPLE_QUERY, limit=limit)
        after_sha = hashlib.sha256(self.db.read_bytes()).hexdigest()

        new_ids = [hit.extracted_segment_id for hit in first.hits]
        legacy_coverage, legacy_distractors = self._quality(legacy_ids, relevant)
        new_coverage, new_distractors = self._quality(new_ids, relevant)

        self.assertEqual(before_sha, after_sha)
        self.assertEqual(first, second)
        self.assertEqual(len(legacy_ids), limit)
        self.assertEqual(len(new_ids), limit)
        self.assertGreater(new_coverage, legacy_coverage)
        self.assertLess(new_distractors, legacy_distractors)
        self.assertEqual(new_coverage, 1.0)
        self.assertEqual(first.hits[0].extracted_segment_id, relevant_ids[0])
        self.assertEqual(first.hits[0].retrieval_strategy, "concept_phrase")
        self.assertTrue(first.stages)
        self.assertEqual(first.stages[0].strategy, "concept_phrase")

    def test_unseen_penalty_wording_is_found_by_controlled_variant_stage(self):
        relevant_ids = self.add_document(
            document_id="DOC-penalty-relevant",
            number="200",
            year=2026,
            texts=[PENALTY_PARAPHRASE],
            filename="penalty-relevant.htm",
            document_type="LEY",
            issuer="CONGRESO",
        )
        for index in range(4):
            self.add_document(
                document_id=f"DOC-penalty-noise-{index}",
                number=str(210 + index),
                year=2026,
                texts=[
                    "La declaración ordinaria se presenta dentro del plazo; "
                    f"nota procedimental {index}."
                ],
                filename=f"penalty-noise-{index}.htm",
                document_type="CONCEPTO",
                issuer="DIAN",
            )

        result = self._service().search_detailed(PENALTY_QUERY, limit=4)
        by_id = {hit.extracted_segment_id: hit for hit in result.hits}

        self.assertIn(relevant_ids[0], by_id)
        self.assertEqual(
            by_id[relevant_ids[0]].retrieval_strategy,
            "controlled_lexical_variants",
        )
        self.assertTrue(
            any(
                stage.strategy == "controlled_lexical_variants"
                and stage.reason == "controlled_variant_recall"
                for stage in result.stages
            )
        )

    def test_short_numeric_token_disambiguates_article_seven_from_seventy(self):
        distractor_ids = self.add_document(
            document_id="DOC-numeric-distractor",
            number="70",
            year=2026,
            texts=[NUMERIC_DISTRACTOR],
            filename="numeric-distractor.htm",
            document_type="LEY",
            issuer="CONGRESO",
        )
        relevant_ids = self.add_document(
            document_id="DOC-numeric-relevant",
            number="7",
            year=2026,
            texts=[NUMERIC_RELEVANT],
            filename="numeric-relevant.htm",
            document_type="LEY",
            issuer="CONGRESO",
        )

        plan = build_thematic_query_plan(NUMERIC_QUERY)
        self.assertIn("7", plan.numeric_terms)
        self.assertTrue(
            any('"7"' in stage.fts_query for stage in plan.stages)
        )

        result = self._service().search_detailed(NUMERIC_QUERY, limit=2)
        ids = [hit.extracted_segment_id for hit in result.hits]
        self.assertEqual(ids[0], relevant_ids[0])
        self.assertIn(distractor_ids[0], ids)

    def test_generated_fts_syntax_neutralizes_operator_and_sql_like_input(self):
        self.add_document(
            document_id="DOC-injection-guard",
            number="300",
            year=2026,
            texts=[
                "Retención en la fuente y régimen simple son expresiones "
                "jurídicas presentes en este segmento de prueba."
            ],
            filename="injection-guard.htm",
            document_type="CONCEPTO",
            issuer="DIAN",
        )
        malicious = (
            'retención" OR turismo* NEAR(simple) ; DROP TABLE documents -- 7'
        )
        plan = build_thematic_query_plan(malicious)
        self.assertTrue(plan.stages)
        for stage in plan.stages:
            self.assertNotIn(";", stage.fts_query)
            self.assertNotIn("*", stage.fts_query)
            self.assertNotIn("--", stage.fts_query)
            self.assertNotIn("NEAR(", stage.fts_query)

        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            before = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            result = CorpusRetrievalService(con).search_detailed(malicious, limit=4)
            after = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(before, after)
        self.assertIsNotNone(result)

    def test_retrieval_configuration_is_versioned_and_stable(self):
        self.assertEqual(RETRIEVAL_VERSION, "6")
        first = retrieval_config_sha256()
        second = retrieval_config_sha256()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
