"""Offline safety and persistence regressions for Morichal status mailbox (#323)."""

from __future__ import annotations

import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1] / "ops"
sys.path.insert(0, str(OPS))
import worker_status_mailbox as mailbox  # noqa: E402


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "status"

    def write(self, worker="DEV-1", stage="STARTED", detail=None, run_id=None):
        args = types.SimpleNamespace(worker=worker, stage=stage,
                                     detail_json=json.dumps(detail or {}),
                                     run_id=run_id)
        with patch.object(mailbox, "ROOT", self.root):
            with contextlib.redirect_stdout(StringIO()) as captured:
                mailbox.record(args)
        return json.loads(captured.getvalue())

    def audit(self):
        with patch.object(mailbox, "ROOT", self.root):
            with contextlib.redirect_stdout(StringIO()) as captured:
                mailbox.inspect(types.SimpleNamespace(stale_minutes=90))
        return json.loads(captured.getvalue())["workers"]

    def test_no_report_is_not_falsely_a_success(self):
        result = self.audit()
        self.assertEqual(result["DEV-1"]["status"], "NO_REPORT")
        self.assertEqual(result["DEV-2"]["count"], 0)

    def test_atomic_append_and_same_run_event_chain(self):
        initial = self.write(detail={"issue": 59, "notes": "start"})
        self.assertTrue(initial["stored"])
        self.assertEqual(initial["sequence"], 1)
        second = self.write(stage="BLOCKED", run_id=initial["run_id"],
                            detail={"issue": 59, "operation": "GitHub.create_file",
                                    "error_class": "GITHUB_TOOL_SAFETY_DENIAL",
                                    "exact_error": "Tool call blocked",
                                    "next_action": "Controller recovery"})
        self.assertEqual(second["sequence"], 2)
        result = self.audit()
        self.assertTrue(result["DEV-1"]["chain_verified"])
        self.assertEqual(result["DEV-1"]["last"]["run_id"], initial["run_id"])
        self.assertEqual(result["DEV-1"]["last"]["stage"], "BLOCKED")
        self.assertEqual(result["DEV-2"]["status"], "NO_REPORT")
        for event in (self.root / "events" / "DEV-1").glob("*.json"):
            self.assertEqual(event.stat().st_mode & 0o777, 0o600)

    def test_missing_failure_details_rejected_without_append(self):
        with self.assertRaisesRegex(ValueError, "blocked status requires"):
            self.write(stage="BLOCKED", detail={"error_class": "bad"})
        self.assertEqual(self.audit()["DEV-1"]["count"], 0)

    def test_tampered_history_is_not_accepted(self):
        self.write(detail={"notes": "unchanged"})
        path = self.root / "events" / "DEV-1" / "00000001.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["detail"]["notes"] = "modified"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "status chain mismatch"):
            self.audit()
        with self.assertRaisesRegex(ValueError, "status chain mismatch"):
            self.write()

    def test_unsupported_worker_stage_and_unexpected_field(self):
        for worker, stage, detail in (("DEV-A", "STARTED", {}),
                                      ("DEV-1", "SUCCESS", {}),
                                      ("DEV-1", "STARTED", {"token": "private"})):
            with self.subTest(worker=worker, stage=stage):
                with self.assertRaises(ValueError):
                    self.write(worker=worker, stage=stage, detail=detail)
        self.assertEqual(self.audit()["DEV-1"]["count"], 0)

    def test_secret_redaction_before_writing(self):
        self.write(detail={"notes": "Authorization: Bearer verySensitive0123456789 "
                             "password=superSecret"})
        record = self.audit()["DEV-1"]["last"]
        encoded = json.dumps(record)
        self.assertNotIn("verySensitive", encoded)
        self.assertNotIn("superSecret", encoded)
        self.assertIn("[REDACTED]", encoded)

    def test_per_worker_independent_histories(self):
        self.write(worker="DEV-1", detail={"issue": 59})
        self.write(worker="DEV-2", detail={"issue": 60})
        status = self.audit()
        self.assertEqual(status["DEV-1"]["count"], 1)
        self.assertEqual(status["DEV-2"]["count"], 1)
        self.assertEqual(status["DEV-2"]["last"]["detail"]["issue"], 60)


if __name__ == "__main__":
    unittest.main()
