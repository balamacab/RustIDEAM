from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_attempt_evidence import canonical_json_bytes
from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    case_draft_generation_schema,
    source_quote_candidates,
    validate_case_draft,
)
from llm_client import (
    PROMPT_TEMPLATE_VERSION,
    CaseStructuringService,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
)


PROBLEM = (
    "La sociedad no tiene sucursal en Colombia y pagó USD 10.000 el 15 de enero "
    "de 2026.\n\nEl proveedor es España Tecnología SAS."
)
HISTORICAL_PROBLEM_SHA256 = (
    "ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1"
)
HISTORICAL_FAILURE_PATH = "$.facts[14].source_quote"


def case_input(
    problem_text: str = PROBLEM,
    *,
    with_optional_fields: bool = False,
) -> dict:
    result = {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
    }
    if with_optional_fields:
        result["as_of_date"] = "2026-09-26"
        result["client_reference"] = "external-reference"
    return result


def candidate_claim() -> dict:
    return {
        "kind": "candidate_claim",
        "contract_version": "3.0.0",
        "claim_ref": "claim:main",
        "text": "La situación requiere análisis tributario.",
        "status": "candidate",
        "requires_canonical_validation": True,
        "target_hints": ["análisis tributario"],
    }


def final_draft(problem_text: str, quote: str) -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
        "facts": [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:source",
                "label": "Hecho fuente",
                "value": "valor",
                "state": "user_provided",
                "source_quote": quote,
                "requires_confirmation": False,
            }
        ],
        "questions": [],
        "candidate_claims": [candidate_claim()],
        "unresolved": [],
        "model_metadata": {
            "adapter": "test-adapter",
            "provider": "test-provider",
            "model": "test-model",
            "schema_version": "3.0.0",
            "prompt_template_id": "case-structuring-v3",
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "run_reference": "issue91-unit",
            "generated_at": "2026-09-26T00:00:00+00:00",
            "routing_role": "primary",
        },
    }


def provider_proposal(quote: str) -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "facts": [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:source",
                "label": "Hecho fuente",
                "value": "valor",
                "state": "user_provided",
                "source_quote": quote,
                "requires_confirmation": False,
            }
        ],
        "questions": [],
        "candidate_claims": [candidate_claim()],
        "unresolved": [],
    }


def make_config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="test-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("primary-model", "primary", 100_000, 4096),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


