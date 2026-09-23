from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from detect_normative_references import extract_mentions
from migrate_issuer_identities import reprocess
from register_document_identity import register_document_identity
from resolve_references import resolve_one
from source_identity import assess_generic_normative_identity, classify_source_url


NOW = "2026-09-22T00:00:00+00:00"


class Def0002IssuerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite"
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(migration.read_text(encoding="utf-8"))
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fixture(self, filename: str, heading: str) -> tuple[str, str]:
        source_url = (
            "https://normograma.dian.gov.co/dian/compilacion/docs/"
            + filename
        )
        token = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        source_id = "SRC-" + token
        manifestation_id = "MAN-" + token
        extraction_id = "EXT-" + token
        con = sqlite3.connect(self.db)
        try:
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
                ) VALUES (?, NULL, ?, 'text/html', ?, 1, ?, ?, 'test')
                """,
                (
                    manifestation_id,
                    source_id,
                    hashlib.sha256(("raw:" + filename).encode()).hexdigest(),
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
                ) VALUES (?, ?, 'test', '1', ?, 1, ?, 1, ?, ?, 'success')
                """,
                (
                    extraction_id,
                    manifestation_id,
                    hashlib.sha256(("normalized:" + filename).encode()).hexdigest(),
                    len(heading),
                    f"normalized/{token}.txt",
                    NOW,
                ),
            )
            con.execute(
                """
                INSERT INTO extracted_segments(
                    extracted_segment_id, extraction_id, sequence_no,
                    segment_type, section_path, char_start, char_end,
                    text, text_sha256
                ) VALUES (?, ?, 1, 'document_heading', NULL, 0, ?, ?, ?)
                """,
                (
                    f"SEG-{token}",
                    extraction_id,
                    len(heading),
                    heading,
                    hashlib.sha256(heading.encode()).hexdigest(),
                ),
            )
            con.commit()
        finally:
            con.close()
        return extraction_id, manifestation_id

    def register_pair(
        self,
        number: int,
        year: int,
    ) -> tuple[dict[str, object], dict[str, object]]:
        dian_ext, _ = self.fixture(
            f"resolucion_dian_{number:04d}_{year}.htm",
            f"RESOLUCIÓN {number} DE {year}",
        )
        banrep_ext, _ = self.fixture(
            f"resolucion_banrepublica_jd-{number:04d}_{year}.htm",
            f"RESOLUCIÓN {number} DE {year}",
        )
        return (
            register_document_identity(extraction_id=dian_ext, db_path=self.db),
            register_document_identity(extraction_id=banrep_ext, db_path=self.db),
        )

    def assert_distinct_resolution_pair(self, number: int, year: int) -> None:
        dian, banrep = self.register_pair(number, year)
        self.assertNotEqual(dian["document_id"], banrep["document_id"])
        self.assertEqual(
            dian["canonical_key"],
            f"CO:DIAN:RESOLUCION:{number}:{year}",
        )
        self.assertEqual(
            banrep["canonical_key"],
            f"CO:BANREP_JD:RESOLUCION:{number}:{year}",
        )
        con = sqlite3.connect(self.db)
        try:
            aliases = con.execute(
                """
                SELECT document_id, issuer, is_primary
                FROM document_identifiers
                WHERE identifier_type='canonical_key'
                  AND identifier_value=?
                ORDER BY issuer
                """,
                (f"CO:RESOLUCION:{number}:{year}",),
            ).fetchall()
            self.assertEqual(
                aliases,
                [
                    (banrep["document_id"], "BANREP_JD", 0),
                    (dian["document_id"], "DIAN", 0),
                ],
            )
        finally:
            con.close()

    def test_resolution_1_2018_is_split_by_issuer(self):
        self.assert_distinct_resolution_pair(1, 2018)

    def test_resolution_7_2021_is_split_by_issuer(self):
        self.assert_distinct_resolution_pair(7, 2021)

    def test_same_number_circulars_are_split_by_issuer(self):
        dian_ext, _ = self.fixture(
            "circular_dian_0001_2019.htm", "CIRCULAR 1 DE 2019"
        )
        presidencia_ext, _ = self.fixture(
            "circular_presidencia_0001_2019.htm", "CIRCULAR 1 DE 2019"
        )
        dian = register_document_identity(extraction_id=dian_ext, db_path=self.db)
        presidencia = register_document_identity(
            extraction_id=presidencia_ext, db_path=self.db
        )
        self.assertNotEqual(dian["document_id"], presidencia["document_id"])
        self.assertEqual(dian["canonical_key"], "CO:DIAN:CIRCULAR:1:2019")
        self.assertEqual(
            presidencia["canonical_key"],
            "CO:PRESIDENCIA:CIRCULAR:1:2019",
        )

    def test_normal_dian_resolution_is_issuer_aware_and_deterministic(self):
        ext, _ = self.fixture(
            "resolucion_dian_0227_2025.htm", "RESOLUCIÓN 227 DE 2025"
        )
        first = register_document_identity(extraction_id=ext, db_path=self.db)
        second = register_document_identity(extraction_id=ext, db_path=self.db)
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertEqual(first["canonical_key"], "CO:DIAN:RESOLUCION:227:2025")
        self.assertTrue(second["reused"])

    def test_explicit_issuer_reference_resolves_and_missing_issuer_is_ambiguous(self):
        dian, banrep = self.register_pair(1, 2018)
        con = sqlite3.connect(self.db)
        try:
            explicit = resolve_one(
                con,
                mention_id="REF-explicit",
                mention_type="document",
                target_document_key="CO:RESOLUCION:1:2018",
                target_issuer="DIAN",
                article_designation=None,
            )
            self.assertEqual(explicit["status"], "resolved")
            self.assertEqual(explicit["target_document_id"], dian["document_id"])

            other = resolve_one(
                con,
                mention_id="REF-banrep",
                mention_type="document",
                target_document_key="CO:RESOLUCION:1:2018",
                target_issuer="BANREP_JD",
                article_designation=None,
            )
            self.assertEqual(other["target_document_id"], banrep["document_id"])

            ambiguous = resolve_one(
                con,
                mention_id="REF-ambiguous",
                mention_type="document",
                target_document_key="CO:RESOLUCION:1:2018",
                target_issuer=None,
                article_designation=None,
            )
            self.assertEqual(ambiguous["status"], "ambiguous")
            self.assertEqual(ambiguous["reason_code"], "AMBIGUOUS_DOCUMENT_ID")
            self.assertIsNone(ambiguous["target_document_id"])
        finally:
            con.close()

    def test_detector_preserves_explicit_issuer(self):
        mentions = extract_mentions("Ver Resolución DIAN 1 de 2018.")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0].target.issuer_key, "DIAN")
        self.assertEqual(
            mentions[0].normalized_reference,
            "CO:DIAN:RESOLUCION:1:2018",
        )
        self.assertEqual(mentions[0].target.key, "CO:RESOLUCION:1:2018")

    def test_unknown_resolution_issuer_is_not_guessed(self):
        assessment = assess_generic_normative_identity(
            "https://normograma.dian.gov.co/dian/compilacion/docs/"
            "resolucion_entidadinventada_0001_2018.htm",
            "RESOLUCIÓN 1 DE 2018",
        )
        self.assertFalse(assessment.accepted)
        self.assertEqual(assessment.reason_code, "ISSUER_IDENTITY_UNRESOLVED")

    def test_intrinsic_ley_and_decreto_keys_remain_stable(self):
        ley = classify_source_url("https://x/docs/ley_1450_2011.htm")
        decreto = classify_source_url("https://x/docs/decreto_1165_2019.htm")
        self.assertEqual(ley.issuer_key, "CONGRESO")
        self.assertEqual(ley.canonical_key, "CO:LEY:1450:2011")
        self.assertEqual(decreto.issuer_key, "PRESIDENCIA")
        self.assertEqual(decreto.canonical_key, "CO:DECRETO:1165:2019")

    def seed_legacy_collision(self) -> tuple[str, list[str]]:
        dian_ext, dian_man = self.fixture(
            "resolucion_dian_0001_2018.htm", "RESOLUCIÓN 1 DE 2018"
        )
        banrep_ext, banrep_man = self.fixture(
            "resolucion_banrepublica_jd-0001_2018.htm",
            "RESOLUCIÓN 1 DE 2018",
        )
        legacy_document_id = "DOC-legacy-resolution-1-2018"
        legacy_key = "CO:RESOLUCION:1:2018"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'UNKNOWN', 'RESOLUCION', ?, NULL, NULL, ?, ?)
                """,
                (legacy_document_id, "RESOLUCIÓN 1 DE 2018", NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES ('ID-legacy', ?, 'canonical_key', ?, NULL, 1)
                """,
                (legacy_document_id, legacy_key),
            )
            con.executemany(
                "UPDATE manifestations SET document_id=? WHERE manifestation_id=?",
                [
                    (legacy_document_id, dian_man),
                    (legacy_document_id, banrep_man),
                ],
            )
            con.execute(
                """
                INSERT INTO provisions(
                    provision_id, document_id, provision_type, designation,
                    normalized_designation, title, created_at, updated_at
                ) VALUES ('PROV-legacy-1', ?, 'article', '1', '1', NULL, ?, ?)
                """,
                (legacy_document_id, NOW, NOW),
            )
            for index, extraction_id in enumerate((dian_ext, banrep_ext), 1):
                segment_id = con.execute(
                    "SELECT extracted_segment_id FROM extracted_segments WHERE extraction_id=?",
                    (extraction_id,),
                ).fetchone()[0]
                con.execute(
                    """
                    INSERT INTO provision_observations(
                        provision_observation_id, provision_id, extraction_id,
                        extracted_segment_id, observed_text, normative_text,
                        editorial_note, observed_text_sha256,
                        normative_text_sha256, observed_at, parser_name,
                        parser_version
                    ) VALUES (?, 'PROV-legacy-1', ?, ?, 'ARTÍCULO 1', 'Texto',
                              NULL, ?, ?, ?, 'test', '1')
                    """,
                    (
                        f"POBS-{index}",
                        extraction_id,
                        segment_id,
                        hashlib.sha256(f"obs{index}".encode()).hexdigest(),
                        hashlib.sha256(b"Texto").hexdigest(),
                        NOW,
                    ),
                )
            con.commit()
        finally:
            con.close()
        return legacy_document_id, [dian_man, banrep_man]

    def test_collision_migration_dry_run_apply_provenance_and_idempotency(self):
        legacy_document_id, manifestations = self.seed_legacy_collision()
        con = sqlite3.connect(self.db)
        try:
            before_hashes = con.execute(
                "SELECT manifestation_id, sha256 FROM manifestations ORDER BY manifestation_id"
            ).fetchall()
        finally:
            con.close()

        preview = reprocess(db_path=self.db, apply=False)
        self.assertEqual(preview["collision_group_count"], 1)
        self.assertEqual(preview["affected_manifestations"], 2)
        self.assertEqual(preview["new_documents"], 2)
        self.assertFalse(preview["persistent_mutation"])
        self.assertEqual(preview["conflicts"], [])

        con = sqlite3.connect(self.db)
        try:
            current = con.execute(
                "SELECT DISTINCT document_id FROM manifestations WHERE manifestation_id IN (?, ?)",
                manifestations,
            ).fetchall()
            self.assertEqual(current, [(legacy_document_id,)])
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM document_identity_migrations").fetchone()[0],
                0,
            )
        finally:
            con.close()

        applied = reprocess(db_path=self.db, apply=True)
        self.assertTrue(applied["persistent_mutation"])
        self.assertTrue(applied["hashes_unchanged"])
        self.assertEqual(applied["manifestations_rebound"], 2)
        self.assertEqual(applied["legacy_documents_deleted"], 1)
        self.assertEqual(applied["migration_provenance_inserted"], 2)
        self.assertEqual(applied["provision_observations_rebound"], 2)

        con = sqlite3.connect(self.db)
        try:
            after_ids = con.execute(
                "SELECT DISTINCT document_id FROM manifestations WHERE manifestation_id IN (?, ?)",
                manifestations,
            ).fetchall()
            self.assertEqual(len(after_ids), 2)
            self.assertIsNone(
                con.execute(
                    "SELECT document_id FROM documents WHERE document_id=?",
                    (legacy_document_id,),
                ).fetchone()
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM document_identity_migrations").fetchone()[0],
                2,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(DISTINCT provision_id) FROM provision_observations"
                ).fetchone()[0],
                2,
            )
            after_hashes = con.execute(
                "SELECT manifestation_id, sha256 FROM manifestations ORDER BY manifestation_id"
            ).fetchall()
            self.assertEqual(before_hashes, after_hashes)
        finally:
            con.close()

        second = reprocess(db_path=self.db, apply=False)
        self.assertEqual(second["collision_group_count"], 0)
        self.assertEqual(second["affected_manifestations"], 0)

    def test_noncollided_legacy_document_is_backfilled_in_place(self):
        extraction_id, manifestation_id = self.fixture(
            "resolucion_dian_0227_2025.htm", "RESOLUCIÓN 227 DE 2025"
        )
        legacy_document_id = "DOC-stable-existing-resolution"
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                INSERT INTO documents(
                    document_id, jurisdiction, entity, document_type, title,
                    issued_date, publication_date, created_at, updated_at
                ) VALUES (?, 'CO', 'UNKNOWN', 'RESOLUCION', ?, NULL, NULL, ?, ?)
                """,
                (legacy_document_id, "RESOLUCIÓN 227 DE 2025", NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO document_identifiers(
                    identifier_id, document_id, identifier_type,
                    identifier_value, issuer, is_primary
                ) VALUES ('ID-stable-legacy', ?, 'canonical_key',
                          'CO:RESOLUCION:227:2025', NULL, 1)
                """,
                (legacy_document_id,),
            )
            con.execute(
                "UPDATE manifestations SET document_id=? WHERE manifestation_id=?",
                (legacy_document_id, manifestation_id),
            )
            con.commit()
        finally:
            con.close()

        preview = reprocess(db_path=self.db, apply=False)
        self.assertEqual(preview["collision_group_count"], 0)
        self.assertEqual(preview["issuer_backfill_documents"], 1)
        self.assertFalse(preview["persistent_mutation"])

        applied = reprocess(db_path=self.db, apply=True)
        self.assertEqual(applied["documents_backfilled"], 1)
        self.assertEqual(applied["backfill_provenance_inserted"], 1)

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT document_id FROM manifestations WHERE manifestation_id=?",
                    (manifestation_id,),
                ).fetchone()[0],
                legacy_document_id,
            )
            identifiers = con.execute(
                """
                SELECT identifier_value, issuer, is_primary
                FROM document_identifiers
                WHERE document_id=? AND identifier_type='canonical_key'
                ORDER BY is_primary DESC, identifier_value
                """,
                (legacy_document_id,),
            ).fetchall()
            self.assertEqual(
                identifiers,
                [
                    ("CO:DIAN:RESOLUCION:227:2025", "DIAN", 1),
                    ("CO:RESOLUCION:227:2025", "DIAN", 0),
                ],
            )
            explicit = resolve_one(
                con,
                mention_id="REF-existing-explicit",
                mention_type="document",
                target_document_key="CO:RESOLUCION:227:2025",
                target_issuer="DIAN",
                article_designation=None,
            )
            self.assertEqual(explicit["status"], "resolved")
            self.assertEqual(explicit["target_document_id"], legacy_document_id)
        finally:
            con.close()

        second = reprocess(db_path=self.db, apply=False)
        self.assertEqual(second["issuer_backfill_documents"], 0)

    def test_schema_upgrade_from_012_to_013(self):
        upgrade_db = Path(self.tmp.name) / "upgrade.sqlite"
        con = sqlite3.connect(upgrade_db)
        try:
            migrations = sorted((ROOT / "schema").glob("*.sql"))
            for migration in migrations:
                if migration.name >= "013_":
                    break
                con.executescript(migration.read_text(encoding="utf-8"))
            con.executescript(
                (ROOT / "schema" / "013_issuer_aware_identity.sql").read_text(
                    encoding="utf-8"
                )
            )
            reference_columns = {
                row[1] for row in con.execute("PRAGMA table_info(reference_mentions)")
            }
            signal_columns = {
                row[1]
                for row in con.execute("PRAGMA table_info(document_identity_signals)")
            }
            self.assertIn("target_issuer", reference_columns)
            self.assertIn("issuer_key", signal_columns)
            self.assertIsNotNone(
                con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='document_identity_migrations'"
                ).fetchone()
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
