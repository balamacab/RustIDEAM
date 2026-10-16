"""Contract tests for issue #258's SHA-256 configuration primitive."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from config_fingerprint import (  # noqa: E402
    canonical_json_bytes,
    fingerprint_bytes,
    fingerprint_file,
    fingerprint_json,
)


class ConfigFingerprintTests(unittest.TestCase):
    def test_known_sha_and_changed_content(self):
        self.assertEqual(
            fingerprint_bytes(b"abc").sha256,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(fingerprint_bytes(b"abc"), fingerprint_bytes(b"abc"))
        self.assertNotEqual(fingerprint_bytes(b"abc"), fingerprint_bytes(b"abd"))
        self.assertEqual(fingerprint_bytes(b"").sha256, hashlib.sha256(b"").hexdigest())

    def test_content_identity_excludes_path_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "alpha.json"
            b = root / "renamed.yaml"
            a.write_bytes(b"same content")
            b.write_bytes(b"same content")
            self.assertEqual(fingerprint_file(a), fingerprint_file(b))
            b.write_bytes(b"changed content")
            self.assertNotEqual(fingerprint_file(a), fingerprint_file(b))

    def test_canonical_json_ignores_map_insertion_order(self):
        lhs = {"z": [True, None, 3], "a": {"b": "ñ", "a": 1}}
        rhs = {"a": {"a": 1, "b": "ñ"}, "z": [True, None, 3]}
        self.assertEqual(canonical_json_bytes(lhs), canonical_json_bytes(rhs))
        self.assertEqual(fingerprint_json(lhs), fingerprint_json(rhs))
        self.assertNotEqual(fingerprint_json(lhs), fingerprint_json({**rhs, "x": 1}))
        self.assertNotEqual(fingerprint_json([1, 2]), fingerprint_json([2, 1]))

    def test_json_rejects_ambiguous_object_keys(self):
        with self.assertRaisesRegex(ValueError, "cannot be serialized"):
            fingerprint_json({1: "one"})
        with self.assertRaisesRegex(ValueError, "cannot be serialized"):
            fingerprint_json({"nested": [{None: "null"}]})

    def test_missing_is_never_the_empty_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = fingerprint_file(Path(tmp) / "missing")
        self.assertEqual((absent.status, absent.sha256, absent.reason),
                         ("unavailable", None, "not_found"))
        self.assertNotEqual(absent, fingerprint_bytes(b""))

    def test_non_regular_input_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = fingerprint_file(tmp)
            self.assertEqual((result.status, result.reason),
                             ("unavailable", "not_regular_file"))

    def test_secret_safe_failure_messages_and_results(self):
        secret = "PRIVATE_CANARY_SECRET_DO_NOT_ECHO"
        with self.assertRaises(ValueError) as caught:
            fingerprint_json({"token": secret, "not_serializable": {1, 2}})
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(TypeError) as wrong_type:
            fingerprint_bytes(secret)  # type: ignore[arg-type]
        self.assertNotIn(secret, str(wrong_type.exception))
        with tempfile.TemporaryDirectory(prefix=secret) as tmp:
            absent = fingerprint_file(Path(tmp) / secret)
            self.assertNotIn(secret, repr(absent))
            self.assertNotIn(secret, str(absent.reason))
        with self.assertRaises(ValueError):
            fingerprint_json({"invalid": float("nan")})


if __name__ == "__main__":
    unittest.main()
