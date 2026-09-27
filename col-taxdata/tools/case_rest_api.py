#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import sys
from typing import Any, Callable

from case_contract_validation import CaseContractError
from case_contract_validation_v4 import (
    CONTRACT_VERSION as CASE_CONTRACT_VERSION,
    validate_case_input as validate_v4_case_input,
    validate_legal_research_bundle,
)


API_VERSION = "1.0.0"
DEFAULT_ENDPOINT = "/v1/cases"
DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024

_EXTERNAL_FIELDS = frozenset(
    {"problem_text", "as_of_date", "client_reference", "caller_metadata"}
)
_RESERVED_METADATA_KEYS = frozenset(
    {
        "kind",
        "contract_version",
        "case_id",
        "case_ref",
        "bundle_ref",
        "intake_ref",
        "plan_ref",
        "result_ref",
        "authority_ref",
        "document_ref",
        "provision_ref",
        "evidence_ref",
        "span_ref",
        "relationship_ref",
        "rule_ref",
        "evaluation_ref",
        "calculation_ref",
        "unresolved_ref",
        "provenance_ref",
        "source_ref",
        "provider",
        "model",
        "backend",
        "adapter",
        "base_url",
        "api_key",
        "canonical_ids",
        "evidence_bindings",
        "source_hints",
        "expected_conclusions",
        "attachments",
        "file_path",
        "filesystem_path",
        "document_url",
        "document_urls",
        "ocr_payload",
    }
)
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")

CASE_API_INVALID_REQUEST = "CASE_API_INVALID_REQUEST"
CASE_API_NOT_FOUND = "CASE_API_NOT_FOUND"
CASE_API_METHOD_NOT_ALLOWED = "CASE_API_METHOD_NOT_ALLOWED"
CASE_API_LENGTH_REQUIRED = "CASE_API_LENGTH_REQUIRED"
CASE_API_REQUEST_TOO_LARGE = "CASE_API_REQUEST_TOO_LARGE"
CASE_API_UNSUPPORTED_MEDIA_TYPE = "CASE_API_UNSUPPORTED_MEDIA_TYPE"
CASE_API_SERVICE_UNAVAILABLE = "CASE_API_SERVICE_UNAVAILABLE"
CASE_API_TIMEOUT = "CASE_API_TIMEOUT"
CASE_API_INTEGRITY_FAILURE = "CASE_API_INTEGRITY_FAILURE"
CASE_API_INTERNAL_ERROR = "CASE_API_INTERNAL_ERROR"

_ERROR_SPECS: dict[str, tuple[int, str, bool]] = {
    CASE_API_INVALID_REQUEST: (
        HTTPStatus.BAD_REQUEST,
        "The request does not conform to the public CASE API contract.",
        False,
    ),
    CASE_API_NOT_FOUND: (
        HTTPStatus.NOT_FOUND,
        "The requested public CASE API resource does not exist.",
        False,
    ),
    CASE_API_METHOD_NOT_ALLOWED: (
        HTTPStatus.METHOD_NOT_ALLOWED,
        "The HTTP method is not supported by this public CASE API operation.",
        False,
    ),
    CASE_API_LENGTH_REQUIRED: (
        HTTPStatus.LENGTH_REQUIRED,
        "Content-Length is required.",
        False,
    ),
    CASE_API_REQUEST_TOO_LARGE: (
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "The request body exceeds the configured public API limit.",
        False,
    ),
    CASE_API_UNSUPPORTED_MEDIA_TYPE: (
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "Content-Type must be application/json.",
        False,
    ),
    CASE_API_SERVICE_UNAVAILABLE: (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "CASE research is temporarily unavailable.",
        True,
    ),
    CASE_API_TIMEOUT: (
        HTTPStatus.GATEWAY_TIMEOUT,
        "CASE research timed out.",
        True,
    ),
    CASE_API_INTEGRITY_FAILURE: (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "CASE could not produce a contract-valid research bundle.",
        False,
    ),
    CASE_API_INTERNAL_ERROR: (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "An unexpected internal CASE API failure occurred.",
        False,
    ),
}


