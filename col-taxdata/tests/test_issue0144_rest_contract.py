from __future__ import annotations

from copy import deepcopy
import hashlib
from http import HTTPStatus
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlrequest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import CaseContractError
from case_rest_api import (
    API_VERSION,
    CASE_API_INTEGRITY_FAILURE,
    CASE_API_INVALID_REQUEST,
    CASE_API_METHOD_NOT_ALLOWED,
    CASE_API_NOT_FOUND,
    CASE_API_SERVICE_UNAVAILABLE,
    CaseRESTApplication,
    CaseRESTServer,
    CaseRESTUnavailable,
    DEFAULT_ENDPOINT,
    prepare_case_request,
    validate_error_payload,
    validate_success_payload,
)


SPEC_ROOT = ROOT / "specs" / "application"
OPENAPI_PATH = SPEC_ROOT / "openapi" / "case-rest-api-v1.openapi.json"
TRANSPORT_SCHEMA_PATH = SPEC_ROOT / "schemas" / "case-rest-api-v1.schema.json"
EXAMPLE_ROOT = SPEC_ROOT / "examples" / "case-rest-v1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def complete_response() -> dict:
    return load_json(EXAMPLE_ROOT / "complete-response.json")


def request_bytes() -> bytes:
    return (EXAMPLE_ROOT / "request.json").read_bytes()


def _resolve_pointer(document: object, fragment: str) -> object:
    if not fragment:
        return document
    if not fragment.startswith("/"):
        raise AssertionError(f"unsupported JSON pointer: {fragment!r}")
    node = document
    for raw in fragment[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(key)]
        elif isinstance(node, dict):
            node = node[key]
        else:
            raise AssertionError(f"pointer crosses scalar at {key!r}")
    return node


def assert_external_refs_resolve(test: unittest.TestCase, source_path: Path) -> None:
    document = load_json(source_path)

    def walk(value: object) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                target_name, _separator, fragment = ref.partition("#")
                target_path = (source_path.parent / target_name).resolve()
                test.assertTrue(
                    target_path.is_file(),
                    f"external reference target missing: {ref}",
                )
                target = load_json(target_path)
                _resolve_pointer(target, fragment)
                test.assertNotIn("/tools/", target_path.as_posix())
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)


