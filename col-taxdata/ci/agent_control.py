#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from policy import PolicyError, closing_issue_number, parse_metadata

API = "https://api.github.com"
RESUME_MARKER = "<!-- col-taxdata-agent-resume:"
STATE_MARKER = "<!-- col-taxdata-agent-state:"
BLOCKER_MARKER = "<!-- col-taxdata-agent-blocker:"
MAX_RETRIES = 3
RESUME_SCHEMA_VERSION = 2
GITHUB_REPOSITORY_DISPATCH_MAX_PROPERTIES = 10
MERGE_READY_STATES = {"clean", "has_hooks", "unstable"}
MERGE_STATE_RECHECKS = 4
MERGE_STATE_RECHECK_SECONDS = 2
RESUME_EVENT = "col-taxdata-agent-resume"
CONVERGENCE_EVENT = "col-taxdata-convergence"
CI_WORKFLOW_REF = "main"

class ApiError(RuntimeError):
    pass

@dataclass(frozen=True)
class ResumeRequest:
    repository: str
    issue_number: int
    pr_number: int
    branch: str
    head_sha: str
    base_sha: str
    reason: str
    semantic_domains: list[str]
    attempt: int
    max_attempts: int = MAX_RETRIES
    automatic_update: bool = False


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
            "User-Agent": "col-taxdata-autonomous-ci",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ApiError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def build_resume_payload(req: ResumeRequest) -> dict[str, Any]:
    payload = {
        "schema_version": RESUME_SCHEMA_VERSION,
        "repository": req.repository,
        "issue_number": req.issue_number,
        "pr_number": req.pr_number,
        "branch": req.branch,
        "head_sha": req.head_sha,
        "base_sha": req.base_sha,
        "reason": req.reason,
        "semantic_domains": req.semantic_domains,
        "retry": {
            "attempt": req.attempt,
            "max_attempts": req.max_attempts,
            "automatic_update": req.automatic_update,
        },
    }
    if len(payload) > GITHUB_REPOSITORY_DISPATCH_MAX_PROPERTIES:
        raise PolicyError(
            "resume client_payload exceeds GitHub repository_dispatch "
            f"top-level property limit: {len(payload)} > "
            f"{GITHUB_REPOSITORY_DISPATCH_MAX_PROPERTIES}"
        )
    return payload