@dataclass(frozen=True)
class PreparedRESTCaseRequest:
    """Validated public request and its exact/canonical audit fingerprints."""

    case_input: dict[str, Any]
    raw_request_sha256: str
    case_input_sha256: str

    @property
    def fingerprints(self) -> dict[str, str]:
        return {
            "raw_request_sha256": self.raw_request_sha256,
            "case_input_sha256": self.case_input_sha256,
        }


@dataclass(frozen=True)
class RESTResponse:
    status: int
    payload: dict[str, Any]


class CaseRESTProtocolError(ValueError):
    """HTTP framing/routing error expressed through a stable public code."""

    def __init__(self, code: str):
        if code not in _ERROR_SPECS:
            raise ValueError(f"unsupported public API error code: {code}")
        super().__init__(code)
        self.code = code


class CaseRESTUnavailable(RuntimeError):
    """Research application is temporarily unavailable."""


class CaseRESTTimeout(RuntimeError):
    """Research application exceeded its bounded request time."""


class CaseRESTIntegrityError(RuntimeError):
    """Research application returned output unsafe for the public contract."""


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _case_input_sha256(case_input: dict[str, Any]) -> str:
    """Hash deterministic validated v4 CaseInput JSON, never raw legal evidence."""
    validate_v4_case_input(case_input)
    return _sha256_bytes(_compact_json(case_input).encode("utf-8"))


def _invalid_request(detail: str) -> CaseContractError:
    # The detailed validation reason remains useful to server-side tests/logging,
    # while the HTTP error mapper intentionally exposes only a stable message.
    return CaseContractError("INVALID_CASE_INPUT", detail)


def prepare_case_request(raw_body: bytes) -> PreparedRESTCaseRequest:
    """Parse the closed public request and build an exact v4 CaseInput.

    Caller-owned values are copied verbatim. The function performs no text
    trimming, Unicode normalization, semantic repair, provider selection, or
    canonical-ID promotion.
    """
    raw_sha = _sha256_bytes(raw_body)
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid_request("request body is not valid UTF-8") from exc

    try:
        external = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise _invalid_request("request body is not valid JSON") from exc

    if not isinstance(external, dict):
        raise _invalid_request("request body root must be a JSON object")

    extras = sorted(set(external) - _EXTERNAL_FIELDS)
    if extras:
        raise _invalid_request(
            "unsupported external field(s): " + ", ".join(extras)
        )
    if "problem_text" not in external:
        raise _invalid_request("request body is missing required field 'problem_text'")

    caller_metadata = external.get("caller_metadata")
    if isinstance(caller_metadata, dict):
        reserved = sorted(
            key
            for key in caller_metadata
            if isinstance(key, str) and key.lower() in _RESERVED_METADATA_KEYS
        )
        if reserved:
            raise _invalid_request(
                "caller_metadata contains reserved server/control field(s): "
                + ", ".join(reserved)
            )

    case_input: dict[str, Any] = {
        "kind": "case_input",
        "contract_version": CASE_CONTRACT_VERSION,
        "problem_text": external["problem_text"],
    }
    for name in ("as_of_date", "client_reference", "caller_metadata"):
        if name in external:
            case_input[name] = external[name]

    validate_v4_case_input(case_input)
    return PreparedRESTCaseRequest(
        case_input=case_input,
        raw_request_sha256=raw_sha,
        case_input_sha256=_case_input_sha256(case_input),
    )


