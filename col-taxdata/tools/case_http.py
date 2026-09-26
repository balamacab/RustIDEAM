#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

from case_application import (
    AnalysisOutcome,
    CaseAnalysisIntegrityError,
    CaseMaterializationError,
    CasePersistenceError,
    CaseValidationError,
    analyze_case,
    case_input_sha256,
)
from case_contract_validation import (
    CONTRACT_VERSION,
    CaseContractError,
    INVALID_CASE_DRAFT,
    INVALID_CASE_INPUT,
    INVALID_CASE_RESULT,
    validate_case_input,
)
from case_retrieval import RetrievalIntegrityError
from llm_client import (
    CASE_CONTEXT_LIMIT,
    CASE_OUTPUT_LIMIT,
    CASE_PROVIDER_TIMEOUT,
    CASE_STRUCTURING_UNAVAILABLE,
    ContextLimitError,
    LLMClientError,
    OpenAICompatibleLLMClient,
    OutputLimitError,
    CaseStructuringService,
    load_platform_config,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "llm" / "local-platform.yaml"
DEFAULT_ENDPOINT = "/v1/cases"
DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024

_EXTERNAL_FIELDS = frozenset(
    {"problem_text", "as_of_date", "client_reference"}
)
_INTERNAL_ID_VALUE = re.compile(
    r"^(?:CASE|CLM|DOC|PROV|SEG|EVD|MAN|EXT|REL|SRC)-[A-Za-z0-9._-]+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PreparedCaseRequest:
    """Validated external JSON plus exact and canonical audit fingerprints."""

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
class HTTPErrorResponse:
    status: int
    payload: dict[str, Any]


class CaseHTTPProtocolError(ValueError):
    """HTTP framing/routing failure with a machine-readable response."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


def _raw_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def prepare_case_request(raw_body: bytes) -> PreparedCaseRequest:
    """Validate the public HTTP body and construct the canonical v3 CaseInput.

    The transport intentionally exposes only client-owned CaseInput fields.
    Application-owned kind/version and all internal identifiers are generated
    behind the transport boundary.
    """
    raw_sha = _raw_sha256(raw_body)
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseContractError(
            INVALID_CASE_INPUT,
            f"request body is not valid UTF-8: {exc}",
        ) from exc

    try:
        external = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise CaseContractError(
            INVALID_CASE_INPUT,
            f"request body is not valid JSON: {exc.msg}",
        ) from exc

    if not isinstance(external, dict):
        raise CaseContractError(
            INVALID_CASE_INPUT,
            "request body root must be a JSON object",
        )

    extras = sorted(set(external) - _EXTERNAL_FIELDS)
    if extras:
        raise CaseContractError(
            INVALID_CASE_INPUT,
            "unsupported external field(s): " + ", ".join(extras),
        )

    for required in ("problem_text", "as_of_date"):
        if required not in external:
            raise CaseContractError(
                INVALID_CASE_INPUT,
                f"request body is missing required field {required!r}",
            )

    client_reference = external.get("client_reference")
    if (
        isinstance(client_reference, str)
        and _INTERNAL_ID_VALUE.fullmatch(client_reference.strip())
    ):
        raise CaseContractError(
            INVALID_CASE_INPUT,
            "client_reference must be an external correlation value, "
            "not an internal CASE/corpus identifier",
        )

    case_input: dict[str, Any] = {
        "kind": "case_input",
        "contract_version": CONTRACT_VERSION,
        "problem_text": external["problem_text"],
        "as_of_date": external["as_of_date"],
    }
    if "client_reference" in external:
        case_input["client_reference"] = external["client_reference"]

    validate_case_input(case_input)
    return PreparedCaseRequest(
        case_input=case_input,
        raw_request_sha256=raw_sha,
        case_input_sha256=case_input_sha256(case_input),
    )


def outcome_payload(
    outcome: AnalysisOutcome,
    prepared: PreparedCaseRequest,
) -> dict[str, Any]:
    """Serialize the existing CASE orchestrator outcome for HTTP callers."""
    return {
        "case_id": outcome.case_id,
        "case_ref": outcome.case_ref,
        "case_result": outcome.result,
        "request_fingerprints": prepared.fingerprints,
        "persistence": {
            "mode": outcome.persistence_mode,
            "case_reused": outcome.registration["case_reused"],
            "claims_inserted": outcome.registration["claims_inserted"],
            "claims_reused": outcome.registration["claims_reused"],
            "evidence_inserted": outcome.registration["evidence_inserted"],
            "materializations_updated": outcome.materialization["updated_count"],
            "bundle_valid": outcome.validation["valid"],
        },
    }


def error_response(exc: Exception) -> HTTPErrorResponse:
    """Map transport-neutral CASE failures to stable HTTP JSON semantics."""
    if isinstance(exc, ContextLimitError):
        return HTTPErrorResponse(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {
                "error": exc.code,
                "detail": exc.detail,
                "context": exc.metadata,
            },
        )
    if isinstance(exc, OutputLimitError):
        return HTTPErrorResponse(
            HTTPStatus.BAD_GATEWAY,
            {
                "error": exc.code,
                "detail": exc.detail,
                "context": exc.metadata,
            },
        )
    if isinstance(exc, CaseContractError):
        if exc.code == INVALID_CASE_INPUT:
            status = HTTPStatus.BAD_REQUEST
        elif exc.code == INVALID_CASE_DRAFT:
            status = HTTPStatus.BAD_GATEWAY
        elif exc.code == INVALID_CASE_RESULT:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        return HTTPErrorResponse(
            status,
            {"error": exc.code, "detail": exc.detail},
        )
    if isinstance(exc, LLMClientError):
        status = (
            HTTPStatus.GATEWAY_TIMEOUT
            if exc.code == CASE_PROVIDER_TIMEOUT
            else HTTPStatus.SERVICE_UNAVAILABLE
            if exc.code == CASE_STRUCTURING_UNAVAILABLE
            else HTTPStatus.BAD_GATEWAY
        )
        payload: dict[str, Any] = {
            "error": exc.code,
            "detail": exc.detail,
        }
        metadata = getattr(exc, "metadata", None)
        if metadata is not None:
            payload["context"] = metadata
        return HTTPErrorResponse(status, payload)
    if isinstance(exc, RetrievalIntegrityError):
        return HTTPErrorResponse(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {
                "error": "CASE_EVIDENCE_INTEGRITY_FAILURE",
                "detail": str(exc),
            },
        )
    if isinstance(
        exc,
        (
            CasePersistenceError,
            CaseMaterializationError,
            CaseValidationError,
            CaseAnalysisIntegrityError,
        ),
    ):
        return HTTPErrorResponse(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {
                "error": exc.code,
                "detail": exc.detail,
            },
        )
    return HTTPErrorResponse(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        {
            "error": "CASE_HTTP_INTERNAL_ERROR",
            "detail": "unexpected CASE HTTP adapter failure",
        },
    )


class CaseHTTPApplication:
    """Thin transport adapter around the existing CASE application callable."""

    def __init__(
        self,
        analyzer: Callable[[dict[str, Any]], AnalysisOutcome],
    ):
        self._analyzer = analyzer

    def analyze(self, case_input: dict[str, Any]) -> AnalysisOutcome:
        return self._analyzer(case_input)


class CaseHTTPServer(HTTPServer):
    """HTTP server carrying configured application state, not client routing state."""

    def __init__(
        self,
        server_address: tuple[str, int],
        application: CaseHTTPApplication,
        *,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    ):
        self.application = application
        self.max_request_bytes = max_request_bytes
        super().__init__(server_address, CaseHTTPRequestHandler)


class CaseHTTPRequestHandler(BaseHTTPRequestHandler):
    server: CaseHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Request audit below is structured and excludes client text.
        del format, args

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
    ) -> None:
        body = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _audit(
        self,
        *,
        status: int,
        fingerprints: dict[str, str] | None = None,
        case_id: str | None = None,
        error: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "event": "case_http_request",
            "path": self.path,
            "http_status": int(status),
        }
        if fingerprints:
            event["request_fingerprints"] = fingerprints
        if case_id is not None:
            event["case_id"] = case_id
        if error is not None:
            event["error"] = error
        print(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )

    def _read_json_body(self) -> bytes:
        if self.headers.get_content_type() != "application/json":
            raise CaseHTTPProtocolError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                INVALID_CASE_INPUT,
                "Content-Type must be application/json",
            )

        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise CaseHTTPProtocolError(
                HTTPStatus.LENGTH_REQUIRED,
                INVALID_CASE_INPUT,
                "Content-Length is required",
            )
        try:
            length = int(length_header)
        except ValueError as exc:
            raise CaseHTTPProtocolError(
                HTTPStatus.BAD_REQUEST,
                INVALID_CASE_INPUT,
                "Content-Length is invalid",
            ) from exc
        if length < 0:
            raise CaseHTTPProtocolError(
                HTTPStatus.BAD_REQUEST,
                INVALID_CASE_INPUT,
                "Content-Length must not be negative",
            )
        if length > self.server.max_request_bytes:
            raise CaseHTTPProtocolError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "CASE_REQUEST_TOO_LARGE",
                (
                    f"request body exceeds configured limit "
                    f"{self.server.max_request_bytes} bytes"
                ),
            )
        return self.rfile.read(length)

    def do_POST(self) -> None:
        if self.path != DEFAULT_ENDPOINT:
            response = HTTPErrorResponse(
                HTTPStatus.NOT_FOUND,
                {
                    "error": "CASE_HTTP_NOT_FOUND",
                    "detail": f"POST endpoint is {DEFAULT_ENDPOINT}",
                },
            )
            self._send_json(response.status, response.payload)
            self._audit(
                status=response.status,
                error=str(response.payload["error"]),
            )
            return

        prepared: PreparedCaseRequest | None = None
        raw_sha: str | None = None
        try:
            raw_body = self._read_json_body()
            raw_sha = _raw_sha256(raw_body)
            prepared = prepare_case_request(raw_body)
            outcome = self.server.application.analyze(prepared.case_input)
            payload = outcome_payload(outcome, prepared)
        except CaseHTTPProtocolError as exc:
            payload = {"error": exc.code, "detail": exc.detail}
            self._send_json(exc.status, payload)
            self._audit(status=exc.status, error=exc.code)
            return
        except Exception as exc:
            response = error_response(exc)
            fingerprints: dict[str, str] = {}
            if prepared is not None:
                fingerprints.update(prepared.fingerprints)
            elif raw_sha is not None:
                fingerprints["raw_request_sha256"] = raw_sha
            if fingerprints:
                response.payload["request_fingerprints"] = fingerprints
            self._send_json(response.status, response.payload)
            self._audit(
                status=response.status,
                fingerprints=fingerprints or None,
                error=str(response.payload["error"]),
            )
            return

        self._send_json(HTTPStatus.OK, payload)
        self._audit(
            status=HTTPStatus.OK,
            fingerprints=prepared.fingerprints,
            case_id=outcome.case_id,
        )

    def do_GET(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {
                "error": "CASE_HTTP_METHOD_NOT_ALLOWED",
                "detail": f"use POST {DEFAULT_ENDPOINT}",
            },
        )

    def do_PUT(self) -> None:
        self.do_GET()

    def do_PATCH(self) -> None:
        self.do_GET()

    def do_DELETE(self) -> None:
        self.do_GET()


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None else int(value)


def build_runtime_application(
    *,
    db_path: Path,
    case_root: Path,
    config_path: Path,
    dry_run: bool,
) -> tuple[CaseHTTPApplication, str, str]:
    """Construct server-side runtime configuration once for all HTTP requests."""
    config = load_platform_config(config_path)
    client = OpenAICompatibleLLMClient(config)
    structurer = CaseStructuringService(config, client)

    def analyzer(case_input: dict[str, Any]) -> AnalysisOutcome:
        return analyze_case(
            case_input=case_input,
            db_path=db_path,
            case_root=case_root,
            structurer=structurer,
            dry_run=dry_run,
            include_debug_provenance=False,
        )

    return (
        CaseHTTPApplication(analyzer),
        config.provider,
        config.primary.name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expose the existing col-taxdata v3 CASE application through "
            f"POST {DEFAULT_ENDPOINT}."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("COL_TAXDATA_HTTP_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("COL_TAXDATA_HTTP_PORT", 8765),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get(
            "COL_TAXDATA_DB",
            "data/state/taxdata.sqlite",
        ),
    )
    parser.add_argument(
        "--case-root",
        default=os.environ.get("COL_TAXDATA_CASE_ROOT", "data/cases"),
    )
    parser.add_argument(
        "--config",
        default=os.environ.get(
            "COL_TAXDATA_LLM_CONFIG",
            str(DEFAULT_CONFIG),
        ),
    )
    parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=_env_int(
            "COL_TAXDATA_HTTP_MAX_REQUEST_BYTES",
            DEFAULT_MAX_REQUEST_BYTES,
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Use the normal CASE dry-run path: temporary SQLite snapshot "
            "and temporary case materializations only."
        ),
    )
    args = parser.parse_args()

    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if args.max_request_bytes < 1:
        parser.error("--max-request-bytes must be positive")

    try:
        application, provider, model = build_runtime_application(
            db_path=Path(args.db),
            case_root=Path(args.case_root),
            config_path=Path(args.config),
            dry_run=args.dry_run,
        )
        server = CaseHTTPServer(
            (args.host, args.port),
            application,
            max_request_bytes=args.max_request_bytes,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "error": "CASE_HTTP_CONFIGURATION_FAILURE",
                    "detail": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    host, port = server.server_address[:2]
    print(
        json.dumps(
            {
                "event": "case_http_listening",
                "host": host,
                "port": port,
                "endpoint": DEFAULT_ENDPOINT,
                "provider": provider,
                "model": model,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
