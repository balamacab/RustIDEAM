#!/usr/bin/env python3
"""Private, append-only self-report channel for Col-taxdata scheduled workers.

No HTTP listener, no GitHub writer, no production access. Both workers use the
same SSH account; worker identity here is self-declared, NOT authenticated.
"""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

ROOT = Path("/home/user/col-taxdata-agent-status")
WORKERS = {"DEV-1", "DEV-2"}
STAGES = {"STARTED", "PREFLIGHT", "WORKING", "WAITING", "BLOCKED", "FAILED", "DONE"}
REQUIRED_FAILURE = {"operation", "error_class", "exact_error", "next_action"}
FIELDS = {"issue", "claim_attempt", "branch", "main_sha", "operation",
          "error_class", "exact_error", "stack_excerpt", "steps",
          "evidence", "next_action", "commits", "pr", "ci", "checks",
          "notes", "artifact_path", "github_response"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RUN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,119}$")
CREDENTIAL = re.compile(r"(?i)((?:authorization|token|password|secret|api[_-]?key)\s*[:=]\s*)([^\s,;]+)")
BEARER = re.compile(r"(?i)\bBearer\s+[a-zA-Z0-9._~+/-]{8,}")

def fail(message):
    """Reject invalid evidence without guessing."""
    raise ValueError(message)

def clean(obj, depth=0):
    """Bound and redact diagnostic material before durable storage."""
    if depth > 7:
        fail("detail nesting too deep")
    if isinstance(obj, str):
        if len(obj) > 6000:
            fail("detail field too long")
        return CREDENTIAL.sub(r"\1[REDACTED]", BEARER.sub("Bearer [REDACTED]", obj))
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, list):
        if len(obj) > 80:
            fail("detail list too long")
        return [clean(v, depth + 1) for v in obj]
    if isinstance(obj, dict):
        if len(obj) > 50 or any(not isinstance(k, str) for k in obj):
            fail("invalid detail mapping")
        return {k: clean(v, depth + 1) for k, v in obj.items()}
    fail("unsupported detail data")

def canonical(value):
    """Create stable UTF-8 bytes for immutable event chaining."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def validate(worker, stage, detail, run_id):
    """Validate worker identity, stage and required diagnostic fields."""
    if worker not in WORKERS or stage not in STAGES:
        fail("unsupported worker or stage")
    if not isinstance(detail, dict) or set(detail) - FIELDS:
        fail("invalid/unexpected status detail field")
    if len(canonical(detail)) > 16000:
        fail("status detail exceeds 16 KiB")
    if stage in ("BLOCKED", "FAILED"):
        if any(not isinstance(detail.get(k), str) or not detail[k].strip() for k in REQUIRED_FAILURE):
            fail("blocked status requires operation, error_class, exact_error, next_action")
    if "issue" in detail and (type(detail["issue"]) is not int or detail["issue"] <= 0):
        fail("invalid issue")
    if "claim_attempt" in detail and (type(detail["claim_attempt"]) is not int or detail["claim_attempt"] <= 0):
        fail("invalid attempt")
    if "main_sha" in detail and (type(detail["main_sha"]) is not str or not SHA40.fullmatch(detail["main_sha"])):
        fail("invalid main SHA")
    if run_id and not RUN_ID.fullmatch(run_id):
        fail("invalid run id")

def worker_dir(worker):
    """Resolve the private per-worker event directory."""
    if worker not in WORKERS:
        fail("invalid worker")
    directory = ROOT / "events" / worker
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    return directory

def load_entries(directory):
    """Revalidate every historical record and its previous hash."""
    previous = "0" * 64
    entries = []
    for path in sorted(directory.glob("*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("sequence") != len(entries) + 1 or path.name != f"{len(entries)+1:08d}.json":
            fail("sequence discontinuity in " + str(directory))
        core = {k: v for k, v in obj.items() if k != "chain_hash"}
        digest = hashlib.sha256(previous.encode("ascii") + b"\n" + canonical(core)).hexdigest()
        if obj.get("previous_hash") != previous or obj.get("chain_hash") != digest:
            fail("status chain mismatch")
        previous = digest
        entries.append(obj)
    return entries

def record(args):
    """Persist one self-reported event with an atomic immutable append."""
    detail = json.loads(args.detail_json)
    validate(args.worker, args.stage, detail, args.run_id)
    cleaned = clean(detail)
    directory = worker_dir(args.worker)
    now = dt.datetime.now(dt.timezone.utc)
    os.makedirs(ROOT, mode=0o700, exist_ok=True)
    os.chmod(ROOT, 0o700)
    with (ROOT / ".lock").open("a+", encoding="utf-8") as lock:
        os.chmod(ROOT / ".lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = load_entries(directory)
        sequence = len(prior) + 1
        previous = prior[-1]["chain_hash"] if prior else "0" * 64
        run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        core = {"schema_version": 1, "sequence": sequence, "worker_id": args.worker,
                "source": "worker_self_report", "run_id": run_id,
                "stage": args.stage, "server_time_utc": now.isoformat(),
                "detail": cleaned, "previous_hash": previous}
        core["chain_hash"] = hashlib.sha256(previous.encode("ascii") + b"\n" + canonical(core)).hexdigest()
        data = canonical(core) + b"\n"
        fd, temp = tempfile.mkstemp(prefix=".pending-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, directory / f"{sequence:08d}.json")
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    print(json.dumps({"stored": True, "worker": args.worker, "run_id": run_id,
                      "sequence": sequence, "stage": args.stage,
                      "sha256": hashlib.sha256(data).hexdigest()}))

def inspect(args):
    """Summarize latest events and verify chain integrity."""
    result = {"schema_version": 1, "server_time_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "workers": {}}
    for worker in sorted(WORKERS):
        directory = worker_dir(worker)
        with (ROOT / ".lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            events = load_entries(directory)
        if not events:
            result["workers"][worker] = {"status": "NO_REPORT", "count": 0}
            continue
        last = events[-1]
        reported = dt.datetime.fromisoformat(last["server_time_utc"])
        age = (dt.datetime.now(dt.timezone.utc) - reported).total_seconds() / 60
        result["workers"][worker] = {
            "status": "STALE" if age > args.stale_minutes else "RECORDED",
            "count": len(events), "age_minutes": round(age, 2),
            "last": last, "chain_verified": True,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

def main():
    """Parse the supported record and inspect operations."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    post = sub.add_parser("record", help="persist one immutable status event")
    post.add_argument("--worker", choices=sorted(WORKERS), required=True)
    post.add_argument("--stage", choices=sorted(STAGES), required=True)
    post.add_argument("--run-id", default=None)
    post.add_argument("--detail-json", required=True)
    read = sub.add_parser("inspect", help="verify chains and report both workers")
    read.add_argument("--stale-minutes", type=int, default=90)
    args = parser.parse_args()
    try:
        if args.action == "record":
            record(args)
        else:
            inspect(args)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

