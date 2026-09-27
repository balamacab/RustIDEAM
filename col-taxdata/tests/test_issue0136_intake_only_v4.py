from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_application import (
    ResearchAnalysisOutcome,
    analyze_case,
)
from case_contract_dispatch import validate_structured_intake
from case_contract_validation import CaseContractError
from case_http import prepare_case_request
from case_contract_validation_v4 import (
    INVALID_INTAKE_DRAFT,
    intake_draft_generation_schema,
)
from deterministic_intake_adapter import DeterministicIntakeAdapter
from llm_client import (
    CaseStructuringService,
    LLMPlatformConfig,
    ModelRoute,
)
from openai_compatible_intake_adapter import OpenAICompatibleIntakeAdapter


PROBLEM = (
    "La sociedad está en liquidación y mantiene una cuenta bancaria en Estados Unidos. "
    "El cliente pregunta cómo debe regularizar su situación tributaria."
)
QUOTE = (
    "La sociedad está en liquidación y mantiene una cuenta bancaria en Estados Unidos. "
    "El cliente pregunta cómo debe regularizar su situación tributaria."
)


def case_input() -> dict:
    return {
        "kind": "case_input",
        "contract_version": "4.0.0",
        "problem_text": PROBLEM,
        "as_of_date": "2026-09-27",
        "client_reference": "client:issue136",
        "caller_metadata": {"channel": "webcam", "attempt": 1},
    }


def generated_intake(*, hints: list[dict] | None = None) -> dict:
    return {
        "kind": "intake_draft",
        "contract_version": "4.0.0",
        "intake_ref": "intake:issue136",
        "facts": [
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:liquidation-account",
                "label": "Situación societaria y cuenta exterior",
                "value": "Sociedad en liquidación con cuenta en Estados Unidos",
                "state": "user_provided",
                "source_quote": QUOTE,
                "requires_confirmation": False,
            }
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "4.0.0",
                "question_ref": "question:regularization",
                "text": "¿Cómo debe regularizarse la situación tributaria descrita?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:liquidation-account"],
            }
        ],
        "search_hints": [] if hints is None else hints,
    }


def complete_intake(*, hints: list[dict] | None = None) -> dict:
    value = generated_intake(hints=hints)
    value["problem_text"] = PROBLEM
    value["as_of_date"] = "2026-09-27"
    value["client_reference"] = "client:issue136"
    value["caller_metadata"] = {"channel": "webcam", "attempt": 1}
    return value


def config() -> LLMPlatformConfig:
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="issue136-provider",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=ModelRoute(
            "issue136-model",
            "primary",
            100_000,
            2048,
        ),
        auxiliary=None,
        review=None,
        primary_attempts=1,
        review_on_invalid_output=False,
        review_on_provider_error=False,
        api_key_env=None,
    )


class Response:
    def __init__(self, value: dict):
        self.status = 200
        self._raw = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


def envelope(payload: dict) -> dict:
    return {
        "model": "issue136-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(payload)},
            }
        ],
        "usage": {"completion_tokens": 50, "prompt_tokens": 50},
    }


