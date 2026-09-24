#!/usr/bin/env python3
"""Plan, apply and verify autonomous governance for the main branch."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import error, request

RULESET_NAME = "col-taxdata-autonomous-main"
REQUIRED_CHECKS = ("scope-policy", "project-invariants", "project-tests")


def desired_ruleset() -> dict[str, Any]:
    """Return the exact machine-controlled merge policy for main."""
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {"include": ["refs/heads/main"], "exclude": []}
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
                    "required_status_checks": [
                        {"context": context} for context in REQUIRED_CHECKS
                    ],
                },
            },
        ],
        "bypass_actors": [],
    }


def desired_repository_settings() -> dict[str, Any]:
    return {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "delete_branch_on_merge": True,
    }


class AdminAPI:
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
                "User-Agent": "col-taxdata-governance",
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

    def list_rulesets(self) -> list[dict]:
        return self.call("GET", "/rulesets?includes_parents=false") or []

    def apply(self) -> dict:
        existing = next(
            (item for item in self.list_rulesets() if item.get("name") == RULESET_NAME),
            None,
        )
        if existing:
            ruleset = self.call(
                "PUT", f"/rulesets/{existing['id']}", desired_ruleset()
            )
            action = "updated"
        else:
            ruleset = self.call("POST", "/rulesets", desired_ruleset())
            action = "created"
        self.call("PATCH", "", desired_repository_settings())
        return {"ruleset_action": action, "ruleset_id": ruleset.get("id")}

    def verify(self) -> dict:
        repo_state = self.call("GET", "")
        existing = next(
            (item for item in self.list_rulesets() if item.get("name") == RULESET_NAME),
            None,
        )
        return {
            "ruleset_present": bool(existing),
            "ruleset_enforcement": existing.get("enforcement") if existing else None,
            "allow_squash_merge": repo_state.get("allow_squash_merge"),
            "allow_merge_commit": repo_state.get("allow_merge_commit"),
            "allow_rebase_merge": repo_state.get("allow_rebase_merge"),
            "delete_branch_on_merge": repo_state.get("delete_branch_on_merge"),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply", "verify"))
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)

    if args.command == "plan":
        print(
            json.dumps(
                {
                    "ruleset": desired_ruleset(),
                    "repository": desired_repository_settings(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    token = os.environ.get("GITHUB_ADMIN_TOKEN")
    if not token:
        print(
            "GITHUB_ADMIN_TOKEN with repository administration permission is required",
            file=sys.stderr,
        )
        return 2

    try:
        api = AdminAPI(args.repo, token)
        result = api.apply() if args.command == "apply" else api.verify()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "verify":
        expected = {
            "ruleset_present": True,
            "ruleset_enforcement": "active",
            **desired_repository_settings(),
        }
        return 0 if result == expected else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
