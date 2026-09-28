from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CI_DIR = ROOT / "ci"
sys.path.insert(0, str(CI_DIR))

import agent_control  # noqa: E402
import convergence  # noqa: E402
import policy  # noqa: E402


def metadata(*, mode: str = "convergence", issue: int | None = None) -> dict:
    value = {
        "base_sha": "b" * 40,
        "parallel_safe": False,
        "semantic_domains": ["repository-automation"],
        "likely_touched": ["col-taxdata/**"],
        "depends_on": [],
        "completion_mode": mode,
    }
    if issue is not None:
        value["issue_number"] = issue
    return value


def normal_pr_body(issue: int = 231) -> str:
    return (
        f"Fixes #{issue}\n\n"
        "<!-- col-taxdata-agent-metadata: "
        + json.dumps(metadata())
        + " -->"
    )


def post_merge_pr_body(issue: int = 231) -> str:
    return (
        f"Tracks #{issue}\n\n"
        "<!-- col-taxdata-agent-metadata: "
        + json.dumps(metadata(mode="post_merge_acceptance", issue=issue))
        + " -->"
    )


class CompletionOwnershipPolicyTests(unittest.TestCase):
    def test_legacy_convergence_completion_still_uses_closing_target(self):
        self.assertEqual(policy.owning_issue_number(normal_pr_body()), 231)

    def test_post_merge_acceptance_owns_issue_without_github_closing_syntax(self):
        body = post_merge_pr_body()
        self.assertEqual(policy.owning_issue_number(body), 231)
        self.assertEqual(
            policy.parse_metadata(body)["completion_mode"],
            "post_merge_acceptance",
        )

    def test_post_merge_acceptance_rejects_premature_closing_syntax(self):
        body = (
            "Fixes #231\n\n"
            "<!-- col-taxdata-agent-metadata: "
            + json.dumps(metadata(mode="post_merge_acceptance", issue=231))
            + " -->"
        )
        with self.assertRaises(policy.PolicyError):
            policy.owning_issue_number(body)

    def test_post_merge_acceptance_requires_explicit_issue_number(self):
        body = (
            "Tracks #231\n\n"
            "<!-- col-taxdata-agent-metadata: "
            + json.dumps(metadata(mode="post_merge_acceptance"))
            + " -->"
        )
        with self.assertRaises(policy.PolicyError):
            policy.parse_metadata(body)

    def test_convergence_metadata_issue_must_match_closing_target(self):
        body = (
            "Fixes #231\n\n"
            "<!-- col-taxdata-agent-metadata: "
            + json.dumps({**metadata(), "issue_number": 232})
            + " -->"
        )
        with self.assertRaises(policy.PolicyError):
            policy.owning_issue_number(body)


class AgentLifecycleTests(unittest.TestCase):
    def pr(self, *, mode: str = "convergence") -> dict:
        body = normal_pr_body() if mode == "convergence" else post_merge_pr_body()
        return {
            "body": body,
            "head": {
                "ref": "agent/issue-231-developer-lifecycle-completion",
                "sha": "a" * 40,
            },
            "base": {"sha": "b" * 40},
            "mergeable": True,
            "mergeable_state": "clean",
        }

    def test_agent_context_preserves_post_merge_owning_issue(self):
        issue, meta, branch, head, base = agent_control.pr_context(
            self.pr(mode="post_merge_acceptance")
        )
        self.assertEqual(issue, 231)
        self.assertEqual(meta["completion_mode"], "post_merge_acceptance")
        self.assertEqual(branch, "agent/issue-231-developer-lifecycle-completion")
        self.assertEqual(head, "a" * 40)
        self.assertEqual(base, "b" * 40)

    @mock.patch.object(agent_control, "dispatch_convergence")
    @mock.patch.object(agent_control, "post_issue_comment")
    @mock.patch.object(agent_control, "request_json")
    @mock.patch.object(agent_control, "fetch_pr")
    def test_merge_is_nonterminal_and_dispatches_convergence(
        self, fetch_pr, request_json, post_comment, dispatch_convergence
    ):
        fetch_pr.return_value = self.pr(mode="post_merge_acceptance")
        request_json.return_value = {"merged": True, "sha": "c" * 40}
        result = agent_control.handle_lifecycle(
            "token",
            "balamacab/RustIDEAM",
            999,
            "success",
            "a" * 40,
        )
        self.assertTrue(result["merged"])
        states = [call.args[3] for call in post_comment.call_args_list]
        self.assertTrue(any("READY_FOR_MERGE" in body for body in states))
        self.assertTrue(any("MERGED" in body for body in states))
        self.assertFalse(any('"state":"DONE"' in body for body in states))
        dispatch_convergence.assert_called_once()


