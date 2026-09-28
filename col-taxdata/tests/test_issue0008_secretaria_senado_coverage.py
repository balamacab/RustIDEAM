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

import acquire_secretaria_senado as adapter
from extract_normograma_html import extract_manifestation
from fetch_source import (
    deterministic_manifestation_id,
    load_allowed_domains,
)
from register_simple_normative_act import register_simple_act
from resolve_references import close_obsolete_reference_reviews
from source_identity import (
    NORMATIVE_ACT,
    assess_generic_normative_identity,
    classify_source_url,
)


SENATE_LAW_URL = (
    "http://www.secretariasenado.gov.co/senado/basedoc/"
    "ley_2080_2021.html"
)


class SenateTargetTests(unittest.TestCase):
    def test_target_key_maps_to_deterministic_official_url(self) -> None:
        target = adapter.parse_target_key("co:ley:2080:2021")
        self.assertEqual(target.canonical_key, "CO:LEY:2080:2021")
        self.assertEqual(target.source_url, SENATE_LAW_URL)

        padded = adapter.parse_target_key("CO:LEY:489:1998")
        self.assertTrue(
            padded.source_url.endswith("/ley_0489_1998.html")
        )

    def test_scope_rejects_non_law_and_non_numeric_keys(self) -> None:
        for key in (
            "CO:DECRETO:117:2017",
            "CO:DIAN:RESOLUCION:7941:2008",
            "CO:LEY:12A:2020",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    adapter.parse_target_key(key)

    def test_senate_domain_is_allowlisted(self) -> None:
        allowed = load_allowed_domains(
            ROOT / "config" / "official_domains.json"
        )
        self.assertIn("secretariasenado.gov.co", allowed)
        adapter.validate_source_url(
            SENATE_LAW_URL,
            allowed_domains=allowed,
        )

    def test_url_guard_rejects_mirror_and_decorated_urls(self) -> None:
        allowed = {"secretariasenado.gov.co"}
        rejected = (
            "http://secretariasenado.gov.co.evil.example/"
            "senado/basedoc/ley_2080_2021.html",
            "http://www.secretariasenado.gov.co/other/"
            "ley_2080_2021.html",
            SENATE_LAW_URL + "?mirror=1",
        )
        for url in rejected:
            with self.subTest(url=url):
                with self.assertRaises(adapter.SenateSourceError):
                    adapter.validate_source_url(
                        url,
                        allowed_domains=allowed,
                    )

    def test_existing_identity_contract_accepts_senate_law(self) -> None:
        signal = classify_source_url(SENATE_LAW_URL)
        self.assertEqual(signal.family, NORMATIVE_ACT)
        self.assertEqual(signal.canonical_key, "CO:LEY:2080:2021")
        self.assertEqual(signal.issuer_key, "CONGRESO")

        assessment = assess_generic_normative_identity(
            SENATE_LAW_URL,
            "LEY 2080 DE 2021",
        )
        self.assertTrue(assessment.accepted)
        self.assertEqual(
            assessment.content.canonical_key,
            "CO:LEY:2080:2021",
        )

    def test_target_html_must_match_requested_identity(self) -> None:
        target = adapter.parse_target_key("CO:LEY:2080:2021")
        html = """
        <html><body>
        <h1>LEY 2080 DE 2021</h1>
        <p>(enero 25)</p>
        <p>EL CONGRESO DE LA REPÚBLICA DE COLOMBIA</p>
        <p>DECRETA:</p>
        <p>ARTÍCULO 1o. PRIMERA REGLA. Texto de prueba.</p>
        <p>ARTÍCULO 2o. SEGUNDA REGLA. Otro texto.</p>
        </body></html>
        """
        result = adapter.assess_target_html(
            target,
            source_url=SENATE_LAW_URL,
            html_text=html,
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["canonical_key"], target.canonical_key)
        self.assertEqual(result["issuer_key"], "CONGRESO")

        wrong_target = adapter.parse_target_key("CO:LEY:2081:2021")
        with self.assertRaises(adapter.SenateSourceError):
            adapter.assess_target_html(
                wrong_target,
                source_url=SENATE_LAW_URL,
                html_text=html,
            )


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
        con.executemany(
            """
            INSERT INTO reference_mentions(
                reference_mention_id,
                target_document_key,
                detection_run_id
            )
            VALUES (?, ?, ?)
            """,
            [
                ("REF-L1", "CO:LEY:2080:2021", "RUN-1"),
                ("REF-L2", "CO:LEY:2080:2021", "RUN-2"),
                ("REF-L3", "CO:LEY:1437:2011", "RUN-3"),
                ("REF-D1", "CO:DECRETO:117:2017", "RUN-4"),
            ],
        )
        con.executemany(
            """
            INSERT INTO review_queue(
                review_id,
                entity_type,
                entity_id,
                reason_code,
                resolved_at
            )
            VALUES (
                ?, 'reference_mention', ?,
                'TARGET_DOCUMENT_NOT_FOUND', NULL
            )
            """,
            [
                ("REV-L1", "REF-L1"),
                ("REV-L2", "REF-L2"),
                ("REV-L3", "REF-L3"),
                ("REV-D1", "REF-D1"),
            ],
        )
        con.commit()
        con.close()

    def test_demand_ranking_uses_open_law_reviews_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite"
            self.make_minimal_db(db)
            con = sqlite3.connect(db)
            rows = adapter.demand_rows(con)
            con.close()

            self.assertEqual(
                [row["target"].canonical_key for row in rows],
                ["CO:LEY:2080:2021", "CO:LEY:1437:2011"],
            )
            self.assertEqual(rows[0]["open_reviews"], 2)

    def test_preview_is_network_backed_but_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite"
            self.make_minimal_db(db)
            target = adapter.parse_target_key("CO:LEY:2080:2021")
            entry = {
                "target": target,
                "open_reviews": 2,
                "detection_runs": 2,
            }
            page = {
                "requested_url": SENATE_LAW_URL,
                "final_url": SENATE_LAW_URL,
                "content_type": "text/html",
                "bytes": b"<html></html>",
                "text": "<html></html>",
                "sha256": "a" * 64,
            }
            assessment = {
                "status": "accepted",
                "canonical_key": target.canonical_key,
                "issuer_key": "CONGRESO",
                "heading": "LEY 2080 DE 2021",
                "segment_count": 2,
                "normalized_sha256": "b" * 64,
            }

            with (
                mock.patch.object(
                    adapter,
                    "read_official_html",
                    return_value=page,
                ),
                mock.patch.object(
                    adapter,
                    "assess_target_html",
                    return_value=assessment,
                ),
            ):
                result = adapter.preview_or_apply_target(
                    entry,
                    db_path=db,
                    data_root=Path(tmp) / "data",
                    allowed_domains_path=(
                        ROOT / "config" / "official_domains.json"
                    ),
                    timeout=1.0,
                    max_bytes=1024,
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

    def stage_senate_law(
        self,
        db: Path,
        data_root: Path,
    ) -> tuple[str, str]:
        raw = """
        <html><body>
        <h1>LEY 2080 DE 2021</h1>
        <p>(enero 25)</p>
        <p>EL CONGRESO DE LA REPÚBLICA DE COLOMBIA</p>
        <p>DECRETA:</p>
        <p>ARTÍCULO 1o. PRIMERA REGLA. Texto de prueba.</p>
        <p>ARTÍCULO 2o. SEGUNDA REGLA. Otro texto.</p>
        </body></html>
        """.encode("utf-8")
        raw_sha = hashlib.sha256(raw).hexdigest()
        source_id = "SRC-SEN-TEST"
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
                SENATE_LAW_URL,
                "Secretaría General del Senado de la República",
                "senado_basedoc",
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
            VALUES (
                ?, NULL, ?, 'text/html', ?, ?, ?,
                NULL, NULL, ?, NULL
            )
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

    def test_registration_constraint_idempotency_and_raw_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.sqlite"
            data_root = root / "data"
            self.init_db(db)
            manifestation_id, raw_sha = self.stage_senate_law(
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
                con.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM review_queue"
                ).fetchone()[0],
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
            self.assertEqual(
                first["canonical_key"],
                "CO:LEY:2080:2021",
            )
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
