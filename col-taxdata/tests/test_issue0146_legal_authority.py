from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation_v4 import validate_contract_object
from legal_authority_classification import classify_canonical_authority


NOW = "2026-09-27T00:00:00+00:00"
BASE = "https://normograma.dian.gov.co/dian/compilacion/docs/"


class Issue0146LegalAuthorityClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "authority.sqlite"
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
        document_type: str,
        issuer: str,
        filename: str,
        number: str = "1",
        year: int = 2020,
        canonical_key: str | None = None,
        title: str | None = None,
        source_authority: str = "DIAN",
        source_kind: str = "normograma_html",
    ) -> dict[str, str]:
        source_url = BASE + filename
        token = document_id.replace("DOC-", "").lower()
        source_id = f"SRC-{token}"
        manifestation_id = f"MAN-{token}"
        extraction_id = f"EXT-{token}"
        raw_sha = hashlib.sha256(
            f"raw:{source_url}".encode()
        ).hexdigest()
        normalized_sha = hashlib.sha256(
            f"normalized:{source_url}".encode()
        ).hexdigest()
        if canonical_key is None:
            if document_type in {"LEY", "DECRETO"}:
                canonical_key = f"CO:{document_type}:{number}:{year}"
            else:
                canonical_key = (
                    f"CO:{issuer}:{document_type}:{number}:{year}"
                )

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    document_id,
                    issuer,
                    document_type,
                    title or f"{document_type} {number} DE {year}",
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
                    canonical_key,
                    issuer,
                ),
            )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    source_id,
                    source_url,
                    source_authority,
                    source_kind,
                    NOW,
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (?, ?, ?, 'text/html', ?, 10, ?, ?, 'test')
                """,
                (
                    manifestation_id,
                    document_id,
                    source_id,
                    raw_sha,
                    NOW,
                    f"raw/{token}.html",
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size, char_count,
                    segment_count, local_path, created_at, status
                ) VALUES (?, ?, 'test', '1', ?, 10, 10, 0, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    normalized_sha,
                    f"normalized/{token}.txt",
                    NOW,
                ),
            )
            con.commit()
        finally:
            con.close()

        return {
            "source_id": source_id,
            "source_url": source_url,
            "manifestation_id": manifestation_id,
            "extraction_id": extraction_id,
            "raw_sha": raw_sha,
            "identifier_id": f"ID-{token}",
        }

    def add_evidence(
        self,
        document_id: str,
        *,
        suffix: str,
        quote: str,
    ) -> str:
        con = sqlite3.connect(self.db)
        try:
            row = con.execute(
                """
                SELECT m.manifestation_id, m.sha256, m.retrieved_at, s.source_url
                FROM manifestations m
                JOIN sources s ON s.source_id = m.source_id
                WHERE m.document_id = ?
                ORDER BY m.manifestation_id
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            evidence_id = f"EVD-{document_id}-{suffix}"
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, segment_id,
                    page_number, char_start, char_end, exact_quote,
                    source_url, source_sha256, retrieved_at,
                    extraction_method, extractor_version, confidence,
                    review_status, extracted_segment_id
                )
                VALUES (
                    ?, NULL, ?, NULL, NULL, 0, ?, ?, ?, ?, ?,
                    'issue146-test', '1', 1.0, 'machine_validated', NULL
                )
                """,
                (
                    evidence_id,
                    row[0],
                    len(quote),
                    quote,
                    row[3],
                    row[1],
                    row[2],
                ),
            )
            con.commit()
            return evidence_id
        finally:
            con.close()

    def bind_identifier_evidence(
        self,
        identifier_id: str,
        evidence_id: str,
    ) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO document_identifier_evidence(
                    identifier_id, evidence_id, evidence_role, created_at
                ) VALUES (?, ?, 'document_identity', ?)
                """,
                (identifier_id, evidence_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def add_temporal_event(
        self,
        document_id: str,
        *,
        suffix: str,
        event_type: str,
        event_date: str,
        evidence_id: str,
        effective_from: str | None = None,
        effective_to: str | None = None,
    ) -> None:
        con = sqlite3.connect(self.db)
        try:
            event_id = f"TEV-{document_id}-{suffix}"
            con.execute(
                """
                INSERT INTO temporal_events(
                    temporal_event_id, entity_type, entity_id, event_type,
                    event_date, effective_from, effective_to, caused_by_type,
                    caused_by_id, scope, status, evidence_id, confidence,
                    requires_human_review
                )
                VALUES (
                    ?, 'document', ?, ?, ?, ?, ?, NULL, NULL, 'document',
                    'validated', ?, 1.0, 0
                )
                """,
                (
                    event_id,
                    document_id,
                    event_type,
                    event_date,
                    effective_from,
                    effective_to,
                    evidence_id,
                ),
            )
            con.execute(
                """
                INSERT INTO temporal_event_evidence(
                    temporal_event_id, evidence_id, evidence_role, created_at
                ) VALUES (?, ?, 'issue146_test', ?)
                """,
                (event_id, evidence_id, NOW),
            )
            con.commit()
        finally:
            con.close()

    def add_relationship(
        self,
        *,
        relationship_id: str,
        source_document_id: str,
        target_document_id: str,
        relationship_type: str,
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
                    ?, 'document', ?, ?, 'document', ?, 'issue146_test',
                    NULL, NULL, NULL, 'validated', ?, 1.0, 0
                )
                """,
                (
                    relationship_id,
                    source_document_id,
                    relationship_type,
                    target_document_id,
                    evidence_id,
                ),
            )
            con.commit()
        finally:
            con.close()

    def test_statute_and_regulation_families_expose_distinct_metadata(self):
        fixtures = [
            (
                "DOC-law",
                "LEY",
                "CONGRESO",
                "ley_0001_2020.htm",
                "normative",
            ),
            (
                "DOC-decree",
                "DECRETO",
                "PRESIDENCIA",
                "decreto_0001_2020.htm",
                "normative",
            ),
            (
                "DOC-resolution",
                "RESOLUCION",
                "DIAN",
                "resolucion_dian_0001_2020.htm",
                "normative",
            ),
            (
                "DOC-circular",
                "CIRCULAR",
                "DIAN",
                "circular_dian_0001_2020.htm",
                "guidance",
            ),
        ]
        for (
            document_id,
            document_type,
            issuer,
            filename,
            legal_function,
        ) in fixtures:
            with self.subTest(document_id=document_id):
                self.add_document(
                    document_id=document_id,
                    document_type=document_type,
                    issuer=issuer,
                    filename=filename,
                )
                result = classify_canonical_authority(
                    document_id=document_id,
                    db_path=self.db,
                )
                authority = result["authority"]
                self.assertEqual(
                    authority["document_type"],
                    document_type,
                )
                self.assertEqual(authority["issuer"], issuer)
                self.assertEqual(
                    authority["jurisdiction_scope"],
                    "CO",
                )
                self.assertEqual(
                    authority["source_family"],
                    "NORMATIVE_ACT",
                )
                self.assertEqual(
                    authority["legal_function"],
                    legal_function,
                )
                self.assertEqual(
                    authority["classification_state"],
                    "resolved",
                )
                validate_contract_object(authority)
                for source in result["sources"]:
                    validate_contract_object(source)

    def test_doctrine_guidance_and_jurisprudence_do_not_masquerade_as_statutes(self):
        self.add_document(
            document_id="DOC-concept",
            document_type="CONCEPTO",
            issuer="DIAN",
            filename="concepto_tributario_dian_0000001_2020.htm",
        )
        self.add_document(
            document_id="DOC-sentence",
            document_type="SENTENCIA_C",
            issuer="CORTE_CONSTITUCIONAL",
            filename="c-0621_2013.htm",
            number="621",
            year=2013,
        )
        self.add_document(
            document_id="DOC-guidance",
            document_type="TRAMITE_OFICIAL",
            issuer="DIAN",
            filename="cancelacion-rut.html",
            canonical_key="CO:DIAN:TRAMITE:RUT_CANCELACION",
        )

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO dian_doctrine_metadata(
                    document_id, external_number, normalized_external_number,
                    internal_number, document_year, doctrine_date,
                    web_publication_date, created_at, updated_at
                )
                VALUES (
                    'DOC-concept', '1', '1', NULL, 2020, NULL, NULL, ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO official_guidance_metadata(
                    document_id, guidance_kind, canonical_slug,
                    created_at, updated_at
                )
                VALUES (
                    'DOC-guidance', 'rut_cancellation', 'rut_cancelacion', ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.commit()
        finally:
            con.close()

        concept_result = classify_canonical_authority(
            document_id="DOC-concept",
            db_path=self.db,
        )
        sentence_result = classify_canonical_authority(
            document_id="DOC-sentence",
            db_path=self.db,
        )
        guidance_result = classify_canonical_authority(
            document_id="DOC-guidance",
            db_path=self.db,
        )

        self.assertEqual(
            concept_result["authority"]["legal_function"],
            "administrative_interpretation",
        )
        self.assertEqual(
            sentence_result["authority"]["legal_function"],
            "jurisprudential",
        )
        self.assertEqual(
            guidance_result["authority"]["legal_function"],
            "guidance",
        )
        for result in (
            concept_result,
            sentence_result,
            guidance_result,
        ):
            self.assertNotEqual(
                result["authority"]["legal_function"],
                "normative",
            )

    def test_same_number_year_different_issuer_remains_distinct(self):
        self.add_document(
            document_id="DOC-dian-resolution",
            document_type="RESOLUCION",
            issuer="DIAN",
            filename="resolucion_dian_0001_2018.htm",
            year=2018,
        )
        self.add_document(
            document_id="DOC-banrep-resolution",
            document_type="RESOLUCION",
            issuer="BANREP_JD",
            filename="resolucion_banrepublica_jd-0001_2018.htm",
            year=2018,
        )

        dian = classify_canonical_authority(
            document_id="DOC-dian-resolution",
            db_path=self.db,
        )["authority"]
        banrep = classify_canonical_authority(
            document_id="DOC-banrep-resolution",
            db_path=self.db,
        )["authority"]

        self.assertNotEqual(
            dian["document_ref"],
            banrep["document_ref"],
        )
        self.assertNotEqual(
            dian["authority_ref"],
            banrep["authority_ref"],
        )
        self.assertEqual(dian["issuer"], "DIAN")
        self.assertEqual(banrep["issuer"], "BANREP_JD")

    def test_publication_temporal_as_of_and_relationships_are_supported_not_inferred(self):
        source = self.add_document(
            document_id="DOC-source",
            document_type="DECRETO",
            issuer="PRESIDENCIA",
            filename="decreto_0002_2020.htm",
            number="2",
        )
        self.add_document(
            document_id="DOC-target",
            document_type="LEY",
            issuer="CONGRESO",
            filename="ley_0003_2019.htm",
            number="3",
            year=2019,
        )

        identity_evidence = self.add_evidence(
            "DOC-source",
            suffix="identity",
            quote="DECRETO 2 DE 2020",
        )
        self.bind_identifier_evidence(
            source["identifier_id"],
            identity_evidence,
        )
        publication_evidence = self.add_evidence(
            "DOC-source",
            suffix="publication",
            quote="Publicado el 2 de enero de 2020.",
        )
        effect_evidence = self.add_evidence(
            "DOC-source",
            suffix="effect",
            quote=(
                "Rige del 2 de enero de 2020 al 31 de diciembre de 2025."
            ),
        )
        self.add_temporal_event(
            "DOC-source",
            suffix="published",
            event_type="published",
            event_date="2020-01-02",
            evidence_id=publication_evidence,
        )
        self.add_temporal_event(
            "DOC-source",
            suffix="effective",
            event_type="enters_into_force",
            event_date="2020-01-02",
            effective_from="2020-01-02",
            effective_to="2025-12-31",
            evidence_id=effect_evidence,
        )

        relationship_types = ["modifies", "repeals", "regulates"]
        for index, relationship_type in enumerate(
            relationship_types,
            1,
        ):
            rel_evidence = self.add_evidence(
                "DOC-source",
                suffix=f"rel-{index}",
                quote=f"Relación explícita: {relationship_type}.",
            )
            self.add_relationship(
                relationship_id=f"REL-{relationship_type}",
                source_document_id="DOC-source",
                target_document_id="DOC-target",
                relationship_type=relationship_type,
                evidence_id=rel_evidence,
            )

        during = classify_canonical_authority(
            document_id="DOC-source",
            db_path=self.db,
            as_of_date="2024-01-01",
        )
        after = classify_canonical_authority(
            document_id="DOC-source",
            db_path=self.db,
            as_of_date="2026-01-01",
        )

        self.assertEqual(
            during["authority"]["publication_metadata"]["state"],
            "resolved",
        )
        self.assertEqual(
            during["authority"]["publication_metadata"][
                "publication_dates"
            ],
            ["2020-01-02"],
        )
        self.assertEqual(
            during["authority"]["temporal_state"]["resolution_state"],
            "resolved",
        )
        self.assertIs(
            during["authority"]["temporal_state"]["effective"],
            True,
        )
        self.assertIs(
            after["authority"]["temporal_state"]["effective"],
            False,
        )

        self.assertEqual(
            {
                item["relationship_type"]
                for item in during["relationships"]
            },
            set(relationship_types),
        )
        self.assertEqual(
            set(during["authority"]["relationship_refs"]),
            {
                "relationship:REL-modifies",
                "relationship:REL-repeals",
                "relationship:REL-regulates",
            },
        )
        for relationship in during["relationships"]:
            validate_contract_object(relationship)

        # A commencement event without a supported end does not prove continued
        # effect merely because no repeal row exists.
        self.add_document(
            document_id="DOC-open-ended",
            document_type="DECRETO",
            issuer="PRESIDENCIA",
            filename="decreto_0004_2020.htm",
            number="4",
        )
        open_effect = self.add_evidence(
            "DOC-open-ended",
            suffix="effect",
            quote="Rige a partir del 2 de enero de 2020.",
        )
        self.add_temporal_event(
            "DOC-open-ended",
            suffix="effective",
            event_type="enters_into_force",
            event_date="2020-01-02",
            effective_from="2020-01-02",
            evidence_id=open_effect,
        )
        unresolved = classify_canonical_authority(
            document_id="DOC-open-ended",
            db_path=self.db,
            as_of_date="2024-01-01",
        )
        self.assertEqual(
            unresolved["authority"]["temporal_state"][
                "resolution_state"
            ],
            "unresolved",
        )
        self.assertIsNone(
            unresolved["authority"]["temporal_state"]["effective"],
        )
        self.assertTrue(
            any(
                item["category"] == "temporal_uncertainty"
                for item in unresolved["unresolved"]
            )
        )

    def test_ambiguous_and_unknown_classification_remain_explicit(self):
        fixture = self.add_document(
            document_id="DOC-ambiguous",
            document_type="RESOLUCION",
            issuer="DIAN",
            filename="resolucion_dian_0005_2020.htm",
            number="5",
        )
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                UPDATE document_identifiers
                SET issuer = 'BANREP_JD'
                WHERE identifier_id = ?
                """,
                (fixture["identifier_id"],),
            )
            con.commit()
        finally:
            con.close()

        ambiguous = classify_canonical_authority(
            document_id="DOC-ambiguous",
            db_path=self.db,
        )
        self.assertEqual(
            ambiguous["authority"]["classification_state"],
            "ambiguous",
        )
        self.assertNotIn("issuer", ambiguous["authority"])
        self.assertTrue(
            any(
                item["category"] == "conflicting_authority"
                for item in ambiguous["unresolved"]
            )
        )

        self.add_document(
            document_id="DOC-unknown",
            document_type="ACTA",
            issuer="DIAN",
            filename="documento_sin_familia_2020.htm",
            canonical_key="CO:DIAN:ACTA:1:2020",
        )
        unknown = classify_canonical_authority(
            document_id="DOC-unknown",
            db_path=self.db,
        )
        self.assertEqual(
            unknown["authority"]["legal_function"],
            "unknown",
        )
        self.assertEqual(
            unknown["authority"]["classification_state"],
            "unknown",
        )
        for item in unknown["unresolved"]:
            validate_contract_object(item)

    def test_classification_is_deterministic_rank_free_and_read_only(self):
        fixture = self.add_document(
            document_id="DOC-stable",
            document_type="LEY",
            issuer="CONGRESO",
            filename="ley_0007_2021.htm",
            number="7",
            year=2021,
        )
        evidence_id = self.add_evidence(
            "DOC-stable",
            suffix="identity",
            quote="LEY 7 DE 2021",
        )
        self.bind_identifier_evidence(
            fixture["identifier_id"],
            evidence_id,
        )

        con = sqlite3.connect(self.db)
        try:
            before = {
                "document": con.execute(
                    """
                    SELECT *
                    FROM documents
                    WHERE document_id='DOC-stable'
                    """
                ).fetchone(),
                "identifier": con.execute(
                    """
                    SELECT identifier_value, issuer, is_primary
                    FROM document_identifiers
                    WHERE document_id='DOC-stable'
                    ORDER BY identifier_id
                    """
                ).fetchall(),
                "manifestation": con.execute(
                    """
                    SELECT manifestation_id, document_id, sha256
                    FROM manifestations
                    WHERE document_id='DOC-stable'
                    ORDER BY manifestation_id
                    """
                ).fetchall(),
                "evidence": con.execute(
                    """
                    SELECT evidence_id, source_sha256, exact_quote
                    FROM evidence
                    WHERE evidence_id=?
                    """,
                    (evidence_id,),
                ).fetchall(),
            }
        finally:
            con.close()

        first = classify_canonical_authority(
            document_id="DOC-stable",
            db_path=self.db,
            as_of_date="2026-09-27",
        )
        second = classify_canonical_authority(
            document_id="DOC-stable",
            db_path=self.db,
            as_of_date="2026-09-27",
        )
        self.assertEqual(first, second)

        forbidden = {
            "rank",
            "weight",
            "authority_weight",
            "precedence_score",
        }

        def assert_rank_free(value: object) -> None:
            if isinstance(value, dict):
                self.assertTrue(
                    forbidden.isdisjoint(value.keys())
                )
                for child in value.values():
                    assert_rank_free(child)
            elif isinstance(value, list):
                for child in value:
                    assert_rank_free(child)

        assert_rank_free(first)
        validate_contract_object(first["authority"])
        for source in first["sources"]:
            validate_contract_object(source)
        for unresolved in first["unresolved"]:
            validate_contract_object(unresolved)

        con = sqlite3.connect(self.db)
        try:
            after = {
                "document": con.execute(
                    """
                    SELECT *
                    FROM documents
                    WHERE document_id='DOC-stable'
                    """
                ).fetchone(),
                "identifier": con.execute(
                    """
                    SELECT identifier_value, issuer, is_primary
                    FROM document_identifiers
                    WHERE document_id='DOC-stable'
                    ORDER BY identifier_id
                    """
                ).fetchall(),
                "manifestation": con.execute(
                    """
                    SELECT manifestation_id, document_id, sha256
                    FROM manifestations
                    WHERE document_id='DOC-stable'
                    ORDER BY manifestation_id
                    """
                ).fetchall(),
                "evidence": con.execute(
                    """
                    SELECT evidence_id, source_sha256, exact_quote
                    FROM evidence
                    WHERE evidence_id=?
                    """,
                    (evidence_id,),
                ).fetchall(),
            }
        finally:
            con.close()

        self.assertEqual(before, after)
        self.assertEqual(
            before["manifestation"][0][2],
            fixture["raw_sha"],
        )


if __name__ == "__main__":
    unittest.main()
