from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))

from agent_control import (
    build_dispatch_payload,
    count_attempts,
    make_attempt_record,
    marker,
    request_resume,
)


class FakeAPI:
    def __init__(self, comments=None):
        self._comments = comments or []
        self.dispatched = []
        self.comments_posted = []
        self.blockers = []

    def comments(self, issue):
        return self._comments

    def dispatch(self, payload):
        self.dispatched.append(payload)

    def comment(self, issue, body):
        self.comments_posted.append((issue, body))

    def create_blocker(self, **kwargs):
        self.blockers.append(kwargs)
        return {"number": 901}


class AgentControlTests(unittest.TestCase):
    def test_dispatch_payload_is_stable_and_issue_owned(self):
        payload = build_dispatch_payload(
            repository="balamacab/RustIDEAM",
            issue=28,
            pr=44,
            head_sha="a" * 40,
            reason="NEEDS_REBASE",
            attempt=2,
            semantic_domains=["repository-automation"],
        )
        self.assertEqual(payload["event_type"], "agent.resume.requested")
        client = payload["client_payload"]
        self.assertEqual(client["issue_number"], 28)
        self.assertEqual(client["pull_request_number"], 44)
        self.assertEqual(client["attempt"], 2)
        self.assertEqual(client["required_action"], "reconcile_same_pr_against_current_main")

    def test_retry_counter_scoped_to_reason_and_head(self):
        record = make_attempt_record(
            issue=28, pr=44, head_sha="a" * 40, reason="CI_FAILED", attempt=2
        )
        comments = [{"body": marker(record)}]
        self.assertEqual(
            count_attempts(comments, issue=28, head_sha="a" * 40, reason="CI_FAILED"),
            2,
        )
        self.assertEqual(
            count_attempts(comments, issue=28, head_sha="b" * 40, reason="CI_FAILED"),
            0,
        )
        self.assertEqual(
            count_attempts(comments, issue=28, head_sha="a" * 40, reason="NEEDS_REBASE"),
            0,
        )

    def test_resume_dispatches_below_bound(self):
        api = FakeAPI()
        state = request_resume(
            api,
            repo="balamacab/RustIDEAM",
            issue=28,
            pr=44,
            head_sha="a" * 40,
            reason="CI_FAILED",
            semantic_domains=["ci-governance"],
            max_retries=3,
        )
        self.assertEqual(state, "dispatched")
        self.assertEqual(len(api.dispatched), 1)
        self.assertFalse(api.blockers)

    def test_retry_exhaustion_creates_blocker_and_no_dispatch(self):
        comments = []
        for attempt in range(1, 4):
            comments.append(
                {
                    "body": marker(
                        make_attempt_record(
                            issue=28,
                            pr=44,
                            head_sha="a" * 40,
                            reason="MERGE_CONFLICT",
                            attempt=attempt,
                        )
                    )
                }
            )
        api = FakeAPI(comments)
        state = request_resume(
            api,
            repo="balamacab/RustIDEAM",
            issue=28,
            pr=44,
            head_sha="a" * 40,
            reason="MERGE_CONFLICT",
            semantic_domains=["ci-governance"],
            max_retries=3,
        )
        self.assertEqual(state, "blocked")
        self.assertEqual(len(api.blockers), 1)
        self.assertFalse(api.dispatched)
        self.assertIn("#901", api.comments_posted[0][1])


if __name__ == "__main__":
    unittest.main()
