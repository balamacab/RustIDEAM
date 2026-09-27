from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from case_attempt_evidence import (
    FAILURE_JSON_PARSE,
    FAILURE_OUTPUT_CEILING,
    FAILURE_PROVIDER_ENVELOPE,
    FAILURE_SCHEMA_VALIDATION,
    FAILURE_TRANSPORT,
    GenerationEvidence,
    canonical_json_bytes,
    sha256_hex,
)
from case_contract_validation import INVALID_CASE_DRAFT, case_draft_generation_schema
from llm_client import (
    CASE_PROVIDER_TIMEOUT,
    CASE_STRUCTURING_UNAVAILABLE,
    ContextLimitError,
    GeneratedCaseDraft,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OutputLimitError,
    StructuredGenerationCapability,
    SYSTEM_PROMPT,
    _compact_json,
    _estimate_request_tokens,
    _materialize_client_owned_fields,
    _model_input_context,
)

class OpenAICompatibleIntakeAdapter:
    """Minimal provider-neutral HTTP adapter for OpenAI-compatible chat completions."""

    adapter_id = "openai-compatible"
    structured_generation_capability = StructuredGenerationCapability(
        mechanism="json_schema",
        schema_constrained=True,
        direct_object=False,
        post_response_repair=False,
        deterministic_client_payload_materialization=True,
    )

    def __init__(self, config: LLMPlatformConfig):
        self.config = config
        self.provider_id = config.provider

    def _authorization_header(self) -> dict[str, str]:
        if not self.config.api_key_env:
            return {}
        value = os.environ.get(self.config.api_key_env)
        if not value:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"required credential environment variable {self.config.api_key_env!r} is absent",
            )
        return {"Authorization": f"Bearer {value}"}

    def structure_intake(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        """Return one parsed structured intake candidate, never a provider envelope."""
        return self.complete_case_draft(case_input=case_input, route=route)

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        response_schema = case_draft_generation_schema(case_input)
        response_schema_sha256 = sha256_hex(canonical_json_bytes(response_schema))
        model_input = _model_input_context(case_input)
        char_count, estimated_tokens = _estimate_request_tokens(
            model_input=model_input,
            response_schema=response_schema,
            chars_per_token=self.config.chars_per_token_estimate,
        )
        total_budget = estimated_tokens + route.max_output_tokens
        if total_budget > route.context_tokens:
            raise ContextLimitError(
                (
                    f"estimated request/output budget {total_budget} exceeds "
                    f"configured context {route.context_tokens}; input was not truncated"
                ),
                {
                    "model": route.name,
                    "routing_role": route.routing_role,
                    "input_chars": len(case_input["problem_text"]),
                    "serialized_request_chars": char_count,
                    "estimated_input_tokens": estimated_tokens,
                    "reserved_output_tokens": route.max_output_tokens,
                    "configured_context_tokens": route.context_tokens,
                    "processed_portions": [],
                    "truncated": False,
                },
            )

        forbidden_request_options = {
            "model",
            "messages",
            "response_format",
            "temperature",
            "max_tokens",
        }.intersection(self.config.request_options)
        if forbidden_request_options:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                "adapter request_options cannot override application-owned fields: "
                + ", ".join(sorted(forbidden_request_options)),
            )

        payload = {
            "model": route.name,
            "temperature": 0,
            "max_tokens": route.max_output_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _compact_json(model_input),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "case_draft_v3_generation",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            **deepcopy(self.config.request_options),
        }
        body = _compact_json(payload).encode("utf-8")
        provider_request_sha256 = sha256_hex(body)
        authorization_headers = self._authorization_header()
        configured_secret_values: tuple[bytes, ...] = ()
        if self.config.api_key_env and authorization_headers:
            # Capture only the exact credential value actually resolved for this
            # outbound request. It is carried in memory solely for deterministic
            # evidence suppression and is never serialized into the audit store.
            api_key_value = os.environ.get(self.config.api_key_env)
            if api_key_value:
                configured_secret_values = (api_key_value.encode("utf-8"),)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **authorization_headers,
        }
        req = urlrequest.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )

        def evidence(
            *,
            raw: bytes | None = None,
            http_status: int | None = None,
            served_model: str | None = None,
            finish_reason: str | None = None,
            usage: dict[str, Any] | None = None,
            content: str | None = None,
            candidate: Any = None,
            candidate_present: bool = False,
        ) -> GenerationEvidence:
            candidate_bytes = (
                canonical_json_bytes(candidate)
                if candidate_present
                else None
            )
            return GenerationEvidence(
                provider_contacted=True,
                provider_request_sha256=provider_request_sha256,
                response_schema_sha256=response_schema_sha256,
                provider_response_bytes=raw,
                http_status=http_status,
                served_model=served_model,
                finish_reason=finish_reason,
                usage=deepcopy(usage) if usage is not None else None,
                assistant_content=content,
                candidate_json_bytes=candidate_bytes,
                configured_secret_values=configured_secret_values,
            )

        try:
            with urlrequest.urlopen(
                req,
                timeout=self.config.timeout_seconds,
            ) as response:
                raw = response.read()
                http_status = getattr(response, "status", None)
        except TimeoutError as exc:
            raise LLMClientError(
                CASE_PROVIDER_TIMEOUT,
                f"OpenAI-compatible backend timed out: {exc}",
                retryable=True,
                generation_evidence=evidence(),
                failure_stage=FAILURE_TRANSPORT,
            ) from exc
        except urlerror.HTTPError as exc:
            try:
                error_body = exc.read()
            except Exception:
                error_body = None
            if not isinstance(error_body, bytes):
                error_body = None
            observed = evidence(raw=error_body, http_status=exc.code)
            if 400 <= exc.code < 500:
                raise LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    (
                        "backend rejected the required structured-generation "
                        f"request with HTTP {exc.code}"
                    ),
                    retryable=False,
                    generation_evidence=observed,
                    failure_stage=FAILURE_TRANSPORT,
                ) from exc
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: HTTP {exc.code}",
                retryable=True,
                generation_evidence=observed,
                failure_stage=FAILURE_TRANSPORT,
            ) from exc
        except urlerror.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMClientError(
                    CASE_PROVIDER_TIMEOUT,
                    f"OpenAI-compatible backend timed out: {exc.reason}",
                    retryable=True,
                    generation_evidence=evidence(),
                    failure_stage=FAILURE_TRANSPORT,
                ) from exc
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: {exc}",
                retryable=True,
                generation_evidence=evidence(),
                failure_stage=FAILURE_TRANSPORT,
            ) from exc
        except OSError as exc:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: {exc}",
                retryable=True,
                generation_evidence=evidence(),
                failure_stage=FAILURE_TRANSPORT,
            ) from exc

        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed provider envelope: {exc}",
                retryable=True,
                generation_evidence=evidence(raw=raw, http_status=http_status),
                failure_stage=FAILURE_PROVIDER_ENVELOPE,
            ) from exc
        if not isinstance(envelope, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "backend returned malformed provider envelope: root is not an object",
                retryable=True,
                generation_evidence=evidence(raw=raw, http_status=http_status),
                failure_stage=FAILURE_PROVIDER_ENVELOPE,
            )

        served_model_value = envelope.get("model")
        served_model = (
            served_model_value if isinstance(served_model_value, str) else None
        )
        try:
            if served_model is None:
                raise TypeError("response.model is not a string")
            choices = envelope["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError("response.choices is not a non-empty array")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise TypeError("response.choices[0] is not an object")
            finish_reason_value = choice.get("finish_reason")
            finish_reason = (
                finish_reason_value
                if isinstance(finish_reason_value, str)
                else None
            )
            usage_value = envelope.get("usage") or {}
            if not isinstance(usage_value, dict):
                raise TypeError("response.usage is not an object")
            usage = usage_value
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError("response.choices[0].message is not an object")
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("message.content is not a string")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed provider envelope: {exc}",
                retryable=True,
                generation_evidence=evidence(
                    raw=raw,
                    http_status=http_status,
                    served_model=served_model,
                ),
                failure_stage=FAILURE_PROVIDER_ENVELOPE,
            ) from exc

        observed = evidence(
            raw=raw,
            http_status=http_status,
            served_model=served_model,
            finish_reason=finish_reason,
            usage=usage,
            content=content,
        )
        if served_model != route.name:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                (
                    f"backend served model {served_model!r} for requested "
                    f"route {route.name!r}"
                ),
                retryable=False,
                generation_evidence=observed,
                failure_stage=FAILURE_PROVIDER_ENVELOPE,
            )

        completion_tokens = usage.get("completion_tokens")
        output_ceiling_reached = (
            finish_reason == "length"
            or (
                isinstance(completion_tokens, int)
                and not isinstance(completion_tokens, bool)
                and completion_tokens >= route.max_output_tokens
            )
        )
        if output_ceiling_reached:
            raise OutputLimitError(
                (
                    "backend response reached the configured output "
                    f"ceiling of {route.max_output_tokens} tokens"
                ),
                {
                    "model": route.name,
                    "routing_role": route.routing_role,
                    "finish_reason": finish_reason,
                    "completion_tokens": completion_tokens,
                    "max_output_tokens": route.max_output_tokens,
                    "truncated": True,
                },
                generation_evidence=observed,
            )

        try:
            draft_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed structured JSON: {exc}",
                retryable=True,
                generation_evidence=observed,
                failure_stage=FAILURE_JSON_PARSE,
            ) from exc

        observed = evidence(
            raw=raw,
            http_status=http_status,
            served_model=served_model,
            finish_reason=finish_reason,
            usage=usage,
            content=content,
            candidate=draft_payload,
            candidate_present=True,
        )
        if not isinstance(draft_payload, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "structured output root is not an object",
                retryable=True,
                generation_evidence=observed,
                failure_stage=FAILURE_SCHEMA_VALIDATION,
                failure_path="$",
            )
        return GeneratedCaseDraft(
            _materialize_client_owned_fields(case_input, draft_payload),
            observed,
        )

