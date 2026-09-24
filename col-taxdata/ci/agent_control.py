#!/usr/bin/env python3
"""Bounded autonomous agent resume dispatcher for Issue-owned pull requests."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib import error, request

MARKER_RE = re.compile(r"<!--\s*agent-resume-attempt:(\{.*?\})\s*-->", re.DOTALL)
DEFAULT_MAX_RETRIES = 3
ALLOWED_REASONS = {
    "NEEDS_REBASE",
    "MERGE_CONFLICT",
    "CI_FAILED",
    "SEMANTIC_REVALIDATION_REQUIRED",
}


def make_attempt_record(*, issue: int, pr: int, head_sha: str, reason: str, attempt: int) -> dict:
    if reason not in ALLOWED_REASONS:
        raise ValueError(f"unsupported resume reason: {reason}")
    if attempt < 1:
        raise ValueError("attempt must be positive")
    return {"issue": issue, "pr": pr, "head_sha": head_sha, "reason": reason, "attempt": attempt}


def marker(record: dict) -> str:
    return "<!-- agent-resume-attempt:" + json.dumps(
        record, sort_keys=True, separators=(",", ":")
    ) + " -->"


def count_attempts(
    comments: list[dict[str, Any]], *, issue: int, head_sha: str, reason: str
) -> int:
    """Count durable attempts for the exact failure reason and immutable head."""
    highest = 0
    for comment in comments:
        body = str(comment.get("body") or "")
        for match in MARKER_RE.finditer(body):
            try:
                record = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if (
                record.get("issue") == issue
                and record.get("head_sha") == head_sha
                and record.get("reason") == reason
                and isinstance(record.get("attempt"), int)
            ):
                highest = max(highest, record["attempt"])
    return highest


def build_dispatch_payload(
    *,
    repository: str,
    issue: int,
    pr: int,
    head_sha: str,
    reason: str,
    attempt: int,
    semantic_domains: list[str],
) -> dict:
    """Build the stable repository_dispatch contract consumed by orchestration."""
    return {
        "event_type": "agent.resume.requested",
        "client_payload": {
            "schema_version": 1,
            "repository": repository,
            "issue_number": issue,
            "pull_request_number": pr,
            "head_sha": head_sha,
            "reason": reason,
            "attempt": attempt,
            "semantic_domains": semantic_domains,
            "required_action": "reconcile_same_pr_against_current_main",
        },
    }


class GitHubAPI:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req = request.Request(
            f"https://api.github.com/repos/{self.repo}{path}",
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "col-taxdata-autonomous-agent-control",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API {method} {path} failed: {exc.code} {detail}"
            ) from exc

    def comments(self, issue: int) -> list[dict]:
        return self.call("GET", f"/issues/{issue}/comments?per_page=100") or []

    def comment(self, issue: int, body: str) -> None:
        self.call("POST", f"/issues/{issue}/comments", {"body": body})

    def dispatch(self, payload: dict) -> None:
        self.call("POST", "/dispatches", payload)

    def create_blocker(self, *, issue: int, pr: int, reason: str, head_sha: str) -> dict:
        title = f"[BLOCKER][Issue #{issue}] Autonomous recovery exhausted: {reason}"
        body = (
            f"Automatically created after bounded recovery attempts for Issue #{issue}.\n\n"
            f"- Pull request: #{pr}\n"
            f"- Failure state: {reason}\n"
            f"- Head SHA: {head_sha}\n\n"
            "This blocker records a deterministic no-progress condition. "
            "The original issue and PR stay open and unsafe merge remains prohibited."
        )
        return self.call("POST", "/issues", {"title": title, "body": body})


def request_resume(
    api: GitHubAPI,
    *,
    repo: str,
    issue: int,
    pr: int,
    head_sha: str,
    reason: str,
    semantic_domains: list[str],
    max_retries: int,
) -> str:
    comments = api.comments(issue)
    previous = count_attempts(
        comments, issue=issue, head_sha=head_sha, reason=reason
    )
    if previous >= max_retries:
        blocker = api.create_blocker(
            issue=issue, pr=pr, reason=reason, head_sha=head_sha
        )
        blocker_number = blocker.get("number", "unknown")
        api.comment(
            issue,
            f"Autonomous recovery BLOCKED after {previous} attempts for {reason} "
            f"at {head_sha}. Corrective issue: #{blocker_number}.",
        )
        return "blocked"

    attempt = previous + 1
    record = make_attempt_record(
        issue=issue, pr=pr, head_sha=head_sha, reason=reason, attempt=attempt
    )
    payload = build_dispatch_payload(
        repository=repo,
        issue=issue,
        pr=pr,
        head_sha=head_sha,
        reason=reason,
        attempt=attempt,
        semantic_domains=semantic_domains,
    )
    api.dispatch(payload)
    api.comment(
        issue,
        marker(record)
        + f"\nAutonomous resume requested: {reason}, attempt {attempt}/{max_retries}, "
        f"PR #{pr}, head {head_sha}.",
    )
    return "dispatched"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--reason", choices=sorted(ALLOWED_REASONS), required=True)
    parser.add_argument("--semantic-domains-json", default="[]")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    if args.max_retries < 1 or args.max_retries > 10:
        print("max-retries must be between 1 and 10", file=sys.stderr)
        return 2

    try:
        domains = json.loads(args.semantic_domains_json)
        if not isinstance(domains, list) or not all(
            isinstance(value, str) for value in domains
        ):
            raise ValueError("semantic domains must be a JSON string array")
        api = GitHubAPI(args.repo, token)
        state = request_resume(
            api,
            repo=args.repo,
            issue=args.issue,
            pr=args.pr,
            head_sha=args.head_sha,
            reason=args.reason,
            semantic_domains=domains,
            max_retries=args.max_retries,
        )
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent-control failure: {exc}", file=sys.stderr)
        return 2

    print(state)
    return 0 if state == "dispatched" else 3


if __name__ == "__main__":
    raise SystemExit(main())