def _error_response(
    code: str,
    *,
    fingerprints: dict[str, str] | None = None,
) -> RESTResponse:
    status, message, retryable = _ERROR_SPECS[code]
    payload: dict[str, Any] = {
        "api_version": API_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    if fingerprints:
        payload["request_fingerprints"] = dict(fingerprints)
    return RESTResponse(status=int(status), payload=payload)


def _validate_fingerprints(
    fingerprints: object,
    *,
    require_both: bool,
) -> None:
    if not isinstance(fingerprints, dict):
        raise ValueError("request_fingerprints must be an object")
    allowed = {"raw_request_sha256", "case_input_sha256"}
    if not set(fingerprints).issubset(allowed):
        raise ValueError("request_fingerprints contains an unsupported field")
    if not fingerprints:
        raise ValueError("request_fingerprints must not be empty")
    if require_both and set(fingerprints) != allowed:
        raise ValueError("success response requires both request fingerprints")
    for value in fingerprints.values():
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError("request fingerprint is not a SHA-256 value")


def validate_success_payload(payload: dict[str, Any]) -> None:
    """Validate the transport envelope plus complete v4 bundle semantics."""
    if not isinstance(payload, dict) or set(payload) != {
        "api_version",
        "request_fingerprints",
        "bundle",
    }:
        raise ValueError("public success response has an invalid top-level shape")
    if payload["api_version"] != API_VERSION:
        raise ValueError("unsupported public API version")
    _validate_fingerprints(payload["request_fingerprints"], require_both=True)
    validate_legal_research_bundle(payload["bundle"])


def validate_error_payload(payload: dict[str, Any]) -> None:
    """Validate the stable public error envelope without internal diagnostics."""
    if not isinstance(payload, dict):
        raise ValueError("public error response must be an object")
    if not {"api_version", "error"}.issubset(payload):
        raise ValueError("public error response is missing required fields")
    if not set(payload).issubset(
        {"api_version", "error", "request_fingerprints"}
    ):
        raise ValueError("public error response exposes an unsupported field")
    if payload["api_version"] != API_VERSION:
        raise ValueError("unsupported public API version")

    error = payload["error"]
    if not isinstance(error, dict) or set(error) != {
        "code",
        "message",
        "retryable",
    }:
        raise ValueError("public error object has an invalid shape")
    code = error["code"]
    if code not in _ERROR_SPECS:
        raise ValueError("unsupported public error code")
    _status, message, retryable = _ERROR_SPECS[code]
    if error["message"] != message or error["retryable"] is not retryable:
        raise ValueError("public error semantics do not match the registered code")

    if "request_fingerprints" in payload:
        _validate_fingerprints(
            payload["request_fingerprints"],
            require_both=False,
        )


class CaseRESTApplication:
    """Public REST application boundary around a v4 CASE research service."""

    def __init__(
        self,
        researcher: Callable[..., dict[str, Any]],
        *,
        forward_request_fingerprints: bool = False,
    ):
        self._researcher = researcher
        self._forward_request_fingerprints = forward_request_fingerprints

    def research(
        self,
        case_input: dict[str, Any],
        *,
        request_fingerprints: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return only a validated v4 bundle bound to the accepted CaseInput."""
        if self._forward_request_fingerprints:
            bundle = self._researcher(
                case_input,
                request_fingerprints=request_fingerprints,
            )
        else:
            bundle = self._researcher(case_input)

        if not isinstance(bundle, dict):
            raise CaseRESTIntegrityError(
                "research service returned a non-object result"
            )
        try:
            validate_legal_research_bundle(bundle)
        except (CaseContractError, TypeError, ValueError, KeyError) as exc:
            raise CaseRESTIntegrityError(
                "research service returned a contract-invalid LegalResearchBundle"
            ) from exc

        if bundle["case_input"] != case_input:
            raise CaseRESTIntegrityError(
                "research bundle does not preserve the accepted CaseInput exactly"
            )
        return bundle


class CaseRESTServer(HTTPServer):
    """HTTP server carrying only public transport/application state."""

    def __init__(
        self,
        server_address: tuple[str, int],
        application: CaseRESTApplication,
        *,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    ):
        if max_request_bytes < 1:
            raise ValueError("max_request_bytes must be positive")
        self.application = application
        self.max_request_bytes = max_request_bytes
        super().__init__(server_address, CaseRESTRequestHandler)


class CaseRESTRequestHandler(BaseHTTPRequestHandler):
    server: CaseRESTServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Structured audit below intentionally excludes caller legal text.
        del format, args

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = (_compact_json(payload) + "\n").encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Col-Taxdata-API-Version", API_VERSION)
        # CORS is deliberately absent. Browser cross-origin policy belongs to
        # explicit deployment configuration or the #143 same-origin proxy.
        self.end_headers()
        self.wfile.write(body)

    def _audit(
        self,
        *,
        status: int,
        fingerprints: dict[str, str] | None = None,
        bundle_ref: str | None = None,
        error_code: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "event": "case_rest_api_request",
            "api_version": API_VERSION,
            "path": self.path,
            "http_status": int(status),
        }
        if fingerprints:
            event["request_fingerprints"] = fingerprints
        if bundle_ref is not None:
            event["bundle_ref"] = bundle_ref
        if error_code is not None:
            event["error"] = error_code
        print(
            _compact_json(event),
            file=sys.stderr,
            flush=True,
        )

    def _send_registered_error(
        self,
        code: str,
        *,
        fingerprints: dict[str, str] | None = None,
    ) -> None:
        response = _error_response(code, fingerprints=fingerprints)
        validate_error_payload(response.payload)
        self._send_json(response.status, response.payload)
        self._audit(
            status=response.status,
            fingerprints=fingerprints,
            error_code=code,
        )

    def _read_body(self) -> bytes:
        if self.headers.get_content_type() != "application/json":
            raise CaseRESTProtocolError(CASE_API_UNSUPPORTED_MEDIA_TYPE)

        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise CaseRESTProtocolError(CASE_API_LENGTH_REQUIRED)
        try:
            length = int(length_header)
        except ValueError as exc:
            raise CaseRESTProtocolError(CASE_API_INVALID_REQUEST) from exc
        if length < 0:
            raise CaseRESTProtocolError(CASE_API_INVALID_REQUEST)
        if length > self.server.max_request_bytes:
            raise CaseRESTProtocolError(CASE_API_REQUEST_TOO_LARGE)

        body = self.rfile.read(length)
        if len(body) != length:
            raise CaseRESTProtocolError(CASE_API_INVALID_REQUEST)
        return body

    def do_POST(self) -> None:
        if self.path != DEFAULT_ENDPOINT:
            self._send_registered_error(CASE_API_NOT_FOUND)
            return

        try:
            raw_body = self._read_body()
        except CaseRESTProtocolError as exc:
            self._send_registered_error(exc.code)
            return

        raw_fingerprints = {"raw_request_sha256": _sha256_bytes(raw_body)}
        try:
            prepared = prepare_case_request(raw_body)
        except (CaseContractError, TypeError, ValueError) as exc:
            del exc
            self._send_registered_error(
                CASE_API_INVALID_REQUEST,
                fingerprints=raw_fingerprints,
            )
            return

        try:
            bundle = self.server.application.research(
                prepared.case_input,
                request_fingerprints=prepared.fingerprints,
            )
        except (CaseRESTTimeout, TimeoutError):
            self._send_registered_error(
                CASE_API_TIMEOUT,
                fingerprints=prepared.fingerprints,
            )
            return
        except CaseRESTUnavailable:
            self._send_registered_error(
                CASE_API_SERVICE_UNAVAILABLE,
                fingerprints=prepared.fingerprints,
            )
            return
        except CaseRESTIntegrityError:
            self._send_registered_error(
                CASE_API_INTEGRITY_FAILURE,
                fingerprints=prepared.fingerprints,
            )
            return
        except Exception:
            # Never serialize arbitrary exception text across the public boundary.
            self._send_registered_error(
                CASE_API_INTERNAL_ERROR,
                fingerprints=prepared.fingerprints,
            )
            return

        payload = {
            "api_version": API_VERSION,
            "request_fingerprints": prepared.fingerprints,
            "bundle": bundle,
        }
        try:
            validate_success_payload(payload)
        except (CaseContractError, TypeError, ValueError, KeyError):
            self._send_registered_error(
                CASE_API_INTEGRITY_FAILURE,
                fingerprints=prepared.fingerprints,
            )
            return

        self._send_json(HTTPStatus.OK, payload)
        self._audit(
            status=HTTPStatus.OK,
            fingerprints=prepared.fingerprints,
            bundle_ref=bundle["bundle_ref"],
        )

    def _method_not_allowed(self) -> None:
        self._send_registered_error(CASE_API_METHOD_NOT_ALLOWED)

    def do_GET(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()
