"""Independent REST-contract client and deterministic MCP bundle views.

This module intentionally uses only the Python standard library.  It does not
import col-taxdata backend packages, access CASE storage, or know the corpus
filesystem/SQLite layout.  Its only semantic dependency is the published CASE
REST v1 JSON contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

REST_API_VERSION = "1.0.0"
CASE_CONTRACT_VERSION = "4.0.0"
GATEWAY_CONTRACT_VERSION = "1.0.0"
REST_CASE_PATH = "/v1/cases"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_CACHE_ENTRIES = 32

TOOL_NAMES = (
    "research_case",
    "get_case_research",
    "get_authority",
    "get_provision",
    "get_evidence",
    "get_normative_relationships",
    "get_calculation",
)

_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_REQUIRED_BUNDLE_FIELDS = frozenset(
    {
        "kind",
        "contract_version",
        "bundle_ref",
        "status",
        "case_input",
        "intake_draft",
        "research_plan",
        "research_result",
        "sources",
        "authorities",
        "evidence_spans",
        "normative_relationships",
        "rule_fragments",
        "deterministic_evaluations",
        "calculation_traces",
        "unresolved",
        "generated_at",
    }
)

_UPSTREAM_ERROR_MAP = {
    "CASE_API_INVALID_REQUEST": ("MCP_CASE_INVALID_REQUEST", False),
    "CASE_API_NOT_FOUND": ("MCP_CASE_CONTRACT_MISMATCH", False),
    "CASE_API_METHOD_NOT_ALLOWED": ("MCP_CASE_CONTRACT_MISMATCH", False),
    "CASE_API_LENGTH_REQUIRED": ("MCP_CASE_CONTRACT_MISMATCH", False),
    "CASE_API_REQUEST_TOO_LARGE": ("MCP_CASE_REQUEST_TOO_LARGE", False),
    "CASE_API_UNSUPPORTED_MEDIA_TYPE": ("MCP_CASE_CONTRACT_MISMATCH", False),
    "CASE_API_SERVICE_UNAVAILABLE": ("MCP_CASE_UPSTREAM_UNAVAILABLE", True),
    "CASE_API_TIMEOUT": ("MCP_CASE_UPSTREAM_TIMEOUT", True),
    "CASE_API_INTEGRITY_FAILURE": ("MCP_CASE_UPSTREAM_INTEGRITY_FAILURE", False),
    "CASE_API_INTERNAL_ERROR": ("MCP_CASE_UPSTREAM_INTERNAL_ERROR", False),
}


class GatewayConfigError(ValueError):
    """Raised when deployment configuration violates the gateway boundary."""


class GatewayError(RuntimeError):
    """Stable, non-secret-bearing error exposed at the MCP boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        upstream_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        self.upstream_code = upstream_code

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.upstream_code is not None:
            payload["upstream_code"] = self.upstream_code
        return payload


