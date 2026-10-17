"""Deterministic regressions for pinned executable source identity (#268)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import build_pinned_source as pinned  # noqa: E402

SHA = "a" * 40


def git(repo: Path, *argv: str) -> str:
    cmd = ["git", "-C", str(repo), *argv]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


class PinnedSourceTests(unittest.TestCase):
    def test_exact_sha_validation(self):
        self.assertEqual(pinned.validate_commit_sha(SHA), SHA)
        for invalid in ("main", "HEAD", SHA[:12], SHA.upper(), SHA + "z",
                        "", "../main", "a" * 39, None, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(pinned.SourceRevisionError):
                    pinned.validate_commit_sha(invalid)

    def test_remote_git_context_contains_exact_commit(self):
        self.assertEqual(pinned.pinned_build_context(SHA),
                         "https://github.com/balamacab/RustIDEAM.git#" +
                         SHA + ":col-taxdata")
        self.assertNotIn("#main", pinned.pinned_build_context(SHA))

    def test_spec_is_deterministic_and_requires_compose(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "compose.pinned.yaml"
            path.write_text("services: {}\n", encoding="utf-8")
            a = pinned.build_spec(SHA, compose_path=path)
            b = pinned.build_spec(SHA, compose_path=path)
            self.assertEqual(a, b)
            self.assertEqual(a["source_commit_sha"], SHA)
            self.assertEqual(a["image"], f"col-taxdata:{SHA}")
            path.unlink()
            with self.assertRaises(pinned.SourceRevisionError):
                pinned.build_spec(SHA, compose_path=path)

    def test_missing_commit_is_not_assumed_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init")
            with self.assertRaisesRegex(pinned.SourceRevisionError,
                                        "local source revision unavailable"):
                pinned.verify_local_revision(repo, SHA)

    def test_nonexistent_checkout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pinned.SourceRevisionError,
                                        "local source repository unavailable"):
                pinned.verify_local_revision(Path(tmp) / "absent", SHA)

    def test_moving_head_does_not_change_old_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init")
            (repo / "proof.txt").write_text("revision one", encoding="utf-8")
            git(repo, "add", "proof.txt")
            git(repo, "-c", "user.name=ci", "-c",
                "user.email=ci@example.test", "commit", "-m", "one")
            first = git(repo, "rev-parse", "HEAD")
            self.assertEqual(pinned.verify_local_revision(repo, first), first)
            (repo / "proof.txt").write_text("revision two", encoding="utf-8")
            git(repo, "add", "proof.txt")
            git(repo, "-c", "user.name=ci", "-c",
                "user.email=ci@example.test", "commit", "-m", "two")
            second = git(repo, "rev-parse", "HEAD")
            self.assertNotEqual(first, second)
            self.assertEqual(pinned.verify_local_revision(repo, first), first)
            self.assertIn("#" + first + ":col-taxdata",
                          pinned.pinned_build_context(first))

    def test_build_invokes_docker_only_with_explicit_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "compose.pinned.yaml"
            path.write_text("services: {}\n", encoding="utf-8")
            with patch.object(pinned.subprocess, "run") as run:
                spec = pinned.build_pinned_image(SHA, compose_path=path)
                run.assert_called_once()
                args = run.call_args
                self.assertEqual(args.args[0],
                                 ["docker", "compose", "--file", str(path), "build",
                                  "taxdata"])
                self.assertEqual(args.kwargs["env"]["COL_TAXDATA_SOURCE_SHA"], SHA)
                self.assertTrue(args.kwargs["check"])
            self.assertEqual(spec["source_commit_sha"], SHA)

    def test_invalid_sha_never_calls_docker(self):
        with patch.object(pinned.subprocess, "run") as run:
            with self.assertRaises(pinned.SourceRevisionError):
                pinned.build_pinned_image("main")
            run.assert_not_called()

    def test_build_failure_is_not_silent_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compose.pinned.yaml"
            path.write_text("services: {}\n", encoding="utf-8")
            with patch.object(pinned.subprocess, "run", side_effect=OSError):
                with self.assertRaisesRegex(pinned.SourceRevisionError,
                                            "pinned source build unavailable"):
                    pinned.build_pinned_image(SHA, compose_path=path)

    def test_default_cli_is_non_mutating_and_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "compose.pinned.yaml"
            path.write_text("services: {}\n", encoding="utf-8")
            with patch.object(pinned, "build_spec",
                              return_value=pinned.build_spec(SHA, compose_path=path)):
                with patch.object(pinned, "build_pinned_image") as build:
                    with patch("sys.stdout") as out:
                        self.assertEqual(pinned.main(["--commit", SHA]), 0)
                    build.assert_not_called()
                    self.assertTrue(out.write.called)

    def test_compose_identity_contract(self):
        text = (TOOLS.parent / "compose.pinned.yaml").read_text(encoding="utf-8")
        self.assertIn("#${COL_TAXDATA_SOURCE_SHA:", text)
        self.assertIn("col-taxdata:${COL_TAXDATA_SOURCE_SHA:", text)
        self.assertIn("org.opencontainers.image.revision:", text)
        self.assertIn("restart: \"no\"", text)

    def test_default_moving_main_workflow_not_replaced(self):
        remote = (TOOLS.parent / "compose.remote.yaml").read_text(encoding="utf-8")
        self.assertIn("#main:col-taxdata", remote)
        self.assertNotIn("COL_TAXDATA_SOURCE_SHA", remote)


if __name__ == "__main__":
    unittest.main()
