#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API = "https://api.github.com"
RULESET_NAME = "col-taxdata-autonomous-main"
REQUIRED_CONTEXT = "CI Gate"

class GovernanceError(RuntimeError):
    pass


def desired_ruleset() -> dict[str, Any]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": ["~DEFAULT_BRANCH"],
                "exclude": [],
            }
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": REQUIRED_CONTEXT}],
                },
            },
        ],
    }


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
            "User-Agent": "col-taxdata-repository-governance",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise GovernanceError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
    return json.loads(raw.decode("utf-8")) if raw else None


def find_ruleset(rulesets: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in rulesets if item.get("name") == RULESET_NAME), None)


def verify_ruleset(ruleset: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if ruleset.get("enforcement") != "active":
        problems.append("ruleset is not active")
    conditions = ruleset.get("conditions") or {}
    includes = ((conditions.get("ref_name") or {}).get("include") or [])
    if "~DEFAULT_BRANCH" not in includes:
        problems.append("ruleset does not target the default branch")
    rules = {rule.get("type"): rule for rule in ruleset.get("rules") or []}
    if "non_fast_forward" not in rules:
        problems.append("force-push protection is missing")
    pr_rule = rules.get("pull_request") or {}
    approvals = (pr_rule.get("parameters") or {}).get("required_approving_review_count")
    if approvals != 0:
        problems.append("pull-request rule must require zero human approvals")
    status_rule = rules.get("required_status_checks") or {}
    params = status_rule.get("parameters") or {}
    if params.get("strict_required_status_checks_policy") is not True:
        problems.append("required status checks are not strict/current-base")
    contexts = [item.get("context") for item in params.get("required_status_checks") or []]
    if REQUIRED_CONTEXT not in contexts:
        problems.append(f"required status context {REQUIRED_CONTEXT!r} is missing")
    if ruleset.get("bypass_actors"):
        problems.append("ruleset unexpectedly contains bypass actors")
    return problems


def token() -> str:
    value = os.environ.get("GITHUB_ADMIN_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not value:
        raise GovernanceError("GITHUB_ADMIN_TOKEN (or GH_TOKEN) is required for repository governance mutation")
    return value


def list_rulesets(auth: str, repo: str) -> list[dict[str, Any]]:
    result = request_json(auth, "GET", f"/repos/{repo}/rulesets?per_page=100")
    return result if isinstance(result, list) else []


def cmd_plan(args: argparse.Namespace) -> int:
    auth = token()
    current = find_ruleset(list_rulesets(auth, args.repo))
    print(json.dumps({"current": current, "desired": desired_ruleset()}, indent=2, sort_keys=True))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    auth = token()
    current = find_ruleset(list_rulesets(auth, args.repo))
    desired = desired_ruleset()
    if current:
        result = request_json(auth, "PUT", f"/repos/{args.repo}/rulesets/{current['id']}", desired)
    else:
        result = request_json(auth, "POST", f"/repos/{args.repo}/rulesets", desired)
    problems = verify_ruleset(result)
    if problems:
        raise GovernanceError("applied ruleset failed verification: " + "; ".join(problems))
    print(json.dumps({"result": "PASS", "ruleset_id": result.get("id"), "name": result.get("name")}, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    auth = token()
    current = find_ruleset(list_rulesets(auth, args.repo))
    if not current:
        raise GovernanceError(f"ruleset {RULESET_NAME!r} not found")
    full = request_json(auth, "GET", f"/repos/{args.repo}/rulesets/{current['id']}")
    problems = verify_ruleset(full)
    if problems:
        raise GovernanceError("; ".join(problems))
    print(json.dumps({"result": "PASS", "ruleset_id": full.get("id"), "name": full.get("name")}, indent=2))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    auth = token()
    current = find_ruleset(list_rulesets(auth, args.repo))
    if not current:
        print(json.dumps({"deleted": False, "reason": "not-found"}))
        return 0
    request_json(auth, "DELETE", f"/repos/{args.repo}/rulesets/{current['id']}")
    print(json.dumps({"deleted": True, "ruleset_id": current["id"]}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan/apply/verify the autonomous main-branch ruleset")
    parser.add_argument("command", choices=["plan", "apply", "verify", "delete"])
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    try:
        return {
            "plan": cmd_plan,
            "apply": cmd_apply,
            "verify": cmd_verify,
            "delete": cmd_delete,
        }[args.command](args)
    except GovernanceError as exc:
        print(f"GOVERNANCE FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
