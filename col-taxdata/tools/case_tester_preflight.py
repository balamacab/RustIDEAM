#!/usr/bin/env python3
from __future__ import annotations

import importlib
from importlib import metadata
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-case-tester.txt"

REQUIRED_MODULES = {
    "yaml": "PyYAML",
    "jsonschema": "jsonschema",
    "requests": "requests",
}

EXPECTED_CASE_CONTRACT = "4.0.0"
EXPECTED_REST_CONTRACT = "1.0.0"
EXPECTED_REST_ENDPOINT = "/v1/cases"


def _declared_versions() -> dict[str, str]:
    declared: dict[str, str] = {}
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise RuntimeError(
                f"case-tester dependency must use an exact == pin: {line}"
            )
        distribution, version = line.split("==", 1)
        distribution = distribution.strip()
        version = version.strip()
        if not distribution or not version:
            raise RuntimeError(f"invalid case-tester dependency pin: {line}")
        declared[distribution.casefold()] = version
    return declared


def _dependency_status() -> dict[str, dict[str, object]]:
    declared = _declared_versions()
    result: dict[str, dict[str, object]] = {}
    for module_name, distribution in REQUIRED_MODULES.items():
        importable = importlib.util.find_spec(module_name) is not None
        installed_version = None
        version_match = False
        if importable:
            installed_version = metadata.version(distribution)
            expected = declared.get(distribution.casefold())
            version_match = installed_version == expected
        result[module_name] = {
            "distribution": distribution,
            "importable": importable,
            "declared_version": declared.get(distribution.casefold()),
            "installed_version": installed_version,
            "version_match": version_match,
        }
    return result


def main() -> int:
    dependencies = _dependency_status()

    from case_contract_validation_v4 import CONTRACT_VERSION
    from case_rest_api import API_VERSION, DEFAULT_ENDPOINT

    payload = {
        "status": "PASS",
        "case_contract_version": CONTRACT_VERSION,
        "rest_api_version": API_VERSION,
        "rest_endpoint": DEFAULT_ENDPOINT,
        "dependencies": dependencies,
    }

    failures: list[str] = []
    if CONTRACT_VERSION != EXPECTED_CASE_CONTRACT:
        failures.append(
            f"CASE contract drift: {CONTRACT_VERSION} != {EXPECTED_CASE_CONTRACT}"
        )
    if API_VERSION != EXPECTED_REST_CONTRACT:
        failures.append(
            f"REST contract drift: {API_VERSION} != {EXPECTED_REST_CONTRACT}"
        )
    if DEFAULT_ENDPOINT != EXPECTED_REST_ENDPOINT:
        failures.append(
            f"REST endpoint drift: {DEFAULT_ENDPOINT} != {EXPECTED_REST_ENDPOINT}"
        )

    for module_name, state in dependencies.items():
        if not state["importable"]:
            failures.append(f"missing harness module: {module_name}")
        elif not state["version_match"]:
            failures.append(
                "harness dependency version drift: "
                f"{state['distribution']} installed={state['installed_version']} "
                f"declared={state['declared_version']}"
            )

    if failures:
        payload["status"] = "FAIL"
        payload["failures"] = failures

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
