from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import os
from pathlib import Path
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest
import uuid

from case_attempt_evidence import (
    GenerationEvidence,
    GenerationResult,
    RejectedAttemptEvidenceStore,
    deterministic_json_bytes,
)
from case_contract_validation import (
    CONTRACT_VERSION,
    CaseContractError,
    INVALID_CASE_DRAFT,
    case_draft_response_schema,
    validate_case_draft,
    validate_schema_object,
)


CASE_STRUCTURING_UNAVAILABLE = "CASE_STRUCTURING_UNAVAILABLE"
CASE_PROVIDER_TIMEOUT = "CASE_PROVIDER_TIMEOUT"
CASE_CONTEXT_LIMIT = "CASE_CONTEXT_LIMIT"
CASE_OUTPUT_LIMIT = "CASE_OUTPUT_LIMIT"

PROMPT_TEMPLATE_ID = "case-structuring-v3"
PROMPT_TEMPLATE_VERSION = "4"

SYSTEM_PROMPT = """You structure a Colombian legal/tax case into the supplied JSON schema.
The response schema pins problem_text, as_of_date, and client_reference to the
exact client-owned values and presence/absence. Emit them exactly as constrained;
never rewrite, normalize, omit, or manufacture them.
Only problem_text is client fact source text. analysis_context.as_of_date is a
temporal analysis parameter, not a user-provided fact or source quote.
client_reference is correlation metadata and is intentionally not model context.
Never create a CaseFact from either metadata field unless the same information is
also stated verbatim inside problem_text. Every user_provided fact must use a
source_quote copied verbatim from problem_text and requires_confirmation=false.
llm_normalized and llm_inferred facts always use requires_confirmation=true.
missing and ambiguous facts always use requires_confirmation=true and
needed_information. If problem_text directly and unambiguously states information
for a fact you choose to represent, never downgrade that fact to missing; represent
the stated client information as user_provided with a verbatim source_quote. Use
missing only for a concrete datum absent from problem_text, and needed_information
must name that absent datum instead of generically asking what information about an
already described topic is required. Truly ambiguous information remains ambiguous.
Every legal conclusion is only a candidate_claim. Never emit canonical/persistence document,
provision, evidence, manifestation, segment, relationship, source, claim, or case
identifiers. Target hints may contain ordinary human-readable legal references or
search phrases only. Do not assert that a candidate is validated and do not
invent evidence."""


