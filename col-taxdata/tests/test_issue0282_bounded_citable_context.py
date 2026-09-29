from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_issue0276_exact_reference_expansion as issue276

from case_evidence_graph import (
    _candidate_span,
    materialize_citable_context_spans,
)
from case_retrieval import CorpusRetrievalService, RetrievalHit


NOW = issue276.NOW


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Issue0282BoundedCitableContextTests(unittest.TestCase):
    setUp = issue276.Issue0276ExactReferenceExpansionTests.setUp
    tearDown = issue276.Issue0276ExactReferenceExpansionTests.tearDown
    add_document = issue276.Issue0276ExactReferenceExpansionTests.add_document
    add_provision = issue276.Issue0276ExactReferenceExpansionTests.add_provision
    add_reference = issue276.Issue0276ExactReferenceExpansionTests.add_reference

    def add_observation(
        self,
        *,
        token: str,
        document: dict[str, object],
        provision_id: str,
        segment_id: str,
        normative_text: str,
    ) -> None:
        text_sha = sha256_text(normative_text)
        con = sqlite3.connect(self.db)
        try:
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

    def add_bare_provision(
        self,
        *,
        token: str,
        document: dict[str, object],
        designation: str,
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
            con.commit()
        finally:
            con.close()
        return provision_id

    @staticmethod
    def candidate_from_hit(hit: RetrievalHit, provision_id: str) -> dict:
        assert hit.document_id is not None
        return {
            "extracted_segment_id": hit.extracted_segment_id,
            "extraction_id": hit.extraction_id,
            "sequence_no": hit.sequence_no,
            "text": hit.text,
            "text_sha256": hit.text_sha256,
            "manifestation_id": hit.manifestation_id,
            "manifestation_sha256": hit.manifestation_sha256,
            "source_ref": f"source:{hit.source_id}",
            "source_url": hit.source_url,
            "retrieved_at": hit.retrieved_at,
            "document_ref": f"document:{hit.document_id}",
            "authority_ref": f"authority:{hit.document_id}",
            "provision_ref": f"provision:{provision_id}",
        }

    def readonly(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        self.addCleanup(con.close)
        return con

    def test_heading_only_hit_expands_to_verified_following_parts_with_exact_hashes(
        self,
    ) -> None:
        heading = "OBJETIVO DEL SISTEMA"
        operative = (
            "El sistema tiene por objetivo coordinar las obligaciones "
            "tributarias dentro del marco legal aplicable."
        )
        exception = (
            "PARÁGRAFO. La coordinación se exceptúa cuando una norma especial "
            "disponga expresamente otra regla."
        )
        other_article = "ARTÍCULO 2. Regla independiente que no pertenece al artículo 1."
        document = self.add_document(
            token="heading-context",
            document_type="LEY",
            number="282",
            year=2026,
            issuer="CONGRESO",
            texts=[heading, operative, exception, other_article],
        )
        provision_id = self.add_provision(
            token="heading-context",
            document=document,
            segment_id=str(document["segment_ids"][0]),
            designation="ARTÍCULO 1",
            normative_text=heading,
        )
        self.add_observation(
            token="heading-operative",
            document=document,
            provision_id=provision_id,
            segment_id=str(document["segment_ids"][1]),
            normative_text=operative,
        )
        self.add_observation(
            token="heading-exception",
            document=document,
            provision_id=provision_id,
            segment_id=str(document["segment_ids"][2]),
            normative_text=exception,
        )
        self.add_provision(
            token="heading-other",
            document=document,
            segment_id=str(document["segment_ids"][3]),
            designation="ARTÍCULO 2",
            normative_text=other_article,
        )

        before_db = hashlib.sha256(self.db.read_bytes()).hexdigest()
        con = self.readonly()
        retrieval = CorpusRetrievalService(con)

        lookup = retrieval.lookup_canonical_target(
            str(document["document_id"]),
            target_provision_id=provision_id,
            limit=10,
        )
        anchor_hit = next(
            hit
            for hit in lookup.hits
            if hit.extracted_segment_id == document["segment_ids"][0]
        )
        anchor_span, _ = _candidate_span(
            con,
            self.candidate_from_hit(anchor_hit, provision_id),
        )
        assert anchor_span is not None
        self.assertEqual(anchor_span["exact_text"], heading)

        first = retrieval.retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=4,
            include_resolved_references=False,
        )
        second = retrieval.retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=4,
            include_resolved_references=False,
        )
        spans = materialize_citable_context_spans(con, first)
        after_db = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(first, second)
        self.assertEqual(before_db, after_db)
        self.assertEqual(first.context_status, "expanded_verified")
        self.assertFalse(first.budget_exhausted)
        self.assertEqual(first.gaps, ())
        self.assertEqual(
            [item.hit.extracted_segment_id for item in first.hits],
            list(document["segment_ids"][1:3]),
        )
        self.assertNotIn(
            str(document["segment_ids"][3]),
            {item.hit.extracted_segment_id for item in first.hits},
        )
        self.assertEqual(
            [span["exact_text"] for span in spans],
            [operative, exception],
        )
        self.assertEqual(
            [span["text_sha256"] for span in spans],
            [sha256_text(operative), sha256_text(exception)],
        )
        self.assertEqual(
            {span["source_sha256"] for span in spans},
            {document["raw_sha"]},
        )
        self.assertEqual(
            {span["provision_ref"] for span in spans},
            {f"provision:{provision_id}"},
        )
        self.assertEqual(len({span["span_ref"] for span in spans}), 2)
        self.assertEqual(
            {item.bases for item in first.hits},
            {("contiguous_provision",)},
        )

    def test_amendment_introduction_keeps_replacement_text_as_separate_span(self) -> None:
        introduction = (
            "Modifíquese el artículo 10 de la presente ley, el cual quedará así:"
        )
        replacement = (
            "ARTÍCULO 10. La obligación se cumplirá dentro del plazo especial "
            "previsto para el supuesto regulado."
        )
        document = self.add_document(
            token="amendment-context",
            document_type="LEY",
            number="283",
            year=2026,
            issuer="CONGRESO",
            texts=[introduction, replacement],
        )
        provision_id = self.add_provision(
            token="amendment-context",
            document=document,
            segment_id=str(document["segment_ids"][0]),
            designation="ARTÍCULO 10",
            normative_text=introduction,
        )
        self.add_observation(
            token="amendment-replacement",
            document=document,
            provision_id=provision_id,
            segment_id=str(document["segment_ids"][1]),
            normative_text=replacement,
        )

        con = self.readonly()
        result = CorpusRetrievalService(con).retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=2,
            include_resolved_references=False,
        )
        spans = materialize_citable_context_spans(con, result)

        self.assertEqual(result.context_status, "expanded_verified")
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].hit.text, replacement)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["exact_text"], replacement)
        self.assertNotIn(introduction, spans[0]["exact_text"])
        self.assertNotEqual(spans[0]["span_ref"], "")

    def test_unverified_contiguous_segment_is_a_hard_gap_and_cannot_be_skipped(
        self,
    ) -> None:
        anchor = "ARTÍCULO 1. Regla inicial que necesita contexto."
        unverifiable = "Texto intermedio sin observación de provisión verificable."
        later = "PARÁGRAFO. Esta parte posterior no puede saltar el hueco."
        document = self.add_document(
            token="unverified-boundary",
            document_type="LEY",
            number="284",
            year=2026,
            issuer="CONGRESO",
            texts=[anchor, unverifiable, later],
        )
        provision_id = self.add_provision(
            token="unverified-boundary",
            document=document,
            segment_id=str(document["segment_ids"][0]),
            designation="ARTÍCULO 1",
            normative_text=anchor,
        )
        self.add_observation(
            token="unverified-later",
            document=document,
            provision_id=provision_id,
            segment_id=str(document["segment_ids"][2]),
            normative_text=later,
        )

        con = self.readonly()
        result = CorpusRetrievalService(con).retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=4,
            include_resolved_references=False,
        )

        self.assertEqual(result.context_status, "incomplete")
        self.assertEqual(result.hits, ())
        self.assertEqual(
            {gap.reason for gap in result.gaps},
            {"unverified_contiguous_boundary"},
        )
        self.assertNotIn(
            str(document["segment_ids"][2]),
            {item.hit.extracted_segment_id for item in result.hits},
        )

    def test_resolved_provision_reference_materializes_definition_without_broadening(
        self,
    ) -> None:
        source_text = (
            "ARTÍCULO 5. Para aplicar esta regla, véase la definición del "
            "ARTÍCULO 2 DE LA LEY 90 DE 2020."
        )
        target_text = (
            "ARTÍCULO 2. DEFINICIÓN. Beneficiario es la persona que cumple "
            "los requisitos expresamente previstos por esta ley."
        )
        source = self.add_document(
            token="xref-source",
            document_type="LEY",
            number="285",
            year=2026,
            issuer="CONGRESO",
            texts=[source_text],
        )
        source_provision = self.add_provision(
            token="xref-source",
            document=source,
            segment_id=str(source["segment_ids"][0]),
            designation="ARTÍCULO 5",
            normative_text=source_text,
        )
        target = self.add_document(
            token="xref-target",
            document_type="LEY",
            number="90",
            year=2020,
            issuer="CONGRESO",
            texts=[target_text],
        )
        target_provision = self.add_provision(
            token="xref-target",
            document=target,
            segment_id=str(target["segment_ids"][0]),
            designation="ARTÍCULO 2",
            normative_text=target_text,
        )
        self.add_reference(
            token="xref-definition",
            source=source,
            normalized_reference="ARTÍCULO 2 DE LA LEY 90 DE 2020",
            target_document_id=str(target["document_id"]),
            target_provision_id=target_provision,
        )

        con = self.readonly()
        result = CorpusRetrievalService(con).retrieve_citable_context(
            str(source["segment_ids"][0]),
            provision_id=source_provision,
            max_context_hits=2,
        )
        spans = materialize_citable_context_spans(con, result)

        self.assertEqual(result.context_status, "expanded_verified")
        self.assertEqual(len(result.hits), 1)
        item = result.hits[0]
        self.assertEqual(item.provision_id, target_provision)
        self.assertEqual(item.bases, ("explicit_cross_reference",))
        self.assertEqual(
            item.source_segment_ids,
            (str(source["segment_ids"][0]),),
        )
        self.assertEqual(item.reference_mention_ids, ("RM-xref-definition",))
        self.assertEqual(spans[0]["exact_text"], target_text)
        self.assertEqual(
            spans[0]["document_ref"],
            f"document:{target['document_id']}",
        )
        self.assertEqual(
            spans[0]["provision_ref"],
            f"provision:{target_provision}",
        )

    def test_missing_reference_content_is_gap_and_never_uses_thematic_distractor(
        self,
    ) -> None:
        source_text = (
            "ARTÍCULO 8. Véase ARTÍCULO 3 DE LA LEY 91 DE 2020 para la "
            "definición requerida."
        )
        source = self.add_document(
            token="missing-xref-source",
            document_type="LEY",
            number="286",
            year=2026,
            issuer="CONGRESO",
            texts=[source_text],
        )
        source_provision = self.add_provision(
            token="missing-xref-source",
            document=source,
            segment_id=str(source["segment_ids"][0]),
            designation="ARTÍCULO 8",
            normative_text=source_text,
        )
        target = self.add_document(
            token="missing-xref-target",
            document_type="LEY",
            number="91",
            year=2020,
            issuer="CONGRESO",
            texts=["Documento objetivo sin observación del artículo citado."],
        )
        target_provision = self.add_bare_provision(
            token="missing-xref-target",
            document=target,
            designation="ARTÍCULO 3",
        )
        distractor = self.add_document(
            token="missing-xref-distractor",
            document_type="CONCEPTO",
            number="91",
            year=2020,
            issuer="DIAN",
            texts=[
                "ARTÍCULO 3 DE LA LEY 91 DE 2020 definición requerida "
                "aparece aquí sólo como distractor temático."
            ],
        )
        self.add_reference(
            token="missing-xref",
            source=source,
            normalized_reference="ARTÍCULO 3 DE LA LEY 91 DE 2020",
            target_document_id=str(target["document_id"]),
            target_provision_id=target_provision,
        )

        before_db = hashlib.sha256(self.db.read_bytes()).hexdigest()
        con = self.readonly()
        result = CorpusRetrievalService(con).retrieve_citable_context(
            str(source["segment_ids"][0]),
            provision_id=source_provision,
            max_context_hits=4,
        )
        after_db = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(before_db, after_db)
        self.assertEqual(result.context_status, "incomplete")
        self.assertEqual(result.hits, ())
        self.assertIn(
            "reference_target_context_unavailable",
            {gap.reason for gap in result.gaps},
        )
        self.assertNotIn(
            str(distractor["document_id"]),
            {item.hit.document_id for item in result.hits},
        )

    def test_context_budget_exhaustion_is_explicit_and_deterministic(self) -> None:
        texts = [
            "ARTÍCULO 1. Encabezado contextual.",
            "INCISO 1. Primera condición contextual verificable.",
            "INCISO 2. Segunda condición contextual verificable.",
            "PARÁGRAFO. Excepción contextual verificable.",
        ]
        document = self.add_document(
            token="budget-context",
            document_type="LEY",
            number="287",
            year=2026,
            issuer="CONGRESO",
            texts=texts,
        )
        provision_id = self.add_provision(
            token="budget-context",
            document=document,
            segment_id=str(document["segment_ids"][0]),
            designation="ARTÍCULO 1",
            normative_text=texts[0],
        )
        for index in range(1, len(texts)):
            self.add_observation(
                token=f"budget-{index}",
                document=document,
                provision_id=provision_id,
                segment_id=str(document["segment_ids"][index]),
                normative_text=texts[index],
            )

        con = self.readonly()
        service = CorpusRetrievalService(con)
        first = service.retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=1,
            include_resolved_references=False,
        )
        second = service.retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=1,
            include_resolved_references=False,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.context_status, "incomplete")
        self.assertTrue(first.budget_exhausted)
        self.assertEqual(len(first.hits), 1)
        self.assertEqual(first.verified_candidate_count, 2)
        self.assertIn(
            "budget_exhausted",
            {gap.reason for gap in first.gaps},
        )

    def test_concise_exact_provision_remains_one_exact_span(self) -> None:
        text = "ARTÍCULO ÚNICO. La regla completa cabe en este único segmento."
        document = self.add_document(
            token="concise-context",
            document_type="LEY",
            number="288",
            year=2026,
            issuer="CONGRESO",
            texts=[text],
        )
        provision_id = self.add_provision(
            token="concise-context",
            document=document,
            segment_id=str(document["segment_ids"][0]),
            designation="ARTÍCULO ÚNICO",
            normative_text=text,
        )

        con = self.readonly()
        service = CorpusRetrievalService(con)
        lookup = service.lookup_canonical_target(
            str(document["document_id"]),
            target_provision_id=provision_id,
            limit=4,
        )
        self.assertEqual(len(lookup.hits), 1)
        span, _ = _candidate_span(
            con,
            self.candidate_from_hit(lookup.hits[0], provision_id),
        )
        assert span is not None
        context = service.retrieve_citable_context(
            str(document["segment_ids"][0]),
            provision_id=provision_id,
            max_context_hits=4,
            include_resolved_references=False,
        )

        self.assertEqual(span["exact_text"], text)
        self.assertEqual(span["text_sha256"], sha256_text(text))
        self.assertEqual(context.hits, ())
        self.assertEqual(context.context_status, "incomplete")
        self.assertEqual(
            {gap.reason for gap in context.gaps},
            {"no_verified_context"},
        )


if __name__ == "__main__":
    unittest.main()
