#!/usr/bin/env python3
"""Deterministic PR policy checks for the col-taxdata autonomous lifecycle."""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

METADATA_RE = re.compile(r"<!--\s*agent-execution:\s*(\{.*?\})\s*-->", re.IGNORECASE | re.DOTALL)
BRANCH_RE = re.compile(r"^agent/issue-(\d+)-[a-z0-9][a-z0-9-]*$")
CLOSING_RE = re.compile(r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b")
MIGRATION_RE = re.compile(r"^col-taxdata/schema/(\d{3})_[A-Za-z0-9_.-]+\.sql$")
AUTHORIZED_GLOBAL_PREFIXES = (".github/workflows/", ".github/actions/")
RUNTIME_ARTIFACT_RE = re.compile(
    r"(^|/)(?:data|raw|corpus)(?:/|$)|\.(?:db|sqlite|sqlite3)(?:[-.]|$)", re.IGNORECASE
)
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[opusr]_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic-bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{32,}\b")),
)


class PolicyError(ValueError):
    """Raised when an autonomous PR violates a durable repository policy."""


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise PolicyError(
            f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def parse_metadata(pr_body: str) -> dict:
    """Return validated machine-readable execution metadata from a PR body."""
    match = METADATA_RE.search(pr_body or "")
    if not match:
        raise PolicyError("missing agent-execution JSON metadata comment")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid agent-execution JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError("agent-execution metadata must be a JSON object")

    required = {"base_sha", "parallel_safe", "semantic_domains", "likely_touched", "depends_on"}
    missing = sorted(required - set(value))
    if missing:
        raise PolicyError(f"agent-execution metadata missing: {', '.join(missing)}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(value["base_sha"])):
        raise PolicyError("base_sha must be a 40-character lowercase commit SHA")
    if not isinstance(value["parallel_safe"], bool):
        raise PolicyError("parallel_safe must be boolean")
    for name in ("semantic_domains", "likely_touched", "depends_on"):
        if not isinstance(value[name], list):
            raise PolicyError(f"{name} must be an array")
    if not value["semantic_domains"] or not all(
        isinstance(item, str) and item.strip() for item in value["semantic_domains"]
    ):
        raise PolicyError("semantic_domains must contain at least one non-empty string")
    if not value["likely_touched"] or not all(
        isinstance(item, str) and item.strip() for item in value["likely_touched"]
    ):
        raise PolicyError("likely_touched must contain at least one non-empty path/glob")
    if not all(isinstance(item, int) and item > 0 for item in value["depends_on"]):
        raise PolicyError("depends_on entries must be positive issue numbers")
    return value


def issue_number_from_branch(branch: str) -> int:
    """Extract the owning issue number from the mandatory issue branch name."""
    match = BRANCH_RE.fullmatch(branch or "")
    if not match:
        raise PolicyError("branch must match agent/issue-<number>-<lowercase-slug>")
    return int(match.group(1))


def validate_issue_linkage(branch: str, pr_body: str) -> int:
    """Ensure one issue owns the branch and closes only through merged PR syntax."""
    issue_number = issue_number_from_branch(branch)
    closing = [int(value) for value in CLOSING_RE.findall(pr_body or "")]
    if closing != [issue_number]:
        raise PolicyError(f"PR must contain exactly one closing reference: Fixes #{issue_number}")
    return issue_number


def issue_authorizes_global_automation(issue_body: str) -> bool:
    """Recognize explicit authority for repository automation paths conservatively."""
    text = (issue_body or "").lower()
    has_authority = any(term in text for term in ("authoriz", "writable scope", "may modify", "allowed"))
    has_paths = ".github/workflows" in text or ".github/actions" in text
    return has_authority and has_paths


def changed_paths(repo_root: Path, base: str, head: str) -> list[str]:
    output = _git(repo_root, "diff", "--name-only", "-M", f"{base}...{head}")
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def changed_name_status(repo_root: Path, base: str, head: str) -> list[tuple[str, str]]:
    output = _git(repo_root, "diff", "--name-status", "-M", f"{base}...{head}")
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        rows.append((fields[0], fields[-1]))
    return rows


def _covered_by_declared_scope(path: str, declared: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in declared)


def validate_scope(paths: Iterable[str], metadata: dict, issue_body: str) -> None:
    """Reject changed paths outside selected-issue authority and declared scope."""
    global_ok = issue_authorizes_global_automation(issue_body)
    violations: list[str] = []
    undeclared: list[str] = []
    for path in paths:
        if path.startswith("col-taxdata/"):
            allowed = True
        elif path.startswith(AUTHORIZED_GLOBAL_PREFIXES):
            allowed = global_ok
        else:
            allowed = False
        if not allowed:
            violations.append(path)
        if not _covered_by_declared_scope(path, metadata["likely_touched"]):
            undeclared.append(path)
    if violations:
        raise PolicyError("unauthorized changed paths: " + ", ".join(sorted(violations)))
    if undeclared:
        raise PolicyError(
            "changed paths not covered by likely_touched metadata: " + ", ".join(sorted(undeclared))
        )


def validate_migration_immutability(
    repo_root: Path,
    base: str,
    head: str,
    name_status: Iterable[tuple[str, str]] | None = None,
) -> None:
    """Reject edits/deletes/renames of migrations and non-contiguous additions."""
    rows = list(name_status or changed_name_status(repo_root, base, head))
    schema_rows = [(status, path) for status, path in rows if path.startswith("col-taxdata/schema/")]
    if not schema_rows:
        return

    base_listing = _git(repo_root, "ls-tree", "-r", "--name-only", base, "--", "col-taxdata/schema")
    base_numbers: list[int] = []
    for path in base_listing.splitlines():
        match = MIGRATION_RE.fullmatch(path)
        if match:
            base_numbers.append(int(match.group(1)))
    max_existing = max(base_numbers, default=0)

    additions: list[int] = []
    for status, path in schema_rows:
        if status != "A":
            raise PolicyError(f"applied migration history is immutable; {status} forbidden for {path}")
        match = MIGRATION_RE.fullmatch(path)
        if not match:
            raise PolicyError(f"new migration has invalid ordered filename: {path}")
        additions.append(int(match.group(1)))

    expected = list(range(max_existing + 1, max_existing + 1 + len(additions)))
    if sorted(additions) != expected:
        raise PolicyError(
            f"new migrations must be contiguous after {max_existing:03d}; got {sorted(additions)}"
        )


def validate_runtime_artifacts(paths: Iterable[str]) -> None:
    bad = sorted(path for path in paths if RUNTIME_ARTIFACT_RE.search(path))
    if bad:
        raise PolicyError("runtime/raw corpus artifacts must not be committed: " + ", ".join(bad))


def validate_added_secrets(repo_root: Path, base: str, head: str) -> None:
    """Scan only added diff lines for high-confidence credential signatures."""
    diff = _git(repo_root, "diff", "--unified=0", "--no-color", f"{base}...{head}")
    findings: list[str] = []
    current_path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(added):
                findings.append(f"{current_path}:{name}")
    if findings:
        raise PolicyError("possible committed secrets detected: " + ", ".join(findings))


def validate_pr(
    repo_root: Path,
    base: str,
    head: str,
    branch: str,
    pr_body: str,
    issue_body: str,
) -> dict:
    """Run all deterministic PR gates and return workflow-friendly results."""
    issue_number = validate_issue_linkage(branch, pr_body)
    metadata = parse_metadata(pr_body)
    paths = changed_paths(repo_root, base, head)
    statuses = changed_name_status(repo_root, base, head)
    if not paths:
        raise PolicyError("PR contains no changed files")
    validate_scope(paths, metadata, issue_body)
    validate_runtime_artifacts(paths)
    validate_migration_immutability(repo_root, base, head, statuses)
    validate_added_secrets(repo_root, base, head)
    return {
        "issue_number": issue_number,
        "metadata": metadata,
        "changed_paths": paths,
        "run_heavy": any(path.startswith("col-taxdata/") for path in paths),
        "repository_automation_changed": any(path.startswith(".github/") for path in paths),
    }


def _write_github_output(path: str | None, result: dict) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"issue_number={result['issue_number']}\n")
        handle.write(f"run_heavy={'true' if result['run_heavy'] else 'false'}\n")
        handle.write(
            "repository_automation_changed="
            + ("true" if result["repository_automation_changed"] else "false")
            + "\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--pr-body-file", required=True)
    parser.add_argument("--issue-body-file", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    try:
        result = validate_pr(
            repo_root=Path(args.repo_root).resolve(),
            base=args.base,
            head=args.head,
            branch=args.branch,
            pr_body=Path(args.pr_body_file).read_text(encoding="utf-8"),
            issue_body=Path(args.issue_body_file).read_text(encoding="utf-8"),
        )
    except (OSError, PolicyError) as exc:
        print(f"POLICY FAIL: {exc}", file=sys.stderr)
        return 2
    _write_github_output(args.github_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
