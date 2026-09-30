from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any
import uuid

from case_attempt_evidence import (
    FAILURE_JSON_PARSE,
    FAILURE_OUTPUT_CEILING,
    FAILURE_PROVIDER_ENVELOPE,
    FAILURE_SCHEMA_VALIDATION,
    FAILURE_SEMANTIC_VALIDATION,
    FAILURE_TRANSPORT,
    GenerationEvidence,
    RejectedStructuringEvidenceStore,
    canonical_json_bytes,
    sha256_hex,
    split_validation_detail,
    utc_audit_now,
)
from case_intake_inference import IntakeInferencePort
from case_contract_dispatch import (
    V3_CONTRACT_VERSION,
    V4_CONTRACT_VERSION,
    V5_CONTRACT_VERSION,
    validate_case_input as validate_dispatched_case_input,
    validate_structured_intake,
)
from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    validate_case_draft,
    validate_schema_object,
)
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    SCHEMA_PATH as V4_SCHEMA_PATH,
    normalize_intake_draft as normalize_v4_intake_draft,
)
from case_contract_validation_v5 import (
    SCHEMA_PATH as V5_SCHEMA_PATH,
    normalize_intake_draft as normalize_v5_intake_draft,
)


CASE_STRUCTURING_UNAVAILABLE = "CASE_STRUCTURING_UNAVAILABLE"
CASE_PROVIDER_TIMEOUT = "CASE_PROVIDER_TIMEOUT"
CASE_CONTEXT_LIMIT = "CASE_CONTEXT_LIMIT"
CASE_OUTPUT_LIMIT = "CASE_OUTPUT_LIMIT"
CASE_EVIDENCE_PERSISTENCE_FAILED = "CASE_EVIDENCE_PERSISTENCE_FAILED"

PROMPT_TEMPLATE_ID = "case-structuring-v3"
PROMPT_TEMPLATE_VERSION = "5"
V4_PROMPT_TEMPLATE_ID = "case-intake-v4"
V4_PROMPT_TEMPLATE_VERSION = "2"

SYSTEM_PROMPT = """You structure a Colombian legal/tax case into the supplied JSON schema.
The response schema contains the model-owned CaseDraft fields. problem_text,
as_of_date, and client_reference remain application-owned and are copied verbatim
from the validated CaseInput after generation; do not manufacture or reinterpret
them.
Only problem_text in the user message is client fact source text.
analysis_context.as_of_date is a temporal analysis parameter, not a user-provided
fact or source quote. client_reference is correlation metadata and is intentionally
not model context. Never create a CaseFact from either metadata field unless the same
information is also stated in problem_text.
For every user_provided fact, select source_quote exactly from the values permitted
by the response schema and use requires_confirmation=false. Those allowed values are
exact contiguous spans from problem_text. Never paraphrase, normalize, concatenate,
shorten, expand, or otherwise recreate their bytes. llm_normalized and llm_inferred
facts always use requires_confirmation=true and do not carry literal source_quote
evidence in the generation schema. missing and ambiguous facts always use
requires_confirmation=true and needed_information.
If problem_text directly and unambiguously states information for a fact you choose
to represent, never downgrade that fact to missing; represent the stated client
information as user_provided with one exact allowed source_quote. Use missing only
for a concrete datum absent from problem_text, and needed_information must name that
absent datum instead of generically asking what information about an already
described topic is required. Truly ambiguous information remains ambiguous.
Every legal conclusion is only a candidate_claim. Never emit canonical/persistence
document, provision, evidence, manifestation, segment, relationship, source, claim,
or case identifiers. Target hints may contain ordinary human-readable legal
references or search phrases only. Do not assert that a candidate is validated and
do not invent evidence."""

