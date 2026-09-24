from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CI_DIR = ROOT / "ci"
sys.path.insert(0, str(CI_DIR))

import convergence  # noqa: E402


class Issue0032ConvergenceLifecycleTests(unittest.TestCase):
    def test_multiline_dispatch_domains_are_compacted(self):
        raw = '[\n  "case-contracts",\n  "case-validation",\n  "application-interface"\n]'
        self.assertEqual(
            convergence.compact_semantic_domains(raw),
            '["case-contracts","case-validation","application-interface"]',
        )

    def test_semantic_domains_must_be_nonempty_string_array(self):
        for raw in ('{}', '[]', '[1]', '[""]'):
            with self.subTest(raw=raw):
                with self.assertRaises(convergence.ConvergenceError):
                    convergence.parse_semantic_domains(raw)

    @mock.patch.object(convergence, "request_json")
    def test_successful_completion_closes_open_issue_and_records_done(self, request_json):
        request_json.side_effect = [
            {"state": "open"},
            {"state": "closed"},
            {},
        ]
        changed = convergence.close_issue_completed(
            "token",
            "balamacab/RustIDEAM",
            32,
            pr=33,
            convergence_sha="c" * 40,
            original_merge_sha="c" * 40,
            recovered=False,
        )
        self.assertTrue(changed)
        patch = request_json.call_args_list[1]
        self.assertEqual(patch.args[:3], ("token", "PATCH", "/repos/balamacab/RustIDEAM/issues/32"))
        self.assertEqual(patch.args[3]["state"], "closed")
        comment = request_json.call_args_list[2].args[3]["body"]
        self.assertIn('"state":"DONE"', comment)
        self.assertIn('"recovered":false', comment)

    @mock.patch.object(convergence, "request_json")
    def test_closed_issue_completion_is_idempotent(self, request_json):
        request_json.return_value = {"state": "closed"}
        self.assertFalse(
            convergence.close_issue_completed(
                "token",
                "balamacab/RustIDEAM",
                32,
                pr=33,
                convergence_sha="c" * 40,
                original_merge_sha="c" * 40,
                recovered=False,
            )
        )
        self.assertEqual(request_json.call_count, 1)

    @mock.patch.object(convergence, "is_ancestor_of_validated_sha", return_value=True)
    @mock.patch.object(convergence, "issue_reopened_after", return_value=False)
    @mock.patch.object(convergence, "close_issue_completed", return_value=True)
    @mock.patch.object(convergence, "request_json")
    def test_reconcile_recovers_stranded_merged_autonomous_issue(
        self, request_json, close_issue, reopened, ancestor
    ):
        metadata = {
            "base_sha": "a" * 40,
            "parallel_safe": False,
            "semantic_domains": ["case-contracts"],
            "likely_touched": ["col-taxdata/**"],
            "depends_on": [],
        }
        request_json.side_effect = [
            [{
                "number": 31,
                "merged_at": "2026-09-24T04:21:57Z",
                "merge_commit_sha": "b" * 40,
                "body": "Fixes #27\n<!-- col-taxdata-agent-metadata: " + json.dumps(metadata) + " -->",
            }],
            {"state": "open"},
        ]
        recovered = convergence.reconcile_stranded_merged_issues(
            "token",
            "balamacab/RustIDEAM",
            validated_sha="c" * 40,
            current_pr=33,
        )
        self.assertEqual(recovered, [27])
        ancestor.assert_called_once()
        reopened.assert_called_once()
        close_issue.assert_called_once()
        self.assertTrue(close_issue.call_args.kwargs["recovered"])

    @mock.patch.object(convergence, "is_ancestor_of_validated_sha", return_value=True)
    @mock.patch.object(convergence, "issue_reopened_after", return_value=True)
    @mock.patch.object(convergence, "close_issue_completed")
    @mock.patch.object(convergence, "request_json")
    def test_reconcile_does_not_reclose_explicitly_reopened_issue(
        self, request_json, close_issue, reopened, ancestor
    ):
        metadata = {
            "base_sha": "a" * 40,
            "parallel_safe": False,
            "semantic_domains": ["ci-governance"],
            "likely_touched": ["col-taxdata/**"],
            "depends_on": [],
        }
        request_json.side_effect = [
            [{
                "number": 29,
                "merged_at": "2026-09-24T03:48:54Z",
                "merge_commit_sha": "b" * 40,
                "body": "Fixes #28\n<!-- col-taxdata-agent-metadata: " + json.dumps(metadata) + " -->",
            }],
            {"state": "open"},
        ]
        recovered = convergence.reconcile_stranded_merged_issues(
            "token",
            "balamacab/RustIDEAM",
            validated_sha="c" * 40,
            current_pr=33,
        )
        self.assertEqual(recovered, [])
        close_issue.assert_not_called()

    def test_workflow_normalizes_dispatch_json_before_github_output(self):
        text = (ROOT.parent / ".github" / "workflows" / "col-taxdata-convergence.yml").read_text(encoding="utf-8")
        self.assertIn("normalize-domains --semantic-domains", text)
        self.assertNotIn('DOMAINS="$DISPATCH_DOMAINS"', text)
        self.assertIn('echo "semantic_domains=$DOMAINS" >> "$GITHUB_OUTPUT"', text)


if __name__ == "__main__":
    unittest.main()