class RunningServer:
    def __init__(
        self,
        researcher,
        *,
        max_request_bytes: int = 1024 * 1024,
    ):
        self.server = CaseRESTServer(
            ("127.0.0.1", 0),
            CaseRESTApplication(researcher),
            max_request_bytes=max_request_bytes,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Issue0144PublishedContractTests(unittest.TestCase):
    def test_openapi_and_referenced_contract_artifacts_resolve(self):
        openapi = load_json(OPENAPI_PATH)
        self.assertEqual(openapi["openapi"], "3.1.0")
        self.assertEqual(openapi["info"]["version"], API_VERSION)
        operation = openapi["paths"][DEFAULT_ENDPOINT]["post"]
        self.assertEqual(operation["operationId"], "researchCase")
        self.assertIn("200", operation["responses"])
        for status in ("400", "404", "405", "411", "413", "415", "500", "503", "504"):
            self.assertIn(status, operation["responses"])

        assert_external_refs_resolve(self, OPENAPI_PATH)
        assert_external_refs_resolve(self, TRANSPORT_SCHEMA_PATH)

        serialized = json.dumps(openapi, sort_keys=True)
        self.assertNotIn("tools/", serialized)
        self.assertNotIn("sqlite", serialized.lower())
        self.assertNotIn("filesystem", serialized.lower())

    def test_request_example_builds_exact_v4_case_input(self):
        raw = request_bytes()
        external = json.loads(raw)
        prepared = prepare_case_request(raw)

        self.assertEqual(prepared.case_input["kind"], "case_input")
        self.assertEqual(prepared.case_input["contract_version"], "4.0.0")
        for name, value in external.items():
            self.assertEqual(prepared.case_input[name], value)

        self.assertEqual(
            prepared.raw_request_sha256,
            hashlib.sha256(raw).hexdigest(),
        )

        equivalent = json.dumps(
            external,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        second = prepare_case_request(equivalent)
        self.assertNotEqual(
            prepared.raw_request_sha256,
            second.raw_request_sha256,
        )
        self.assertEqual(
            prepared.case_input_sha256,
            second.case_input_sha256,
        )

    def test_as_of_date_and_other_optional_caller_fields_remain_optional(self):
        raw = json.dumps(
            {"problem_text": "Consulta autosuficiente."},
            ensure_ascii=False,
        ).encode("utf-8")
        prepared = prepare_case_request(raw)
        self.assertEqual(
            set(prepared.case_input),
            {"kind", "contract_version", "problem_text"},
        )

    def test_complete_partial_and_unresolved_examples_validate(self):
        cases = {
            "complete-response.json": "complete",
            "partial-response.json": "partial",
            "unresolved-response.json": "blocked",
        }
        for filename, status in cases.items():
            with self.subTest(filename=filename):
                payload = load_json(EXAMPLE_ROOT / filename)
                validate_success_payload(payload)
                self.assertEqual(payload["bundle"]["status"], status)

        partial = load_json(EXAMPLE_ROOT / "partial-response.json")
        self.assertEqual(
            partial["bundle"]["unresolved"][0]["category"],
            "requires_interpretive_synthesis",
        )
        blocked = load_json(EXAMPLE_ROOT / "unresolved-response.json")
        self.assertIsInstance(blocked["bundle"]["unresolved"], list)
        self.assertTrue(blocked["bundle"]["unresolved"])

    def test_error_examples_use_only_stable_public_envelope(self):
        for filename in (
            "invalid-request-error.json",
            "service-unavailable-error.json",
        ):
            with self.subTest(filename=filename):
                payload = load_json(EXAMPLE_ROOT / filename)
                validate_error_payload(payload)
                self.assertNotIn("detail", payload["error"])
                self.assertNotIn("context", payload["error"])
                self.assertNotIn("provider", payload["error"])
                self.assertNotIn("path", payload["error"])

    def test_external_fixtures_require_no_backend_source_import(self):
        for path in sorted(EXAMPLE_ROOT.glob("*.json")):
            with self.subTest(path=path.name):
                parsed = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(parsed, dict)


class Issue0144RequestBoundaryTests(unittest.TestCase):
    def test_internal_ids_evidence_provider_controls_and_files_fail_closed(self):
        forbidden = {
            "case_id": "CASE-forged",
            "document_ref": "document:forged",
            "evidence_refs": ["evidence:forged"],
            "provider": "attacker-selected",
            "model": "attacker-selected",
            "backend": "attacker-selected",
            "attachments": ["payload.pdf"],
            "file_path": "/tmp/payload.pdf",
            "document_url": "https://example.invalid/untrusted.pdf",
            "ocr_payload": "pretend-ocr",
        }
        base = {"problem_text": "Consulta."}
        for field, value in forbidden.items():
            with self.subTest(field=field):
                raw = json.dumps({**base, field: value}).encode("utf-8")
                with self.assertRaises(CaseContractError):
                    prepare_case_request(raw)

    def test_reserved_server_controls_cannot_hide_in_caller_metadata(self):
        for field in (
            "provider",
            "model",
            "document_ref",
            "evidence_bindings",
            "api_key",
            "attachments",
            "document_url",
        ):
            with self.subTest(field=field):
                raw = json.dumps(
                    {
                        "problem_text": "Consulta.",
                        "caller_metadata": {field: "forged"},
                    }
                ).encode("utf-8")
                with self.assertRaises(CaseContractError):
                    prepare_case_request(raw)

    def test_normal_scalar_caller_metadata_is_preserved(self):
        raw = json.dumps(
            {
                "problem_text": "Consulta.",
                "caller_metadata": {
                    "channel": "mcp",
                    "attempt": 2,
                    "review": False,
                    "nullable": None,
                },
            }
        ).encode("utf-8")
        prepared = prepare_case_request(raw)
        self.assertEqual(
            prepared.case_input["caller_metadata"],
            {
                "channel": "mcp",
                "attempt": 2,
                "review": False,
                "nullable": None,
            },
        )


class Issue0144LiveAdapterTests(unittest.TestCase):
    def test_live_http_adapter_returns_only_contract_success_surface(self):
        fixture = complete_response()
        captured: list[dict] = []

        def researcher(case_input: dict) -> dict:
            captured.append(deepcopy(case_input))
            return deepcopy(fixture["bundle"])

        with RunningServer(researcher) as running:
            req = urlrequest.Request(
                running.base_url + DEFAULT_ENDPOINT,
                data=request_bytes(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            audit_log = io.StringIO()
            with mock.patch("case_rest_api.sys.stderr", audit_log):
                with urlrequest.urlopen(req, timeout=3) as response:
                    payload = json.loads(response.read())
                    headers = response.headers
                    status = response.status

        self.assertEqual(status, HTTPStatus.OK)
        validate_success_payload(payload)
        self.assertEqual(headers["X-Col-Taxdata-API-Version"], API_VERSION)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(
            set(payload),
            {"api_version", "request_fingerprints", "bundle"},
        )
        self.assertNotIn("persistence", payload)
        self.assertNotIn("case_id", payload)
        self.assertEqual(captured, [payload["bundle"]["case_input"]])

        audit = json.loads(audit_log.getvalue().strip())
        self.assertEqual(audit["event"], "case_rest_api_request")
        self.assertEqual(audit["bundle_ref"], payload["bundle"]["bundle_ref"])
        self.assertNotIn("problem_text", audit)

    def test_invalid_external_field_is_400_with_raw_fingerprint_only(self):
        def unreachable(_case_input: dict) -> dict:
            self.fail("researcher must not run for invalid public input")

        raw = json.dumps(
            {"problem_text": "Consulta.", "provider": "forged"}
        ).encode("utf-8")
        with RunningServer(unreachable) as running:
            req = urlrequest.Request(
                running.base_url + DEFAULT_ENDPOINT,
                data=raw,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_rest_api.sys.stderr", io.StringIO()):
                with self.assertRaises(urlerror.HTTPError) as raised:
                    urlrequest.urlopen(req, timeout=3)
            error = raised.exception
            payload = json.loads(error.read())

        self.assertEqual(error.code, HTTPStatus.BAD_REQUEST)
        validate_error_payload(payload)
        self.assertEqual(payload["error"]["code"], CASE_API_INVALID_REQUEST)
        self.assertEqual(
            set(payload["request_fingerprints"]),
            {"raw_request_sha256"},
        )

    def test_service_exception_text_and_provider_details_do_not_leak(self):
        def researcher(_case_input: dict) -> dict:
            raise CaseRESTUnavailable(
                "secret provider https://127.0.0.1:9999 token=do-not-leak"
            )

        with RunningServer(researcher) as running:
            req = urlrequest.Request(
                running.base_url + DEFAULT_ENDPOINT,
                data=request_bytes(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch("case_rest_api.sys.stderr", io.StringIO()):
                with self.assertRaises(urlerror.HTTPError) as raised:
                    urlrequest.urlopen(req, timeout=3)
            error = raised.exception
            payload = json.loads(error.read())

        self.assertEqual(error.code, HTTPStatus.SERVICE_UNAVAILABLE)
        validate_error_payload(payload)
        self.assertEqual(
            payload["error"]["code"],
            CASE_API_SERVICE_UNAVAILABLE,
        )
        serialized = json.dumps(payload)
        self.assertNotIn("127.0.0.1", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("provider", serialized)

    def test_contract_invalid_or_rebound_bundle_fails_as_integrity_error(self):
        mutations = []

        def add_internal_field(bundle: dict) -> None:
            bundle["persistence"] = {"db": "/internal/path"}

        def rebind_case_input(bundle: dict) -> None:
            bundle["case_input"]["client_reference"] = "different-matter"

        mutations.extend([add_internal_field, rebind_case_input])

        for mutate in mutations:
            with self.subTest(mutate=mutate):
                fixture = deepcopy(complete_response()["bundle"])
                mutate(fixture)

                def researcher(_case_input: dict, value=fixture) -> dict:
                    return deepcopy(value)

                with RunningServer(researcher) as running:
                    req = urlrequest.Request(
                        running.base_url + DEFAULT_ENDPOINT,
                        data=request_bytes(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with mock.patch(
                        "case_rest_api.sys.stderr",
                        io.StringIO(),
                    ):
                        with self.assertRaises(urlerror.HTTPError) as raised:
                            urlrequest.urlopen(req, timeout=3)
                    error = raised.exception
                    payload = json.loads(error.read())

                self.assertEqual(
                    error.code,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                self.assertEqual(
                    payload["error"]["code"],
                    CASE_API_INTEGRITY_FAILURE,
                )
                self.assertNotIn("persistence", json.dumps(payload))
                self.assertNotIn("/internal/path", json.dumps(payload))

    def test_unknown_version_path_and_wrong_method_fail_without_fallback(self):
        fixture = complete_response()

        def researcher(_case_input: dict) -> dict:
            return deepcopy(fixture["bundle"])

        with RunningServer(researcher) as running:
            for path, method, expected_code in (
                ("/v2/cases", "POST", CASE_API_NOT_FOUND),
                (DEFAULT_ENDPOINT, "GET", CASE_API_METHOD_NOT_ALLOWED),
            ):
                with self.subTest(path=path, method=method):
                    data = request_bytes() if method == "POST" else None
                    headers = (
                        {"Content-Type": "application/json"}
                        if method == "POST"
                        else {}
                    )
                    req = urlrequest.Request(
                        running.base_url + path,
                        data=data,
                        headers=headers,
                        method=method,
                    )
                    with mock.patch(
                        "case_rest_api.sys.stderr",
                        io.StringIO(),
                    ):
                        with self.assertRaises(urlerror.HTTPError) as raised:
                            urlrequest.urlopen(req, timeout=3)
                    error = raised.exception
                    payload = json.loads(error.read())
                    self.assertEqual(payload["error"]["code"], expected_code)
                    self.assertEqual(
                        error.headers["X-Col-Taxdata-API-Version"],
                        API_VERSION,
                    )


if __name__ == "__main__":
    unittest.main()