class ConvergenceCompletionTests(unittest.TestCase):
    @mock.patch.object(convergence, "set_status")
    @mock.patch.object(convergence, "reconcile_stranded_merged_issues", return_value=[])
    @mock.patch.object(convergence, "close_issue_completed")
    @mock.patch.object(convergence, "mark_post_merge_acceptance_pending")
    @mock.patch.object(convergence, "request_json")
    @mock.patch.object(convergence, "auth", return_value="token")
    def test_convergence_success_leaves_post_merge_acceptance_issue_open(
        self,
        auth,
        request_json,
        mark_pending,
        close_issue,
        reconcile,
        set_status,
    ):
        request_json.return_value = {"body": post_merge_pr_body()}
        args = type(
            "Args",
            (),
            {
                "result": "success",
                "repo": "balamacab/RustIDEAM",
                "issue": 231,
                "pr": 999,
                "sha": "c" * 40,
                "details": "",
            },
        )()
        self.assertEqual(convergence.cmd_finalize(args), 0)
        mark_pending.assert_called_once()
        close_issue.assert_not_called()
        set_status.assert_called_once()

    @mock.patch.object(convergence, "set_status")
    @mock.patch.object(convergence, "reconcile_stranded_merged_issues", return_value=[])
    @mock.patch.object(convergence, "close_issue_completed")
    @mock.patch.object(convergence, "mark_post_merge_acceptance_pending")
    @mock.patch.object(convergence, "request_json")
    @mock.patch.object(convergence, "auth", return_value="token")
    def test_convergence_success_closes_normal_issue(
        self,
        auth,
        request_json,
        mark_pending,
        close_issue,
        reconcile,
        set_status,
    ):
        request_json.return_value = {"body": normal_pr_body()}
        args = type(
            "Args",
            (),
            {
                "result": "success",
                "repo": "balamacab/RustIDEAM",
                "issue": 231,
                "pr": 999,
                "sha": "c" * 40,
                "details": "",
            },
        )()
        self.assertEqual(convergence.cmd_finalize(args), 0)
        close_issue.assert_called_once()
        mark_pending.assert_not_called()

    @mock.patch.object(convergence, "is_ancestor_of_validated_sha")
    @mock.patch.object(convergence, "close_issue_completed")
    @mock.patch.object(convergence, "request_json")
    def test_stranded_reconciliation_never_closes_post_merge_acceptance(
        self, request_json, close_issue, ancestor
    ):
        request_json.return_value = [
            {
                "number": 999,
                "merged_at": "2026-09-28T04:00:00Z",
                "merge_commit_sha": "c" * 40,
                "body": post_merge_pr_body(),
            }
        ]
        recovered = convergence.reconcile_stranded_merged_issues(
            "token",
            "balamacab/RustIDEAM",
            validated_sha="d" * 40,
            current_pr=1000,
        )
        self.assertEqual(recovered, [])
        close_issue.assert_not_called()
        ancestor.assert_not_called()


class DurableContractTests(unittest.TestCase):
    def test_scheduled_developer_contract_marks_ci_and_merge_nonterminal(self):
        text = (ROOT / "docs" / "scheduled-case-validation-swarm.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("CI_VALIDATING", text)
        self.assertIn("pending convergence", text)
        self.assertIn("are **not** terminal", text)
        self.assertIn("next activation resumes it", text)


if __name__ == "__main__":
    unittest.main()