V4_SYSTEM_PROMPT = """You are an intake structurer for a Colombian legal/tax research platform.
Return only the supplied IntakeDraft JSON shape. Your authority ends at intake
structure: facts, questions, missing/ambiguous client facts, and optional neutral
search vocabulary.

Only problem_text is client fact source text. analysis_context.as_of_date is an
analysis parameter, not a fact. client_reference and caller_metadata are correlation
metadata and are intentionally not model context.

For user_provided facts, copy source_quote exactly from the allowed response-schema
values and use requires_confirmation=false. Prefer the narrowest allowed quote that
contains the complete stated fact. For llm_normalized facts, normalization may clarify
representation but must preserve the stated substance, must use an exact allowed
source_quote, and requires_confirmation=true. Never invent an unstated fact.

Missing and ambiguous facts require needed_information and confirmation. If the
problem text directly and unambiguously states a factual assertion that you choose to
represent, preserve that assertion as user_provided: do not downgrade it to missing or
ambiguous merely because its legal qualification, tax treatment, relevance, or legal
consequence still requires research. Put that legal uncertainty in an open legal
question instead. Use ambiguous only when the client text itself leaves the factual
value/meaning unresolved.

For an explicitly stated natural-person gross-income amount in UVT, use semantic_key
"col.tax.natural_person.gross_income" and a measurement containing the exact decimal
amount, unit "UVT", and the explicitly stated UVT year. For explicitly stated gross
patrimony in UVT, use semantic_key "col.tax.natural_person.gross_patrimony" with the
same measurement rules. These keys only structure caller facts; they are not legal
conclusions. Do not add a measurement or UVT year unless it is stated in source_quote.

Questions describe what platform research must resolve. A question asking how
Colombian tax/IVA law treats, applies to, taxes, exempts, requires, or characterizes a
transaction is category="legal", even when dates or components appear in the facts.
Use category="temporal" for a question whose requested answer is itself a date,
deadline, period, or effective-time fact. Do not duplicate a legal, factual,
procedural, temporal, or evidentiary research question as a missing fact merely
because its answer is unknown. A missing fact is an absent client-supplied input, not
an unknown legal answer.

search_hints may be an empty array. If present, terms are neutral advisory vocabulary
linked to questions. They do not select controlling law and must not contain typed
application/canonical identifiers.

Never emit legal conclusions, candidate claims, tax determinations, validated claim
text, calculations, final-answer prose, evidence, research plans/results, canonical
documents/provisions/sources/relationships, or platform-owned identifiers. Never
repair, relabel, or infer around the schema."""


