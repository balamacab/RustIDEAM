from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_intake_factory import build_intake_inference_port
from case_intake_inference import IntakeInferencePort
from deterministic_intake_adapter import DeterministicIntakeAdapter
from llm_client import CASE_STRUCTURING_UNAVAILABLE, CaseStructuringService, LLMClientError, LLMPlatformConfig, ModelRoute
from openai_compatible_intake_adapter import OpenAICompatibleIntakeAdapter


PROBLEM = "La sociedad consulta cómo cancelar su registro tributario."


def case_input() -> dict:
    return {"kind": "case_input", "contract_version": "3.0.0", "problem_text": PROBLEM}


def intake_payload() -> dict:
    return {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": PROBLEM,
        "facts": [],
        "questions": [],
        "candidate_claims": [],
        "unresolved": [],
    }


def config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible", provider="test-provider",
        base_url="http://127.0.0.1:8080/v1", timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute("primary-model", "primary", 100_000, 1024),
        auxiliary=None, review=None, primary_attempts=1,
        review_on_invalid_output=False, review_on_provider_error=False,
        api_key_env=None,
    )


class Response:
    def __init__(self, value: dict):
        self.status = 200
        self._raw = json.dumps(value).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self._raw


def envelope(payload: dict, *, model: str = "primary-model") -> dict:
    return {
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
        "usage": {"completion_tokens": 10, "prompt_tokens": 10},
    }


class Issue0135IntakeInferencePortTests(unittest.TestCase):
    def test_application_owned_port_is_semantic(self):
        source = (ROOT / "tools" / "case_intake_inference.py").read_text(encoding="utf-8")
        self.assertIn("class IntakeInferencePort", source)
        self.assertIn("def structure_intake(", source)
        for forbidden in ("urllib", "chat/completions", "base_url", "response_format"):
            self.assertNotIn(forbidden, source)

    def test_application_and_entry_points_do_not_construct_provider_adapter(self):
        for name in ("case_application.py", "analyze_case.py", "case_http.py"):
            with self.subTest(name=name):
                source = (ROOT / "tools" / name).read_text(encoding="utf-8")
                self.assertNotIn("OpenAICompatibleLLMClient", source)
                self.assertNotIn("OpenAICompatibleIntakeAdapter", source)
                self.assertNotIn("urlrequest", source)
                self.assertNotIn("urllib", source)

    def test_factory_selects_adapter_from_configuration(self):
        selected = build_intake_inference_port(config())
        self.assertIsInstance(selected, OpenAICompatibleIntakeAdapter)
        self.assertIsInstance(selected, IntakeInferencePort)
        with self.assertRaises(ValueError):
            build_intake_inference_port(replace(config(), adapter="unknown-provider-shape"))

    def test_shared_adapter_contract_returns_structured_candidate_not_envelope(self):
        adapters = [DeterministicIntakeAdapter([intake_payload()]), OpenAICompatibleIntakeAdapter(config())]
        for adapter in adapters:
            with self.subTest(adapter=adapter.adapter_id):
                if isinstance(adapter, OpenAICompatibleIntakeAdapter):
                    context = mock.patch("openai_compatible_intake_adapter.urlrequest.urlopen", return_value=Response(envelope(intake_payload())))
                else:
                    context = mock.patch.object(adapter, "provider_id", adapter.provider_id)
                with context:
                    candidate = adapter.structure_intake(case_input=case_input(), route=config().primary)
                self.assertEqual(candidate["kind"], "case_draft")
                self.assertNotIn("choices", candidate)
                self.assertNotIn("usage", candidate)

    def test_deterministic_adapter_has_same_application_semantics(self):
        payload = intake_payload()
        deterministic = CaseStructuringService(config(), DeterministicIntakeAdapter([payload])).structure(case_input())
        adapter = OpenAICompatibleIntakeAdapter(config())
        with mock.patch("openai_compatible_intake_adapter.urlrequest.urlopen", return_value=Response(envelope(payload))):
            transported = CaseStructuringService(config(), adapter).structure(case_input())
        for field in ("facts", "questions", "candidate_claims", "unresolved"):
            self.assertEqual(deterministic.draft[field], transported.draft[field])

    def test_model_identity_mismatch_maps_to_stable_application_error(self):
        adapter = OpenAICompatibleIntakeAdapter(config())
        with mock.patch("openai_compatible_intake_adapter.urlrequest.urlopen", return_value=Response(envelope(intake_payload(), model="wrong-model"))):
            with self.assertRaises(LLMClientError) as raised:
                adapter.structure_intake(case_input=case_input(), route=config().primary)
        self.assertEqual(raised.exception.code, CASE_STRUCTURING_UNAVAILABLE)

    def test_provider_transport_is_confined_to_infrastructure_adapter(self):
        source = (ROOT / "tools" / "openai_compatible_intake_adapter.py").read_text(encoding="utf-8")
        self.assertIn("urlrequest.Request", source)
        self.assertIn("/chat/completions", source)


if __name__ == "__main__":
    unittest.main()
