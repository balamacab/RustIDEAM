#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from policy import PolicyError, parse_metadata

API = "https://api.github.com"
STATUS_CONTEXT = "Convergence Gate"
CORRECTIVE_MARKER = "<!-- col-taxdata-convergence-corrective:"

class ConvergenceError(RuntimeError):
    pass


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
            "User-Agent": "col-taxdata-convergence",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ConvergenceError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
    return json.loads(raw.decode("utf-8")) if raw else None


def overlap_with_prs(current_domains: list[str], prs: list[dict[str, Any]], current_pr: int) -> list[dict[str, Any]]:
    current = set(current_domains)
    overlaps: list[dict[str, Any]] = []
    for pr in prs:
        if int(pr.get("number") or 0) == current_pr or not pr.get("merged_at"):
            continue
        try:
            metadata = parse_metadata(str(pr.get("body") or ""))
        except PolicyError:
            continue
        intersection = sorted(current.intersection(metadata["semantic_domains"]))
        if intersection:
            overlaps.append({"pr_number": int(pr["number"]), "semantic_domains": intersection})
    return overlaps


def set_status(token: str, repo: str, sha: str, state: str, description: str) -> None:
    request_json(token, "POST", f"/repos/{repo}/statuses/{sha}", {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description[:140],
    })


def corrective_issue(token: str, repo: str, sha: str, pr: int, issue: int, details: str) -> dict[str, Any]:
    key = sha.lower()
    issues = request_json(token, "GET", f"/repos/{repo}/issues?state=all&per_page=100")
    if isinstance(issues, list):
        for item in issues:
            body = str(item.get("body") or "")
            if f'"sha":"{key}"' in body and CORRECTIVE_MARKER in body:
                return item
    marker = json.dumps({"sha": key, "source_pr": pr, "source_issue": issue}, separators=(",", ":"))
    body = (
        f"{CORRECTIVE_MARKER} {marker} -->\n"
        f"Post-merge convergence failed for `{sha}` after PR #{pr} / issue #{issue}.\n\n"
        f"Validation detail: {details}\n\n"
        "Downstream readiness remains blocked by the failing `Convergence Gate` commit status. "
        "The merged history is preserved; any revert or forward fix must be an explicit, separately validated change."
    )
    return request_json(token, "POST", f"/repos/{repo}/issues", {
        "title": f"[CORRECTIVE][CI] Convergence failure at {sha[:12]}",
        "body": body,
    })


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def auth() -> str:
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        raise ConvergenceError("GITHUB_TOKEN is required")
    return token


def cmd_prepare(args: argparse.Namespace) -> int:
    token = auth()
    domains = json.loads(args.semantic_domains)
    prs = request_json(token, "GET", f"/repos/{args.repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30")
    overlaps = overlap_with_prs(domains, prs if isinstance(prs, list) else [], args.pr)
    set_status(token, args.repo, args.sha, "pending", "post-merge convergence validation in progress")
    write_output("semantic_overlap", str(bool(overlaps)).lower())
    write_output("overlaps_json", json.dumps(overlaps, separators=(",", ":")))
    print(json.dumps({"semantic_overlap": bool(overlaps), "overlaps": overlaps}, indent=2))
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    token = auth()
    if args.result == "success":
        set_status(token, args.repo, args.sha, "success", "post-merge convergence validation passed")
        print(json.dumps({"result": "PASS", "sha": args.sha}))
        return 0
    set_status(token, args.repo, args.sha, "failure", "post-merge convergence validation failed")
    corrective = corrective_issue(token, args.repo, args.sha, args.pr, args.issue, args.details)
    print(json.dumps({"result": "FAIL", "corrective_issue": corrective.get("html_url")}, indent=2))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-merge semantic/invariant convergence control")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--repo", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--semantic-domains", required=True)
    p.set_defaults(func=cmd_prepare)
    p = sub.add_parser("finalize")
    p.add_argument("--repo", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--result", choices=["success", "failure"], required=True)
    p.add_argument("--details", default="full integration/invariant suite failed")
    p.set_defaults(func=cmd_finalize)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (ConvergenceError, PolicyError, json.JSONDecodeError) as exc:
        print(f"CONVERGENCE FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

[executed on device: morichalserver (2bfaa62f-23ff-40e5-9fc7-7c1a7d28b1fc)]