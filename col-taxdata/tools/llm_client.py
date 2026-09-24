from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest
import uuid

from case_contract_validation import (
    CONTRACT_VERSION,
    CaseContractError,
    INVALID_CASE_DRAFT,
    case_draft_response_schema,
    validate_case_draft,
)


CASE_STRUCTURING_UNAVAILABLE = "CASE_STRUCTURING_UNAVAILABLE"
CASE_CONTEXT_LIMIT = "CASE_CONTEXT_LIMIT"

PROMPT_TEMPLATE_ID = "case-structuring-v3"
PROMPT_TEMPLATE_VERSION = "1"

SYSTEM_PROMPT = """You structure a Colombian legal/tax case into the supplied JSON schema.
Preserve problem_text, as_of_date, and client_reference exactly, including absence.
Facts explicitly stated by the client use state=user_provided and a verbatim source_quote.
Normalization or inference must use llm_normalized/llm_inferred and require confirmation.
Unknown required facts remain missing/ambiguous. Every legal conclusion is only a
candidate_claim. Never emit canonical/persistence document, provision, evidence,
manifestation, segment, relationship, source, claim, or case identifiers. Target hints
may contain ordinary human-readable legal references or search phrases only.
Do not assert that a candidate is validated and do not invent evidence."""


class LLMClientError(RuntimeError):
    """Operational failure in an LLM backend adapter."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable


class ContextLimitError(LLMClientError):
    def __init__(self, detail: str, metadata: dict[str, Any]):
        super().__init__(CASE_CONTEXT_LIMIT, detail, retryable=False)
        self.metadata = metadata


@dataclass(frozen=True)
class ModelRoute:
    name: str
    routing_role: str
    context_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class LLMPlatformConfig:
    adapter: str
    provider: str
    base_url: str
    timeout_seconds: int
    chars_per_token_estimate: float
    primary: ModelRoute
    auxiliary: ModelRoute | None
    review: ModelRoute | None
    primary_attempts: int
    review_on_invalid_output: bool
    review_on_provider_error: bool
    api_key_env: str | None = None
    request_options: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    adapter_id: str
    provider_id: str

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        """Return model-owned CaseDraft fields, excluding model_metadata."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _model_route(value: dict[str, Any] | None, role: str) -> ModelRoute | None:
    if value is None:
        return None
    return ModelRoute(
        name=str(value["name"]),
        routing_role=str(value.get("routing_role", role)),
        context_tokens=int(value["context_tokens"]),
        max_output_tokens=int(value["max_output_tokens"]),
    )


