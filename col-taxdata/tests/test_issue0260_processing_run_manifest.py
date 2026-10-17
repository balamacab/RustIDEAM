"""Contract regressions for bounded processing manifest serialization (#260)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from config_fingerprint import ConfigFingerprint, fingerprint_bytes  # noqa: E402
from migration_fingerprint import fingerprint_applied_migrations  # noqa: E402
from processing_run_manifest import (  # noqa: E402
    ManifestError, make_run_manifest, serialize_run_manifest,
)

SHA = "a" * 40
MIGRATION_SHA = "b" * 64


def facts(**changes):
    values = dict(
        run_id="run-123", pipeline="ingest", tool_name="col-taxdata",
        git_commit_sha=SHA, tool_version="1.2.3", input_sha256="c" * 64,
        python_version="3.12.4", runtime_platform="linux-x86_64",
        container_digest="sha256:" + "d" * 64,
        config_fingerprint=fingerprint_bytes(b'{"token":"PRIVATE-SECRET-DO-NOT-EMIT"}'),
        migration_fingerprint=fingerprint_applied_migrations(
            [("001_setup.sql", MIGRATION_SHA)]),
    )
    values.update(changes)
    return values


class ManifestTests(unittest.TestCase):
    def test_deterministic_canonical_serialization(self):
        first = serialize_run_manifest(**facts())
        second = serialize_run_manifest(**facts())
        self.assertEqual(first, second)
        self.assertEqual(first, json.dumps(json.loads(first), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode() + b"\n")

    def test_schema_kind_version_and_source(self):
        m = make_run_manifest(**facts())
        self.assertEqual(m["schema_version"], 1)
        self.assertEqual(m["kind"], "col-taxdata-processing-run")
        self.assertEqual(m["source"]["git_commit_sha"],
                         {"status": "available", "value": SHA})

    def test_reuses_canonical_configuration_hash(self):
        m = make_run_manifest(**facts())
        self.assertEqual(m["configuration"]["sha256"],
                         facts()["config_fingerprint"].sha256)

    def test_reuses_ordered_migration_digest_and_count(self):
        m = make_run_manifest(**facts())
        self.assertEqual(m["migrations"]["sha256"],
                         facts()["migration_fingerprint"].sha256)
        self.assertEqual(m["migrations"]["count"], 1)
        reversed_mig = fingerprint_applied_migrations(
            [("002_second.sql", MIGRATION_SHA), ("001_setup.sql", "c" * 64)])
        normal_mig = fingerprint_applied_migrations(
            [("001_setup.sql", "c" * 64), ("002_second.sql", MIGRATION_SHA)])
        self.assertNotEqual(
            make_run_manifest(**facts(migration_fingerprint=reversed_mig))["migrations"],
            make_run_manifest(**facts(migration_fingerprint=normal_mig))["migrations"],
        )

    def test_missing_revisions_do_not_imply_current_main(self):
        m = make_run_manifest(**facts(
            git_commit_sha=None, tool_version=None, python_version=None,
            runtime_platform=None, container_digest=None, input_sha256=None,
        ))
        self.assertEqual(m["source"]["git_commit_sha"],
                         {"status": "unavailable", "reason": "not_supplied"})
        self.assertEqual(m["runtime"]["container_digest"]["status"], "unavailable")

    def test_unavailable_config_is_not_empty_hash(self):
        m = make_run_manifest(**facts(
            config_fingerprint=ConfigFingerprint("unavailable", reason="not_found"),
        ))
        self.assertEqual(m["configuration"],
                         {"status": "unavailable", "reason": "not_found"})

    def test_unavailable_migrations_distinct_from_empty(self):
        unknown = make_run_manifest(**facts(
            migration_fingerprint=fingerprint_applied_migrations(None)))
        empty = make_run_manifest(**facts(
            migration_fingerprint=fingerprint_applied_migrations([])))
        self.assertEqual(unknown["migrations"]["status"], "unavailable")
        self.assertEqual(empty["migrations"]["count"], 0)
        self.assertNotEqual(unknown["migrations"], empty["migrations"])

    def test_inconsistent_migration_state_preserved(self):
        m = make_run_manifest(**facts(
            migration_fingerprint=fingerprint_applied_migrations(
                [("bad.sql", "invalid")])
        ))
        self.assertEqual(m["migrations"]["status"], "inconsistent")

    def test_no_raw_config_or_secrets_leaked(self):
        encoded = serialize_run_manifest(**facts())
        for forbidden in (b"PRIVATE-SECRET", b"token", b"password", b"Authorization"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(set(json.loads(encoded)),
                         {"kind", "schema_version", "run", "tool",
                          "source", "configuration", "migrations",
                          "input", "runtime"})

    def test_unknown_fields_disallowed(self):
        with self.assertRaises(TypeError):
            serialize_run_manifest(**facts(api_key="SHOULD-NOT-APPEAR"))

    def test_invalid_shas_rejected_without_echoing_content(self):
        for key, value in (
            ("git_commit_sha", "redacted"), ("input_sha256", "wrong"),
            ("container_digest", "sha256:short"),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ManifestError) as context:
                    serialize_run_manifest(**facts(**{key: value}))
                self.assertNotIn(value, str(context.exception))

    def test_invalid_required_fingerprint_types_rejected(self):
        with self.assertRaises(ManifestError):
            make_run_manifest(**facts(config_fingerprint=None))
        with self.assertRaises(ManifestError):
            make_run_manifest(**facts(migration_fingerprint=None))

    def test_no_implicit_time_or_host_drift(self):
        m = make_run_manifest(**facts())
        self.assertNotIn("timestamp", str(m))
        self.assertNotIn("hostname", str(m))


if __name__ == "__main__":
    unittest.main()
