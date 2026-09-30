from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "compose.case.yaml"
REMOTE_COMPOSE = ROOT / "compose.case.remote.yaml"
EXAMPLE_ENV = ROOT / "docs" / "case-compose.env.example"
DEPLOYMENT_DOC = ROOT / "docs" / "case-compose-deployment.md"

REVISION = "0123456789abcdef0123456789abcdef01234567"


class Issue0307CaseComposeStackTests(unittest.TestCase):
    """Static/declarative validation for the crawler-free CASE application stack."""

    def _compose_json(self, *, remote: bool = False) -> dict:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("docker CLI is unavailable for compose config validation")
        version = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if version.returncode != 0:
            self.skipTest("docker compose plugin is unavailable")

        command = [
            docker,
            "compose",
            "--env-file",
            str(EXAMPLE_ENV),
            "-f",
            str(BASE_COMPOSE),
        ]
        if remote:
            command.extend(["-f", str(REMOTE_COMPOSE)])
        command.extend(["config", "--format", "json"])

        # Keep host-specific deployment variables from overriding the committed
        # example. Docker Compose itself still receives PATH/HOME as usual.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        }
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(
                "docker compose config failed:\n"
                + completed.stdout
                + completed.stderr
            )
        return json.loads(completed.stdout)

    def test_base_compose_renders_exact_three_service_topology(self) -> None:
        rendered = self._compose_json()
        services = rendered["services"]

        self.assertEqual(set(services), {"case-rest", "case-web", "case-mcp"})
        self.assertEqual(
            services["case-rest"]["command"][:2],
            ["python3", "tools/case_rest_runtime_v2.py"],
        )
        self.assertNotIn("taxdata", services)
        self.assertNotIn("case-tester", services)

        for name in services:
            self.assertEqual(set(services[name]["networks"]), {"case-app"})
            self.assertEqual(services[name]["restart"], "unless-stopped")
            self.assertIn("healthcheck", services[name])

        for name in ("case-web", "case-mcp"):
            self.assertEqual(
                services[name]["depends_on"]["case-rest"]["condition"],
                "service_healthy",
            )

        self.assertEqual(
            services["case-web"]["environment"]["CASE_API_UPSTREAM"],
            "http://case-rest:8766",
        )
        self.assertEqual(
            services["case-mcp"]["environment"]["CASE_REST_BASE_URL"],
            "http://case-rest:8766",
        )

    def test_only_case_rest_receives_external_state_mounts(self) -> None:
        services = self._compose_json()["services"]

        self.assertEqual(services["case-web"].get("volumes", []), [])
        self.assertEqual(services["case-mcp"].get("volumes", []), [])

        mounts = {
            item["target"]: item
            for item in services["case-rest"]["volumes"]
        }
        self.assertEqual(
            set(mounts),
            {
                "/runtime/corpus/taxdata.sqlite",
                "/runtime/case-state",
                "/run/col-taxdata/llm-profile.json",
            },
        )
        self.assertFalse(
            mounts["/runtime/corpus/taxdata.sqlite"]["bind"]["create_host_path"]
        )
        self.assertFalse(
            mounts["/runtime/case-state"]["bind"]["create_host_path"]
        )
        self.assertFalse(
            mounts["/run/col-taxdata/llm-profile.json"]["bind"][
                "create_host_path"
            ]
        )
        self.assertTrue(
            mounts["/run/col-taxdata/llm-profile.json"]["read_only"]
        )
        self.assertNotIn("/app/data", str(services["case-rest"]["volumes"]))
        self.assertNotIn("/raw", str(services["case-rest"]["volumes"]))

    def test_provider_and_host_bind_contract_are_explicit(self) -> None:
        services = self._compose_json()["services"]
        case = services["case-rest"]

        self.assertEqual(
            case["environment"]["COL_TAXDATA_LLM_BASE_URL"],
            "http://provider.example:8080/v1",
        )
        self.assertEqual(
            case["environment"]["COL_TAXDATA_LLM_CONFIG"],
            "/run/col-taxdata/llm-profile.json",
        )
        self.assertEqual(case["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(case["ports"][0]["published"], "18766")
        self.assertEqual(services["case-web"]["ports"][0]["published"], "18080")
        self.assertEqual(services["case-mcp"]["ports"][0]["published"], "18000")

        compose_text = BASE_COMPOSE.read_text(encoding="utf-8")
        self.assertIn("COL_TAXDATA_PROVIDER_BASE_URL:?", compose_text)
        self.assertNotIn("host.docker.internal", compose_text)

    def test_immutable_override_binds_all_builds_and_tags_to_one_revision(self) -> None:
        rendered = self._compose_json(remote=True)
        services = rendered["services"]
        expected = {
            "case-rest": (
                "col-taxdata",
                "col-taxdata-case-rest",
            ),
            "case-web": (
                "col-taxdata/web/case-console",
                "col-taxdata-web-console",
            ),
            "case-mcp": (
                "col-taxdata/mcp_gateway",
                "col-taxdata-mcp",
            ),
        }

        for name, (subdir, image_name) in expected.items():
            context = services[name]["build"]["context"]
            self.assertEqual(
                context,
                "https://github.com/balamacab/RustIDEAM.git#"
                + REVISION
                + ":"
                + subdir,
            )
            self.assertEqual(
                services[name]["image"],
                f"{image_name}:{REVISION}",
            )

        remote_text = REMOTE_COMPOSE.read_text(encoding="utf-8")
        self.assertEqual(remote_text.count("${COL_TAXDATA_REVISION:?"), 6)
        self.assertNotIn("host.docker.internal", remote_text)

    def test_documentation_covers_standard_lifecycle_and_no_secret_default(self) -> None:
        doc = DEPLOYMENT_DOC.read_text(encoding="utf-8")
        example = EXAMPLE_ENV.read_text(encoding="utf-8")

        self.assertIn("up -d --build", doc)
        self.assertIn(" compose.case.yaml ps", doc.replace("\\\n", " "))
        self.assertIn(" compose.case.yaml down", doc.replace("\\\n", " "))
        self.assertIn("compose.case.remote.yaml", doc)
        self.assertIn("COL_TAXDATA_REVISION", doc)
        self.assertIn("create_host_path: false", doc)
        self.assertIn("Web and MCP", doc)
        self.assertIn("no SQLite", doc)
        self.assertIn("COL_TAXDATA_LLM_API_KEY=", example)
        self.assertNotIn("COL_TAXDATA_LLM_API_KEY=sk-", example)


if __name__ == "__main__":
    unittest.main()
