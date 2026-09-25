from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import controller_memory as cm


MAIN = "a" * 40


def session_bytes(
    sid: str,
    timestamp: str,
    records: list[str],
    *,
    main_sha: str = MAIN,
    prev: str = "-",
) -> bytes:
    return (
        f"CM1|S|{sid}|{timestamp}|{main_sha}|{prev}\n"
        + "\n".join(records)
        + "\n"
    ).encode("utf-8")


class ControllerMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "controller-memory"
        (self.root / "sessions").mkdir(parents=True)
        (self.root / "SCHEMA.cm").write_bytes(cm.SCHEMA_BYTES)
        cm.rebuild_index(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_session(
        self,
        sid: str = "C260925T181700Z00",
        timestamp: str = "20260925T181700Z",
        records: list[str] | None = None,
        *,
        prev: str = "-",
    ) -> Path:
        records = records or [
            "D|1|0|cm|8|ses|i83|d1,i83,tcm",
            "E|83|2|81|i81|i81,i83,tcm",
        ]
        path = self.root / "sessions" / f"{sid}.cm"
        path.write_bytes(session_bytes(sid, timestamp, records, prev=prev))
        return path

    def test_valid_compact_session_parses_deterministically(self) -> None:
        path = self.write_session()
        one = cm.parse_session_file(path)
        two = cm.parse_session_file(path)
        self.assertEqual(one, two)
        self.assertEqual(one.sid, "C260925T181700Z00")
        self.assertEqual(one.records[0].keys, ("d1", "i83", "tcm"))

    def test_malformed_version_header_and_record_are_rejected(self) -> None:
        bad_version = session_bytes(
            "C260925T181700Z00",
            "20260925T181700Z",
            ["D|1|0|cm|8|ses|i83|d1,i83,tcm"],
        ).replace(b"CM1|S|", b"CM2|S|", 1)
        with self.assertRaises(cm.MemoryError):
            cm.parse_session_bytes(bad_version)

        with self.assertRaises(cm.MemoryError):
            cm.parse_session_bytes(b"CM1|S|bad\n")

        bad_record = session_bytes(
            "C260925T181700Z00",
            "20260925T181700Z",
            ["Z|unknown|i83"],
        )
        with self.assertRaises(cm.MemoryError):
            cm.parse_session_bytes(bad_record)

    def test_session_identity_path_mismatch_is_rejected(self) -> None:
        data = session_bytes(
            "C260925T181700Z00",
            "20260925T181700Z",
            ["D|1|0|cm|8|ses|i83|d1,i83,tcm"],
        )
        with self.assertRaises(cm.MemoryError):
            cm.parse_session_bytes(data, expected_filename="C260925T181701Z00.cm")

    def test_handoff_is_create_only_and_rebuilds_index(self) -> None:
        prepared_dir = Path(self.tmp.name) / "prepared"
        prepared_dir.mkdir()
        sid = "C260925T181700Z00"
        prepared = prepared_dir / f"{sid}.cm"
        prepared.write_bytes(
            session_bytes(
                sid,
                "20260925T181700Z",
                ["D|1|0|cm|8|ses|i83|d1,i83,tcm"],
            )
        )
        target = cm.handoff(self.root, prepared)
        self.assertTrue(target.is_file())
        self.assertEqual(cm.verify(self.root).session_count, 1)
        with self.assertRaises(cm.MemoryError):
            cm.handoff(self.root, prepared)

    def test_rebuild_is_byte_for_byte_deterministic(self) -> None:
        self.write_session()
        first = cm.rebuild_index(self.root)
        second = cm.rebuild_index(self.root)
        self.assertEqual(first, second)
        self.assertEqual(first, (self.root / "INDEX.cm").read_bytes())

    def test_manifest_fingerprint_changes_with_session_bytes_or_set(self) -> None:
        first_path = self.write_session()
        first = cm.rebuild_index(self.root)
        fp1 = cm.parse_index_bytes(first).manifest_sha256

        first_path.write_bytes(
            session_bytes(
                "C260925T181700Z00",
                "20260925T181700Z",
                [
                    "D|1|0|cm|8|ses|i83|d1,i83,tcm",
                    "F|1|fmt|1|i83|i83,tcm",
                ],
            )
        )
        fp2 = cm.parse_index_bytes(cm.rebuild_index(self.root)).manifest_sha256
        self.assertNotEqual(fp1, fp2)

        self.write_session(
            sid="C260925T181800Z00",
            timestamp="20260925T181800Z",
            records=["D|2|0|idx|7|ses|i83|d2,i83,tcm"],
            prev="C260925T181700Z00",
        )
        fp3 = cm.parse_index_bytes(cm.rebuild_index(self.root)).manifest_sha256
        self.assertNotEqual(fp2, fp3)

    def test_verify_detects_index_drift(self) -> None:
        self.write_session()
        cm.rebuild_index(self.root)
        (self.root / "INDEX.cm").write_text(
            "CM1|I|0|-|" + hashlib.sha256(b"").hexdigest() + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(cm.MemoryError, "drift"):
            cm.verify(self.root)

    def test_bootstrap_does_not_expand_session_history(self) -> None:
        self.write_session()
        cm.rebuild_index(self.root)
        with mock.patch.object(cm, "load_sessions", side_effect=AssertionError("history loaded")):
            data = cm.bootstrap(self.root)
        self.assertTrue(data.startswith(b"CM1|I|1|"))

    def test_exact_key_query_loads_only_indexed_sessions(self) -> None:
        relevant = self.write_session(
            records=[
                "D|1|0|cm|8|ses|i67|d1,i67,tcm",
                "F|1|other|1|i83|i83,tother",
            ]
        )
        unrelated = self.write_session(
            sid="C260925T181800Z00",
            timestamp="20260925T181800Z",
            records=["D|2|0|x|1|y|i99|d2,i99,tx"],
            prev="C260925T181700Z00",
        )
        cm.rebuild_index(self.root)
        unrelated.write_bytes(b"not-a-valid-session\n")

        result = cm.query(self.root, "i67").decode("utf-8")
        self.assertIn(relevant.stem, result)
        self.assertIn("D|1|0|cm|8|ses|i67|d1,i67,tcm", result)
        self.assertNotIn("F|1|other", result)
        self.assertNotIn(unrelated.stem, result)

    def test_issue_pr_decision_and_topic_keys_are_retrievable(self) -> None:
        self.write_session(records=["D|42|0|cm|8|ses|i67|d42,i67,p82,tcm"])
        cm.rebuild_index(self.root)
        for key in ("i67", "p82", "d42", "tcm"):
            with self.subTest(key=key):
                output = cm.query(self.root, key).decode("utf-8")
                self.assertIn("D|42|0|cm|8|ses|i67|d42,i67,p82,tcm", output)

    def test_supersession_is_append_only(self) -> None:
        first = self.write_session(records=["D|1|0|rt|6|ff|i75|d1,i75,trt"])
        original = first.read_bytes()
        cm.rebuild_index(self.root)

        prepared_dir = Path(self.tmp.name) / "prepared"
        prepared_dir.mkdir()
        sid2 = "C260925T181800Z00"
        second = prepared_dir / f"{sid2}.cm"
        second.write_bytes(
            session_bytes(
                sid2,
                "20260925T181800Z",
                ["D|2|0|rt|4|d1|i75|d1,d2,i75,trt"],
                prev="C260925T181700Z00",
            )
        )
        cm.handoff(self.root, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(cm.verify(self.root).session_count, 2)

    def test_repository_memory_is_self_consistent(self) -> None:
        index = cm.verify(ROOT / "controller-memory")
        self.assertGreaterEqual(index.session_count, 1)
        self.assertIn("i83", index.pointers)
        self.assertIn("tcm", index.pointers)

    def test_controller_docs_require_index_first_on_demand_handoff(self) -> None:
        orchestration = (ROOT / "docs" / "controller-orchestration.md").read_text(encoding="utf-8")
        handoff = (ROOT / "docs" / "controller-handoff-template.md").read_text(encoding="utf-8")
        self.assertIn("load only `controller-memory/INDEX.cm`", orchestration)
        self.assertIn("Do not load all historical session files by default.", orchestration)
        self.assertIn("CM: col-taxdata/controller-memory/INDEX.cm", handoff)
        self.assertIn("SID: <latest/new CM1 session id>", handoff)

    def test_tool_has_no_model_or_network_dependency(self) -> None:
        source = (ROOT / "tools" / "controller_memory.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "openai", "httpx", "socket"):
            self.assertNotIn(f"import {forbidden}", source)


if __name__ == "__main__":
    unittest.main()