class Response:
    def __init__(self, payload: dict):
        self.status = 200
        self._raw = json.dumps(
            {
                "model": "primary-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        },
                    }
                ],
                "usage": {"completion_tokens": 100, "prompt_tokens": 100},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class Issue0091SourceQuoteFidelityTests(unittest.TestCase):
    def test_exact_literal_quote_remains_valid(self):
        quote = "La sociedad no tiene sucursal en Colombia"
        validate_case_draft(case_input(), final_draft(PROBLEM, quote))

    def test_lexical_semantic_and_material_changes_remain_rejected(self):
        cases = {
            "lexical_paraphrase": "La compañía no tiene sucursal en Colombia",
            "semantic_paraphrase": "La sociedad carece de sucursal en Colombia",
            "deleted_negation": "La sociedad tiene sucursal en Colombia",
            "changed_number": "pagó USD 12.000 el 15 de enero de 2026",
            "changed_date": "pagó USD 10.000 el 16 de enero de 2026",
            "changed_entity": "El proveedor es Iberia Tecnología SAS.",
            "merged_noncontiguous": (
                "La sociedad no tiene sucursal en Colombia "
                "El proveedor es España Tecnología SAS."
            ),
            "punctuation_change": "El proveedor es España Tecnología SAS",
            "whitespace_change": (
                "La sociedad no tiene sucursal en Colombia  y pagó USD 10.000"
            ),
        }
        for name, quote in cases.items():
            with self.subTest(name=name), self.assertRaises(CaseContractError) as raised:
                validate_case_draft(case_input(), final_draft(PROBLEM, quote))
            self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
            self.assertIn("$.facts[0].source_quote", raised.exception.detail)

    def test_unicode_normalization_is_not_silently_accepted(self):
        source = "La sociedad está domiciliada en España."
        decomposed = unicodedata.normalize("NFD", "España")
        quote = "La sociedad está domiciliada en " + decomposed + "."
        self.assertNotEqual(quote, source)
        with self.assertRaises(CaseContractError) as raised:
            validate_case_draft(case_input(source), final_draft(source, quote))
        self.assertIn("$.facts[0].source_quote", raised.exception.detail)

    def test_generation_schema_uses_only_exact_contiguous_quote_candidates(self):
        ci = case_input(with_optional_fields=True)
        schema = case_draft_generation_schema(ci)
        draft_schema = schema["$defs"]["CaseDraft"]

        for name in ("problem_text", "as_of_date", "client_reference"):
            self.assertNotIn(name, draft_schema["properties"])
            self.assertNotIn(name, draft_schema["required"])

        variants = schema["$defs"]["CaseFact"]["oneOf"]
        user = next(
            item for item in variants
            if item["properties"]["state"]["const"] == "user_provided"
        )
        expected = source_quote_candidates(PROBLEM)
        self.assertEqual(user["properties"]["source_quote"]["enum"], expected)
        self.assertTrue(expected)
        self.assertTrue(all(quote in PROBLEM for quote in expected))

        for variant in variants:
            if variant["properties"]["state"]["const"] != "user_provided":
                self.assertNotIn("source_quote", variant["properties"])

    def test_duplicate_source_text_has_deterministic_text_only_candidates(self):
        problem = "Texto repetido.\n\nTexto repetido.\n\nOtro texto."
        self.assertEqual(
            source_quote_candidates(problem),
            ["Texto repetido.", "Otro texto."],
        )

    def test_empty_quote_still_fails_public_v3_schema(self):
        with self.assertRaises(CaseContractError) as raised:
            validate_case_draft(case_input(), final_draft(PROBLEM, ""))
        self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_adapter_materializes_only_missing_client_owned_fields(self):
        ci = case_input(with_optional_fields=True)
        quote = source_quote_candidates(PROBLEM)[0]
        config = make_config()
        client = OpenAICompatibleLLMClient(config)

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(provider_proposal(quote)),
        ) as opened:
            outcome = CaseStructuringService(config, client).structure(ci)

        self.assertEqual(outcome.draft["problem_text"], ci["problem_text"])
        self.assertEqual(outcome.draft["as_of_date"], ci["as_of_date"])
        self.assertEqual(outcome.draft["client_reference"], ci["client_reference"])
        self.assertEqual(outcome.draft["facts"][0]["source_quote"], quote)

        request = json.loads(opened.call_args.args[0].data)
        generation_schema = request["response_format"]["json_schema"]["schema"]
        generated_root = generation_schema["$defs"]["CaseDraft"]
        self.assertNotIn("problem_text", generated_root["properties"])
        self.assertEqual(
            request["response_format"]["json_schema"]["name"],
            "case_draft_v3_generation",
        )

    def test_materialization_never_overwrites_model_supplied_client_drift(self):
        ci = case_input()
        proposal = provider_proposal(source_quote_candidates(PROBLEM)[0])
        proposal["problem_text"] = "texto modificado por el proveedor"
        config = make_config()

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(proposal),
        ):
            with self.assertRaises(CaseContractError) as raised:
                CaseStructuringService(
                    config,
                    OpenAICompatibleLLMClient(config),
                ).structure(ci)

        self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)
        self.assertIn("$.problem_text", raised.exception.detail)

    def test_openai_capability_declares_materialization_without_repair(self):
        capability = OpenAICompatibleLLMClient.structured_generation_capability
        self.assertFalse(capability.direct_object)
        self.assertTrue(capability.deterministic_client_payload_materialization)
        self.assertFalse(capability.post_response_repair)
        self.assertTrue(capability.is_case_compatible())

    def test_historical_issue67_failure_metadata_has_frozen_input_regression(self):
        historical = ROOT / "config" / "benchmarks" / "issue65" / "complex-case.txt"
        problem = historical.read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(problem.encode("utf-8")).hexdigest(),
            HISTORICAL_PROBLEM_SHA256,
        )

        # #67 preserved only the failing path, not the rejected provider payload.
        # Do not invent the lost quote. This synthetic quote exercises the exact
        # historical validation boundary against the frozen historical input.
        synthetic_quote = (
            "El proveedor español no tiene establecimiento permanente en Colombia."
        )
        self.assertNotIn(synthetic_quote, problem)
        with self.assertRaises(CaseContractError) as raised:
            validate_case_draft(
                {
                    "kind": "case_input",
                    "contract_version": "3.0.0",
                    "problem_text": problem,
                    "as_of_date": "2026-09-24",
                },
                {
                    **final_draft(problem, synthetic_quote),
                    "as_of_date": "2026-09-24",
                },
            )
        self.assertEqual(
            raised.exception.detail.split(":", 1)[0],
            "$.facts[0].source_quote",
        )
        self.assertEqual(HISTORICAL_FAILURE_PATH, "$.facts[14].source_quote")

    def test_existing_short_literal_substrings_remain_backward_compatible(self):
        paragraph = source_quote_candidates(PROBLEM)[0]
        quote = "pagó USD 10.000"
        self.assertIn(quote, paragraph)
        validate_case_draft(case_input(), final_draft(PROBLEM, quote))

    def test_candidate_serialization_preserves_generated_quote_bytes(self):
        quote = source_quote_candidates(PROBLEM)[0]
        proposal = provider_proposal(quote)
        encoded = canonical_json_bytes(proposal)
        self.assertIn(quote.encode("utf-8"), encoded)


if __name__ == "__main__":
    unittest.main()
