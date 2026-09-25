#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_ROOT = ROOT / "controller-memory"
SCHEMA_VERSION = "CM1"
SCHEMA_BYTES = (
    b"CM1|C\n"
    b"R|D|7\n"
    b"R|E|5\n"
    b"R|F|5\n"
    b"R|A|5\n"
    b"R|X|4\n"
    b"H|P|2\n"
    b"H|R|2\n"
    b"H|S|6\n"
    b"K|i|1\n"
    b"K|p|2\n"
    b"K|d|3\n"
    b"K|t|4\n"
    b"K|b|5\n"
)
SESSION_ID_RE = re.compile(r"^C[0-9]{6}T[0-9]{6}Z[A-Z0-9]{2}$")
TIMESTAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
KEY_RE = re.compile(r"^[a-z][A-Za-z0-9._:-]{0,63}$")
RECORD_FIELD_COUNTS = {"D": 7, "E": 5, "F": 5, "A": 5, "X": 4}
ETHOS_VERSION = 1
ETHOS_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
ETHOS_REQUIRED_PRINCIPLES = (
    ("evidence", "fluency"),
    ("architecture", "unblock"),
    ("live", "stale"),
    ("uncertainty", "guess"),
    ("history", "rewrite"),
    ("root", "symptom"),
    ("ownership", "proximity"),
    ("reversible", "premature"),
    ("critical", "agreement"),
    ("convergence", "closure"),
)
ETHOS_REQUIRED_RULES = (
    ("absence-evidence", "not-authorization"),
    ("speed", "subordinate-correctness"),
    ("challenge-evidence", "preserve-history"),
)
ETHOS_REQUIRED_STAGES = (
    "observation",
    "conclusion",
    "decision",
    "authorization",
    "execution",
    "verified-integration",
)
ETHOS_BYTES = (
    b"CM1|H|1\n"
    b"P|evidence|fluency\n"
    b"P|architecture|unblock\n"
    b"P|live|stale\n"
    b"P|uncertainty|guess\n"
    b"P|history|rewrite\n"
    b"P|root|symptom\n"
    b"P|ownership|proximity\n"
    b"P|reversible|premature\n"
    b"P|critical|agreement\n"
    b"P|convergence|closure\n"
    b"R|absence-evidence|not-authorization\n"
    b"R|speed|subordinate-correctness\n"
    b"R|challenge-evidence|preserve-history\n"
    b"S|observation|conclusion|decision|authorization|execution|verified-integration\n"
)


class MemoryError(ValueError):
    pass


@dataclass(frozen=True)
class Record:
    kind: str
    fields: tuple[str, ...]
    keys: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class Ethos:
    version: int
    principles: tuple[tuple[str, str], ...]
    rules: tuple[tuple[str, str], ...]
    stages: tuple[str, ...]
    raw: bytes


@dataclass(frozen=True)
class Session:
    sid: str
    timestamp: str
    main_sha: str
    prev_sid: str
    records: tuple[Record, ...]
    raw: bytes


@dataclass(frozen=True)
class Index:
    session_count: int
    latest_sid: str
    manifest_sha256: str
    pointers: dict[str, tuple[str, ...]]
    raw: bytes


