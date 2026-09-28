from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import acquire_funcion_publica as adapter
from document_family_identity import (
    SegmentIdentityInput,
    assess_supported_family_identity,
)
from extract_normograma_html import extract_manifestation
from fetch_source import deterministic_manifestation_id
from register_simple_normative_act import register_simple_act
from resolve_references import close_obsolete_reference_reviews
from source_identity import (
    FUNCION_PUBLICA_NORMATIVE_ACT,
    NORMATIVE_ACT,
    assess_generic_normative_identity,
    classify_source_url,
)


FP_LAW_URL = (
    "https://www.funcionpublica.gov.co/eva/gestornormativo/"
    "norma.php?i=156590"
)
FP_DECREE_URL = (
    "https://www1.funcionpublica.gov.co/eva/gestornormativo/"
    "norma.php?i=82478"
)


class FuncionPublicaIdentityTests(unittest.TestCase):
    def test_source_family_accepts_only_official_norma_endpoint(self) -> None:
        self.assertEqual(
            classify_source_url(FP_LAW_URL).family,
            FUNCION_PUBLICA_NORMATIVE_ACT,
        )
        self.assertEqual(
            classify_source_url(FP_DECREE_URL).family,
            FUNCION_PUBLICA_NORMATIVE_ACT,
        )
        self.assertNotEqual(
            classify_source_url(
                "https://funcionpublica.gov.co.evil.example/"
                "eva/gestornormativo/norma.php?i=156590"
            ).family,
            FUNCION_PUBLICA_NORMATIVE_ACT,
        )

    def test_law_and_decree_front_matter_are_canonicalized(self) -> None:
        law = assess_supported_family_identity(
            FP_LAW_URL,
            [
                SegmentIdentityInput(
                    1,
                    "document_heading",
                    "LEY 2080 DE 2021",
                )
            ],
        )
        self.assertIsNotNone(law)
        assert law is not None
        self.assertTrue(law.accepted)
        self.assertEqual(law.identity.canonical_key, "CO:LEY:2080:2021")
        self.assertEqual(law.identity.issuer_key, "CONGRESO")

        decree = assess_supported_family_identity(
            FP_DECREE_URL,
            [
                SegmentIdentityInput(
                    1,
                    "document_heading",
                    "DECRETO 117 DE 2017",
                )
            ],
        )
        self.assertIsNotNone(decree)
        assert decree is not None
        self.assertTrue(decree.accepted)
        self.assertEqual(
            decree.identity.canonical_key,
            "CO:DECRETO:117:2017",
        )
        self.assertEqual(decree.identity.issuer_key, "PRESIDENCIA")

    def test_unsupported_or_ambiguous_front_matter_fails_closed(self) -> None:
        unsupported = assess_supported_family_identity(
            FP_LAW_URL,
            [
                SegmentIdentityInput(
                    1,
                    "document_heading",
                    "RESOLUCIÓN 7941 DE 2008",
                )
            ],
        )
        self.assertIsNotNone(unsupported)
        assert unsupported is not None
        self.assertFalse(unsupported.accepted)
        self.assertEqual(
            unsupported.assessment.reason_code,
            "SOURCE_IDENTITY_UNRESOLVED",
        )

        ambiguous = assess_supported_family_identity(
            FP_LAW_URL,
            [
                SegmentIdentityInput(
                    1,
                    "document_heading",
                    "LEY 2080 DE 2021",
                ),
                SegmentIdentityInput(
                    2,
                    "document_heading",
                    "DECRETO 117 DE 2017",
                ),
            ],
        )
        self.assertIsNotNone(ambiguous)
        assert ambiguous is not None
        self.assertFalse(ambiguous.accepted)
        self.assertEqual(
            ambiguous.assessment.reason_code,
            "FAMILY_IDENTITY_AMBIGUOUS",
        )

    def test_existing_normograma_identity_path_is_preserved(self) -> None:
        url = (
            "https://normograma.dian.gov.co/dian/compilacion/docs/"
            "ley_0001_2020.htm"
        )
        self.assertEqual(classify_source_url(url).family, NORMATIVE_ACT)
        assessment = assess_generic_normative_identity(
            url,
            "LEY 1 DE 2020",
        )
        self.assertTrue(assessment.accepted)
        self.assertEqual(
            assessment.content.canonical_key,
            "CO:LEY:1:2020",
        )


