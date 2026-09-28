from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CI_DIR = ROOT / "ci"
sys.path.insert(0, str(CI_DIR))

import agent_control  # noqa: E402
import issue_state_sync  # noqa: E402


class Issue0240BlockedStatusTests(unittest.TestCase):
    def marker(self, state: str, **extra: object) -> str:
        payload = {"state": state, **extra}
        return (
            f"{issue_state_sync.STATE_MARKER} "
            f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))} -->\n"
            f"Agent state: \`{state}\`."
        )

    def test_arbitrary_blocked_prose_is_not_control_state(self):
        self.assertIsNone(
            issue_state_sync.marker_payload(
                "Development log — State: BLOCKED by #239, but no machine marker."
            )
        )

    def test_237_style_machine_block_is_accepted(self):
        body = self.marker(
            "BLOCKED",
            reason="post-merge provider acceptance failed",
            blocker="https://github.com/balamacab/RustIDEAM/issues/239",
            main_sha="a" * 40,
        )
        payload = issue_state_sync.marker_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIn("239", payload["blocker"])

    def test_latest_marker_uses_comment_identity_not_prose(self):
        comments = [
            {"id": 10, "body": self.marker("BLOCKED")},
            {"id": 11, "body": "BLOCKED in prose only"},
            {"id": 12, "body": self.marker("WORKING")},
        ]
        self.assertEqual(issue_state_sync.latest_marker_state(comments), "WORKING")

    @mock.patch.object(issue_state_sync, "request_json")
    def test_blocked_creates_label_and_adds_it(self, request_json):
        def side_effect(token, method, path, payload=None):
            if method == "GET" and path.endswith("/issues/240"):
                return {"state": "open", "labels": []}
            if method == "GET" and "/labels/status%3Ablocked" in path:
                if side_effect.label_exists:
                    return {"name": "status:blocked"}
                raise issue_state_sync.ApiError(404, "not found")
            if method == "POST" and path.endswith("/labels"):
                side_effect.label_exists = True
                return {"name": "status:blocked"}
            if method == "POST" and path.endswith("/issues/240/labels"):
                return [{"name": "status:blocked"}]
            raise AssertionError((method, path, payload))

        side_effect.label_exists = False
        request_json.side_effect = side_effect
        result = issue_state_sync.apply_visible_state(
            "token", "balamacab/RustIDEAM", 240, "BLOCKED"
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["action"], "added")
        create_calls = [
            call
            for call in request_json.call_args_list
            if call.args[1] == "POST"
            and call.args[2] == "/repos/balamacab/RustIDEAM/labels"
        ]
        self.assertEqual(len(create_calls), 1)

    @mock.patch.object(issue_state_sync, "request_json")
    def test_repeated_blocked_is_idempotent(self, request_json):
        request_json.return_value = {
            "state": "open",
            "labels": [{"name": issue_state_sync.BLOCKED_LABEL}],
        }
        result = issue_state_sync.apply_visible_state(
            "token", "balamacab/RustIDEAM", 240, "BLOCKED"
        )
        self.assertFalse(result["changed"])
        self.assertEqual(request_json.call_count, 1)

    @mock.patch.object(issue_state_sync, "request_json")
    def test_nonblocked_state_removes_label(self, request_json):
        request_json.side_effect = [
            {"state": "open", "labels": [{"name": issue_state_sync.BLOCKED_LABEL}]},
            None,
        ]
        result = issue_state_sync.apply_visible_state(
            "token", "balamacab/RustIDEAM", 240, "WORKING"
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["action"], "removed")
        delete = request_json.call_args_list[1]
        self.assertEqual(delete.args[1], "DELETE")
        self.assertTrue(delete.args[2].endswith("/labels/status%3Ablocked"))

    @mock.patch.object(issue_state_sync, "request_json")
    def test_repeated_unblock_is_idempotent(self, request_json):
        request_json.return_value = {"state": "open", "labels": []}
        result = issue_state_sync.apply_visible_state(
            "token", "balamacab/RustIDEAM", 240, "WORKING"
        )
        self.assertFalse(result["changed"])
        self.assertEqual(request_json.call_count, 1)

    @mock.patch.object(issue_state_sync, "apply_visible_state")
    @mock.patch.object(issue_state_sync, "fetch_all_comments")
    def test_sync_uses_latest_machine_marker(self, fetch_comments, apply_state):
        fetch_comments.return_value = [
            {"id": 100, "body": self.marker("BLOCKED")},
            {"id": 101, "body": self.marker("CI_VALIDATING")},
        ]
        apply_state.return_value = {"changed": True}
        issue_state_sync.sync_from_comments(
            "token", "balamacab/RustIDEAM", 240
        )
        apply_state.assert_called_once_with(
            "token", "balamacab/RustIDEAM", 240, "CI_VALIDATING"
        )

    @mock.patch.object(issue_state_sync, "sync_from_comments")
    def test_event_with_unrelated_comment_does_nothing(self, sync_from_comments):
        event = {
            "issue": {"number": 240},
            "comment": {"body": "This issue is BLOCKED in ordinary prose.", "author_association": "OWNER"},
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            json.dump(event, fh)
            event_path = fh.name
        args = type(
            "Args",
            (),
            {"event": event_path, "repository": "balamacab/RustIDEAM"},
        )()
        self.assertEqual(issue_state_sync.cmd_event(args), 0)
        sync_from_comments.assert_not_called()

    @mock.patch.object(issue_state_sync, "sync_from_comments")
    def test_untrusted_commenter_cannot_mutate_visible_state(self, sync_from_comments):
        event = {
            "issue": {"number": 240},
            "comment": {
                "body": self.marker("BLOCKED"),
                "author_association": "NONE",
            },
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            json.dump(event, fh)
            event_path = fh.name
        args = type("Args", (), {"event": event_path, "repository": "balamacab/RustIDEAM"})()
        self.assertEqual(issue_state_sync.cmd_event(args), 0)
        sync_from_comments.assert_not_called()

    @mock.patch.object(issue_state_sync, "sync_from_comments")
    @mock.patch.dict("os.environ", {"GITHUB_TOKEN": "token"})
    def test_owner_marker_is_eligible_for_sync(self, sync_from_comments):
        event = {
            "issue": {"number": 240},
            "comment": {
                "body": self.marker("BLOCKED"),
                "author_association": "OWNER",
            },
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            json.dump(event, fh)
            event_path = fh.name
        sync_from_comments.return_value = {"changed": False}
        args = type("Args", (), {"event": event_path, "repository": "balamacab/RustIDEAM"})()
        self.assertEqual(issue_state_sync.cmd_event(args), 0)
        sync_from_comments.assert_called_once_with("token", "balamacab/RustIDEAM", 240)

    def test_issue_comment_workflow_has_only_required_write_scope(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "col-taxdata-issue-state.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("issue_comment:", workflow)
        self.assertIn("types: [created]", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn("issue_state_sync.py event", workflow)
        self.assertNotIn("write-all", workflow)

    def test_durable_docs_define_marker_as_source_of_truth(self):
        autonomous = (ROOT / "docs" / "autonomous-agent-execution.md").read_text(
            encoding="utf-8"
        )
        workers = (ROOT / "docs" / "scheduled-developer-workers.md").read_text(
            encoding="utf-8"
        )
        for text in (autonomous, workers):
            self.assertIn("status:blocked", text)
            self.assertIn("col-taxdata-agent-state", text)
        self.assertIn("prose alone is insufficient", workers)

    @mock.patch.object(agent_control, "apply_visible_state")
    @mock.patch.object(agent_control, "post_issue_comment")
    def test_agent_state_comment_projects_visible_state(self, post_comment, apply_state):
        agent_control.post_state_comment(
            "token",
            "balamacab/RustIDEAM",
            240,
            "BLOCKED",
            reason="dependency",
            blocker="https://example/239",
        )
        body = post_comment.call_args.args[3]
        self.assertIn('"state":"BLOCKED"', body)
        apply_state.assert_called_once_with(
            "token", "balamacab/RustIDEAM", 240, "BLOCKED"
        )


if __name__ == "__main__":
    unittest.main()