def load_platform_config(path: Path) -> LLMPlatformConfig:
    """Load the JSON-compatible YAML integration profile with no third-party dependency."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    models = raw["models"]
    routing = raw["routing"]
    context = raw["context"]

    primary = _model_route(models.get("primary"), "primary")
    if primary is None:
        raise ValueError("LLM configuration requires models.primary")

    return LLMPlatformConfig(
        adapter=str(raw["adapter"]),
        provider=str(raw["provider"]),
        base_url=os.environ.get(
            "COL_TAXDATA_LLM_BASE_URL",
            str(raw["base_url"]),
        ).rstrip("/"),
        timeout_seconds=int(raw.get("request_timeout_seconds", 120)),
        chars_per_token_estimate=float(
            context.get("chars_per_token_estimate", 4.0)
        ),
        primary=primary,
        auxiliary=_model_route(models.get("auxiliary"), "auxiliary"),
        review=_model_route(models.get("review"), "review"),
        primary_attempts=max(1, int(routing.get("primary_attempts", 1))),
        review_on_invalid_output=bool(
            routing.get("review_on_invalid_output", False)
        ),
        review_on_provider_error=bool(
            routing.get("review_on_provider_error", False)
        ),
        api_key_env=raw.get("api_key_env"),
        request_options=deepcopy(raw.get("request_options", {})),
    )


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _estimate_request_tokens(
    *,
    case_input: dict[str, Any],
    response_schema: dict[str, Any],
    chars_per_token: float,
) -> tuple[int, int]:
    serialized_chars = len(SYSTEM_PROMPT)
    serialized_chars += len(_compact_json(case_input))
    serialized_chars += len(_compact_json(response_schema))
    estimated_tokens = math.ceil(serialized_chars / max(chars_per_token, 1.0))
    return serialized_chars, estimated_tokens


class OpenAICompatibleLLMClient:
    """Minimal provider-neutral HTTP adapter for OpenAI-compatible chat completions."""

    adapter_id = "openai-compatible"

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

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        response_schema = case_draft_response_schema()
        char_count, estimated_tokens = _estimate_request_tokens(
            case_input=case_input,
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
                    "content": _compact_json(case_input),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "case_draft_v3",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            **deepcopy(self.config.request_options),
        }
        body = _compact_json(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._authorization_header(),
        }
        req = urlrequest.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlrequest.urlopen(
                req,
                timeout=self.config.timeout_seconds,
            ) as response:
                raw = response.read()
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: {exc}",
                retryable=True,
            ) from exc

        try:
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content is not a string")
            draft_payload = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed structured output: {exc}",
                retryable=True,
            ) from exc

        if not isinstance(draft_payload, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "structured output root is not an object",
                retryable=True,
            )
        return draft_payload


class FakeLLMClient:
    """Deterministic model adapter used by unit/integration tests."""

    adapter_id = "fake-llm"
    provider_id = "test"

    def __init__(self, outputs: list[dict[str, Any] | Exception]):
        self._outputs = list(outputs)
        self.calls: list[ModelRoute] = []

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        del case_input
        self.calls.append(route)
        if not self._outputs:
            raise AssertionError("fake LLM output queue exhausted")
        value = self._outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


@dataclass(frozen=True)
class StructuringOutcome:
    draft: dict[str, Any]
    attempts: int
    used_review: bool


class CaseStructuringService:
    """Apply configured retry/escalation policy around a provider-neutral LLM client."""

    def __init__(self, config: LLMPlatformConfig, client: LLMClient):
        self.config = config
        self.client = client

    def _attempt(
        self,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        payload = self.client.complete_case_draft(
            case_input=case_input,
            route=route,
        )
        if "model_metadata" in payload:
            raise CaseContractError(
                INVALID_CASE_DRAFT,
                "model must not supply app-owned model_metadata",
            )

        draft = deepcopy(payload)
        draft["model_metadata"] = {
            "adapter": self.client.adapter_id,
            "provider": self.client.provider_id,
            "model": route.name,
            "schema_version": CONTRACT_VERSION,
            "prompt_template_id": PROMPT_TEMPLATE_ID,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "run_reference": f"run:{uuid.uuid4().hex}",
            "generated_at": utc_now(),
            "routing_role": route.routing_role,
        }
        validate_case_draft(case_input, draft)
        return draft

    def structure(self, case_input: dict[str, Any]) -> StructuringOutcome:
        attempts = 0
        last_invalid: Exception | None = None
        provider_error: LLMClientError | None = None

        for _ in range(self.config.primary_attempts):
            attempts += 1
            try:
                return StructuringOutcome(
                    draft=self._attempt(case_input, self.config.primary),
                    attempts=attempts,
                    used_review=False,
                )
            except ContextLimitError:
                raise
            except CaseContractError as exc:
                last_invalid = exc
            except LLMClientError as exc:
                if exc.code == CASE_CONTEXT_LIMIT:
                    raise
                if exc.code == INVALID_CASE_DRAFT:
                    last_invalid = exc
                    continue
                provider_error = exc
                if not exc.retryable:
                    break

        should_review = False
        if last_invalid is not None:
            should_review = self.config.review_on_invalid_output
        elif provider_error is not None:
            should_review = self.config.review_on_provider_error

        if should_review and self.config.review is not None:
            attempts += 1
            try:
                return StructuringOutcome(
                    draft=self._attempt(case_input, self.config.review),
                    attempts=attempts,
                    used_review=True,
                )
            except ContextLimitError:
                raise
            except (CaseContractError, LLMClientError) as exc:
                last_invalid = exc

        if last_invalid is not None:
            if isinstance(last_invalid, CaseContractError):
                raise last_invalid
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                getattr(last_invalid, "detail", str(last_invalid)),
                retryable=False,
            )
        if provider_error is not None:
            raise provider_error
        raise LLMClientError(
            CASE_STRUCTURING_UNAVAILABLE,
            "no structuring attempt produced a result",
        )