class FuncionPublicaDiscoveryTests(unittest.TestCase):
    def test_search_candidate_parser_rejects_unofficial_links(self) -> None:
        search_url = adapter.build_search_url(
            adapter.parse_target_key("CO:LEY:2080:2021")
        )
        html = """
        <html><body>
          <a href="/eva/gestornormativo/norma.php?i=156590">Ley</a>
          <a href="https://www1.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=156590">duplicate</a>
          <a href="https://funcionpublica.gov.co.evil.example/eva/gestornormativo/norma.php?i=99">evil</a>
          <a href="/eva/gestornormativo/norma.php?i=not-a-number">bad</a>
          <a href="/eva/gestornormativo/norma_pdf.php?i=156590">pdf</a>
        </body></html>
        """
        self.assertEqual(
            adapter.parse_search_candidates(search_url, html),
            [
                "https://www1.funcionpublica.gov.co/"
                "eva/gestornormativo/norma.php?i=156590"
            ],
        )

    def test_target_html_uses_family_safe_extraction(self) -> None:
        html = """
        <html><body>
        <h1>LEY 2080 DE 2021</h1>
        <p>(Enero 25)</p>
        <p>EL CONGRESO DE LA REPÚBLICA DE COLOMBIA</p>
        <p>DECRETA:</p>
        <p>ARTÍCULO 1. PRIMERA REGLA. Texto de prueba.</p>
        <p>ARTÍCULO 2. SEGUNDA REGLA. Otro texto.</p>
        </body></html>
        """
        result = adapter.assess_target_html(
            source_url=FP_LAW_URL,
            html_text=html,
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["canonical_key"], "CO:LEY:2080:2021")
        self.assertGreaterEqual(result["segment_count"], 5)

    def test_target_key_scope_excludes_issuer_sensitive_families(self) -> None:
        self.assertEqual(
            adapter.parse_target_key("co:decreto:0117:2017").canonical_key,
            "CO:DECRETO:117:2017",
        )
        with self.assertRaises(ValueError):
            adapter.parse_target_key("CO:DIAN:RESOLUCION:7941:2008")
        with self.assertRaises(ValueError):
            adapter.parse_target_key("CO:RESOLUCION:7941:2008")


class ReviewReconciliationTests(unittest.TestCase):
    def test_superseded_missing_document_review_closes_idempotently(self) -> None:
        con = sqlite3.connect(":memory:")
        con.execute(
            """
            CREATE TABLE review_queue(
                review_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                resolved_at TEXT,
                resolution TEXT,
                reviewer TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO review_queue(
                review_id, entity_type, entity_id, reason_code
            )
            VALUES (?, 'reference_mention', 'REF-1', ?)
            """,
            [
                ("REV-DOC", "TARGET_DOCUMENT_NOT_FOUND"),
                ("REV-PROV", "TARGET_PROVISION_NOT_FOUND"),
            ],
        )
        closed = close_obsolete_reference_reviews(
            con,
            mention_id="REF-1",
            now="2026-09-28T00:00:00+00:00",
            current_reason="TARGET_PROVISION_NOT_FOUND",
        )
        self.assertEqual(closed, 1)
        states = dict(
            con.execute(
                "SELECT reason_code, resolved_at FROM review_queue"
            ).fetchall()
        )
        self.assertIsNotNone(states["TARGET_DOCUMENT_NOT_FOUND"])
        self.assertIsNone(states["TARGET_PROVISION_NOT_FOUND"])

        closed_again = close_obsolete_reference_reviews(
            con,
            mention_id="REF-1",
            now="2026-09-28T00:01:00+00:00",
            current_reason="TARGET_PROVISION_NOT_FOUND",
        )
        self.assertEqual(closed_again, 0)