def _decode_canonical(data: bytes, label: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryError(f"{label}: not UTF-8") from exc
    if "\r" in text:
        raise MemoryError(f"{label}: CR characters are forbidden")
    if not text.endswith("\n"):
        raise MemoryError(f"{label}: final LF required")
    return text


def _validate_sid(value: str, label: str = "session id") -> None:
    if not SESSION_ID_RE.fullmatch(value):
        raise MemoryError(f"{label}: invalid compact session id {value!r}")


def _validate_timestamp(value: str) -> None:
    if not TIMESTAMP_RE.fullmatch(value):
        raise MemoryError(f"invalid UTC timestamp {value!r}")
    try:
        datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError as exc:
        raise MemoryError(f"invalid UTC timestamp {value!r}") from exc


def _parse_keys(field: str) -> tuple[str, ...]:
    keys = tuple(field.split(","))
    if not keys or any(not KEY_RE.fullmatch(key) for key in keys):
        raise MemoryError(f"invalid retrieval key list {field!r}")
    if tuple(sorted(set(keys))) != keys:
        raise MemoryError("record retrieval keys must be sorted and unique")
    return keys


def _validate_ethos_token(value: str, label: str) -> None:
    if not ETHOS_TOKEN_RE.fullmatch(value):
        raise MemoryError(f"ethos: invalid {label} token {value!r}")


def parse_ethos_bytes(data: bytes) -> Ethos:
    if len(data) > 1024:
        raise MemoryError("ethos: compact payload exceeds 1024 bytes")
    text = _decode_canonical(data, "ethos")
    lines = text.splitlines()
    header = lines[0].split("|") if lines else []
    if len(header) != 3 or header[:2] != [SCHEMA_VERSION, "H"]:
        raise MemoryError("ethos: invalid header")
    try:
        version = int(header[2])
    except ValueError as exc:
        raise MemoryError("ethos: version must be an integer") from exc
    if version <= 0:
        raise MemoryError("ethos: version must be positive")
    if version != ETHOS_VERSION:
        raise MemoryError(
            f"ethos: unsupported version {version}; expected {ETHOS_VERSION}"
        )

    principles: list[tuple[str, str]] = []
    rules: list[tuple[str, str]] = []
    stages: tuple[str, ...] | None = None
    seen_principle_left: set[str] = set()
    seen_rule_left: set[str] = set()

    for line_no, line in enumerate(lines[1:], start=2):
        if not line:
            raise MemoryError(f"ethos:{line_no}: blank records are forbidden")
        parts = line.split("|")
        kind = parts[0]
        fields = parts[1:]
        if kind in {"P", "R"}:
            if len(fields) != 2:
                raise MemoryError(f"ethos:{line_no}: {kind} requires 2 fields")
            left, right = fields
            _validate_ethos_token(left, "left")
            _validate_ethos_token(right, "right")
            seen = seen_principle_left if kind == "P" else seen_rule_left
            if left in seen:
                raise MemoryError(f"ethos:{line_no}: duplicate {kind} identity {left!r}")
            seen.add(left)
            (principles if kind == "P" else rules).append((left, right))
        elif kind == "S":
            if stages is not None:
                raise MemoryError("ethos: duplicate stage record")
            if len(fields) != len(ETHOS_REQUIRED_STAGES):
                raise MemoryError(
                    f"ethos:{line_no}: S requires {len(ETHOS_REQUIRED_STAGES)} stages"
                )
            for value in fields:
                _validate_ethos_token(value, "stage")
            stages = tuple(fields)
        else:
            raise MemoryError(f"ethos:{line_no}: unknown record type {kind!r}")

    if tuple(principles) != ETHOS_REQUIRED_PRINCIPLES:
        raise MemoryError("ethos: required principle set/order mismatch")
    if tuple(rules) != ETHOS_REQUIRED_RULES:
        raise MemoryError("ethos: required rule set/order mismatch")
    if stages != ETHOS_REQUIRED_STAGES:
        raise MemoryError("ethos: required stage distinction mismatch")
    return Ethos(version, tuple(principles), tuple(rules), stages, data)


def verify_ethos(memory_root: Path) -> Ethos:
    path = memory_root / "ETHOS.cm"
    if not path.is_file():
        raise MemoryError("missing ETHOS.cm")
    return parse_ethos_bytes(path.read_bytes())


def parse_session_bytes(data: bytes, *, expected_filename: str | None = None) -> Session:
    text = _decode_canonical(data, "session")
    lines = text.splitlines()
    if not lines:
        raise MemoryError("session: empty")
    header = lines[0].split("|")
    if len(header) != 6 or header[:2] != [SCHEMA_VERSION, "S"]:
        raise MemoryError("session: invalid header")
    _, _, sid, timestamp, main_sha, prev_sid = header
    _validate_sid(sid)
    _validate_timestamp(timestamp)
    if not SHA_RE.fullmatch(main_sha):
        raise MemoryError("session: main SHA must be 40 lowercase hex")
    if prev_sid != "-":
        _validate_sid(prev_sid, "previous session id")
        if prev_sid == sid:
            raise MemoryError("session: previous session cannot equal current session")
    if expected_filename is not None and expected_filename != f"{sid}.cm":
        raise MemoryError(
            f"session identity/path mismatch: header {sid!r}, file {expected_filename!r}"
        )

    records: list[Record] = []
    for line_no, line in enumerate(lines[1:], start=2):
        if not line:
            raise MemoryError(f"session:{line_no}: blank records are forbidden")
        parts = line.split("|")
        kind = parts[0]
        expected = RECORD_FIELD_COUNTS.get(kind)
        if expected is None:
            raise MemoryError(f"session:{line_no}: unknown record type {kind!r}")
        fields = parts[1:]
        if len(fields) != expected:
            raise MemoryError(
                f"session:{line_no}: {kind} requires {expected} positional fields"
            )
        if any(field == "" for field in fields):
            raise MemoryError(f"session:{line_no}: empty positional field")
        keys = _parse_keys(fields[-1])
        records.append(Record(kind, tuple(fields), keys, line))
    if not records:
        raise MemoryError("session: at least one knowledge record required")
    return Session(sid, timestamp, main_sha, prev_sid, tuple(records), data)


def parse_session_file(path: Path) -> Session:
    return parse_session_bytes(path.read_bytes(), expected_filename=path.name)


def _session_paths(memory_root: Path) -> list[Path]:
    sessions_dir = memory_root / "sessions"
    if not sessions_dir.exists():
        return []
    return sorted(
        path for path in sessions_dir.iterdir()
        if path.is_file() and path.suffix == ".cm"
    )


def load_sessions(memory_root: Path) -> list[Session]:
    sessions: list[Session] = []
    seen: set[str] = set()
    for path in _session_paths(memory_root):
        session = parse_session_file(path)
        if session.sid in seen:
            raise MemoryError(f"duplicate session identity {session.sid}")
        seen.add(session.sid)
        sessions.append(session)
    return sessions


def source_manifest(sessions: Iterable[Session]) -> str:
    rows = [
        f"{session.sid}|{hashlib.sha256(session.raw).hexdigest()}\n"
        for session in sorted(sessions, key=lambda item: item.sid)
    ]
    return hashlib.sha256("".join(rows).encode("ascii")).hexdigest()


def build_index_bytes(sessions: Iterable[Session]) -> bytes:
    items = list(sessions)
    fingerprint = source_manifest(items)
    latest = max(items, key=lambda item: (item.timestamp, item.sid)).sid if items else "-"
    pointers: dict[str, set[str]] = {}
    for session in items:
        for record in session.records:
            for key in record.keys:
                pointers.setdefault(key, set()).add(session.sid)
    lines = [f"{SCHEMA_VERSION}|I|{len(items)}|{latest}|{fingerprint}"]
    for key in sorted(pointers):
        lines.append(f"K|{key}|{','.join(sorted(pointers[key]))}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_index_bytes(data: bytes) -> Index:
    text = _decode_canonical(data, "index")
    lines = text.splitlines()
    header = lines[0].split("|") if lines else []
    if len(header) != 5 or header[:2] != [SCHEMA_VERSION, "I"]:
        raise MemoryError("index: invalid header")
    try:
        count = int(header[2])
    except ValueError as exc:
        raise MemoryError("index: invalid session count") from exc
    if count < 0:
        raise MemoryError("index: negative session count")
    latest = header[3]
    if latest != "-":
        _validate_sid(latest, "index latest session")
    fingerprint = header[4]
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise MemoryError("index: invalid manifest SHA-256")

    pointers: dict[str, tuple[str, ...]] = {}
    prior_key: str | None = None
    for line_no, line in enumerate(lines[1:], start=2):
        parts = line.split("|")
        if len(parts) != 3 or parts[0] != "K":
            raise MemoryError(f"index:{line_no}: invalid pointer record")
        key = parts[1]
        if not KEY_RE.fullmatch(key):
            raise MemoryError(f"index:{line_no}: invalid retrieval key")
        if prior_key is not None and key <= prior_key:
            raise MemoryError("index pointer keys must be strictly sorted")
        prior_key = key
        sids = tuple(parts[2].split(","))
        if not sids or tuple(sorted(set(sids))) != sids:
            raise MemoryError(f"index:{line_no}: session ids must be sorted and unique")
        for sid in sids:
            _validate_sid(sid, "index pointer session id")
        pointers[key] = sids
    return Index(count, latest, fingerprint, pointers, data)


def verify_schema(memory_root: Path) -> None:
    path = memory_root / "SCHEMA.cm"
    if not path.is_file():
        raise MemoryError("missing SCHEMA.cm")
    if path.read_bytes() != SCHEMA_BYTES:
        raise MemoryError("SCHEMA.cm does not match controller-memory CM1 contract")


def expected_index(memory_root: Path) -> bytes:
    return build_index_bytes(load_sessions(memory_root))


def rebuild_index(memory_root: Path) -> bytes:
    verify_schema(memory_root)
    memory_root.mkdir(parents=True, exist_ok=True)
    data = expected_index(memory_root)
    target = memory_root / "INDEX.cm"
    fd, temp_name = tempfile.mkstemp(prefix=".INDEX.", dir=memory_root)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return data


def verify(memory_root: Path) -> Index:
    verify_schema(memory_root)
    verify_ethos(memory_root)
    expected = expected_index(memory_root)
    path = memory_root / "INDEX.cm"
    if not path.is_file():
        raise MemoryError("missing INDEX.cm")
    current = path.read_bytes()
    parsed = parse_index_bytes(current)
    if current != expected:
        raise MemoryError("INDEX.cm drift: rebuild required")
    sessions = load_sessions(memory_root)
    if parsed.session_count != len(sessions):
        raise MemoryError("INDEX.cm session count mismatch")
    if parsed.manifest_sha256 != source_manifest(sessions):
        raise MemoryError("INDEX.cm manifest fingerprint mismatch")
    return parsed


def _load_index(memory_root: Path) -> Index:
    path = memory_root / "INDEX.cm"
    if not path.is_file():
        raise MemoryError("missing INDEX.cm")
    return parse_index_bytes(path.read_bytes())


def bootstrap(memory_root: Path) -> bytes:
    verify_schema(memory_root)
    ethos = verify_ethos(memory_root)
    index = _load_index(memory_root)
    return b"CM1|B\n" + ethos.raw + index.raw


def query(memory_root: Path, key: str) -> bytes:
    if not KEY_RE.fullmatch(key):
        raise MemoryError(f"invalid retrieval key {key!r}")
    verify_schema(memory_root)
    index = _load_index(memory_root)
    sids = index.pointers.get(key, ())
    lines = [f"{SCHEMA_VERSION}|Q|{key}|{len(sids)}"]
    for sid in sids:
        path = memory_root / "sessions" / f"{sid}.cm"
        session = parse_session_file(path)
        matches = [record.raw for record in session.records if key in record.keys]
        if not matches:
            raise MemoryError(f"index/session drift for key {key!r}, session {sid}")
        lines.append(
            f"S|{session.sid}|{session.timestamp}|{session.main_sha}|{session.prev_sid}"
        )
        lines.extend(matches)
    return ("\n".join(lines) + "\n").encode("utf-8")


def handoff(memory_root: Path, prepared_session: Path) -> Path:
    data = prepared_session.read_bytes()
    session = parse_session_bytes(data, expected_filename=prepared_session.name)
    verify_schema(memory_root)
    sessions_dir = memory_root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    target = sessions_dir / prepared_session.name
    try:
        with target.open("xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except FileExistsError as exc:
        raise MemoryError(f"session already exists and is immutable: {session.sid}") from exc
    rebuild_index(memory_root)
    return target


def _write_stdout(data: bytes) -> None:
    import sys
    sys.stdout.buffer.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic compact controller-memory manager (CM1)."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_MEMORY_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap")
    q = commands.add_parser("query")
    q.add_argument("key")
    commands.add_parser("verify")
    commands.add_parser("rebuild")
    h = commands.add_parser("handoff")
    h.add_argument("session", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "bootstrap":
            _write_stdout(bootstrap(args.root))
        elif args.command == "query":
            _write_stdout(query(args.root, args.key))
        elif args.command == "verify":
            index = verify(args.root)
            ethos = verify_ethos(args.root)
            print(
                f"{SCHEMA_VERSION}|V|1|H{ethos.version}|{index.session_count}|"
                f"{index.latest_sid}|{index.manifest_sha256}"
            )
        elif args.command == "rebuild":
            _write_stdout(rebuild_index(args.root))
        else:
            target = handoff(args.root, args.session)
            print(f"{SCHEMA_VERSION}|H|1|{target.name}")
        return 0
    except (MemoryError, OSError) as exc:
        import sys
        print(f"CONTROLLER_MEMORY_FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
