from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_issue0180_evidence_owner_closure as issue180
import test_issue0283_case_v5_coverage as issue283

from case_evidence_graph import materialize_selected_relationship_support
from case_research_coverage_v5 import (
    build_research_result_v5,
    research_context_for_coverage_v5,
)
from case_relationship_selection_v5 import (
    GRAPH_SELECTION_VERSION,
    RelationshipSelectionError,
    select_research_relationships_v5,
)
from legal_authority_classification import classify_canonical_authority


NOW = issue180.NOW
ARTICLE_592 = issue180.ARTICLE_592


class Issue0284RelationshipSelectionTests(unittest.TestCase):
    """Regression coverage for v5 relationship selection before support closure."""

    setUp = issue180.Issue0180EvidenceOwnerClosureTests.setUp
    tearDown = issue180.Issue0180EvidenceOwnerClosureTests.tearDown
    add_provision_document = (
        issue180.Issue0180EvidenceOwnerClosureTests.add_provision_document
    )

    def add_extra_provision(
        self,
        *,
        provision_id: str,
        document_id: str,
        designation: str,
    ) -> None:
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
                    document_id,
                    designation,
                    designation.casefold(),
                    NOW,
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()

    def add_scoped_relationship(
        self,
        *,
        relationship_id: str,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
        evidence_id: str,
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
                    ?, ?, ?, ?, ?, ?, 'issue284_test',
                    NULL, NULL, NULL, 'validated', ?, 1.0, 0
                )
                """,
                (
                    relationship_id,
                    source_type,
                    source_id,
                    relation_type,
                    target_type,
                    target_id,
                    evidence_id,
                ),
            )
            con.commit()
        finally:
            con.close()

    def selector_plan(
        self,
        *,
        aspect_ref: str = "aspect:issue284",
        max_relationships: int = 16,
        required: bool = True,
    ) -> dict:
        return {
            "plan_ref": "plan:issue284",
            "aspects": [
                {
                    "aspect_ref": aspect_ref,
                    "required": required,
                }
            ],
            "budgets": {
                "support": {
                    "max_relationships_per_aspect": max_relationships,
                }
            },
        }

    @staticmethod
    def evidence_span(
        fixture: dict[str, str],
        *,
        aspect_authority_ref: str,
    ) -> dict:
        return {
            "evidence_ref": f"evidence:{fixture['evidence_id']}",
            "authority_ref": aspect_authority_ref,
            "provision_ref": f"provision:{fixture['provision_id']}",
        }

    @staticmethod
    def evidence_selection(
        *,
        aspect_ref: str,
        authority_ref: str,
        evidence_ref: str,
        task_ref: str = "task:issue284",
    ) -> dict:
        return {
            "aspect_ref": aspect_ref,
            "task_ref": task_ref,
            "authority_ref": authority_ref,
            "evidence_refs": [evidence_ref],
            "basis": "thematic_relevance",
            "context_status": "exact_sufficient",
            "authority_status": "resolved",
            "temporal_status": "unassessed",
        }

    def classify(self, document_id: str) -> dict:
        return classify_canonical_authority(
            document_id=document_id,
            db_path=self.db,
            as_of_date=None,
        )

    def test_high_degree_fixture_selects_before_complete_support_closure(self):
        primary = self.add_provision_document(
            token="284-hub",
            document_id="DOC-284-hub",
            document_type="LEY",
            number="284",
            year=2026,
            filename="ley_0284_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        exact_endpoint = self.add_provision_document(
            token="284-exact-endpoint",
            document_id="DOC-284-exact-endpoint",
            document_type="DECRETO",
            number="1",
            year=2026,
            filename="decreto_0001_2026.htm",
            text="Endpoint necesario sin vocabulario de la consulta.",
            designation="Artículo 1",
        )
        document_dependency = self.add_provision_document(
            token="284-document-dependency",
            document_id="DOC-284-document-dependency",
            document_type="LEY",
            number="2",
            year=2026,
            filename="ley_0002_2026.htm",
            text="Dependencia documental sin similitud textual.",
            designation="Artículo 1",
        )
        unrelated_endpoint = self.add_provision_document(
            token="284-unrelated-endpoint",
            document_id="DOC-284-unrelated-endpoint",
            document_type="RESOLUCION",
            number="3",
            year=2026,
            filename="resolucion_0003_2026.htm",
            text="Relación de otra provisión del mismo documento.",
            designation="Artículo 1",
        )
        cited_endpoint = self.add_provision_document(
            token="284-cited-endpoint",
            document_id="DOC-284-cited-endpoint",
            document_type="CIRCULAR",
            number="4",
            year=2026,
            filename="circular_0004_2026.htm",
            text="Mención documental no obligatoria.",
            designation="Artículo 1",
        )
        evidence_owner = self.add_provision_document(
            token="284-evidence-owner",
            document_id="DOC-284-evidence-owner",
            document_type="RESOLUCION",
            number="5",
            year=2026,
            filename="resolucion_0005_2026.htm",
            text="Fuente propietaria de la evidencia de relación.",
            designation="Artículo 1",
        )
        second_degree = self.add_provision_document(
            token="284-second-degree",
            document_id="DOC-284-second-degree",
            document_type="RESOLUCION",
            number="6",
            year=2026,
            filename="resolucion_0006_2026.htm",
            text="Segundo grado que no debe materializarse.",
            designation="Artículo 1",
        )

        other_provision_id = "PROV-284-hub-other"
        self.add_extra_provision(
            provision_id=other_provision_id,
            document_id=primary["document_id"],
            designation="Artículo 999",
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-selected",
            source_type="provision",
            source_id=primary["provision_id"],
            relation_type="implements",
            target_type="provision",
            target_id=exact_endpoint["provision_id"],
            evidence_id=evidence_owner["evidence_id"],
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-document-repeal",
            source_type="document",
            source_id=primary["document_id"],
            relation_type="repeals",
            target_type="document",
            target_id=document_dependency["document_id"],
            evidence_id=primary["evidence_id"],
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-unrelated-provision",
            source_type="provision",
            source_id=other_provision_id,
            relation_type="defines",
            target_type="provision",
            target_id=unrelated_endpoint["provision_id"],
            evidence_id=unrelated_endpoint["evidence_id"],
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-document-cite",
            source_type="document",
            source_id=primary["document_id"],
            relation_type="cites",
            target_type="document",
            target_id=cited_endpoint["document_id"],
            evidence_id=cited_endpoint["evidence_id"],
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-second-degree",
            source_type="document",
            source_id=exact_endpoint["document_id"],
            relation_type="defines",
            target_type="document",
            target_id=second_degree["document_id"],
            evidence_id=second_degree["evidence_id"],
        )

        classified = self.classify(primary["document_id"])
        candidate_refs = {
            item["relationship_ref"] for item in classified["relationships"]
        }
        self.assertEqual(
            candidate_refs,
            {
                "relationship:REL-284-document-cite",
                "relationship:REL-284-document-repeal",
                "relationship:REL-284-selected",
                "relationship:REL-284-unrelated-provision",
            },
        )

        aspect_ref = "aspect:issue284"
        authority_ref = f"authority:{primary['document_id']}"
        span = self.evidence_span(
            primary,
            aspect_authority_ref=authority_ref,
        )
        selection = self.evidence_selection(
            aspect_ref=aspect_ref,
            authority_ref=authority_ref,
            evidence_ref=span["evidence_ref"],
        )
        plan = self.selector_plan(aspect_ref=aspect_ref, max_relationships=8)

        before_db = hashlib.sha256(self.db.read_bytes()).hexdigest()
        first = select_research_relationships_v5(
            plan=plan,
            evidence_selections=[selection],
            evidence_spans=[span],
            relationships=classified["relationships"],
            db_path=self.db,
        )
        second = select_research_relationships_v5(
            plan=plan,
            evidence_selections=[selection],
            evidence_spans=[span],
            relationships=classified["relationships"],
            db_path=self.db,
        )
        support = materialize_selected_relationship_support(
            authorities=[classified["authority"]],
            relationships=first.selected_relationships,
            unresolved=classified["unresolved"],
            db_path=self.db,
        )
        support_again = materialize_selected_relationship_support(
            authorities=[classified["authority"]],
            relationships=second.selected_relationships,
            unresolved=classified["unresolved"],
            db_path=self.db,
        )
        after_db = hashlib.sha256(self.db.read_bytes()).hexdigest()

        self.assertEqual(first, second)
        self.assertEqual(support, support_again)
        self.assertEqual(before_db, after_db)
        self.assertEqual(
            {item["relationship_ref"] for item in first.selected_relationships},
            {
                "relationship:REL-284-document-repeal",
                "relationship:REL-284-selected",
            },
        )
        self.assertEqual(first.metrics["candidate_relationship_count"], 4)
        self.assertEqual(first.metrics["selected_relationship_count"], 2)
        self.assertEqual(first.metrics["excluded_relationship_count"], 2)
        self.assertEqual(first.metrics["selected_provision_count"], 1)
        self.assertEqual(first.metrics["aspects_with_selected_relationships"], 1)
        self.assertEqual(first.metrics["canonical_relationship_rows_loaded"], 4)
        self.assertEqual(first.metrics["aspect_relationship_evaluations"], 4)

        relationship_refs = {
            item["relationship_ref"] for item in support["normative_relationships"]
        }
        authority_refs = {
            item["authority_ref"] for item in support["authorities"]
        }
        evidence_refs = {
            item["evidence_ref"] for item in support["evidence_spans"]
        }
        self.assertEqual(
            relationship_refs,
            {
                "relationship:REL-284-document-repeal",
                "relationship:REL-284-selected",
            },
        )
        self.assertIn(
            f"authority:{exact_endpoint['document_id']}",
            authority_refs,
        )
        self.assertIn(
            f"authority:{document_dependency['document_id']}",
            authority_refs,
        )
        self.assertIn(
            f"authority:{evidence_owner['document_id']}",
            authority_refs,
        )
        self.assertNotIn(
            f"authority:{unrelated_endpoint['document_id']}",
            authority_refs,
        )
        self.assertNotIn(
            f"authority:{cited_endpoint['document_id']}",
            authority_refs,
        )
        self.assertNotIn(
            f"authority:{second_degree['document_id']}",
            authority_refs,
        )
        self.assertIn(
            f"evidence:{evidence_owner['evidence_id']}",
            evidence_refs,
        )
        self.assertIn(
            f"authority:{evidence_owner['document_id']}",
            support["support_only_authority_refs"],
        )
        for relationship in support["normative_relationships"]:
            self.assertIn(relationship["source_authority_ref"], authority_refs)
            self.assertIn(relationship["target_authority_ref"], authority_refs)
            for evidence_ref in relationship["evidence_refs"]:
                self.assertIn(evidence_ref, evidence_refs)

    def test_mandatory_dependency_families_survive_without_text_similarity(self):
        primary = self.add_provision_document(
            token="284-families",
            document_id="DOC-284-families",
            document_type="LEY",
            number="10",
            year=2026,
            filename="ley_0010_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        relation_types = {
            "modifies": "amendment_dependency",
            "repeals": "repeal_dependency",
            "exception_to": "exception_dependency",
            "defines": "definition_dependency",
            "conflicts_with": "conflict_dependency",
        }
        for index, relation_type in enumerate(relation_types, start=1):
            target = self.add_provision_document(
                token=f"284-family-{index}",
                document_id=f"DOC-284-family-{index}",
                document_type="DECRETO",
                number=str(100 + index),
                year=2026,
                filename=f"decreto_{100 + index}_2026.htm",
                text=f"ZZZ contenido ajeno {index}.",
                designation="Artículo 1",
            )
            self.add_scoped_relationship(
                relationship_id=f"REL-284-family-{index}",
                source_type="document",
                source_id=primary["document_id"],
                relation_type=relation_type,
                target_type="document",
                target_id=target["document_id"],
                evidence_id=primary["evidence_id"],
            )

        classified = self.classify(primary["document_id"])
        authority_ref = f"authority:{primary['document_id']}"
        span = self.evidence_span(primary, aspect_authority_ref=authority_ref)
        result = select_research_relationships_v5(
            plan=self.selector_plan(max_relationships=10),
            evidence_selections=[
                self.evidence_selection(
                    aspect_ref="aspect:issue284",
                    authority_ref=authority_ref,
                    evidence_ref=span["evidence_ref"],
                )
            ],
            evidence_spans=[span],
            relationships=classified["relationships"],
            db_path=self.db,
        )

        self.assertEqual(len(result.selected_relationships), 5)
        selected_records = [item for item in result.records if item.selected]
        self.assertEqual(len(selected_records), 5)
        for record in selected_records:
            self.assertEqual(record.scope_state, "document_scope_conservative")
            self.assertIn("document_scope_uncertain", record.reasons)
            relationship_type = next(
                item["relationship_type"]
                for item in result.selected_relationships
                if item["relationship_ref"] == record.relationship_ref
            )
            self.assertIn(relation_types[relationship_type], record.reasons)
        self.assertEqual(result.omitted_work_inputs, ())

    def test_support_budget_overflow_is_explicit_and_prevents_complete_coverage(self):
        case_input, intake, plan = issue283._plan(
            (("graph_budget", [], False),),
        )
        task = issue283._task_by_dimension(plan)["graph_budget"]
        aspect_ref = task["aspect_ref"]

        primary = self.add_provision_document(
            token="284-budget",
            document_id="DOC-284-budget",
            document_type="LEY",
            number="20",
            year=2026,
            filename="ley_0020_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        for index in range(5):
            target = self.add_provision_document(
                token=f"284-budget-target-{index}",
                document_id=f"DOC-284-budget-target-{index}",
                document_type="DECRETO",
                number=str(200 + index),
                year=2026,
                filename=f"decreto_{200 + index}_2026.htm",
                text=f"Dependencia {index}.",
                designation="Artículo 1",
            )
            self.add_scoped_relationship(
                relationship_id=f"REL-284-budget-{index}",
                source_type="provision",
                source_id=primary["provision_id"],
                relation_type="implements",
                target_type="document",
                target_id=target["document_id"],
                evidence_id=primary["evidence_id"],
            )

        classified = self.classify(primary["document_id"])
        authority_ref = f"authority:{primary['document_id']}"
        evidence = {
            "evidence_ref": f"evidence:{primary['evidence_id']}",
            "authority_ref": authority_ref,
            "provision_ref": f"provision:{primary['provision_id']}",
        }
        selection_input = issue283._selection(
            task,
            authority_ref,
            [evidence["evidence_ref"]],
        )
        selector = select_research_relationships_v5(
            plan=plan,
            evidence_selections=[selection_input],
            evidence_spans=[evidence],
            relationships=classified["relationships"],
            db_path=self.db,
        )

        self.assertEqual(
            plan["budgets"]["support"]["max_relationships_per_aspect"],
            4,
        )
        self.assertEqual(selector.metrics["relevant_relationship_count"], 5)
        self.assertEqual(selector.metrics["selected_relationship_count"], 4)
        self.assertEqual(
            selector.metrics["budget_omitted_aspect_relationship_pairs"],
            1,
        )
        self.assertEqual(len(selector.omitted_work_inputs), 1)
        self.assertEqual(
            selector.omitted_work_inputs[0]["reason"],
            "budget_exhausted",
        )
        self.assertTrue(selector.omitted_work_inputs[0]["required"])

        trace = issue283._trace(
            task,
            "issue284-budget",
            retrieved=[authority_ref],
            selected_authorities=[authority_ref],
            selected_evidence=[evidence["evidence_ref"]],
        )
        context = research_context_for_coverage_v5(
            plan,
            corpus_snapshot_sha256=None,
            schema_migration_fingerprint=None,
            retrieval_config_sha256=None,
            retrieval_version="fixture-retrieval-1",
            graph_selection_version=GRAPH_SELECTION_VERSION,
        )
        coverage_result = build_research_result_v5(
            plan,
            case_input=case_input,
            trace=[trace],
            selection_inputs=[selection_input],
            authorities=[{"authority_ref": authority_ref}],
            evidence_spans=[evidence],
            unresolved=[],
            facts=intake["facts"],
            research_context=context,
            omitted_work_inputs=selector.omitted_work_inputs,
            generated_at=NOW,
        )
        coverage = coverage_result["aspect_coverage"][0]
        self.assertEqual(coverage_result["status"], "partial")
        self.assertEqual(coverage["support_closure"], "incomplete")
        self.assertTrue(coverage["omission_refs"])

    def test_canonical_relationship_drift_fails_closed(self):
        primary = self.add_provision_document(
            token="284-drift",
            document_id="DOC-284-drift",
            document_type="LEY",
            number="30",
            year=2026,
            filename="ley_0030_2026.htm",
            text=ARTICLE_592,
            designation="Artículo 592",
        )
        target = self.add_provision_document(
            token="284-drift-target",
            document_id="DOC-284-drift-target",
            document_type="DECRETO",
            number="31",
            year=2026,
            filename="decreto_0031_2026.htm",
            text="Objetivo.",
            designation="Artículo 1",
        )
        self.add_scoped_relationship(
            relationship_id="REL-284-drift",
            source_type="provision",
            source_id=primary["provision_id"],
            relation_type="modifies",
            target_type="document",
            target_id=target["document_id"],
            evidence_id=primary["evidence_id"],
        )
        classified = self.classify(primary["document_id"])
        bad = deepcopy(classified["relationships"])
        bad[0]["target_authority_ref"] = "authority:tampered"

        authority_ref = f"authority:{primary['document_id']}"
        span = self.evidence_span(primary, aspect_authority_ref=authority_ref)
        with self.assertRaises(RelationshipSelectionError):
            select_research_relationships_v5(
                plan=self.selector_plan(),
                evidence_selections=[
                    self.evidence_selection(
                        aspect_ref="aspect:issue284",
                        authority_ref=authority_ref,
                        evidence_ref=span["evidence_ref"],
                    )
                ],
                evidence_spans=[span],
                relationships=bad,
                db_path=self.db,
            )


if __name__ == "__main__":
    unittest.main()