def marker_payload(body: str, marker: str) -> dict[str, Any] | None:
    start = body.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = body.find("-->", start)
    if end < 0:
        return None
    try:
        value = json.loads(body[start:end].strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def retry_count(comments: list[dict[str, Any]], reason: str, head_sha: str) -> int:
    count = 0
    for comment in comments:
        payload = marker_payload(str(comment.get("body") or ""), RESUME_MARKER)
        if payload and payload.get("reason") == reason and payload.get("head_sha") == head_sha:
            count += 1
    return count


def state_comment(state: str, **details: Any) -> str:
    payload = {"state": state, **details}
    return f"{STATE_MARKER} {json.dumps(payload, sort_keys=True, separators=(',', ':'))} -->\nAgent state: `{state}`."


def resume_comment(payload: dict[str, Any]) -> str:
    marker = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    retry = payload.get("retry")
    if not isinstance(retry, dict):
        retry = payload
    return (
        f"{RESUME_MARKER} {marker} -->\n"
        f"Autonomous resume requested: `{payload['reason']}` "
        f"(attempt {retry['attempt']}/{retry['max_attempts']}, head `{payload['head_sha'][:12]}`)."
    )


def post_issue_comment(token: str, repo: str, issue: int, body: str) -> None:
    request_json(token, "POST", f"/repos/{repo}/issues/{issue}/comments", {"body": body})


def fetch_comments(token: str, repo: str, issue: int) -> list[dict[str, Any]]:
    data = request_json(token, "GET", f"/repos/{repo}/issues/{issue}/comments?per_page=100")
    return data if isinstance(data, list) else []


def create_blocker(token: str, req: ResumeRequest) -> dict[str, Any]:
    comments = fetch_comments(token, req.repository, req.issue_number)
    key = f"{req.reason}:{req.head_sha}"
    for comment in comments:
        payload = marker_payload(str(comment.get("body") or ""), BLOCKER_MARKER)
        if payload and payload.get("key") == key:
            return {"html_url": payload.get("url"), "number": payload.get("number"), "reused": True}
    body = (
        f"{BLOCKER_MARKER} {json.dumps({'key': key}, separators=(',', ':'))} -->\n"
        f"Autonomous recovery for #{req.issue_number} / PR #{req.pr_number} exhausted "
        f"{req.max_attempts} retries for `{req.reason}` at `{req.head_sha}`.\n\n"
        "This blocker requires a focused repository decision or corrective implementation. "
        "Unsafe merge remains blocked; no production/runtime mutation is authorized."
    )
    issue = request_json(token, "POST", f"/repos/{req.repository}/issues", {
        "title": f"[BLOCKER] Issue #{req.issue_number}: {req.reason} retry exhaustion",
        "body": body,
    })
    note = {
        "key": key,
        "number": issue.get("number"),
        "url": issue.get("html_url"),
    }
    post_issue_comment(
        token,
        req.repository,
        req.issue_number,
        f"{BLOCKER_MARKER} {json.dumps(note, separators=(',', ':'))} -->\n"
        f"Retry budget exhausted; focused blocker created: {issue.get('html_url')}",
    )
    return issue


def request_resume(token: str, req: ResumeRequest) -> dict[str, Any]:
    comments = fetch_comments(token, req.repository, req.issue_number)
    prior = retry_count(comments, req.reason, req.head_sha)
    attempt = prior + 1
    if attempt > req.max_attempts:
        blocked = ResumeRequest(**{**req.__dict__, "attempt": attempt})
        blocker = create_blocker(token, blocked)
        post_issue_comment(token, req.repository, req.issue_number, state_comment(
            "BLOCKED", reason=req.reason, head_sha=req.head_sha, blocker=blocker.get("html_url")
        ))
        return {"dispatched": False, "blocked": True, "attempt": attempt, "blocker": blocker}
    actual = ResumeRequest(**{**req.__dict__, "attempt": attempt})
    payload = build_resume_payload(actual)
    post_issue_comment(token, req.repository, req.issue_number, resume_comment(payload))
    request_json(token, "POST", f"/repos/{req.repository}/dispatches", {
        "event_type": RESUME_EVENT,
        "client_payload": payload,
    })
    return {"dispatched": True, "blocked": False, "attempt": attempt, "payload": payload}


def fetch_pr(token: str, repo: str, pr_number: int) -> dict[str, Any]:
    for _ in range(3):
        pr = request_json(token, "GET", f"/repos/{repo}/pulls/{pr_number}")
        if pr.get("mergeable") is not None:
            return pr
        time.sleep(2)
    return pr


def settle_mergeability_after_success(
    token: str,
    repo: str,
    pr_number: int,
    expected_head_sha: str,
    initial_pr: dict[str, Any],
) -> dict[str, Any]:
    """Boundedly wait for GitHub's mergeability state to reflect a just-finished CI run."""
    pr = initial_pr
    for attempt in range(MERGE_STATE_RECHECKS):
        head_sha = str((pr.get("head") or {}).get("sha") or "")
        mergeable = pr.get("mergeable")
        state = str(pr.get("mergeable_state") or "unknown")
        if head_sha != expected_head_sha:
            return pr
        if not (mergeable is True and state == "blocked"):
            return pr
        if attempt + 1 >= MERGE_STATE_RECHECKS:
            return pr
        time.sleep(MERGE_STATE_RECHECK_SECONDS)
        pr = fetch_pr(token, repo, pr_number)
    return pr


def pr_context(pr: dict[str, Any]) -> tuple[int, dict[str, Any], str, str, str]:
    body = str(pr.get("body") or "")
    issue = closing_issue_number(body)
    metadata = parse_metadata(body)
    branch = str((pr.get("head") or {}).get("ref") or "")
    head_sha = str((pr.get("head") or {}).get("sha") or "")
    base_sha = str((pr.get("base") or {}).get("sha") or "")
    return issue, metadata, branch, head_sha, base_sha


def dispatch_ci(token: str, repo: str, branch: str, pr_number: int) -> None:
    # The workflow definition must come from the trusted integration branch.
    # The workflow resolves and checks out the exact PR head itself.
    request_json(token, "POST", f"/repos/{repo}/actions/workflows/col-taxdata-ci.yml/dispatches", {
        "ref": CI_WORKFLOW_REF,
        "inputs": {"pr_number": str(pr_number)},
    })


def dispatch_convergence(token: str, repo: str, *, sha: str, pr: int, issue: int, domains: list[str]) -> None:
    request_json(token, "POST", f"/repos/{repo}/dispatches", {
        "event_type": CONVERGENCE_EVENT,
        "client_payload": {
            "schema_version": 1,
            "sha": sha,
            "pr_number": pr,
            "issue_number": issue,
            "semantic_domains": domains,
        },
    })


def handle_lifecycle(token: str, repo: str, pr_number: int, ci_conclusion: str | None, ci_head_sha: str | None) -> dict[str, Any]:
    pr = fetch_pr(token, repo, pr_number)
    issue, metadata, branch, head_sha, base_sha = pr_context(pr)
    domains = list(metadata["semantic_domains"])
    if ci_conclusion and ci_conclusion != "success":
        req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "CI_FAILED", domains, 0)
        return request_resume(token, req)

    mergeable = pr.get("mergeable")
    state = str(pr.get("mergeable_state") or "unknown")
    if mergeable is False or state == "dirty":
        req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "MERGE_CONFLICT", domains, 0)
        return request_resume(token, req)

    if state == "behind":
        post_issue_comment(token, repo, issue, state_comment("NEEDS_REBASE", pr_number=pr_number, head_sha=head_sha))
        automatic_update = False
        try:
            request_json(token, "PUT", f"/repos/{repo}/pulls/{pr_number}/update-branch", {"expected_head_sha": head_sha})
            automatic_update = True
            time.sleep(2)
            refreshed = fetch_pr(token, repo, pr_number)
            new_branch = str((refreshed.get("head") or {}).get("ref") or branch)
            dispatch_ci(token, repo, new_branch, pr_number)
        except ApiError:
            automatic_update = False
        req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "NEEDS_REBASE", domains, 0, automatic_update=automatic_update)
        return request_resume(token, req)

    if ci_conclusion == "success":
        if ci_head_sha and ci_head_sha != head_sha:
            req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "NEEDS_REBASE", domains, 0)
            return request_resume(token, req)

        if ci_head_sha and mergeable is True and state == "blocked":
            pr = settle_mergeability_after_success(token, repo, pr_number, ci_head_sha, pr)
            issue, metadata, branch, head_sha, base_sha = pr_context(pr)
            domains = list(metadata["semantic_domains"])
            mergeable = pr.get("mergeable")
            state = str(pr.get("mergeable_state") or "unknown")
            if head_sha != ci_head_sha:
                req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "NEEDS_REBASE", domains, 0)
                return request_resume(token, req)
            if mergeable is True and state == "blocked":
                post_issue_comment(
                    token,
                    repo,
                    issue,
                    state_comment(
                        "CHECKS_OUTDATED",
                        pr_number=pr_number,
                        head_sha=head_sha,
                        mergeable_state=state,
                    ),
                )
                req = ResumeRequest(
                    repo,
                    issue,
                    pr_number,
                    branch,
                    head_sha,
                    base_sha,
                    "CHECKS_OUTDATED",
                    domains,
                    0,
                )
                return request_resume(token, req)

        if mergeable is not True or state not in MERGE_READY_STATES:
            return {"merged": False, "waiting": True, "mergeable": mergeable, "mergeable_state": state}
        post_issue_comment(token, repo, issue, state_comment("READY_FOR_MERGE", pr_number=pr_number, head_sha=head_sha))
        result = request_json(token, "PUT", f"/repos/{repo}/pulls/{pr_number}/merge", {
            "sha": head_sha,
            "merge_method": "squash",
            "commit_title": f"Issue #{issue}: autonomous validated merge",
        })
        if not result.get("merged"):
            req = ResumeRequest(repo, issue, pr_number, branch, head_sha, base_sha, "NEEDS_REBASE", domains, 0)
            return request_resume(token, req)
        merge_sha = str(result.get("sha") or "")
        post_issue_comment(token, repo, issue, state_comment("MERGED", pr_number=pr_number, merge_sha=merge_sha))
        dispatch_convergence(token, repo, sha=merge_sha, pr=pr_number, issue=issue, domains=domains)
        if branch.startswith(f"agent/issue-{issue}-"):
            encoded = urllib.parse.quote(branch, safe="")
            try:
                request_json(token, "DELETE", f"/repos/{repo}/git/refs/heads/{encoded}")
            except ApiError:
                pass
        return {"merged": True, "merge_sha": merge_sha, "issue_number": issue}

    if ci_conclusion is None:
        post_issue_comment(
            token,
            repo,
            issue,
            state_comment("CI_VALIDATING", pr_number=pr_number, head_sha=head_sha),
        )
        dispatch_ci(token, repo, branch, pr_number)
        return {
            "merged": False,
            "ci_dispatched": True,
            "head_sha": head_sha,
            "mergeable": mergeable,
            "mergeable_state": state,
        }

    return {"merged": False, "waiting": True, "mergeable": mergeable, "mergeable_state": state}


def cmd_lifecycle(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    result = handle_lifecycle(token, args.repo, args.pr, args.ci_conclusion, args.ci_head_sha)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    domains = json.loads(args.semantic_domains)
    req = ResumeRequest(args.repo, args.issue, args.pr, args.branch, args.head_sha, args.base_sha, args.reason, domains, 0)
    result = request_resume(token, req)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded autonomous PR lifecycle control")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("lifecycle")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--ci-conclusion")
    p.add_argument("--ci-head-sha")
    p.set_defaults(func=cmd_lifecycle)
    p = sub.add_parser("request-resume")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--reason", required=True, choices=["NEEDS_REBASE", "MERGE_CONFLICT", "CI_FAILED", "CHECKS_OUTDATED", "SEMANTIC_REVALIDATION_REQUIRED"])
    p.add_argument("--semantic-domains", required=True)
    p.set_defaults(func=cmd_resume)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (ApiError, PolicyError) as exc:
        print(f"CONTROL FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