@dataclass(frozen=True)
class GatewayConfig:
    """Runtime-only connection and resource bounds for the independent gateway."""

    base_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    cache_entries: int = DEFAULT_CACHE_ENTRIES

    def __post_init__(self) -> None:
        parsed = urlparse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise GatewayConfigError(
                "CASE_REST_BASE_URL must be an absolute http(s) service URL"
            )
        if parsed.username is not None or parsed.password is not None:
            raise GatewayConfigError(
                "CASE_REST_BASE_URL must not contain embedded credentials"
            )
        if parsed.query or parsed.fragment:
            raise GatewayConfigError(
                "CASE_REST_BASE_URL must not contain a query or fragment"
            )
        if self.timeout_seconds <= 0:
            raise GatewayConfigError("timeout_seconds must be positive")
        if self.max_request_bytes < 1 or self.max_response_bytes < 1:
            raise GatewayConfigError("payload byte limits must be positive")
        if self.cache_entries < 1:
            raise GatewayConfigError("cache_entries must be positive")

    @property
    def case_url(self) -> str:
        return self.base_url.rstrip("/") + REST_CASE_PATH

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        base_url = os.environ.get("CASE_REST_BASE_URL")
        if not base_url:
            raise GatewayConfigError("CASE_REST_BASE_URL is required")

        def _positive_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise GatewayConfigError(f"{name} must be an integer") from exc
            if value < 1:
                raise GatewayConfigError(f"{name} must be positive")
            return value

        try:
            timeout = float(
                os.environ.get("CASE_REST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
            )
        except ValueError as exc:
            raise GatewayConfigError(
                "CASE_REST_TIMEOUT_SECONDS must be numeric"
            ) from exc

        return cls(
            base_url=base_url,
            timeout_seconds=timeout,
            max_request_bytes=_positive_int(
                "MCP_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
            ),
            max_response_bytes=_positive_int(
                "MCP_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES
            ),
            cache_entries=_positive_int("MCP_BUNDLE_CACHE_ENTRIES", DEFAULT_CACHE_ENTRIES),
        )


def _compact_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatewayError(
            "MCP_CASE_INVALID_REQUEST",
            "Tool arguments cannot be represented by the public CASE JSON contract.",
            retryable=False,
        ) from exc


def _canonical_json(value: Any) -> bytes:
    """Match REST v1's documented deterministic CaseInput fingerprint JSON."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_limited(stream: Any, limit: int) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise GatewayError(
            "MCP_CASE_RESPONSE_TOO_LARGE",
            "The CASE REST response exceeds the configured gateway limit.",
            retryable=False,
        )
    return data


def _parse_json_object(raw: bytes, *, error_code: str, message: str) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayError(error_code, message, retryable=False) from exc
    if not isinstance(payload, dict):
        raise GatewayError(error_code, message, retryable=False)
    return payload


def _validate_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            f"CASE REST success response has an invalid {field}.",
            retryable=False,
        )


def _validate_success_envelope(
    payload: dict[str, Any],
    submitted_request: Mapping[str, Any],
    raw_request: bytes,
) -> None:
    if set(payload) != {"api_version", "request_fingerprints", "bundle"}:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST success response has an unsupported envelope shape.",
        )
    if payload.get("api_version") != REST_API_VERSION:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST success response uses an unsupported API version.",
        )

    fingerprints = payload.get("request_fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != {
        "raw_request_sha256",
        "case_input_sha256",
    }:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST success response has invalid request fingerprints.",
        )
    _validate_sha256(fingerprints["raw_request_sha256"], "raw_request_sha256")
    _validate_sha256(fingerprints["case_input_sha256"], "case_input_sha256")

    expected_raw_sha256 = hashlib.sha256(raw_request).hexdigest()
    if fingerprints["raw_request_sha256"] != expected_raw_sha256:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST response raw-request fingerprint does not match the request sent.",
        )

    bundle = payload.get("bundle")
    if not isinstance(bundle, dict) or set(bundle) != _REQUIRED_BUNDLE_FIELDS:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST success response is not a closed LegalResearchBundle v4.",
        )
    if (
        bundle.get("kind") != "legal_research_bundle"
        or bundle.get("contract_version") != CASE_CONTRACT_VERSION
        or bundle.get("status") not in {"complete", "partial", "blocked"}
    ):
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST success response has invalid LegalResearchBundle identity/state.",
        )

    for name in (
        "sources",
        "authorities",
        "evidence_spans",
        "normative_relationships",
        "rule_fragments",
        "deterministic_evaluations",
        "calculation_traces",
        "unresolved",
    ):
        if not isinstance(bundle.get(name), list):
            raise GatewayError(
                "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
                f"LegalResearchBundle field {name} is not an array.",
            )

    expected_case_input = {
        "kind": "case_input",
        "contract_version": CASE_CONTRACT_VERSION,
        **dict(submitted_request),
    }
    if bundle.get("case_input") != expected_case_input:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST response did not preserve the submitted CaseInput exactly.",
        )

    expected_case_sha256 = hashlib.sha256(
        _canonical_json(expected_case_input)
    ).hexdigest()
    if fingerprints["case_input_sha256"] != expected_case_sha256:
        raise GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST response CaseInput fingerprint does not match the accepted input.",
        )


def _map_http_error(status: int, payload: dict[str, Any]) -> GatewayError:
    error = payload.get("error")
    if not isinstance(error, dict):
        return GatewayError(
            "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            "CASE REST returned a non-contract error envelope.",
            retryable=False,
            http_status=status,
        )

    upstream_code = error.get("code")
    retryable = bool(error.get("retryable")) if isinstance(error.get("retryable"), bool) else False
    if isinstance(upstream_code, str) and upstream_code in _UPSTREAM_ERROR_MAP:
        code, registered_retryable = _UPSTREAM_ERROR_MAP[upstream_code]
        return GatewayError(
            code,
            "CASE REST rejected or could not complete the research request.",
            retryable=registered_retryable,
            http_status=status,
            upstream_code=upstream_code,
        )

    return GatewayError(
        "MCP_CASE_UPSTREAM_ERROR",
        "CASE REST returned an unrecognized public error.",
        retryable=retryable,
        http_status=status,
        upstream_code=upstream_code if isinstance(upstream_code, str) else None,
    )


class CaseRestClient:
    """HTTP/JSON client that knows only the published CASE REST v1 surface."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    def research_case(
        self,
        *,
        problem_text: str,
        as_of_date: str | None = None,
        client_reference: str | None = None,
        caller_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(problem_text, str) or problem_text == "":
            raise GatewayError(
                "MCP_CASE_INVALID_REQUEST",
                "problem_text must be a non-empty string.",
            )

        payload: dict[str, Any] = {"problem_text": problem_text}
        if as_of_date is not None:
            payload["as_of_date"] = as_of_date
        if client_reference is not None:
            payload["client_reference"] = client_reference
        if caller_metadata is not None:
            payload["caller_metadata"] = dict(caller_metadata)

        raw = _compact_json(payload)
        if len(raw) > self.config.max_request_bytes:
            raise GatewayError(
                "MCP_CASE_REQUEST_TOO_LARGE",
                "The research request exceeds the configured gateway limit.",
                retryable=False,
            )

        request = urlrequest.Request(
            self.config.case_url,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"col-taxdata-mcp/{GATEWAY_CONTRACT_VERSION}",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                body = _read_limited(response, self.config.max_response_bytes)
                status = int(response.status)
                content_type = response.headers.get_content_type()
        except urlerror.HTTPError as exc:
            try:
                body = _read_limited(exc, self.config.max_response_bytes)
                error_payload = _parse_json_object(
                    body,
                    error_code="MCP_CASE_UPSTREAM_CONTRACT_ERROR",
                    message="CASE REST returned a non-JSON public error.",
                )
            finally:
                exc.close()
            raise _map_http_error(int(exc.code), error_payload) from None
        except (TimeoutError, socket.timeout) as exc:
            raise GatewayError(
                "MCP_CASE_UPSTREAM_TIMEOUT",
                "CASE REST did not respond within the configured timeout.",
                retryable=True,
            ) from exc
        except urlerror.URLError as exc:
            raise GatewayError(
                "MCP_CASE_UPSTREAM_UNAVAILABLE",
                "CASE REST is not reachable from the MCP gateway.",
                retryable=True,
            ) from exc

        if status != 200:
            raise GatewayError(
                "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
                "CASE REST returned an unexpected successful transport status.",
                http_status=status,
            )
        if content_type != "application/json":
            raise GatewayError(
                "MCP_CASE_UPSTREAM_CONTRACT_ERROR",
                "CASE REST success response is not application/json.",
                http_status=status,
            )

        response_payload = _parse_json_object(
            body,
            error_code="MCP_CASE_UPSTREAM_CONTRACT_ERROR",
            message="CASE REST success response is not valid JSON.",
        )
        _validate_success_envelope(response_payload, payload, raw)
        return response_payload


class BundleStore:
    """Small bounded in-memory cache of REST responses.

    Handles are gateway-local convenience identifiers.  They are explicitly not
    canonical CASE/document/evidence identity and are never persisted.
    """

    def __init__(self, capacity: int = DEFAULT_CACHE_ENTRIES) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @staticmethod
    def handle_for(envelope: Mapping[str, Any]) -> str:
        bundle = envelope["bundle"]
        fingerprints = envelope["request_fingerprints"]
        seed = (
            f"{envelope['api_version']}\0"
            f"{fingerprints['case_input_sha256']}\0"
            f"{bundle['bundle_ref']}"
        ).encode("utf-8")
        return "mcpbundle:" + hashlib.sha256(seed).hexdigest()

    def put(self, envelope: Mapping[str, Any]) -> str:
        handle = self.handle_for(envelope)
        self._entries[handle] = copy.deepcopy(dict(envelope))
        self._entries.move_to_end(handle)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
        return handle

    def get(self, handle: str) -> dict[str, Any]:
        try:
            value = self._entries[handle]
        except KeyError as exc:
            raise GatewayError(
                "MCP_BUNDLE_NOT_FOUND",
                "The requested gateway bundle handle is unknown or has expired.",
                retryable=False,
            ) from exc
        self._entries.move_to_end(handle)
        return copy.deepcopy(value)


def _find_by_ref(
    items: list[dict[str, Any]],
    field: str,
    value: str,
    *,
    code: str,
    label: str,
) -> dict[str, Any]:
    matches = [item for item in items if item.get(field) == value]
    if len(matches) != 1:
        raise GatewayError(
            code,
            f"{label} was not uniquely present in the LegalResearchBundle.",
            retryable=False,
        )
    return copy.deepcopy(matches[0])


def _by_refs(
    items: list[dict[str, Any]],
    field: str,
    refs: set[str],
) -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in items if item.get(field) in refs]


class GatewayService:
    """Semantic legal-research projections backed only by REST bundle content."""

    def __init__(
        self,
        rest_client: Any,
        *,
        store: BundleStore | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.store = store or BundleStore()

    @classmethod
    def from_config(cls, config: GatewayConfig) -> "GatewayService":
        return cls(
            CaseRestClient(config),
            store=BundleStore(config.cache_entries),
        )

    @classmethod
    def from_env(cls) -> "GatewayService":
        return cls.from_config(GatewayConfig.from_env())

    def research_case(
        self,
        *,
        problem_text: str,
        as_of_date: str | None = None,
        client_reference: str | None = None,
        caller_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope = self.rest_client.research_case(
            problem_text=problem_text,
            as_of_date=as_of_date,
            client_reference=client_reference,
            caller_metadata=caller_metadata,
        )
        handle = self.store.put(envelope)
        return {
            "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
            "bundle_handle": handle,
            "handle_scope": "ephemeral_noncanonical",
            "request_fingerprints": copy.deepcopy(envelope["request_fingerprints"]),
            "bundle": copy.deepcopy(envelope["bundle"]),
        }

    def get_case_research(self, *, bundle_handle: str) -> dict[str, Any]:
        envelope = self.store.get(bundle_handle)
        return {
            "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
            "bundle_handle": bundle_handle,
            "handle_scope": "ephemeral_noncanonical",
            "request_fingerprints": copy.deepcopy(envelope["request_fingerprints"]),
            "bundle": copy.deepcopy(envelope["bundle"]),
        }

    def get_authority(
        self,
        *,
        bundle_handle: str,
        authority_ref: str,
    ) -> dict[str, Any]:
        bundle = self.store.get(bundle_handle)["bundle"]
        authority = _find_by_ref(
            bundle["authorities"],
            "authority_ref",
            authority_ref,
            code="MCP_AUTHORITY_NOT_FOUND",
            label="Authority",
        )
        source_refs = set(authority.get("source_refs", []))
        evidence_refs = set(authority.get("evidence_refs", []))
        relationships = [
            copy.deepcopy(item)
            for item in bundle["normative_relationships"]
            if item.get("source_authority_ref") == authority_ref
            or item.get("target_authority_ref") == authority_ref
        ]
        unresolved = [
            copy.deepcopy(item)
            for item in bundle["unresolved"]
            if authority_ref in item.get("related_authority_refs", [])
        ]
        return {
            "view_kind": "mcp_authority_view",
            "bundle_handle": bundle_handle,
            "authority": authority,
            "sources": _by_refs(bundle["sources"], "source_ref", source_refs),
            "evidence_spans": _by_refs(
                bundle["evidence_spans"], "evidence_ref", evidence_refs
            ),
            "normative_relationships": relationships,
            "unresolved": unresolved,
        }

    def get_provision(
        self,
        *,
        bundle_handle: str,
        provision_ref: str,
    ) -> dict[str, Any]:
        bundle = self.store.get(bundle_handle)["bundle"]
        authorities = [
            copy.deepcopy(item)
            for item in bundle["authorities"]
            if provision_ref in item.get("provision_refs", [])
        ]
        evidence = [
            copy.deepcopy(item)
            for item in bundle["evidence_spans"]
            if item.get("provision_ref") == provision_ref
        ]
        if not authorities and not evidence:
            raise GatewayError(
                "MCP_PROVISION_NOT_FOUND",
                "Provision reference was not present in the LegalResearchBundle.",
            )
        return {
            "view_kind": "mcp_provision_reference_view",
            "bundle_handle": bundle_handle,
            "provision_ref": provision_ref,
            "authorities": authorities,
            "evidence_spans": evidence,
            "projection_notice": (
                "REST v1 exposes provision references/evidence, not a standalone "
                "canonical Provision object; this view does not infer missing metadata."
            ),
        }

    def get_evidence(
        self,
        *,
        bundle_handle: str,
        evidence_ref: str,
    ) -> dict[str, Any]:
        bundle = self.store.get(bundle_handle)["bundle"]
        evidence = _find_by_ref(
            bundle["evidence_spans"],
            "evidence_ref",
            evidence_ref,
            code="MCP_EVIDENCE_NOT_FOUND",
            label="Evidence",
        )
        authority = _find_by_ref(
            bundle["authorities"],
            "authority_ref",
            evidence["authority_ref"],
            code="MCP_AUTHORITY_NOT_FOUND",
            label="Evidence authority",
        )
        source = _find_by_ref(
            bundle["sources"],
            "source_ref",
            evidence["source_ref"],
            code="MCP_SOURCE_NOT_FOUND",
            label="Evidence source",
        )
        return {
            "view_kind": "mcp_evidence_view",
            "bundle_handle": bundle_handle,
            "evidence_span": evidence,
            "authority": authority,
            "source": source,
        }

    def get_normative_relationships(
        self,
        *,
        bundle_handle: str,
        authority_ref: str | None = None,
        relationship_type: str | None = None,
    ) -> dict[str, Any]:
        bundle = self.store.get(bundle_handle)["bundle"]
        relationships = []
        for item in bundle["normative_relationships"]:
            if authority_ref is not None and authority_ref not in {
                item.get("source_authority_ref"),
                item.get("target_authority_ref"),
            }:
                continue
            if (
                relationship_type is not None
                and item.get("relationship_type") != relationship_type
            ):
                continue
            relationships.append(copy.deepcopy(item))
        return {
            "view_kind": "mcp_normative_relationship_view",
            "bundle_handle": bundle_handle,
            "authority_ref": authority_ref,
            "relationship_type": relationship_type,
            "normative_relationships": relationships,
        }

    def get_calculation(
        self,
        *,
        bundle_handle: str,
        calculation_ref: str,
    ) -> dict[str, Any]:
        bundle = self.store.get(bundle_handle)["bundle"]
        calculation = _find_by_ref(
            bundle["calculation_traces"],
            "calculation_ref",
            calculation_ref,
            code="MCP_CALCULATION_NOT_FOUND",
            label="Calculation",
        )
        evidence_refs = set(calculation.get("evidence_refs", []))
        rule_refs = set(calculation.get("rule_refs", []))
        evaluations = [
            copy.deepcopy(item)
            for item in bundle["deterministic_evaluations"]
            if calculation_ref in item.get("calculation_trace_refs", [])
        ]
        return {
            "view_kind": "mcp_calculation_view",
            "bundle_handle": bundle_handle,
            "calculation": calculation,
            "deterministic_evaluations": evaluations,
            "rule_fragments": _by_refs(bundle["rule_fragments"], "rule_ref", rule_refs),
            "evidence_spans": _by_refs(
                bundle["evidence_spans"], "evidence_ref", evidence_refs
            ),
        }
