"""Offline, fail-closed reconciliation of scheduled Developer GitHub claims.

This module consumes a *complete* GitHub-connector snapshot and returns only a
decision. It performs no GitHub write, network request or scheduled-task action.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

CLAIM_MARKER = "<!-- col-taxdata-developer-claim:"
STATE_MARKER = "<!-- col-taxdata-agent-state:"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^agent/issue-([1-9][0-9]*)-claim-a([1-9][0-9]*)-([0-9a-f]{12})$")
WORKERS = {"DEV-1", "DEV-2"}


class SnapshotError(ValueError):
    """An incomplete or inconsistent inventory cannot authorize a write."""


def _marker(text: str, prefix: str) -> dict[str, Any] | None:
    start = text.find(prefix)
    if start < 0:
        return None
    end = text.find("-->", start + len(prefix))
    if end < 0:
        raise SnapshotError("unterminated machine-readable marker")
    try:
        value = json.loads(text[start + len(prefix):end].strip())
    except (ValueError, TypeError) as exc:
        raise SnapshotError("invalid machine-readable marker") from None
    if not isinstance(value, dict):
        raise SnapshotError("marker must contain a JSON object")
    return value


def _check_issue(issue: dict[str, Any]) -> None:
    if not isinstance(issue.get("number"), int) or issue["number"] <= 0:
        raise SnapshotError("invalid issue number")
    if issue.get("state") not in ("open", "closed"):
        raise SnapshotError("invalid issue state")
    for name in ("comments", "branches", "prs"):
        if not isinstance(issue.get(name), list) or not issue.get(name + "_complete"):
            raise SnapshotError("incomplete issue " + name + " inventory")
    for c in issue["comments"]:
        if not isinstance(c, dict) or not isinstance(c.get("body"), str):
            raise SnapshotError("incomplete issue comment")
    for b in issue["branches"]:
        if not isinstance(b, dict) or not isinstance(b.get("name"), str) or not SHA_RE.fullmatch(str(b.get("head_sha", ""))):
            raise SnapshotError("invalid branch snapshot")
    for p in issue["prs"]:
        if not isinstance(p, dict) or not isinstance(p.get("head_branch"), str) or p.get("state") not in ("open", "closed"):
            raise SnapshotError("invalid PR snapshot")


def _claims(issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconcile ordered claim events, retaining terminal historical attempts.

    A legacy human-facing DEV-A/DEV-B identity is acceptable only as a
    *withdrawn historical record*. It never acquires current ownership.
    """
    by_branch: dict[str, dict[str, Any]] = {}
    for comment in issue["comments"]:
        mark = _marker(comment["body"], CLAIM_MARKER)
        if mark is None:
            continue
        state = mark.get("state")
        if state not in ("CLAIMED", "WITHDRAWN", "DONE"):
            raise SnapshotError("unsupported claim state")
        worker_id = mark.get("worker_id")
        if worker_id not in WORKERS | {"DEV-A", "DEV-B"} or mark.get("issue") != issue["number"]:
            raise SnapshotError("claim identity does not match issue")
        attempt = mark.get("attempt")
        if type(attempt) is not int or attempt <= 0:
            raise SnapshotError("invalid claim attempt")
        branch = mark.get("branch")
        match = BRANCH_RE.fullmatch(str(branch))
        if not match or int(match.group(1)) != issue["number"] or int(match.group(2)) != attempt:
            raise SnapshotError("claim branch identity mismatch")
        if state == "CLAIMED":
            base_sha = mark.get("base_sha")
            if not SHA_RE.fullmatch(str(base_sha)):
                raise SnapshotError("invalid claim base SHA")
            if match.group(3) != base_sha[:12]:
                raise SnapshotError("claim branch identity mismatch")
            if branch in by_branch:
                raise SnapshotError("duplicate claim admission")
            by_branch[branch] = dict(mark)
            continue

        # Terminal markers update an exact prior admission. Historical DONE
        # markers need not repeat the original base_sha.
        prior = by_branch.get(branch)
        if prior is None:
            raise SnapshotError("terminal claim without prior admission")
        if prior["state"] != "CLAIMED":
            raise SnapshotError("duplicate terminal claim event")
        if worker_id != prior["worker_id"] or attempt != prior["attempt"]:
            raise SnapshotError("terminal claim identity mismatch")
        if mark.get("base_sha") is not None and mark["base_sha"] != prior["base_sha"]:
            raise SnapshotError("terminal claim base SHA mismatch")
        if state == "DONE":
            convergence = mark.get("convergence_sha")
            if issue["state"] != "closed" or not SHA_RE.fullmatch(str(convergence)):
                raise SnapshotError("unverified terminal DONE claim")
            if not any(
                (event := _marker(c["body"], STATE_MARKER))
                and event.get("state") == "DONE"
                and event.get("convergence_sha") == convergence
                for c in issue["comments"]
            ):
                raise SnapshotError("DONE claim lacks matching convergence evidence")
        prior["state"] = state
        if state == "DONE":
            prior["convergence_sha"] = mark["convergence_sha"]
    for claim in by_branch.values():
        if claim["worker_id"] not in WORKERS and claim["state"] != "WITHDRAWN":
            raise SnapshotError("unwithdrawn legacy worker identity")
    return list(by_branch.values())