class DemandAndPreviewTests(unittest.TestCase):
    def make_minimal_db(self, path: Path) -> None:
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE reference_mentions(
                reference_mention_id TEXT PRIMARY KEY,
                target_document_key TEXT NOT NULL,
                detection_run_id TEXT NOT NULL
            );
            CREATE TABLE review_queue(
                review_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE document_identifiers(
                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL
            );
            """
        )
        mentions = [
            ("REF-L1", "CO:LEY:2080:2021", "RUN-1"),
            ("REF-L2", "CO:LEY:2080:2021", "RUN-2"),
            ("REF-D1", "CO:DECRETO:117:2017", "RUN-3"),
            ("REF-R1", "CO:DIAN:RESOLUCION:7941:2008", "RUN-4"),
        ]
        con.executemany(
            """
            INSERT INTO reference_mentions(
                reference_mention_id, target_document_key, detection_run_id
            )
            VALUES (?, ?, ?)
            """,
            mentions,
        )
        con.executemany(
            """
            INSERT INTO review_queue(
                review_id, entity_type, entity_id, reason_code, resolved_at
            )
            VALUES (?, 'reference_mention', ?,
                    'TARGET_DOCUMENT_NOT_FOUND', NULL)
            """,
            [
                ("REV-L1", "REF-L1"),
                ("REV-L2", "REF-L2"),
                ("REV-D1", "REF-D1"),
                ("REV-R1", "REF-R1"),
            ],
        )
        con.commit()
        con.close()

    def test_demand_ranking_filters_unsupported_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite"
            self.make_minimal_db(db)
            con = sqlite3.connect(db)
            rows = adapter.demand_rows(con)
            con.close()
            self.assertEqual(
                [row["target"].canonical_key for row in rows],
                ["CO:LEY:2080:2021", "CO:DECRETO:117:2017"],
            )
            self.assertEqual(rows[0]["open_reviews"], 2)

    def test_preview_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite"
            self.make_minimal_db(db)
            target = adapter.parse_target_key("CO:LEY:2080:2021")
            entry = {
                "target": target,
                "open_reviews": 2,
                "detection_runs": 2,
            }
            discovery = {
                "search_url": "https://www1.funcionpublica.gov.co/search",
                "candidate_count": 1,
                "selected": {
                    "url": FP_LAW_URL,
                    "final_url": FP_LAW_URL,
                    "raw_sha256": "a" * 64,
                    "status": "accepted",
                    "reason_code": None,
                    "canonical_key": target.canonical_key,
                    "title": "LEY 2080 DE 2021",
                    "segment_count": 5,
                    "normalized_sha256": "b" * 64,
                },
            }
            with mock.patch.object(
                adapter,
                "discover_target",
                return_value=discovery,
            ):
                result = adapter.preview_or_apply_target(
                    entry,
                    db_path=db,
                    data_root=Path(tmp) / "data",
                    allowed_domains_path=ROOT
                    / "config"
                    / "official_domains.json",
                    timeout=1.0,
                    max_bytes=1024,
                    max_candidates=5,
                    apply=False,
                )
            self.assertFalse(result["persistent_mutation"])
            self.assertEqual(
                result["action"],
                "acquire_register_reconcile",
            )
            con = sqlite3.connect(db)
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM review_queue "
                    "WHERE resolved_at IS NOT NULL"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM document_identifiers"
                ).fetchone()[0],
                0,
            )
            con.close()


class RegistrarIntegrationTests(unittest.TestCase):
    def init_db(self, db: Path) -> None:
        subprocess.run(
            [
                sys.executable,
                str(TOOLS / "init_db.py"),
                "--db",
                str(db),
                "--schema-dir",
                str(ROOT / "schema"),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stage_fp_law(
        self,
        db: Path,
        data_root: Path,
    ) -> tuple[str, str]:
        raw = """
        <html><body>
        <h1>LEY 2080 DE 2021</h1>
        <p>(Enero 25)</p>
        <p>EL CONGRESO DE LA REPÚBLICA DE COLOMBIA</p>
        <p>DECRETA:</p>
        <p>ARTÍCULO 1. PRIMERA REGLA. Texto de prueba.</p>
        <p>ARTÍCULO 2. SEGUNDA REGLA. Otro texto.</p>
        </body></html>
        """.encode("utf-8")
        raw_sha = hashlib.sha256(raw).hexdigest()
        source_id = "SRC-FP-TEST"
        manifestation_id = deterministic_manifestation_id(
            source_id,
            raw_sha,
        )
        relative = (
            Path("raw")
            / "sha256"
            / raw_sha[:2]
            / f"{raw_sha}.html"
        )
        raw_path = data_root / relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)

        con = sqlite3.connect(db)
        con.execute("PRAGMA foreign_keys = ON")
        con.execute(
            """
            INSERT INTO sources(
                source_id, source_url, authority, source_kind,
                discovered_from, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                source_id,
                FP_LAW_URL,
                "Departamento Administrativo de la Función Pública",
                "gestor_normativo",
                "2026-09-28T00:00:00+00:00",
                "2026-09-28T00:00:00+00:00",
            ),
        )
        con.execute(
            """
            INSERT INTO manifestations(
                manifestation_id, document_id, source_id, content_type,
                sha256, byte_size, retrieved_at, http_etag,
                http_last_modified, local_path, parser_version
            )
            VALUES (?, NULL, ?, 'text/html', ?, ?, ?, NULL, NULL, ?, NULL)
            """,
            (
                manifestation_id,
                source_id,
                raw_sha,
                len(raw),
                "2026-09-28T00:00:00+00:00",
                str(relative),
            ),
        )
        con.commit()
        con.close()
        return manifestation_id, raw_sha

    def test_registration_is_constrained_idempotent_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.sqlite"
            data_root = root / "data"
            self.init_db(db)
            manifestation_id, raw_sha = self.stage_fp_law(
                db,
                data_root,
            )
            extraction = extract_manifestation(
                manifestation_id=manifestation_id,
                db_path=db,
                data_root=data_root,
                dry_run=False,
            )

            mismatch = register_simple_act(
                extraction_id=str(extraction["extraction_id"]),
                db_path=db,
                expected_canonical_key="CO:LEY:9999:2021",
            )
            self.assertEqual(
                mismatch["reason_code"],
                "EXPECTED_CANONICAL_KEY_MISMATCH",
            )
            con = sqlite3.connect(db)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                0,
            )
            self.assertIsNone(
                con.execute(
                    "SELECT document_id FROM manifestations "
                    "WHERE manifestation_id = ?",
                    (manifestation_id,),
                ).fetchone()[0]
            )
            con.close()

            first = register_simple_act(
                extraction_id=str(extraction["extraction_id"]),
                db_path=db,
                expected_canonical_key="CO:LEY:2080:2021",
            )
            self.assertEqual(first["canonical_key"], "CO:LEY:2080:2021")
            self.assertEqual(first["issuer_key"], "CONGRESO")
            self.assertEqual(first["provisions_created"], 2)

            second = register_simple_act(
                extraction_id=str(extraction["extraction_id"]),
                db_path=db,
                expected_canonical_key="CO:LEY:2080:2021",
            )
            self.assertTrue(second["reused"])
            self.assertEqual(second["provisions_created"], 0)
            self.assertEqual(second["observations_created"], 0)

            con = sqlite3.connect(db)
            stored_sha = con.execute(
                "SELECT sha256 FROM manifestations "
                "WHERE manifestation_id = ?",
                (manifestation_id,),
            ).fetchone()[0]
            provision_count = con.execute(
                "SELECT COUNT(*) FROM provisions"
            ).fetchone()[0]
            con.close()
            self.assertEqual(stored_sha, raw_sha)
            self.assertEqual(provision_count, 2)


if __name__ == "__main__":
    unittest.main()
