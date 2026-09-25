from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import controller_memory as cm


MAIN = "b" * 40


def session_bytes(
    sid: str,
    timestamp: str,
    records: list[str],
    *,
    prev: str = "-",
) -> bytes:
    return (
        f"CM1|S|{sid}|{timestamp}|{MAIN}|{prev}\n"
        + "\n".join(records)
        + "\n"
    ).encode("utf-8")


class ControllerEthosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "controller-memory"
        (self.root / "sessions").mkdir(parents=True)
        (self.root / "SCHEMA.cm").write_bytes(cm.SCHEMA_BYTES)
        (self.root / "ETHOS.cm").write_bytes(cm.ETHOS_BYTES)
        cm.rebuild_index(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_valid_ethos_parses_deterministically(self) -> None:
        one = cm.parse_ethos_bytes(cm.ETHOS_BYTES)
        two = cm.parse_ethos_bytes(cm.ETHOS_BYTES)
        self.assertEqual(one, two)
        self.assertEqual(one.version, 1)
        self.assertEqual(one.raw, cm.ETHOS_BYTES)

    def test_required_controller_invariants_are_encoded(self) -> None:
        ethos = cm.parse_ethos_bytes(cm.ETHOS_BYTES)
        self.assertEqual(ethos.principles, cm.ETHOS_REQUIRED_PRINCIPLES)
        self.assertEqual(ethos.rules, cm.ETHOS_REQUIRED_RULES)
        self.assertEqual(ethos.stages, cm.ETHOS_REQUIRED_STAGES)
        self.assertIn(("evidence", "fluency"), ethos.principles)
        self.assertIn(("architecture", "unblock"), ethos.principles)
        self.assertIn(("live", "stale"), ethos.principles)
        self.assertIn(("convergence", "closure"), ethos.principles)
        self.assertIn(
            ("absence-evidence", "not-authorization"),
            ethos.rules,
        )
        self.assertIn(
            ("challenge-evidence", "preserve-history"),
            ethos.rules,
        )
        self.assertEqual(
            ethos.stages,
            (
                "observation",
                "conclusion",
                "decision",
                "authorization",
                "execution",
                "verified-integration",
            ),
        )

    def test_wrong_version_unknown_record_and_missing_stage_fail_closed(self) -> None:
        with self.assertRaisesRegex(cm.MemoryError, "unsupported version"):
            cm.parse_ethos_bytes(
                cm.ETHOS_BYTES.replace(b"CM1|H|1\n", b"CM1|H|2\n", 1)
            )

        unknown = cm.ETHOS_BYTES + b"Z|x|y\n"
        with self.assertRaisesRegex(cm.MemoryError, "unknown record"):
            cm.parse_ethos_bytes(unknown)

        no_stage = b"\n".join(cm.ETHOS_BYTES.rstrip(b"\n").split(b"\n")[:-1]) + b"\n"
        with self.assertRaisesRegex(cm.MemoryError, "stage distinction"):
            cm.parse_ethos_bytes(no_stage)

    def test_nonpositive_malformed_and_duplicate_ethos_fail_closed(self) -> None:
        with self.assertRaises(cm.MemoryError):
            cm.parse_ethos_bytes(
                cm.ETHOS_BYTES.replace(b"CM1|H|1\n", b"CM1|H|0\n", 1)
            )
        with self.assertRaises(cm.MemoryError):
            cm.parse_ethos_bytes(b"CM1|H|1\nP|only-one-field\n")

        duplicate = cm.ETHOS_BYTES.replace(
            b"P|architecture|unblock\n",
            b"P|evidence|unblock\n",
            1,
        )
        with self.assertRaisesRegex(cm.MemoryError, "duplicate"):
            cm.parse_ethos_bytes(duplicate)

    def test_repository_ethos_matches_compiled_contract(self) -> None:
        committed = (ROOT / "controller-memory" / "ETHOS.cm").read_bytes()
        self.assertEqual(committed, cm.ETHOS_BYTES)
        ethos = cm.verify_ethos(ROOT / "controller-memory")
        self.assertEqual(ethos.version, cm.ETHOS_VERSION)

    def test_bootstrap_contains_ethos_and_index_without_session_payload(self) -> None:
        sid = "C260925T190000Z00"
        payload = "z" * 400
        session = self.root / "sessions" / f"{sid}.cm"
        session.write_bytes(
            session_bytes(
                sid,
                "20260925T190000Z",
                [f"X|note|i85|{payload}|i85,tethos"],
            )
        )
        cm.rebuild_index(self.root)
        bootstrap = cm.bootstrap(self.root)
        self.assertTrue(bootstrap.startswith(b"CM1|B\nCM1|H|1\n"))
        self.assertIn(b"CM1|I|1|", bootstrap)
        self.assertNotIn(payload.encode("ascii"), bootstrap)
        self.assertNotIn(f"CM1|S|{sid}".encode("ascii"), bootstrap)

    def test_bootstrap_remains_small_as_session_payload_history_grows(self) -> None:
        huge = "q" * 900
        prior = "-"
        for i in range(40):
            sid = f"C260925T19{i:02d}00Z00"
            timestamp = f"20260925T19{i:02d}00Z"
            path = self.root / "sessions" / f"{sid}.cm"
            path.write_bytes(
                session_bytes(
                    sid,
                    timestamp,
                    [f"X|note|i85|{huge}|i85,tethos"],
                    prev=prior,
                )
            )
            prior = sid
        cm.rebuild_index(self.root)
        bootstrap = cm.bootstrap(self.root)
        total_history = sum(
            path.stat().st_size for path in (self.root / "sessions").glob("*.cm")
        )
        self.assertLess(len(bootstrap), total_history // 5)
        self.assertNotIn((huge[:100]).encode("ascii"), bootstrap)

    def test_verify_fails_when_ethos_is_malformed(self) -> None:
        (self.root / "ETHOS.cm").write_bytes(b"CM1|H|1\nP|broken\n")
        with self.assertRaises(cm.MemoryError):
            cm.verify(self.root)

    def test_bootstrap_and_verify_do_not_mutate_historical_session(self) -> None:
        sid = "C260925T190000Z00"
        path = self.root / "sessions" / f"{sid}.cm"
        original = session_bytes(
            sid,
            "20260925T190000Z",
            ["D|85|0|ethos|5|cm1|i85|d85,i85,tethos"],
        )
        path.write_bytes(original)
        cm.rebuild_index(self.root)
        cm.bootstrap(self.root)
        cm.verify(self.root)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
