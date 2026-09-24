from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import doctor  # noqa: E402


class CorpusDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "state" / "taxdata.sqlite"
        self.data_root = self.root / "data"
        self.schema_dir = PROJECT_ROOT / "schema"

        subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "init_db.py"),
                "--db",
                str(self.db_path),
                "--schema-dir",
                str(self.schema_dir),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.fixture = self._create_healthy_fixture()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _create_healthy_fixture(self) -> dict[str, object]:
        raw = b"<html><body>LEY 1 DE 2020</body></html>"
        raw_sha = self._sha(raw)
        raw_rel = Path("raw") / "sha256" / raw_sha[:2] / f"{raw_sha}.html"
        raw_path = self.data_root / raw_rel
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)

        text = "LEY 1 DE 2020\n\nARTICULO 1. Texto de prueba.\n"
        normalized = text.encode("utf-8")
        normalized_sha = self._sha(normalized)
        normalized_rel = Path("extracted") / "sha256" / normalized_sha[:2] / f"{normalized_sha}.txt"
        normalized_path = self.data_root / normalized_rel
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_bytes(normalized)
        segment_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source_url = "https://normograma.dian.gov.co/dian/compilacion/docs/ley_0001_2020.htm"

        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys = ON")
        now = "2026-09-24T00:00:00+00:00"
        with con:
            con.execute(
                "INSERT INTO documents(document_id, entity, document_type, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("DOC-healthy", "CONGRESO", "LEY", "LEY 1 DE 2020", now, now),
            )
            con.execute(
                "INSERT INTO document_identifiers(identifier_id, document_id, identifier_type, identifier_value, issuer, is_primary) VALUES (?, ?, 'canonical_key', ?, ?, 1)",
                ("ID-healthy", "DOC-healthy", "CO:LEY:1:2020", "CONGRESO"),
            )
            con.execute(
                "INSERT INTO sources(source_id, source_url, authority, source_kind, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("SRC-healthy", source_url, "DIAN", "normograma", now, now),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type, sha256,
                    byte_size, retrieved_at, local_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "MAN-healthy",
                    "DOC-healthy",
                    "SRC-healthy",
                    "text/html",
                    raw_sha,
                    len(raw),
                    now,
                    str(raw_rel),
                ),
            )
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name, extractor_version,
                    normalized_sha256, byte_size, char_count, segment_count,
                    local_path, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "EXT-healthy",
                    "MAN-healthy",
                    "fixture",
                    "1",
                    normalized_sha,
                    len(normalized),
                    len(text),
                    1,
                    str(normalized_rel),
                    now,
                    "success",
                ),
            )
            con.execute(
                """
                INSERT INTO extracted_segments(
                    extracted_segment_id, extraction_id, sequence_no, segment_type,
                    char_start, char_end, text, text_sha256
                ) VALUES (?, ?, 0, 'text', 0, ?, ?, ?)
                """,
                ("SEG-healthy", "EXT-healthy", len(text), text, segment_sha),
            )
            rowid = con.execute(
                "SELECT rowid FROM extracted_segments WHERE extracted_segment_id = 'SEG-healthy'"
            ).fetchone()[0]
            con.execute(
                "INSERT INTO extracted_segments_fts(rowid, extracted_segment_id, text, section_path) VALUES (?, ?, ?, NULL)",
                (rowid, "SEG-healthy", text),
            )
            con.execute(
                """
                INSERT INTO claims(
                    claim_id, subject_type, subject_id, predicate, claim_type,
                    status, extraction_method, created_at
                ) VALUES (?, 'document', ?, 'fixture', 'fixture', 'validated', 'fixture', ?)
                """,
                ("CLM-healthy", "DOC-healthy", now),
            )
            con.execute(
                """
                INSERT INTO evidence(
                    evidence_id, claim_id, manifestation_id, exact_quote,
                    source_url, source_sha256, retrieved_at, review_status,
                    extracted_segment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'machine_validated', ?)
                """,
                (
                    "EVD-healthy",
                    "CLM-healthy",
                    "MAN-healthy",
                    text,
                    source_url,
                    raw_sha,
                    now,
                    "SEG-healthy",
                ),
            )
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        return {
            "raw_path": raw_path,
            "raw": raw,
            "source_url": source_url,
            "rowid": rowid,
        }

    def _run(self, *, mode: str = "quick") -> doctor.DoctorReport:
        return doctor.run_doctor(