class LLMClientError(RuntimeError):
    """Operational failure in an LLM backend adapter."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retryable: bool = False,
        evidence: GenerationEvidence | None = None,
        failure_stage: str | None = None,
    ):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.evidence = evidence
        self.failure_stage = failure_stage


class ContextLimitError(LLMClientError):
    def __init__(self, detail: str, metadata: dict[str, Any]):
        super().__init__(CASE_CONTEXT_LIMIT, detail, retryable=False)
        self.metadata = metadata


class OutputLimitError(LLMClientError):
    """Provider response reached the configured output ceiling."""

    def __init__(
        self,
        detail: str,
        metadata: dict[str, Any],
        *,
        evidence: GenerationEvidence | None = None,
    ):
        super().__init__(
            CASE_OUTPUT_LIMIT,
            detail,
            retryable=False,
            evidence=evidence,
            failure_stage="output_ceiling",
        )
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


@dataclass(frozen=True)
class StructuredGenerationCapability:
    """Provider-neutral guarantees required for CASE draft generation."""

    mechanism: str
    schema_constrained: bool
    direct_object: bool
    post_response_repair: bool = False

    def is_case_compatible(self) -> bool:
        """Return whether the declared mechanism satisfies the CASE boundary."""
        return (
            bool(self.mechanism.strip())
            and self.schema_constrained
            and self.direct_object
            and not self.post_response_repair
        )


class LLMClient(Protocol):
    adapter_id: str
    provider_id: str
    structured_generation_capability: StructuredGenerationCapability | None

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> GenerationResult | dict[str, Any]:
        """Return an untrusted candidate, carrying provider evidence when available."""


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


def _model_input_context(case_input: dict[str, Any]) -> dict[str, Any]:
    """Expose analytical input while keeping correlation metadata out of model facts."""
    context: dict[str, Any] = {"problem_text": case_input["problem_text"]}
    if "as_of_date" in case_input:
        context["analysis_context"] = {"as_of_date": case_input["as_of_date"]}
    return context


def _estimate_request_tokens(
    *,
    model_input: dict[str, Any],
    response_schema: dict[str, Any],
    chars_per_token: float,
) -> tuple[int, int]:
    serialized_chars = len(SYSTEM_PROMPT)
    serialized_chars += len(_compact_json(model_input))
    serialized_chars += len(_compact_json(response_schema))
    estimated_tokens = math.ceil(serialized_chars / max(chars_per_token, 1.0))
    return serialized_chars, estimated_tokens


class OpenAICompatibleLLMClient:
    """Minimal provider-neutral HTTP adapter for OpenAI-compatible chat completions."""

    adapter_id = "openai-compatible"
    structured_generation_capability = StructuredGenerationCapability(
        mechanism="json_schema",
        schema_constrained=True,
        direct_object=True,
        post_response_repair=False,
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

    def _safe_provider_payload(
        self,
        raw: bytes | None,
    ) -> tuple[bytes | None, str | None]:
        """Exclude configured credential material if a provider echoes it."""
        if raw is None or not self.config.api_key_env:
            return raw, None
        secret = os.environ.get(self.config.api_key_env)
        if secret and secret.encode("utf-8") in raw:
            return None, "configured_api_key_material_detected"
        return raw, None

    def complete_case_draft(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> GenerationResult:
        response_schema = case_draft_response_schema(case_input)
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
                {"role": "user", "content": _compact_json(model_input)},
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
        request_sha256 = hashlib.sha256(body).hexdigest()
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

        response_status: int | None = None
        try:
            with urlrequest.urlopen(req, timeout=self.config.timeout_seconds) as response:
                status_value = getattr(response, "status", None)
                if isinstance(status_value, int) and not isinstance(status_value, bool):
                    response_status = status_value
                raw = response.read()
        except TimeoutError as exc:
            raise LLMClientError(
                CASE_PROVIDER_TIMEOUT,
                f"OpenAI-compatible backend timed out: {exc}",
                retryable=True,
                evidence=GenerationEvidence(
                    provider_request_attempted=True,
                    provider_request_sha256=request_sha256,
                    http_status=response_status,
                ),
                failure_stage="transport",
            ) from exc
        except urlerror.HTTPError as exc:
            try:
                raw_error = exc.read()
            except (AttributeError, OSError):
                raw_error = None
            safe_raw, omission_reason = self._safe_provider_payload(raw_error)
            evidence = GenerationEvidence(
                provider_request_attempted=True,
                provider_request_sha256=request_sha256,
                http_status=exc.code,
                raw_response=safe_raw,
                payload_omission_reason=omission_reason,
            )
            if 400 <= exc.code < 500:
                raise LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    (
                        "backend rejected the required structured-generation "
                        f"request with HTTP {exc.code}"
                    ),
                    retryable=False,
                    evidence=evidence,
                    failure_stage="transport",
                ) from exc
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: HTTP {exc.code}",
                retryable=True,
                evidence=evidence,
                failure_stage="transport",
            ) from exc
        except urlerror.URLError as exc:
            code = (
                CASE_PROVIDER_TIMEOUT
                if isinstance(exc.reason, TimeoutError)
                else CASE_STRUCTURING_UNAVAILABLE
            )
            raise LLMClientError(
                code,
                f"OpenAI-compatible backend unavailable: {exc}",
                retryable=True,
                evidence=GenerationEvidence(
                    provider_request_attempted=True,
                    provider_request_sha256=request_sha256,
                ),
                failure_stage="transport",
            ) from exc
        except OSError as exc:
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                f"OpenAI-compatible backend unavailable: {exc}",
                retryable=True,
                evidence=GenerationEvidence(
                    provider_request_attempted=True,
                    provider_request_sha256=request_sha256,
                    http_status=response_status,
                ),
                failure_stage="transport",
            ) from exc

        safe_raw, omission_reason = self._safe_provider_payload(raw)
        base_evidence = GenerationEvidence(
            provider_request_attempted=True,
            provider_request_sha256=request_sha256,
            http_status=response_status,
            raw_response=safe_raw,
            payload_omission_reason=omission_reason,
        )
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed provider envelope: {exc}",
                retryable=True,
                evidence=base_evidence,
                failure_stage="provider_envelope_parse",
            ) from exc

        if not isinstance(envelope, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "backend returned a non-object provider envelope",
                retryable=True,
                evidence=base_evidence,
                failure_stage="provider_envelope_parse",
            )

        body_sensitive = omission_reason is not None
        served_model = None if body_sensitive else deepcopy(envelope.get("model"))
        usage = None if body_sensitive else deepcopy(envelope.get("usage"))
        envelope_evidence = replace(
            base_evidence,
            served_model=served_model,
            usage=usage,
        )

        try:
            if not isinstance(envelope.get("model"), str):
                raise TypeError("response.model is not a string")
            if envelope["model"] != route.name:
                raise LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    (
                        f"backend served model {envelope['model']!r} for requested "
                        f"route {route.name!r}"
                    ),
                    retryable=False,
                    evidence=envelope_evidence,
                    failure_stage="provider_envelope_parse",
                )
            choices = envelope["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError("response.choices is not a non-empty list")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise TypeError("response.choices[0] is not an object")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed structured envelope: {exc}",
                retryable=True,
                evidence=envelope_evidence,
                failure_stage="provider_envelope_parse",
            ) from exc

        finish_reason = None if body_sensitive else deepcopy(choice.get("finish_reason"))
        message = choice.get("message")
        raw_content = message.get("content") if isinstance(message, dict) else None
        assistant_content = (
            raw_content
            if isinstance(raw_content, str) and not body_sensitive
            else None
        )
        choice_evidence = replace(
            envelope_evidence,
            finish_reason=finish_reason,
            assistant_content=assistant_content,
        )

        completion_tokens = (
            usage.get("completion_tokens")
            if isinstance(usage, dict)
            else None
        )
        output_ceiling_reached = (
            choice.get("finish_reason") == "length"
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
                    "finish_reason": choice.get("finish_reason"),
                    "completion_tokens": completion_tokens,
                    "max_output_tokens": route.max_output_tokens,
                    "truncated": True,
                },
                evidence=choice_evidence,
            )

        if not isinstance(message, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "backend returned malformed structured envelope: message is not an object",
                retryable=True,
                evidence=choice_evidence,
                failure_stage="provider_envelope_parse",
            )
        if not isinstance(raw_content, str):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "backend returned malformed structured envelope: message.content is not a string",
                retryable=True,
                evidence=choice_evidence,
                failure_stage="provider_envelope_parse",
            )

        try:
            draft_payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                f"backend returned malformed structured output: {exc}",
                retryable=True,
                evidence=choice_evidence,
                failure_stage="json_parse",
            ) from exc

        candidate_json = deterministic_json_bytes(draft_payload)
        candidate_evidence = replace(
            choice_evidence,
            candidate_json=None if body_sensitive else candidate_json,
            candidate_payload=(
                deepcopy(draft_payload)
                if isinstance(draft_payload, dict) and not body_sensitive
                else None
            ),
        )
        if not isinstance(draft_payload, dict):
            raise LLMClientError(
                INVALID_CASE_DRAFT,
                "structured output root is not an object",
                retryable=True,
                evidence=candidate_evidence,
                failure_stage="schema_validation",
            )

        return GenerationResult(
            payload=draft_payload,
            evidence=candidate_evidence,
        )


class FakeLLMClient:
    """Deterministic model adapter used by unit/integration tests."""

    adapter_id = "fake-llm"
    provider_id = "test"

    def __init__(
        self,
        outputs: list[dict[str, Any] | Exception],
        *,
        structured_generation_capability: StructuredGenerationCapability | None = (
            StructuredGenerationCapability(
                mechanism="deterministic-test-schema",
                schema_constrained=True,
                direct_object=True,
                post_response_repair=False,
            )
        ),
    ):
        self._outputs = list(outputs)
        self.calls: list[ModelRoute] = []
        self.structured_generation_capability = structured_generation_capability

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
    """Apply retry policy and preserve evidence for provider-reaching rejections."""

    def __init__(
        self,
        config: LLMPlatformConfig,
        client: LLMClient,
        *,
        evidence_root: Path | None = None,
    ):
        self.config = config
        self.client = client
        self.evidence_store = (
            RejectedAttemptEvidenceStore(evidence_root)
            if evidence_root is not None
            else None
        )

    def _require_generation_compatibility(self) -> None:
        capability = getattr(self.client, "structured_generation_capability", None)
        if (
            capability is None
            or not isinstance(capability, StructuredGenerationCapability)
            or not capability.is_case_compatible()
        ):
            raise LLMClientError(
                CASE_STRUCTURING_UNAVAILABLE,
                (
                    "backend is incompatible with CASE structuring: a supported "
                    "schema-constrained, directly parseable, non-repairing "
                    "structured-generation mechanism is required"
                ),
                retryable=False,
            )

    @staticmethod
    def _case_input_sha256(case_input: dict[str, Any]) -> str:
        canonical = json.dumps(
            case_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _failure_path(detail: str) -> str | None:
        match = re.match(r"^(\$[^:]*):", detail)
        return match.group(1) if match else None

    def _record_rejection(
        self,
        *,
        attempt_id: str,
        raw_request_sha256: str | None,
        case_input: dict[str, Any],
        route: ModelRoute,
        started_at: str,
        failure_stage: str,
        failure_code: str,
        failure_detail: str,
        evidence: GenerationEvidence,
    ) -> None:
        if self.evidence_store is None:
            return
        if not evidence.provider_request_attempted:
            # Pre-dispatch failures belong to admission/runtime-envelope handling,
            # not the rejected-provider-output artifact namespace.
            return
        self.evidence_store.record(
            attempt_id=attempt_id,
            raw_request_sha256=raw_request_sha256,
            case_input_sha256=self._case_input_sha256(case_input),
            adapter=self.client.adapter_id,
            provider=self.client.provider_id,
            model=route.name,
            routing_role=route.routing_role,
            contract_version=CONTRACT_VERSION,
            prompt_template_id=PROMPT_TEMPLATE_ID,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            schema_version=CONTRACT_VERSION,
            started_at=started_at,
            ended_at=utc_now(),
            failure_stage=failure_stage,
            failure_code=failure_code,
            failure_detail=failure_detail,
            failure_path=self._failure_path(failure_detail),
            evidence=evidence,
        )

    @staticmethod
    def _candidate_evidence(
        payload: dict[str, Any],
        evidence: GenerationEvidence | None,
    ) -> GenerationEvidence:
        candidate_json = deterministic_json_bytes(payload)
        if evidence is None:
            return GenerationEvidence(
                provider_request_attempted=True,
                candidate_payload=deepcopy(payload),
                candidate_json=candidate_json,
            )
        # A successful generation result necessarily represents a completed
        # provider/backend generation attempt, even for a legacy adapter that
        # omitted the explicit dispatch bit.
        updated = (
            evidence
            if evidence.provider_request_attempted
            else replace(evidence, provider_request_attempted=True)
        )
        if updated.payload_omission_reason is not None:
            return updated
        if updated.candidate_json is None or updated.candidate_payload is None:
            return replace(
                updated,
                candidate_payload=deepcopy(payload),
                candidate_json=candidate_json,
            )
        return updated

    def _attempt(
        self,
        case_input: dict[str, Any],
        route: ModelRoute,
        *,
        raw_request_sha256: str | None,
    ) -> dict[str, Any]:
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        started_at = utc_now()
        evidence: GenerationEvidence | None = None
        try:
            generated = self.client.complete_case_draft(
                case_input=case_input,
                route=route,
            )
            if isinstance(generated, GenerationResult):
                payload = generated.payload
                evidence = generated.evidence
            else:
                payload = generated

            evidence = self._candidate_evidence(payload, evidence)

            if "model_metadata" in payload:
                exc = CaseContractError(
                    INVALID_CASE_DRAFT,
                    "$.model_metadata: model must not supply app-owned model_metadata",
                )
                self._record_rejection(
                    attempt_id=attempt_id,
                    raw_request_sha256=raw_request_sha256,
                    case_input=case_input,
                    route=route,
                    started_at=started_at,
                    failure_stage="semantic_validation",
                    failure_code=exc.code,
                    failure_detail=exc.detail,
                    evidence=evidence,
                )
                raise exc

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
            # The authoritative validator remains the first and final application
            # validity gate. Schema replay after rejection is classification only.
            try:
                validate_case_draft(case_input, draft)
            except CaseContractError as exc:
                try:
                    validate_schema_object(draft, "CaseDraft", INVALID_CASE_DRAFT)
                except CaseContractError:
                    failure_stage = "schema_validation"
                else:
                    failure_stage = "semantic_validation"
                self._record_rejection(
                    attempt_id=attempt_id,
                    raw_request_sha256=raw_request_sha256,
                    case_input=case_input,
                    route=route,
                    started_at=started_at,
                    failure_stage=failure_stage,
                    failure_code=exc.code,
                    failure_detail=exc.detail,
                    evidence=evidence,
                )
                raise
            return draft
        except LLMClientError as exc:
            failure_evidence = exc.evidence or evidence
            if (
                failure_evidence is not None
                and failure_evidence.provider_request_attempted
            ):
                self._record_rejection(
                    attempt_id=attempt_id,
                    raw_request_sha256=raw_request_sha256,
                    case_input=case_input,
                    route=route,
                    started_at=started_at,
                    failure_stage=exc.failure_stage or "transport",
                    failure_code=exc.code,
                    failure_detail=exc.detail,
                    evidence=failure_evidence,
                )
            raise
        except CaseContractError:
            # Validation failures above are already recorded with the exact
            # schema/semantic stage and must not create a second artifact.
            raise

    def structure(
        self,
        case_input: dict[str, Any],
        *,
        raw_request_sha256: str | None = None,
    ) -> StructuringOutcome:
        self._require_generation_compatibility()
        attempts = 0
        last_invalid: Exception | None = None
        provider_error: LLMClientError | None = None

        for _ in range(self.config.primary_attempts):
            attempts += 1
            try:
                return StructuringOutcome(
                    draft=self._attempt(
                        case_input,
                        self.config.primary,
                        raw_request_sha256=raw_request_sha256,
                    ),
                    attempts=attempts,
                    used_review=False,
                )
            except (ContextLimitError, OutputLimitError):
                raise
            except CaseContractError as exc:
                last_invalid = exc
            except LLMClientError as exc:
                if exc.code in (CASE_CONTEXT_LIMIT, CASE_OUTPUT_LIMIT):
                    raise
                if exc.code == INVALID_CASE_DRAFT:
                    last_invalid = exc
                    continue
                provider_error = exc
                if not exc.retryable:
                    break

        should_review = (
            self.config.review_on_invalid_output
            if last_invalid is not None
            else self.config.review_on_provider_error
            if provider_error is not None
            else False
        )
        if should_review and self.config.review is not None:
            attempts += 1
            try:
                return StructuringOutcome(
                    draft=self._attempt(
                        case_input,
                        self.config.review,
                        raw_request_sha256=raw_request_sha256,
                    ),
                    attempts=attempts,
                    used_review=True,
                )
            except (ContextLimitError, OutputLimitError):
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

