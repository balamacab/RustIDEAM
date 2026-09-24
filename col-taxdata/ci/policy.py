#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

METADATA_MARKER = "col-taxdata-agent-metadata:"
BRANCH_RE = re.compile(r"^agent/issue-(?P<issue>[1-9][0-9]*)-(?P<slug>[a-z0-9][a-z0-9-]*)$")
CLOSING_RE = re.compile(r"(?im)\b(?:fixes|closes|resolves)\s+#([1-9][0-9]*)\b")
SCHEMA_RE = re.compile(r"^col-taxdata/schema/[^/]+\.sql$")
GLOBAL_WORKFLOW_RE = re.compile(r"^\.github/workflows/col-taxdata-[A-Za-z0-9_.-]+\.ya?ml$")
GLOBAL_ACTION_RE = re.compile(r"^\.github/actions/col-taxdata(?:/|$)")
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm")
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
)

class PolicyError(ValueError):
    pass


def parse_metadata(body: str) -> dict[str, Any]:
    start = body.find(f"<!-- {METADATA_MARKER}")
    if start < 0:
        raise PolicyError("missing machine-readable col-taxdata agent metadata")
    payload_start = start + len(f"<!-- {METADATA_MARKER}")
    end = body.find("-->", payload_start)
    if end < 0:
        raise PolicyError("unterminated col-taxdata agent metadata marker")
    raw = body[payload_start:end].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid agent metadata JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError("agent metadata must be a JSON object")
    required = {"base_sha", "parallel_safe", "semantic_domains", "likely_touched", "depends_on"}
    missing = sorted(required - data.keys())
    if missing:
        raise PolicyError(f"agent metadata missing keys: {', '.join(missing)}")
    if not isinstance(data["base_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", data["base_sha"]):
        raise PolicyError("metadata base_sha must be a 40-character lowercase commit SHA")
    if not isinstance(data["parallel_safe"], bool):
        raise PolicyError("metadata parallel_safe must be boolean")
    for key in ("semantic_domains", "likely_touched"):
        if not isinstance(data[key], list) or not data[key] or not all(isinstance(v, str) and v.strip() for v in data[key]):
            raise PolicyError(f"metadata {key} must be a non-empty string list")
    if not isinstance(data["depends_on"], list) or not all(isinstance(v, int) and v > 0 for v in data["depends_on"]):
        raise PolicyError("metadata depends_on must be a list of positive issue numbers")
    return data


def closing_issue_number(body: str) -> int:
    numbers = {int(v) for v in CLOSING_RE.findall(body)}
    if len(numbers) != 1:
        raise PolicyError("PR body must contain exactly one unique Fixes/Closes/Resolves #<issue> target")
    return next(iter(numbers))


def validate_branch(branch: str, issue_number: int) -> None:
    match = BRANCH_RE.fullmatch(branch)
    if not match:
        raise PolicyError("implementation branch must match agent/issue-<number>-<slug>")
    if int(match.group("issue")) != issue_number:
        raise PolicyError("implementation branch issue number does not match PR closing target")


def is_col_taxdata_path(path: str) -> bool:
    return path.startswith("col-taxdata/")


def is_dedicated_global_path(path: str) -> bool:
    return bool(GLOBAL_WORKFLOW_RE.fullmatch(path) or GLOBAL_ACTION_RE.match(path))


def classify_paths(paths: Iterable[str]) -> tuple[bool, bool]:
    paths = list(paths)
    applicable = any(is_col_taxdata_path(p) or is_dedicated_global_path(p) for p in paths)
    run_heavy = any(is_col_taxdata_path(p) and not p.startswith("col-taxdata/docs/") for p in paths)
    return applicable, run_heavy


def issue_authorizes_global(issue_body: str, path: str) -> bool:
    body = issue_body.lower()
    if "writable-scope exception" not in body and "repository-global" not in body:
        return False
    if path.startswith(".github/workflows/"):
        return ".github/workflows/" in body
    if path.startswith(".github/actions/"):
        return ".github/actions/" in body
    return False


def validate_scope(paths: Iterable[str], issue_body: str) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if is_col_taxdata_path(path):
            continue
        if is_dedicated_global_path(path) and issue_authorizes_global(issue_body, path):
            continue
        violations.append(path)
    return violations


def undeclared_paths(paths: Iterable[str], likely_touched: Iterable[str]) -> list[str]:
    patterns = list(likely_touched)
    return [path for path in paths if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)]


def parse_name_status(text: str) -> list[tuple[str, list[str]]]:
    changes: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        changes.append((fields[0], fields[1:]))
    return changes


def validate_migration_immutability(changes: Iterable[tuple[str, list[str]]]) -> list[str]:
    violations: list[str] = []
    for status, paths in changes:
        migration_paths = [p for p in paths if SCHEMA_RE.fullmatch(p)]
        if not migration_paths:
            continue
        if not status.startswith("A"):
            violations.extend(f"{status}:{p}" for p in migration_paths)
    return violations


def forbidden_artifacts(paths: Iterable[str]) -> list[str]:
    bad: list[str] = []
    for path in paths:
        lower = path.lower()
        if (
            lower.startswith("col-taxdata/data/")
            or lower.startswith("col-taxdata/raw/")
            or lower.endswith(FORBIDDEN_SUFFIXES)
        ):
            bad.append(path)
    return bad


