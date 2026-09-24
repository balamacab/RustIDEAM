from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

CI_DIR = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_DIR))
import agent_control  # noqa: E402


class AgentControlTests(unittest.TestCase):
    def request(self, attempt: int = 0):
        return agent_control.ResumeRequest(
            repository="balamacab/RustIDEAM",
            issue_number=28,
            pr_number=99,
            branch="agent/issue-28-autonomous-ci",
            head_sha="a" * 40,
            base_sha="b" * 40,
            reason="CI_FAILED",
            semantic_domains=["repository-automation"],
            attempt=attempt,
        )

    def test_resume_payload_contract_is_stable(self):
        payload = agent_control.build_resume_payload(self.request(attempt=2))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["reason"], "CI_FAILED")
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["max_attempts"], 3)

    def test_retry_count_is_scoped_to_reason_and_head(self):
        payload = agent_control.build_resume_payload(self.request(attempt=1))
        body = f"{agent_control.RESUME_MARKER} {json.dumps(payload)} -->"
        comments = [{"body": body}, {"body": "unrelated"}]
        self.assertEqual(agent_control.retry_count(comments, "CI_FAILED", "a" * 40), 1)
        self.assertEqual(agent_control.retry_count(comments, "MERGE_CONFLICT", "a" * 40), 0)

    @mock.patch.object(agent_control, "request_json")
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control, "fetch_comments", return_value=[])
    def test_resume_dispatches_repository_event(self, fetch_comments, post_comment, request_json):
        result = agent_control.request_resume("token", self.request())
        self.assertTrue(result["dispatched"])
        dispatch = [call for call in request_json.call_args_list if call.args[1] == "POST" and call.args[2].endswith("/dispatches")]
        self.assertEqual(len(dispatch), 1)
        self.assertEqual(dispatch[0].args[3]["event_type"], agent_control.RESUME_EVENT)

    @mock.patch.object(agent_control, "create_blocker", return_value={"html_url": "https://example/blocker"})
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control, "fetch_comments")
    def test_retry_budget_blocks_instead_of_looping(self, fetch_comments, post_comment, create_blocker):
        payload = agent_control.build_resume_payload(self.request(attempt=1))
        marker = f"{agent_control.RESUME_MARKER} {json.dumps(payload)} -->"
        fetch_comments.return_value = [{"body": marker}] * agent_control.MAX_RETRIES
        result = agent_control.request_resume("token", self.request())
        self.assertFalse(result["dispatched"])
        self.assertTrue(result["blocked"])
        create_blocker.assert_called_once()


if __name__ == "__main__":
    unittest.main()

[executed on device: morichalserver (2bfaa62f-23ff-40e5-9fc7-7c1a7d28b1fc)]