def _terminal(issue: dict[str, Any], claim: dict[str, Any]) -> bool:
    if claim["state"] == "WITHDRAWN":
        return True
    if claim["state"] == "DONE":
        return issue["state"] == "closed"
    if issue["state"] != "closed":
        return False
    for comment in issue["comments"]:
        mark = _marker(comment["body"], STATE_MARKER)
        if mark and mark.get("state") == "DONE" and SHA_RE.fullmatch(str(mark.get("convergence_sha", ""))):
            return True
    return False

def _branch_attempts(issue: dict[str, Any], claims: list[dict[str, Any]]) -> tuple[int, list[str]]:
    max_attempt = max((c["attempt"] for c in claims), default=0)
    orphans: list[str] = []
    claimed = {c["branch"] for c in claims}
    pr_heads = {p["head_branch"] for p in issue["prs"]}
    for branch in issue["branches"]:
        match = BRANCH_RE.fullmatch(branch["name"])
        if not match or int(match.group(1)) != issue["number"]:
            continue
        max_attempt = max(max_attempt, int(match.group(2)))
        if branch["name"] not in claimed and branch["name"] not in pr_heads:
            if branch["head_sha"][:12] == match.group(3):
                orphans.append(branch["name"])
            else:
                raise SnapshotError("unclaimed branch with implementation content")
    return max_attempt, sorted(orphans)


def reconcile(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Select RESUME, CREATE_CLAIM, NO_OP or BLOCKED from verified GitHub facts.

    Candidate priority and parallel safety are supplied by the operator's
    connector-backed preflight. A denied/unverified write channel cannot be
    converted into new ownership by creating an extra orphan branch.
    """
    if not isinstance(snapshot, dict):
        raise SnapshotError("snapshot must be an object")
    worker = snapshot.get("worker_id")
    main = snapshot.get("main_sha")
    if worker not in WORKERS or not SHA_RE.fullmatch(str(main)):
        raise SnapshotError("invalid durable worker or main SHA")
    if snapshot.get("inventory_complete") is not True:
        raise SnapshotError("global GitHub inventory incomplete")
    issues = snapshot.get("issues")
    if not isinstance(issues, list):
        raise SnapshotError("issues inventory missing")
    nums: set[int] = set()
    owned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    candidate: list[tuple[int, int, dict[str, Any], int, list[str]]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise SnapshotError("invalid issue entry")
        _check_issue(issue)
        if issue["number"] in nums:
            raise SnapshotError("duplicate issue")
        nums.add(issue["number"])
        claims = _claims(issue)
        maximum, orphans = _branch_attempts(issue, claims)
        active = [c for c in claims if c["state"] == "CLAIMED" and not _terminal(issue, c)]
        if len(active) > 1:
            raise SnapshotError("conflicting active claims on issue")
        if active:
            claim = active[0]
            branches = {b["name"]: b for b in issue["branches"]}
            if issue["state"] != "open" or claim["branch"] not in branches:
                raise SnapshotError("active claim cannot be resumed safely")
            if claim["worker_id"] == worker:
                owned.append((issue, claim))
            continue
        if issue["state"] == "open" and issue.get("eligible") is True and issue.get("dependencies_satisfied") is True and issue.get("parallel_safe") is True:
            priority = issue.get("priority")
            if not isinstance(priority, int):
                raise SnapshotError("missing candidate priority")
            candidate.append((priority, issue["number"], issue, maximum, orphans))
    if len(owned) > 1:
        raise SnapshotError("worker has conflicting active claims")
    if owned:
        issue, claim = owned[0]
        return {
            "decision": "RESUME", "issue": issue["number"],
            "worker_id": worker, "attempt": claim["attempt"],
            "branch": claim["branch"], "base_sha": claim["base_sha"],
            "claim_origin": claim.get("claim_origin", "WORKER"),
        }
    channel = snapshot.get("write_channel")
    if channel not in ("verified", "denied", "unknown"):
        raise SnapshotError("write channel status missing")
    if not candidate:
        return {"decision": "NO_OP", "reason": "no_eligible_issue"}
    _, number, issue, maximum, orphans = min(candidate, key=lambda t: (t[0], t[1]))
    # An UNKNOWN channel is normal for an initial stateless activation.
    # Allow one provisional atomic claim attempt, but NEVER create another
    # branch after an unclaimed no-op when the write channel remains unknown.
    # Only successful same-context authorized writes may mark it verified.
    if channel == "denied" or (channel == "unknown" and orphans):
        return {
            "decision": "BLOCKED", "issue": number,
            "reason": (
                "external_write_denied" if channel == "denied"
                else "unconfirmed_claim_write_after_orphan"
            ),
            "orphan_noop": orphans, "next_attempt": maximum + 1,
        }
    return {
        "decision": "CREATE_CLAIM", "issue": number, "worker_id": worker,
        "attempt": maximum + 1,
        "branch": f"agent/issue-{number}-claim-a{maximum + 1}-{main[:12]}",
        "base_sha": main, "orphan_noop": orphans,
        "write_channel": channel,
        "precondition": "atomic_branch_create_then_verified_CLAIMED_comment",
    }


def main(argv: list[str] | None = None) -> int:
    """Read a complete GitHub snapshot from stdin; emit machine-readable decision."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        outcome = reconcile(json.load(sys.stdin))
    except (ValueError, TypeError) as exc:
        print(json.dumps({"decision": "BLOCKED", "reason": "invalid_snapshot",
                          "detail": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