class Issue0136IntakeOnlyV4Tests(unittest.TestCase):
    def test_webcam_style_input_yields_intake_not_legal_answer(self):
        outcome = CaseStructuringService(
            config(),
            DeterministicIntakeAdapter([complete_intake()]),
        ).structure(case_input())

        self.assertEqual(outcome.intake["kind"], "intake_draft")
        self.assertEqual(outcome.intake["contract_version"], "4.0.0")
        self.assertEqual(
            outcome.intake["facts"][0]["state"],
            "user_provided",
        )
        self.assertEqual(outcome.intake["questions"][0]["category"], "legal")
        for forbidden in (
            "candidate_claims",
            "legal_conclusion",
            "calculations",
            "final_answer",
            "evidence_spans",
        ):
            self.assertNotIn(forbidden, outcome.intake)

    def test_model_attempt_to_return_legal_conclusion_is_rejected(self):
        payload = complete_intake()
        payload["legal_conclusion"] = "La sociedad debe presentar una declaración."

        with self.assertRaises(CaseContractError) as raised:
            CaseStructuringService(
                config(),
                DeterministicIntakeAdapter([payload]),
            ).structure(case_input())

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)

    def test_question_is_not_allowed_to_duplicate_as_missing_fact(self):
        payload = complete_intake()
        payload["facts"].append(
            {
                "kind": "intake_fact",
                "contract_version": "4.0.0",
                "fact_ref": "fact:duplicated-question",
                "label": "Regularizar situación tributaria",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Regularizar situación tributaria",
            }
        )
        payload["questions"][0]["text"] = "Regularizar situación tributaria"

        with self.assertRaises(CaseContractError) as raised:
            CaseStructuringService(
                config(),
                DeterministicIntakeAdapter([payload]),
            ).structure(case_input())

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("duplicated as a missing fact", raised.exception.detail)

    def test_explicit_client_fact_cannot_be_downgraded_to_missing(self):
        ci = {
            "kind": "case_input",
            "contract_version": "4.0.0",
            "problem_text": (
                "La sociedad tiene una cuenta bancaria en Estados Unidos."
            ),
        }
        payload = {
            "kind": "intake_draft",
            "contract_version": "4.0.0",
            "intake_ref": "intake:false-missing",
            "problem_text": ci["problem_text"],
            "facts": [
                {
                    "kind": "intake_fact",
                    "contract_version": "4.0.0",
                    "fact_ref": "fact:account",
                    "label": "Cuenta bancaria Estados Unidos",
                    "state": "missing",
                    "requires_confirmation": True,
                    "needed_information": (
                        "Qué información sobre cuenta bancaria Estados Unidos"
                    ),
                }
            ],
            "questions": [],
            "search_hints": [],
        }

        with self.assertRaises(CaseContractError) as raised:
            CaseStructuringService(
                config(),
                DeterministicIntakeAdapter([payload]),
            ).structure(ci)

        self.assertEqual(raised.exception.code, INVALID_INTAKE_DRAFT)
        self.assertIn("already stated", raised.exception.detail)

    def test_neutral_hints_can_be_empty(self):
        outcome = CaseStructuringService(
            config(),
            DeterministicIntakeAdapter([complete_intake(hints=[])]),
        ).structure(case_input())
        self.assertEqual(outcome.intake["search_hints"], [])

    def test_poor_hint_remains_advisory_and_does_not_become_legal_truth(self):
        hints = [
            {
                "kind": "search_hint",
                "contract_version": "4.0.0",
                "hint_ref": "hint:poor",
                "terms": ["vocabulario irrelevante", "hipótesis pobre"],
                "origin": "internal_intake_model",
                "related_question_refs": ["question:regularization"],
            }
        ]
        outcome = CaseStructuringService(
            config(),
            DeterministicIntakeAdapter([complete_intake(hints=hints)]),
        ).structure(case_input())

        self.assertEqual(outcome.intake["search_hints"], hints)
        self.assertNotIn("candidate_claims", outcome.intake)
        self.assertNotIn("legal_conclusion", outcome.intake)

    def test_generation_schema_contains_only_intake_authority(self):
        schema = intake_draft_generation_schema(case_input())
        self.assertEqual(
            set(schema["$defs"]),
            {
                "IntakeDraft",
                "IntakeFact",
                "FactMeasurement",
                "DecimalString",
                "CaseQuestion",
                "SearchHint",
            },
        )
        root = schema["$defs"]["IntakeDraft"]
        properties = root["properties"]

        for forbidden in (
            "candidate_claims",
            "legal_conclusion",
            "research_plan",
            "evidence_spans",
            "calculations",
            "final_answer",
        ):
            self.assertNotIn(forbidden, properties)
        for app_owned in (
            "problem_text",
            "as_of_date",
            "client_reference",
            "caller_metadata",
            "model_metadata",
        ):
            self.assertNotIn(app_owned, properties)

        states = {
            variant["properties"]["state"]["const"]
            for variant in schema["$defs"]["IntakeFact"]["oneOf"]
        }
        self.assertEqual(
            states,
            {"user_provided", "llm_normalized", "missing", "ambiguous"},
        )
        for variant in schema["$defs"]["IntakeFact"]["oneOf"]:
            state = variant["properties"]["state"]["const"]
            if state in {"user_provided", "llm_normalized"}:
                self.assertEqual(
                    variant["properties"]["source_quote"]["enum"],
                    [PROBLEM],
                )

    def test_adapter_swap_preserves_v4_intake_contract(self):
        deterministic = CaseStructuringService(
            config(),
            DeterministicIntakeAdapter([complete_intake()]),
        ).structure(case_input())

        adapter = OpenAICompatibleIntakeAdapter(config())
        with mock.patch(
            "openai_compatible_intake_adapter.urlrequest.urlopen",
            return_value=Response(envelope(generated_intake())),
        ) as opened:
            transported = CaseStructuringService(
                config(),
                adapter,
            ).structure(case_input())

        for field in (
            "problem_text",
            "as_of_date",
            "client_reference",
            "caller_metadata",
            "facts",
            "questions",
            "search_hints",
        ):
            self.assertEqual(
                deterministic.intake[field],
                transported.intake[field],
            )

        request = json.loads(opened.call_args.args[0].data)
        self.assertEqual(
            request["response_format"]["json_schema"]["name"],
            "case_intake_v4_generation",
        )
        response_schema = request["response_format"]["json_schema"]["schema"]
        self.assertNotIn(
            "candidate_claims",
            response_schema["$defs"]["IntakeDraft"]["properties"],
        )

    def test_historical_v3_is_interpretable_but_v4_path_does_not_emit_it(self):
        v3_input = {
            "kind": "case_input",
            "contract_version": "3.0.0",
            "problem_text": "Hecho histórico v3.",
        }
        v3_draft = {
            "kind": "case_draft",
            "contract_version": "3.0.0",
            "problem_text": "Hecho histórico v3.",
            "facts": [],
            "questions": [],
            "candidate_claims": [],
            "unresolved": [],
            "model_metadata": {
                "adapter": "fixture",
                "provider": "fixture",
                "model": "fixture",
                "schema_version": "3.0.0",
                "prompt_template_id": "case-structuring-v3",
                "prompt_template_version": "5",
                "run_reference": "run:v3",
                "generated_at": "2026-09-27T00:00:00Z",
                "routing_role": "primary",
            },
        }
        self.assertEqual(
            validate_structured_intake(v3_input, v3_draft),
            "3.0.0",
        )

        outcome = CaseStructuringService(
            config(),
            DeterministicIntakeAdapter([complete_intake()]),
        ).structure(case_input())
        self.assertEqual(outcome.intake["kind"], "intake_draft")
        self.assertNotIn("candidate_claims", outcome.intake)

    def test_historical_http_transport_stays_v3_after_internal_v4_switch(self):
        raw = json.dumps(
            {
                "problem_text": "Consulta histórica por HTTP.",
                "as_of_date": "2026-09-27",
                "client_reference": "issue136-http-compat",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        prepared = prepare_case_request(raw)

        self.assertEqual(prepared.case_input["contract_version"], "3.0.0")
        self.assertEqual(
            prepared.case_input["problem_text"],
            "Consulta histórica por HTTP.",
        )

    def test_v4_application_hands_validated_intake_to_platform_research_before_evidence_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "does-not-exist.sqlite"
            case_root = root / "cases"
            service = CaseStructuringService(
                config(),
                DeterministicIntakeAdapter([complete_intake()]),
            )
            research = mock.Mock(
                plan={"kind": "research_plan"},
                result={"kind": "research_result"},
                evidence_candidates=(),
                authorities=(),
                relationships=(),
                unresolved=(),
            )
            bundle = {"kind": "legal_research_bundle"}

            with (
                mock.patch(
                    "case_application.PlatformResearchService.research",
                    return_value=research,
                ) as platform_research,
                mock.patch(
                    "case_application.build_legal_research_bundle",
                    return_value=bundle,
                ) as evidence_graph,
            ):
                outcome = analyze_case(
                    case_input=case_input(),
                    db_path=db,
                    case_root=case_root,
                    structurer=service,
                    dry_run=False,
                )

            self.assertIsInstance(outcome, ResearchAnalysisOutcome)
            self.assertEqual(outcome.intake_draft["kind"], "intake_draft")
            self.assertEqual(outcome.research_result["kind"], "research_result")
            self.assertIs(outcome.bundle, bundle)
            platform_research.assert_called_once()
            call = platform_research.call_args.kwargs
            self.assertEqual(call["case_input"], case_input())
            self.assertEqual(call["intake_draft"], outcome.intake_draft)
            evidence_graph.assert_called_once_with(
                case_input=case_input(),
                intake_draft=outcome.intake_draft,
                research=research,
                db_path=db,
            )
            expected_intake = complete_intake()
            for field in (
                "kind",
                "contract_version",
                "intake_ref",
                "problem_text",
                "as_of_date",
                "client_reference",
                "caller_metadata",
                "facts",
                "questions",
                "search_hints",
            ):
                self.assertEqual(
                    call["intake_draft"][field],
                    expected_intake[field],
                )
            self.assertEqual(
                call["intake_draft"]["model_metadata"]["routing_role"],
                "intake_structuring",
            )
            self.assertFalse(db.exists())
            self.assertFalse(case_root.exists())


if __name__ == "__main__":
    unittest.main()