def migration_sequence_violations(repo_root: Path, base: str, changes: Iterable[tuple[str, list[str]]]) -> list[str]:
    added: list[str] = []
    for status, paths in changes:
        if status.startswith("A"):
            added.extend(path for path in paths if SCHEMA_RE.fullmatch(path))
    if not added:
        return []
    base_paths = git_output(["ls-tree", "-r", "--name-only", base, "--", "col-taxdata/schema"], repo_root).splitlines()
    def number(path: str) -> int | None:
        match = re.search(r"/(\d+)_", path)
        return int(match.group(1)) if match else None
    existing = [n for path in base_paths if (n := number(path)) is not None]
    new_numbers = sorted(n for path in added if (n := number(path)) is not None)
    if len(new_numbers) != len(added):
        return ["new migration filename must begin with an integer sequence"]
    expected_start = (max(existing) + 1) if existing else 1
    expected = list(range(expected_start, expected_start + len(new_numbers)))
    if new_numbers != expected:
        return [f"new migration numbers {new_numbers} are not contiguous; expected {expected}"]
    return []


def scan_secrets(repo_root: Path, paths: Iterable[str]) -> list[str]:
    findings: list[str] = []
    for rel in paths:
        path = repo_root / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{rel}:{name}")
    return findings


def git_output(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE)
    return proc.stdout


def changed_state(repo_root: Path, base: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    status_text = git_output(["diff", "--name-status", f"{base}...HEAD"], repo_root)
    changes = parse_name_status(status_text)
    paths: list[str] = []
    for _, changed_paths in changes:
        paths.extend(changed_paths)
    return sorted(set(paths)), changes


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def load_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PolicyError(f"expected JSON object in {path}")
    return data


def pr_fields(pr_json: dict[str, Any]) -> tuple[str, str, str]:
    body = pr_json.get("body") or ""
    head = pr_json.get("head") or {}
    base = pr_json.get("base") or {}
    return body, str(head.get("ref") or ""), str(base.get("sha") or "")


def cmd_classify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    paths, _ = changed_state(root, args.base)
    applicable, heavy = classify_paths(paths)
    write_output("applicable", str(applicable).lower())
    write_output("run_heavy", str(heavy).lower())
    print(json.dumps({"applicable": applicable, "run_heavy": heavy, "changed_paths": paths}, indent=2))
    return 0


def cmd_issue_number(args: argparse.Namespace) -> int:
    pr = load_json(args.pr_json)
    body, _, _ = pr_fields(pr)
    number = closing_issue_number(body)
    write_output("issue_number", str(number))
    print(number)
    return 0


def cmd_metadata_domains(args: argparse.Namespace) -> int:
    pr = load_json(args.pr_json)
    body, _, _ = pr_fields(pr)
    metadata = parse_metadata(body)
    print(json.dumps(metadata["semantic_domains"], separators=(",", ":")))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    pr = load_json(args.pr_json)
    issue = load_json(args.issue_json)
    body, branch, _ = pr_fields(pr)
    issue_body = issue.get("body") or ""
    paths, changes = changed_state(root, args.base)
    applicable, heavy = classify_paths(paths)
    write_output("applicable", str(applicable).lower())
    write_output("run_heavy", str(heavy).lower())
    if not applicable:
        print("col-taxdata policy: not applicable to this PR")
        return 0

    issue_number = closing_issue_number(body)
    validate_branch(branch, issue_number)
    metadata = parse_metadata(body)
    if int(issue.get("number") or 0) != issue_number:
        raise PolicyError("fetched issue does not match PR closing target")
    violations = validate_scope(paths, issue_body)
    if violations:
        raise PolicyError("unauthorized changed paths: " + ", ".join(violations))
    undeclared = undeclared_paths(paths, metadata["likely_touched"])
    if undeclared:
        raise PolicyError("changed paths not declared by likely_touched metadata: " + ", ".join(undeclared))
    migrations = validate_migration_immutability(changes)
    if migrations:
        raise PolicyError("applied migration mutation detected: " + ", ".join(migrations))
    sequence = migration_sequence_violations(root, args.base, changes)
    if sequence:
        raise PolicyError("; ".join(sequence))
    artifacts = forbidden_artifacts(paths)
    if artifacts:
        raise PolicyError("runtime/database artifact committed: " + ", ".join(artifacts))
    secrets = scan_secrets(root, paths)
    if secrets:
        raise PolicyError("high-confidence secret material detected: " + ", ".join(secrets))

    write_output("issue_number", str(issue_number))
    write_output("semantic_domains", json.dumps(metadata["semantic_domains"], separators=(",", ":")))
    print(json.dumps({
        "issue_number": issue_number,
        "branch": branch,
        "metadata": metadata,
        "changed_paths": paths,
        "run_heavy": heavy,
        "result": "PASS",
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic CI policy for col-taxdata autonomous PRs")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("classify")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--base", required=True)
    p.set_defaults(func=cmd_classify)
    p = sub.add_parser("issue-number")
    p.add_argument("--pr-json", required=True)
    p.set_defaults(func=cmd_issue_number)
    p = sub.add_parser("metadata-domains")
    p.add_argument("--pr-json", required=True)
    p.set_defaults(func=cmd_metadata_domains)
    p = sub.add_parser("validate")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--pr-json", required=True)
    p.add_argument("--issue-json", required=True)
    p.set_defaults(func=cmd_validate)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (PolicyError, subprocess.CalledProcessError) as exc:
        print(f"POLICY FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

[executed on device: morichalserver (2bfaa62f-23ff-40e5-9fc7-7c1a7d28b1fc)]