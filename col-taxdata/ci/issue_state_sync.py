#!/usr/bin/env python3
"""Project machine-readable Developer lifecycle state into visible GitHub metadata.

GitHub Issues expose OPEN/CLOSED natively; Col-taxdata has a richer operational
lifecycle. This module keeps the single visible `status:blocked` label aligned
with authoritative `col-taxdata-agent-state` comment markers without treating
free-form prose as control input.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.github.com"
STATE_MARKER = "<!-- col-taxdata-agent-state:"
BLOCKED_LABEL = "status:blocked"
BLOCKED_LABEL_COLOR = "B60205"
BLOCKED_LABEL_DESCRIPTION = "Col-taxdata operational lifecycle is BLOCKED"
BLOCKED_STATE = "BLOCKED"
NON_BLOCKED_STATES = {
    "ADMITTED",
    "WORKING",
    "PR_OPEN",
    "CI_VALIDATING",
    "READY_FOR_MERGE",
    "MERGED",
    "POST_MERGE_ACCEPTANCE_PENDING",
    "DONE",
    "NEEDS_REBASE",
    "MERGE_CONFLICT",
    "CI_FAILED",
    "CHECKS_OUTDATED",
    "SEMANTIC_REVALIDATION_REQUIRED",
}
VISIBLE_STATES = NON_BLOCKED_STATES | {BLOCKED_STATE}


class ApiError(RuntimeError):
    """GitHub API failure while projecting lifecycle metadata."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(detail)


def request_json(token: str, method: str, path: str, payload: Any | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "col-taxdata-issue-state-sync",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ApiError(
            exc.code,
            f"GitHub API {method} {path} failed: {exc.code} {detail}",
        ) from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def marker_payload(body: str) -> dict[str, Any] | None:
    """Return one authoritative lifecycle marker payload, never prose-derived state."""
    start = body.find(STATE_MARKER)
    if start < 0:
        return None
    start += len(STATE_MARKER)
    end = body.find("-->", start)
    if end < 0:
        return None
    try:
        value = json.loads(body[start:end].strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    state = value.get("state")
    if not isinstance(state, str) or state not in VISIBLE_STATES:
        return None
    return value


def issue_label_names(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for value in issue.get("labels") or []:
        if isinstance(value, str):
            names.add(value)
        elif isinstance(value, dict) and isinstance(value.get("name"), str):
            names.add(value["name"])
    return names


def ensure_blocked_label(token: str, repo: str) -> None:
    encoded = urllib.parse.quote(BLOCKED_LABEL, safe="")
    try:
        request_json(token, "GET", f"/repos/{repo}/labels/{encoded}")
        return
    except ApiError as exc:
        if exc.status_code != 404:
            raise

    try:
        request_json(
            token,
            "POST",
            f"/repos/{repo}/labels",
            {
                "name": BLOCKED_LABEL,
                "color": BLOCKED_LABEL_COLOR,
                "description": BLOCKED_LABEL_DESCRIPTION,
            },
        )
    except ApiError as exc:
        try:
            request_json(token, "GET", f"/repos/{repo}/labels/{encoded}")
        except ApiError:
            raise exc


def apply_visible_state(token: str, repo: str, issue_number: int, state: str) -> dict[str, Any]:
    """Idempotently project a known lifecycle state to the visible blocked label."""
    if state not in VISIBLE_STATES:
        return {"changed": False, "state": state, "ignored": True}

    issue = request_json(token, "GET", f"/repos/{repo}/issues/{issue_number}")
    if not isinstance(issue, dict):
        raise ApiError(500, f"issue #{issue_number} could not be resolved")
    labels = issue_label_names(issue)

    if state == BLOCKED_STATE:
        if BLOCKED_LABEL in labels:
            return {"changed": False, "state": state, "label": BLOCKED_LABEL}
        ensure_blocked_label(token, repo)
        request_json(
            token,
            "POST",
            f"/repos/{repo}/issues/{issue_number}/labels",
            {"labels": [BLOCKED_LABEL]},
        )
        return {"changed": True, "state": state, "label": BLOCKED_LABEL, "action": "added"}

    if BLOCKED_LABEL not in labels:
        return {"changed": False, "state": state, "label": BLOCKED_LABEL}
    encoded = urllib.parse.quote(BLOCKED_LABEL, safe="")
    request_json(
        token,
        "DELETE",
        f"/repos/{repo}/issues/{issue_number}/labels/{encoded}",
    )
    return {"changed": True, "state": state, "label": BLOCKED_LABEL, "action": "removed"}


def fetch_all_comments(token: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request_json(
            token,
            "GET",
            f"/repos/{repo}/issues/{issue_number}/comments?per_page=100&page={page}",
        )
        if not isinstance(batch, list):
            raise ApiError(500, f"comments for issue #{issue_number} were not a list")
        comments.extend(value for value in batch if isinstance(value, dict))
        if len(batch) < 100:
            break
        page += 1
    return comments


def latest_marker_state(comments: list[dict[str, Any]]) -> str | None:
    """Resolve latest valid marker by GitHub comment id, ignoring arbitrary prose."""
    candidates: list[tuple[int, str]] = []
    for comment in comments:
        payload = marker_payload(str(comment.get("body") or ""))
        if not payload:
            continue
        try:
            comment_id = int(comment.get("id") or 0)
        except (TypeError, ValueError):
            comment_id = 0
        candidates.append((comment_id, str(payload["state"])))
    if not candidates:
        return None
    return max(candidates, key=lambda value: value[0])[1]


def sync_from_comments(token: str, repo: str, issue_number: int) -> dict[str, Any]:
    comments = fetch_all_comments(token, repo, issue_number)
    state = latest_marker_state(comments)
    if state is None:
        return {"changed": False, "ignored": True, "reason": "no lifecycle marker"}
    return apply_visible_state(token, repo, issue_number, state)


def cmd_event(args: argparse.Namespace) -> int:
    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    if issue.get("pull_request"):
        print(json.dumps({"ignored": True, "reason": "pull request comment"}))
        return 0
    issue_number = int(issue.get("number") or 0)
    if issue_number <= 0:
        raise SystemExit("issue_comment event lacks a positive issue number")

    if marker_payload(str(comment.get("body") or "")) is None:
        print(json.dumps({"ignored": True, "reason": "trigger comment has no valid lifecycle marker"}))
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")
    result = sync_from_comments(token, args.repository, issue_number)
    print(json.dumps({"issue": issue_number, **result}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    event = sub.add_parser("event")
    event.add_argument("--repository", required=True)
    event.add_argument("--event", required=True)
    event.set_defaults(func=cmd_event)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
