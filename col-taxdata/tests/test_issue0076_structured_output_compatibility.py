from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib import error as urlerror


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    validate_case_draft,
)
from llm_client import (
    CASE_STRUCTURING_UNAVAILABLE,
    CaseStructuringService,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
    StructuredGenerationCapability,
)


PROBLEM = (
    "La sociedad está en liquidación y solicita saber qué requisitos debe "
    "cumplir para cancelar su registro tributario."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
    }


def model_payload() -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
        "facts": [],
        "questions": [],
        "candidate_claims": [
            {
                "kind": "candidate_claim",
                "contract_version": "3.0.0",
                "claim_ref": "claim:main",
                "text": (
                    "La cancelación del registro exige verificar previamente "
                    "las obligaciones tributarias pendientes."
                ),
                "status": "candidate",
                "requires_canonical_validation": True,
                "target_hints": ["cancelación registro tributario"],
            }
        ],
        "unresolved": [],
    }


def make_config(*, model: str = "primary-model") -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute(model, "primary", 100_000, 1024),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


class Response:
    def __init__(self, envelope: dict):
        self._raw = json.dumps(envelope).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


def response_envelope(content: str, *, model: str = "primary-model") -> dict:
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
    }


class RecordingClient:
    def __init__(
        self,
        output: dict,
        *,
        capability: StructuredGenerationCapability | None,
        adapter_id: str = "test-adapter",
        provider_id: str = "test-provider",
    ):
        self.output = deepcopy(output)
        self.structured_generation_capability = capability
        self.adapter_id = adapter_id
        self.provider_id = provider_id
        self.calls = 0

    def complete_case_draft(self, *, case_input: dict, route: ModelRoute) -> dict:
        del case_input, route
        self.calls += 1
        return deepcopy(self.output)


COMPATIBLE_CAPABILITY = StructuredGenerationCapability(
    mechanism="test-constrained-schema",
    schema_constrained=True,
    direct_object=True,
    post_response_repair=False,
)


