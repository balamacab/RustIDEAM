"""Optional SHA-pinned Docker build path for reproducible source execution (#268).

Explicit full commit SHA, immutable Git build context, and SHA-labelled image.
The default invocation performs no build. Existing compose.remote.yaml is
untouched and remains the convenient moving-main development path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REMOTE = "https://github.com/balamacab/RustIDEAM.git"
_COMPOSE_NAME = "compose.pinned.yaml"


class SourceRevisionError(ValueError):
    """Invalid or unverified source revision, without leaking input content."""


def validate_commit_sha(sha: str) -> str:
    """Require an exact lowercase forty-hex commit, never an abbreviated ref."""
    if type(sha) is not str or not _COMMIT.fullmatch(sha):
        raise SourceRevisionError("source revision requires exact 40-hex lowercase commit SHA")
    return sha


def pinned_build_context(sha: str) -> str:
    """Return Docker's immutable remote-Git-context reference for col-taxdata."""
    return f"{_REMOTE}#{validate_commit_sha(sha)}:col-taxdata"


def verify_local_revision(repository: str | Path, sha: str) -> str:
    """Verify commit object existence locally; never replace it with moving HEAD.

    This check is optional when building directly from the Docker remote Git
    context. If supplied, a missing repository or commit fails closed.
    """
    expected = validate_commit_sha(sha)
    path = Path(repository)
    if not path.is_dir():
        raise SourceRevisionError("local source repository unavailable")
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--verify", f"{expected}^{{commit}}"],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise SourceRevisionError("local source revision unavailable") from None
    if result.stdout.strip() != expected:
        raise SourceRevisionError("local source identity mismatch")
    return expected


def build_spec(sha: str, *, compose_path: str | Path | None = None) -> dict[str, str]:
    """Return a deterministic, side-effect-free build identity specification."""
    revision = validate_commit_sha(sha)
    path = Path(compose_path) if compose_path is not None else Path(__file__).resolve().parents[1] / _COMPOSE_NAME
    if not path.is_file():
        raise SourceRevisionError("pinned compose definition unavailable")
    return {
        "source_commit_sha": revision,
        "build_context": pinned_build_context(revision),
        "image": f"col-taxdata:{revision}",
        "compose_file": str(path.resolve()),
    }


def build_pinned_image(sha: str, *, compose_path: str | Path | None = None) -> dict[str, str]:
    """Build a local image via Docker Compose; never launch containers.

    Compose uses the identical full SHA for remote build context, image tag
    and a runtime provenance field. Docker must reject unavailable revisions;
    this method never retries against HEAD, a branch or a floating tag.
    """
    spec = build_spec(sha, compose_path=compose_path)
    env = dict(os.environ)
    env["COL_TAXDATA_SOURCE_SHA"] = spec["source_commit_sha"]
    try:
        subprocess.run(
            ["docker", "compose", "--file", spec["compose_file"], "build", "taxdata"],
            env=env, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise SourceRevisionError("pinned source build unavailable") from None
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="Exact 40-hex Git commit SHA")
    parser.add_argument("--verify-local", metavar="REPO",
                        help="Optionally require this local repository to contain the exact commit")
    parser.add_argument("--build", action="store_true",
                        help="Build only the pinned image; no container launch")
    args = parser.parse_args(argv)
    try:
        spec = build_spec(args.commit)
        if args.verify_local:
            verify_local_revision(args.verify_local, args.commit)
        if args.build:
            spec = build_pinned_image(args.commit)
    except SourceRevisionError as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "built" if args.build else "planned",
                      "identity": spec}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