class LLMClientError(RuntimeError):
    """Operational failure in an LLM backend adapter."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retryable: bool = False,
        generation_evidence: GenerationEvidence | None = None,
        failure_stage: str | None = None,
        failure_path: str | None = None,
    ):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.generation_evidence = generation_evidence
        self.failure_stage = failure_stage
        self.failure_path = failure_path


class EvidencePersistenceError(LLMClientError):
    """Fail-closed error raised when rejected-attempt evidence cannot be stored."""

    def __init__(
        self,
        *,
        original_failure_code: str,
        original_failure_stage: str,
        original_failure_path: str | None,
        original_failure_detail: str,
        persistence_error: Exception,
    ):
        super().__init__(
            CASE_EVIDENCE_PERSISTENCE_FAILED,
            (
                "rejected-attempt evidence persistence failed; original "
                f"failure={original_failure_code} stage={original_failure_stage}"
            ),
            retryable=False,
            failure_stage=original_failure_stage,
            failure_path=original_failure_path,
        )
        self.original_failure_code = original_failure_code
        self.original_failure_stage = original_failure_stage
        self.original_failure_path = original_failure_path
        self.original_failure_detail = original_failure_detail
        self.persistence_error_type = type(persistence_error).__name__
        self.persistence_error = persistence_error


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
        generation_evidence: GenerationEvidence | None = None,
    ):
        super().__init__(
            CASE_OUTPUT_LIMIT,
            detail,
            retryable=False,
            generation_evidence=generation_evidence,
            failure_stage=FAILURE_OUTPUT_CEILING,
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
    deterministic_client_payload_materialization: bool = False

    def is_case_compatible(self) -> bool:
        """Return whether the declared mechanism satisfies the CASE boundary."""
        return (
            bool(self.mechanism.strip())
            and self.schema_constrained
            and (
                self.direct_object
                or self.deterministic_client_payload_materialization
            )
            and not self.post_response_repair
        )


@dataclass(frozen=True)
class StructuringContractProfile:
    """Version-specific intake generation/validation policy."""

    contract_version: str
    prompt_template_id: str
    prompt_template_version: str
    system_prompt: str
    response_schema_name: str
    invalid_output_code: str
    metadata_routing_role: str | None = None


def _structuring_contract_profile(
    case_input: dict[str, Any],
) -> StructuringContractProfile:
    """Select semantics only from the explicitly validated CaseInput version."""
    version = validate_dispatched_case_input(case_input)
    if version == V3_CONTRACT_VERSION:
        return StructuringContractProfile(
            contract_version=version,
            prompt_template_id=PROMPT_TEMPLATE_ID,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            system_prompt=SYSTEM_PROMPT,
            response_schema_name="case_draft_v3_generation",
            invalid_output_code=INVALID_CASE_DRAFT,
        )
    if version == V4_CONTRACT_VERSION:
        return StructuringContractProfile(
            contract_version=version,
            prompt_template_id=V4_PROMPT_TEMPLATE_ID,
            prompt_template_version=V4_PROMPT_TEMPLATE_VERSION,
            system_prompt=V4_SYSTEM_PROMPT,
            response_schema_name="case_intake_v4_generation",
            invalid_output_code=INVALID_INTAKE_DRAFT,
            metadata_routing_role="intake_structuring",
        )
    if version == V5_CONTRACT_VERSION:
        return StructuringContractProfile(
            contract_version=version,
            prompt_template_id="case-intake-v5",
            prompt_template_version="1",
            system_prompt=V4_SYSTEM_PROMPT,
            response_schema_name="case_intake_v5_generation",
            invalid_output_code=INVALID_INTAKE_DRAFT,
            metadata_routing_role="intake_structuring",
        )
    raise AssertionError(f"validated unsupported CASE contract {version!r}")


class GeneratedCaseDraft(dict[str, Any]):
    """Dict-compatible model candidate carrying non-canonical execution evidence."""

    def __init__(
        self,
        payload: dict[str, Any],
        generation_evidence: GenerationEvidence,
    ):
        super().__init__(payload)
        self.generation_evidence = generation_evidence


# Backward-compatible type alias; new application code depends on the semantic port.
LLMClient = IntakeInferencePort


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


def _materialize_client_owned_fields(
    case_input: dict[str, Any],
    generated_payload: dict[str, Any],
) -> dict[str, Any]:
    """Copy omitted client-owned fields exactly; never overwrite model output.

    This deterministic transport materialization is not semantic repair. If a
    backend unexpectedly emits one of these fields, its value is preserved so the
    authoritative cross-object validator can accept an exact value or reject drift.
    """
    draft = deepcopy(generated_payload)
    for name in (
        "problem_text",
        "as_of_date",
        "client_reference",
        "caller_metadata",
    ):
        if name in case_input and name not in draft:
            draft[name] = case_input[name]
    return draft


def _estimate_request_tokens(
    *,
    model_input: dict[str, Any],
    response_schema: dict[str, Any],
    chars_per_token: float,
    system_prompt: str = SYSTEM_PROMPT,
) -> tuple[int, int]:
    serialized_chars = len(system_prompt)
    serialized_chars += len(_compact_json(model_input))
    serialized_chars += len(_compact_json(response_schema))
    estimated_tokens = math.ceil(serialized_chars / max(chars_per_token, 1.0))
    return serialized_chars, estimated_tokens


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

    def structure_intake(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        """Implement the semantic intake port while preserving legacy fake behavior."""
        return self.complete_case_draft(case_input=case_input, route=route)

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

    @property
    def intake(self) -> dict[str, Any]:
        """Preferred v4 name; draft remains a frozen v3 compatibility alias."""
        return self.draft


class CaseStructuringService:
    """Apply retry policy while preserving rejected model execution evidence."""

    def __init__(
        self,
        config: LLMPlatformConfig,
        client: LLMClient,
        evidence_store: RejectedStructuringEvidenceStore | None = None,
    ):
        self.config = config
        self.client = client
        self.evidence_store = evidence_store

    def _require_generation_compatibility(self) -> None:
        """Fail closed before invoking a backend that cannot honor CASE structure."""
        capability = getattr(
            self.client,
            "structured_generation_capability",
            None,
        )
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

    def _persist_rejection(
        self,
        *,
        attempt_id: str,
        run_reference: str,
        started_at: str,
        case_input: dict[str, Any],
        route: ModelRoute,
        request_fingerprints: dict[str, str] | None,
        generation: GenerationEvidence | None,
        failure_code: str,
        failure_stage: str,
        failure_path: str | None,
        failure_detail: str,
        original_error: BaseException | None = None,
    ) -> None:
        """Persist one rejection, surfacing deterministic audit failure on error."""
        if (
            self.evidence_store is None
            or generation is None
            or not generation.provider_contacted
        ):
            return
        profile = _structuring_contract_profile(case_input)
        try:
            self.evidence_store.write_rejected_attempt(
                attempt_id=attempt_id,
                run_reference=run_reference,
                started_at=started_at,
                ended_at=utc_audit_now(),
                case_input_sha256=sha256_hex(canonical_json_bytes(case_input)),
                request_fingerprints=deepcopy(request_fingerprints),
                adapter=self.client.adapter_id,
                provider=self.client.provider_id,
                requested_model=route.name,
                routing_role=(
                    profile.metadata_routing_role or route.routing_role
                ),
                contract_version=profile.contract_version,
                prompt_template_id=profile.prompt_template_id,
                prompt_template_version=profile.prompt_template_version,
                failure_code=failure_code,
                failure_stage=failure_stage,
                failure_path=failure_path,
                failure_detail=failure_detail,
                generation=generation,
            )
        except Exception as persistence_error:
            audit_error = EvidencePersistenceError(
                original_failure_code=failure_code,
                original_failure_stage=failure_stage,
                original_failure_path=failure_path,
                original_failure_detail=failure_detail,
                persistence_error=persistence_error,
            )
            if original_error is not None:
                raise audit_error from original_error
            raise audit_error from persistence_error

    def _attempt(
        self,
        case_input: dict[str, Any],
        route: ModelRoute,
        *,
        request_fingerprints: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        profile = _structuring_contract_profile(case_input)
        attempt_id = f"ATT-{uuid.uuid4().hex}"
        run_reference = f"run:{uuid.uuid4().hex}"
        started_at = utc_audit_now()

        try:
            payload = self.client.structure_intake(
                case_input=case_input,
                route=route,
            )
        except LLMClientError as exc:
            self._persist_rejection(
                attempt_id=attempt_id,
                run_reference=run_reference,
                started_at=started_at,
                case_input=case_input,
                route=route,
                request_fingerprints=request_fingerprints,
                generation=exc.generation_evidence,
                failure_code=exc.code,
                failure_stage=exc.failure_stage or FAILURE_TRANSPORT,
                failure_path=exc.failure_path,
                failure_detail=exc.detail,
                original_error=exc,
            )
            raise

        generation = getattr(payload, "generation_evidence", None)
        if not isinstance(generation, GenerationEvidence):
            # Provider-neutral adapters may not expose raw transport bytes. Their
            # returned candidate is still preserved losslessly when rejected.
            generation = GenerationEvidence.candidate_only(payload)

        if "model_metadata" in payload:
            detail = "$.model_metadata: model must not supply app-owned model_metadata"
            rejection = CaseContractError(profile.invalid_output_code, detail)
            self._persist_rejection(
                attempt_id=attempt_id,
                run_reference=run_reference,
                started_at=started_at,
                case_input=case_input,
                route=route,
                request_fingerprints=request_fingerprints,
                generation=generation,
                failure_code=profile.invalid_output_code,
                failure_stage=FAILURE_SEMANTIC_VALIDATION,
                failure_path="$.model_metadata",
                failure_detail=detail,
                original_error=rejection,
            )
            raise rejection

        # Preserve the frozen v3 semantic boundary: historical v3 tests require
        # missing/manufactured caller-owned fields from a direct semantic-port
        # adapter to fail instead of being repaired here. v4/v5 generation
        # schemas omit caller-owned root fields by design, so those versions
        # materialize them non-destructively at the application boundary.
        draft = deepcopy(dict(payload))
        if profile.contract_version in {V4_CONTRACT_VERSION, V5_CONTRACT_VERSION}:
            draft = _materialize_client_owned_fields(case_input, draft)
        draft["model_metadata"] = {
            "adapter": self.client.adapter_id,
            "provider": self.client.provider_id,
            "model": route.name,
            "schema_version": profile.contract_version,
            "prompt_template_id": profile.prompt_template_id,
            "prompt_template_version": profile.prompt_template_version,
            "run_reference": run_reference,
            "generated_at": utc_now(),
            "routing_role": (
                profile.metadata_routing_role or route.routing_role
            ),
        }
        if profile.contract_version in {V4_CONTRACT_VERSION, V5_CONTRACT_VERSION}:
            draft["model_metadata"]["structured_generation_mechanism"] = (
                self.client.structured_generation_capability.mechanism
            )
        try:
            # #76 contract: this remains the first and authoritative application
            # validation call. Explicit version dispatch prevents silent v3/v4
            # relabeling while the normal entry path migrates to v4.
            if profile.contract_version == V3_CONTRACT_VERSION:
                # Preserve the frozen #76 authoritative v3 validation surface.
                # v4 is a separate major contract, not a replacement validator
                # masquerading behind the historical symbol.
                validate_case_draft(case_input, draft)
            else:
                # #210 remains a bounded exact-source preprocessing boundary,
                # not a generic repair path. v5 deliberately preserves the same
                # intake semantics while declaring its own closed wire version.
                schema_path = (
                    V4_SCHEMA_PATH
                    if profile.contract_version == V4_CONTRACT_VERSION
                    else V5_SCHEMA_PATH
                )
                validate_schema_object(
                    draft,
                    "IntakeDraft",
                    INVALID_INTAKE_DRAFT,
                    schema_path=schema_path,
                )
                if profile.contract_version == V4_CONTRACT_VERSION:
                    draft = normalize_v4_intake_draft(case_input, draft)
                else:
                    draft = normalize_v5_intake_draft(case_input, draft)
                validate_structured_intake(case_input, draft)
        except CaseContractError as exc:
            failure_stage = FAILURE_SEMANTIC_VALIDATION
            try:
                if profile.contract_version == V3_CONTRACT_VERSION:
                    validate_schema_object(
                        draft,
                        "CaseDraft",
                        INVALID_CASE_DRAFT,
                    )
                else:
                    validate_schema_object(
                        draft,
                        "IntakeDraft",
                        INVALID_INTAKE_DRAFT,
                        schema_path=(
                            V4_SCHEMA_PATH
                            if profile.contract_version == V4_CONTRACT_VERSION
                            else V5_SCHEMA_PATH
                        ),
                    )
            except CaseContractError:
                failure_stage = FAILURE_SCHEMA_VALIDATION
            failure_path, _ = split_validation_detail(exc.detail)
            self._persist_rejection(
                attempt_id=attempt_id,
                run_reference=run_reference,
                started_at=started_at,
                case_input=case_input,
                route=route,
                request_fingerprints=request_fingerprints,
                generation=generation,
                failure_code=exc.code,
                failure_stage=failure_stage,
                failure_path=failure_path,
                failure_detail=exc.detail,
                original_error=exc,
            )
            raise
        return draft

    def structure(
        self,
        case_input: dict[str, Any],
        *,
        request_fingerprints: dict[str, str] | None = None,
    ) -> StructuringOutcome:
        profile = _structuring_contract_profile(case_input)
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
                        request_fingerprints=request_fingerprints,
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
                if exc.code in {INVALID_CASE_DRAFT, INVALID_INTAKE_DRAFT}:
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
                    draft=self._attempt(
                        case_input,
                        self.config.review,
                        request_fingerprints=request_fingerprints,
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
                profile.invalid_output_code,
                getattr(last_invalid, "detail", str(last_invalid)),
                retryable=False,
            )
        if provider_error is not None:
            raise provider_error
        raise LLMClientError(
            CASE_STRUCTURING_UNAVAILABLE,
            "no structuring attempt produced a result",
        )



def __getattr__(name: str) -> Any:
    """Resolve legacy transport symbols lazily without coupling application code to them."""
    if name in {"OpenAICompatibleLLMClient", "OpenAICompatibleIntakeAdapter"}:
        from openai_compatible_intake_adapter import OpenAICompatibleIntakeAdapter

        return OpenAICompatibleIntakeAdapter
    if name == "urlrequest":
        from urllib import request as _urlrequest

        return _urlrequest
    if name == "urlerror":
        from urllib import error as _urlerror

        return _urlerror
    raise AttributeError(name)