class Issue0076StructuredOutputCompatibilityTests(unittest.TestCase):
    def test_direct_parseable_structured_output_reaches_authoritative_validation(self):
        config = make_config()
        client = OpenAICompatibleLLMClient(config)
        envelope = response_envelope(json.dumps(model_payload()))

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(envelope),
        ) as opened, mock.patch(
            "llm_client.validate_case_draft",
            wraps=validate_case_draft,
        ) as validator:
            outcome = CaseStructuringService(config, client).structure(case_input())

        request_payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(request_payload["response_format"]["type"], "json_schema")
        self.assertTrue(
            request_payload["response_format"]["json_schema"]["strict"]
        )
        validator.assert_called_once()
        self.assertEqual(outcome.draft["kind"], "case_draft")
        self.assertEqual(outcome.draft["problem_text"], PROBLEM)

    def test_fenced_prose_wrapped_and_malformed_json_are_not_repaired(self):
        valid_json = json.dumps(model_payload())
        cases = {
            "markdown_fence": "```json\n" + valid_json + "\n```",
            "prose_wrapped": f"Here is the CaseDraft:\n{valid_json}",
            "malformed": '{"kind":"case_draft","contract_version":"3.0.0"',
        }
        self.assertTrue(cases["markdown_fence"].startswith("```json\n"))
        self.assertTrue(cases["markdown_fence"].endswith("\n```"))

        for name, content in cases.items():
            with self.subTest(name=name):
                client = OpenAICompatibleLLMClient(make_config())
                with mock.patch(
                    "llm_client.urlrequest.urlopen",
                    return_value=Response(response_envelope(content)),
                ):
                    with self.assertRaises(LLMClientError) as raised:
                        client.complete_case_draft(
                            case_input=case_input(),
                            route=make_config().primary,
                        )
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_wrong_missing_and_extra_fields_are_not_repaired(self):
        wrong_name = model_payload()
        wrong_name["case_facts"] = wrong_name.pop("facts")

        missing = model_payload()
        del missing["unresolved"]

        extra = model_payload()
        extra["unsupported_extra"] = True

        for name, payload in {
            "wrong_name": wrong_name,
            "missing": missing,
            "extra": extra,
        }.items():
            with self.subTest(name=name), mock.patch(
                "llm_client.validate_case_draft",
                wraps=validate_case_draft,
            ) as validator:
                client = RecordingClient(
                    payload,
                    capability=COMPATIBLE_CAPABILITY,
                )
                with self.assertRaises(CaseContractError) as raised:
                    CaseStructuringService(
                        make_config(),
                        client,
                    ).structure(case_input())
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
                validator.assert_called_once()

    def test_schema_and_semantic_violations_reach_authoritative_validation(self):
        schema_invalid = model_payload()
        schema_invalid["facts"] = "not-a-list"

        semantic_invalid = model_payload()
        semantic_invalid["facts"] = [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:bad-quote",
                "label": "Estado",
                "value": "liquidación",
                "state": "user_provided",
                "source_quote": "texto que no aparece en el problema",
                "requires_confirmation": False,
            }
        ]

        for name, payload in {
            "schema": schema_invalid,
            "semantic": semantic_invalid,
        }.items():
            with self.subTest(name=name), mock.patch(
                "llm_client.validate_case_draft",
                wraps=validate_case_draft,
            ) as validator:
                client = RecordingClient(
                    payload,
                    capability=COMPATIBLE_CAPABILITY,
                )
                with self.assertRaises(CaseContractError) as raised:
                    CaseStructuringService(
                        make_config(),
                        client,
                    ).structure(case_input())
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
                validator.assert_called_once()

    def test_provider_specific_adapter_cannot_bypass_final_validation(self):
        invalid = model_payload()
        invalid["facts"] = [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:forged",
                "label": "Estado",
                "value": "liquidación",
                "state": "user_provided",
                "source_quote": "forged provider quote",
                "requires_confirmation": False,
            }
        ]
        client = RecordingClient(
            invalid,
            capability=StructuredGenerationCapability(
                mechanism="vendor-specific-grammar",
                schema_constrained=True,
                direct_object=True,
                post_response_repair=False,
            ),
            adapter_id="vendor-adapter",
            provider_id="vendor-x",
        )

        with self.assertRaises(CaseContractError) as raised:
            CaseStructuringService(make_config(), client).structure(case_input())

        self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
        self.assertEqual(client.calls, 1)

    def test_incompatible_structuring_capabilities_fail_closed_before_generation(self):
        incompatible = {
            "missing_capability": None,
            "not_schema_constrained": StructuredGenerationCapability(
                mechanism="free-text",
                schema_constrained=False,
                direct_object=True,
                post_response_repair=False,
            ),
            "not_direct_object": StructuredGenerationCapability(
                mechanism="schema-ish",
                schema_constrained=True,
                direct_object=False,
                post_response_repair=False,
            ),
            "requires_repair": StructuredGenerationCapability(
                mechanism="repairing-wrapper",
                schema_constrained=True,
                direct_object=True,
                post_response_repair=True,
            ),
            "unnamed_mechanism": StructuredGenerationCapability(
                mechanism="",
                schema_constrained=True,
                direct_object=True,
                post_response_repair=False,
            ),
        }

        for name, capability in incompatible.items():
            with self.subTest(name=name):
                client = RecordingClient(
                    model_payload(),
                    capability=capability,
                )
                with self.assertRaises(LLMClientError) as raised:
                    CaseStructuringService(
                        make_config(),
                        client,
                    ).structure(case_input())
                self.assertEqual(
                    raised.exception.code,
                    CASE_STRUCTURING_UNAVAILABLE,
                )
                self.assertFalse(raised.exception.retryable)
                self.assertEqual(client.calls, 0)

    def test_compatibility_does_not_depend_on_provider_or_model_identity(self):
        cases = [
            ("adapter-a", "provider-a", "model-a"),
            ("adapter-b", "provider-b", "model-b"),
        ]

        for adapter_id, provider_id, model in cases:
            with self.subTest(provider=provider_id, model=model):
                client = RecordingClient(
                    model_payload(),
                    capability=StructuredGenerationCapability(
                        mechanism=f"{provider_id}-constrained-output",
                        schema_constrained=True,
                        direct_object=True,
                        post_response_repair=False,
                    ),
                    adapter_id=adapter_id,
                    provider_id=provider_id,
                )
                outcome = CaseStructuringService(
                    make_config(model=model),
                    client,
                ).structure(case_input())
                self.assertEqual(
                    outcome.draft["model_metadata"]["provider"],
                    provider_id,
                )
                self.assertEqual(
                    outcome.draft["model_metadata"]["model"],
                    model,
                )

    def test_backend_rejection_of_required_structured_request_is_incompatible(self):
        config = make_config()
        client = OpenAICompatibleLLMClient(config)
        http_error = urlerror.HTTPError(
            config.base_url + "/chat/completions",
            400,
            "unsupported response_format",
            {},
            None,
        )

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaises(LLMClientError) as raised:
                client.complete_case_draft(
                    case_input=case_input(),
                    route=config.primary,
                )

        self.assertEqual(raised.exception.code, CASE_STRUCTURING_UNAVAILABLE)
        self.assertFalse(raised.exception.retryable)
        self.assertIn("structured-generation", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
