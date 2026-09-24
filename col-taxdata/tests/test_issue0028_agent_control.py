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
    def pr(self, state: str = "blocked", head_sha: str | None = None):
        sha = head_sha or ("a" * 40)
        metadata = {
            "base_sha": "b" * 40,
            "parallel_safe": False,
            "semantic_domains": ["repository-automation"],
            "likely_touched": ["col-taxdata/ci/**"],
            "depends_on": [],
        }
        return {
            "body": "Fixes #28\n\n<!-- col-taxdata-agent-metadata: "
            + json.dumps(metadata)
            + " -->",
            "head": {"ref": "agent/issue-28-autonomous-ci", "sha": sha},
            "base": {"sha": "b" * 40},
            "mergeable": True,
            "mergeable_state": state,
        }

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
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["reason"], "CI_FAILED")
        self.assertEqual(payload["retry"]["attempt"], 2)
        self.assertEqual(payload["retry"]["max_attempts"], 3)
        self.assertFalse(payload["retry"]["automatic_update"])
        self.assertLessEqual(
            len(payload),
            agent_control.GITHUB_REPOSITORY_DISPATCH_MAX_PROPERTIES,
        )

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
        client_payload = dispatch[0].args[3]["client_payload"]
        self.assertLessEqual(
            len(client_payload),
            agent_control.GITHUB_REPOSITORY_DISPATCH_MAX_PROPERTIES,
        )
        self.assertEqual(client_payload["retry"]["attempt"], 1)
        self.assertEqual(client_payload["retry"]["max_attempts"], agent_control.MAX_RETRIES)
        self.assertFalse(client_payload["retry"]["automatic_update"])

    @mock.patch.object(agent_control, "request_json")
    def test_dispatch_ci_uses_trusted_main_workflow_definition(self, request_json):
        agent_control.dispatch_ci(
            "token",
            "balamacab/RustIDEAM",
            "agent/issue-28-autonomous-ci",
            99,
        )
        request_json.assert_called_once_with(
            "token",
            "POST",
            "/repos/balamacab/RustIDEAM/actions/workflows/col-taxdata-ci.yml/dispatches",
            {
                "ref": agent_control.CI_WORKFLOW_REF,
                "inputs": {"pr_number": "99"},
            },
        )

    @mock.patch.object(agent_control, "dispatch_ci")
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control, "fetch_pr")
    def test_pull_request_lifecycle_dispatches_ci_when_no_result_exists(
        self, fetch_pr, post_comment, dispatch_ci
    ):
        fetch_pr.return_value = self.pr("blocked")
        result = agent_control.handle_lifecycle(
            "token", "balamacab/RustIDEAM", 99, None, None
        )
        self.assertTrue(result["ci_dispatched"])
        dispatch_ci.assert_called_once_with(
            "token",
            "balamacab/RustIDEAM",
            "agent/issue-28-autonomous-ci",
            99,
        )

    @mock.patch.object(agent_control.time, "sleep")
    @mock.patch.object(agent_control, "fetch_pr")
    def test_green_ci_waits_for_transient_blocked_state_to_clear(self, fetch_pr, sleep):
        initial = self.pr("blocked")
        clean = self.pr("clean")
        fetch_pr.return_value = clean
        result = agent_control.settle_mergeability_after_success(
            "token", "balamacab/RustIDEAM", 99, "a" * 40, initial
        )
        self.assertEqual(result["mergeable_state"], "clean")
        fetch_pr.assert_called_once()
        sleep.assert_called_once_with(agent_control.MERGE_STATE_RECHECK_SECONDS)

    @mock.patch.object(agent_control, "request_resume")
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control.time, "sleep")
    @mock.patch.object(agent_control, "fetch_pr")
    def test_permanently_blocked_green_ci_requests_durable_recovery(
        self, fetch_pr, sleep, post_comment, request_resume
    ):
        blocked = self.pr("blocked")
        fetch_pr.return_value = blocked
        request_resume.return_value = {"dispatched": True}
        result = agent_control.handle_lifecycle(
            "token", "balamacab/RustIDEAM", 99, "success", "a" * 40
        )
        self.assertTrue(result["dispatched"])
        req = request_resume.call_args.args[1]
        self.assertEqual(req.reason, "CHECKS_OUTDATED")
        self.assertEqual(fetch_pr.call_count, agent_control.MERGE_STATE_RECHECKS)
        self.assertEqual(
            sleep.call_count,
            agent_control.MERGE_STATE_RECHECKS - 1,
        )

    @mock.patch.object(agent_control, "request_resume")
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control.time, "sleep")
    @mock.patch.object(agent_control, "fetch_pr")
    def test_head_change_while_settling_never_merges_stale_head(
        self, fetch_pr, sleep, post_comment, request_resume
    ):
        initial = self.pr("blocked")
        changed = self.pr("clean", head_sha="c" * 40)
        fetch_pr.side_effect = [initial, changed]
        request_resume.return_value = {"dispatched": True}
        result = agent_control.handle_lifecycle(
            "token", "balamacab/RustIDEAM", 99, "success", "a" * 40
        )
        self.assertTrue(result["dispatched"])
        req = request_resume.call_args.args[1]
        self.assertEqual(req.reason, "NEEDS_REBASE")
        self.assertEqual(req.head_sha, "c" * 40)

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
