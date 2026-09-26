from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error as urlerror


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from case_application import analyze_case
from case_contract_validation import (
    CaseContractError,
    INVALID_CASE_DRAFT,
    case_draft_response_schema,
    INVALID_CASE_RESULT,
    validate_case_result,
)
from case_retrieval import RetrievalIntegrityError
from rematerialize_case import refresh_case_materializations
from validate_case_bundle import validate_case
from llm_client import (
    CASE_CONTEXT_LIMIT,
    CASE_STRUCTURING_UNAVAILABLE,
    CaseStructuringService,
    ContextLimitError,
    FakeLLMClient,
    LLMClientError,
    LLMPlatformConfig,
    ModelRoute,
    OpenAICompatibleLLMClient,
    load_platform_config,
)


NOW = "2026-09-24T05:30:00+00:00"
SOURCE_SHA = "a" * 64
CLAIM_TEXT = (
    "La cancelación del registro exige verificar previamente las obligaciones "
    "tributarias pendientes."
)
PROBLEM = (
    "La sociedad está en liquidación y solicita saber qué requisitos debe "
    "cumplir para cancelar su registro tributario."
)


def model_payload(
    *,
    problem_text: str = PROBLEM,
    as_of_date: str | None = None,
    client_reference: str | None = None,
    claim_text: str = CLAIM_TEXT,
    facts: list[dict] | None = None,
    unresolved: list[dict] | None = None,
) -> dict:
    payload = {
        "kind": "case_draft",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
        "facts": [] if facts is None else facts,
        "questions": [],
        "candidate_claims": [
            {
                "kind": "candidate_claim",
                "contract_version": "3.0.0",
                "claim_ref": "claim:main",
                "text": claim_text,
                "status": "candidate",
                "requires_canonical_validation": True,
                "target_hints": ["cancelación registro tributario"],
            }
        ],
        "unresolved": [] if unresolved is None else unresolved,
    }
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date
    if client_reference is not None:
        payload["client_reference"] = client_reference
    return payload


def make_config(
    *,
    primary_attempts: int = 1,
    review: bool = False,
    review_on_provider_error: bool = False,
    context_tokens: int = 100_000,
) -> LLMPlatformConfig:
    primary = ModelRoute(
        "primary-model", "primary", context_tokens, 1024
    )
    review_route = (
        ModelRoute("review-model", "review", context_tokens, 1024)
        if review
        else None
    )
    return LLMPlatformConfig(
        adapter="openai-compatible",
        provider="local-test",
        base_url="http://127.0.0.1:8080/v1",
        timeout_seconds=2,
        chars_per_token_estimate=4.0,
        primary=primary,
        auxiliary=ModelRoute(
            "aux-model", "auxiliary", context_tokens, 512
        ),
        review=review_route,
        primary_attempts=primary_attempts,
        review_on_invalid_output=review,
        review_on_provider_error=review_on_provider_error,
        api_key_env=None,
    )


def case_input(
    *,
    problem_text: str = PROBLEM,
    as_of_date: str | None = None,
    client_reference: str | None = None,
) -> dict:
    value = {
        "kind": "case_input",
        "contract_version": "3.0.0",
        "problem_text": problem_text,
    }
    if as_of_date is not None:
        value["as_of_date"] = as_of_date
    if client_reference is not None:
        value["client_reference"] = client_reference
    return value


def valid_result() -> dict:
    return {
        "kind": "case_result",
        "contract_version": "3.0.0",
        "case_ref": "case:test",
        "analysis_status": "partial",
        "facts": [
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:one",
                "label": "Dato",
                "value": "valor",
                "state": "user_provided",
                "source_quote": "valor",
                "requires_confirmation": False,
            }
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "3.0.0",
                "question_ref": "question:one",
                "text": "¿Qué aplica?",
                "category": "legal",
                "status": "open",
                "depends_on_fact_refs": ["fact:one"],
            }
        ],
        "supported_claims": [
            {
                "claim_ref": "claim:supported",
                "text": CLAIM_TEXT,
                "status": "validated",
                "evidence_refs": ["evidence:one"],
                "related_question_refs": ["question:one"],
            }
        ],
        "remaining_candidate_claims": [
            {
                "kind": "candidate_claim",
                "contract_version": "3.0.0",
                "claim_ref": "claim:remaining",
                "text": "Otra conclusión candidata suficientemente extensa para prueba.",
                "status": "candidate",
                "requires_canonical_validation": True,
                "related_question_refs": ["question:one"],
            }
        ],
        "unresolved": [
            {
                "kind": "case_unresolved",
                "contract_version": "3.0.0",
                "unresolved_ref": "unresolved:one",
                "category": "unsupported_claim",
                "description": "Falta soporte",
                "related_fact_refs": ["fact:one"],
                "related_question_refs": ["question:one"],
                "related_claim_refs": ["claim:remaining"],
                "next_action": "human_review",
            }
        ],
        "evidence": [
            {
                "kind": "case_evidence",
                "contract_version": "3.0.0",
                "evidence_ref": "evidence:one",
                "source_ref": "source:one",
                "document_ref": "document:one",
                "provision_ref": "provision:one",
                "exact_quote": CLAIM_TEXT,
                "support_status": "validated",
                "provenance_ref": "provenance:one",
            }
        ],
        "sources": [
            {
                "source_ref": "source:one",
                "authority": "DIAN",
                "source_url": "https://example.test/source",
            }
        ],
        "documents": [
            {
                "document_ref": "document:one",
                "display_name": "Documento de prueba",
            }
        ],
        "provisions": [
            {
                "provision_ref": "provision:one",
                "document_ref": "document:one",
                "display_name": "Artículo 1",
            }
        ],
        "model_metadata": {
            "adapter": "fake-llm",
            "provider": "test",
            "model": "primary-model",
            "schema_version": "3.0.0",
            "prompt_template_id": "case-structuring-v3",
            "prompt_template_version": "1",
            "run_reference": "run:test",
            "generated_at": NOW,
            "routing_role": "primary",
        },
        "generated_at": NOW,
    }


class Issue0016ContractAndRoutingTests(unittest.TestCase):
    def test_exact_client_payload_preservation_and_absence(self):
        original = case_input(
            as_of_date="2026-09-24",
            client_reference="matter-16",
        )
        outcome = CaseStructuringService(
            make_config(),
            FakeLLMClient(
                [
                    model_payload(
                        as_of_date="2026-09-24",
                        client_reference="matter-16",
                    )
                ]
            ),
        ).structure(original)
        self.assertEqual(outcome.draft["problem_text"], original["problem_text"])
        self.assertEqual(outcome.draft["as_of_date"], original["as_of_date"])
        self.assertEqual(
            outcome.draft["client_reference"],
            original["client_reference"],
        )

        absent = CaseStructuringService(
            make_config(), FakeLLMClient([model_payload()])
        ).structure(case_input()).draft
        self.assertNotIn("as_of_date", absent)
        self.assertNotIn("client_reference", absent)

    def test_model_facing_schema_pins_exact_client_payload(self):
        original = case_input(
            as_of_date="2026-09-24",
            client_reference="matter-16",
        )
        schema = case_draft_response_schema(original)
        draft = schema["$defs"]["CaseDraft"]
        self.assertNotIn("model_metadata", draft["properties"])
        self.assertNotIn("model_metadata", draft["required"])
        for name in ("problem_text", "as_of_date", "client_reference"):
            self.assertIn(name, draft["required"])
            self.assertEqual(
                draft["properties"][name]["const"],
                original[name],
            )

        absent = case_draft_response_schema(case_input())["$defs"]["CaseDraft"]
        self.assertIn("problem_text", absent["required"])
        self.assertEqual(
            absent["properties"]["problem_text"]["const"],
            PROBLEM,
        )
        for name in ("as_of_date", "client_reference"):
            self.assertNotIn(name, absent["properties"])
            self.assertNotIn(name, absent["required"])

    def test_modified_or_manufactured_client_fields_are_invalid(self):
        cases = [
            (
                case_input(),
                model_payload(problem_text=PROBLEM + " cambiado"),
            ),
            (
                case_input(as_of_date="2026-09-24"),
                model_payload(as_of_date="2026-09-23"),
            ),
            (
                case_input(),
                model_payload(as_of_date="2026-09-24"),
            ),
            (
                case_input(as_of_date="2026-09-24"),
                model_payload(),
            ),
            (
                case_input(client_reference="matter-16"),
                model_payload(client_reference="matter-17"),
            ),
            (
                case_input(client_reference="matter-16"),
                model_payload(),
            ),
            (
                case_input(),
                model_payload(client_reference="matter-16"),
            ),
        ]
        for original, payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(CaseContractError) as raised:
                    CaseStructuringService(
                        make_config(),
                        FakeLLMClient([payload]),
                    ).structure(original)
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_schema_rejects_missing_extra_and_model_owned_metadata(self):
        missing = model_payload()
        del missing["facts"]
        extra = model_payload()
        extra["surprise"] = True
        metadata = model_payload()
        metadata["model_metadata"] = {"model": "forged"}

        for payload in (missing, extra, metadata):
            with self.subTest(payload=payload):
                with self.assertRaises(CaseContractError) as raised:
                    CaseStructuringService(
                        make_config(),
                        FakeLLMClient([payload]),
                    ).structure(case_input())
                self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_user_fact_traceability_and_inference_are_distinct(self):
        quote = "está en liquidación"
        explicit = {
            "kind": "case_fact",
            "contract_version": "3.0.0",
            "fact_ref": "fact:explicit",
            "label": "Estado",
            "value": "liquidación",
            "state": "user_provided",
            "source_quote": quote,
            "requires_confirmation": False,
        }
        inferred = {
            "kind": "case_fact",
            "contract_version": "3.0.0",
            "fact_ref": "fact:inferred",
            "label": "Supuesto",
            "value": "sin deuda",
            "state": "llm_inferred",
            "requires_confirmation": True,
        }
        payload = model_payload(facts=[explicit, inferred])
        draft = CaseStructuringService(
            make_config(), FakeLLMClient([payload])
        ).structure(case_input()).draft
        self.assertEqual(
            [item["state"] for item in draft["facts"]],
            ["user_provided", "llm_inferred"],
        )

        bad = model_payload(facts=[{**explicit, "source_quote": "no aparece"}])
        with self.assertRaises(CaseContractError):
            CaseStructuringService(
                make_config(), FakeLLMClient([bad])
            ).structure(case_input())

    def test_model_schema_expands_case_fact_state_constraints(self):
        schema = case_draft_response_schema(case_input())
        variants = schema["$defs"]["CaseFact"]["oneOf"]
        states = {
            item["properties"]["state"]["const"]: item
            for item in variants
        }
        self.assertEqual(
            set(states),
            {
                "user_provided",
                "llm_normalized",
                "llm_inferred",
                "missing",
                "ambiguous",
            },
        )
        self.assertFalse(
            states["user_provided"]["properties"][
                "requires_confirmation"
            ]["const"]
        )
        self.assertIn("source_quote", states["user_provided"]["required"])
        for state in ("llm_normalized", "llm_inferred", "missing", "ambiguous"):
            self.assertTrue(
                states[state]["properties"][
                    "requires_confirmation"
                ]["const"]
            )
        self.assertIn("needed_information", states["missing"]["required"])
        self.assertIn("needed_information", states["ambiguous"]["required"])

    def test_hallucinated_canonical_hint_is_rejected(self):
        payload = model_payload()
        payload["candidate_claims"][0]["target_hints"] = [
            "DOC-deadbeef"
        ]
        with self.assertRaises(CaseContractError) as raised:
            CaseStructuringService(
                make_config(), FakeLLMClient([payload])
            ).structure(case_input())
        self.assertEqual(raised.exception.code, INVALID_CASE_DRAFT)

    def test_primary_retry_and_review_routing_are_explicit(self):
        invalid = model_payload()
        del invalid["facts"]
        fake = FakeLLMClient([invalid, model_payload()])
        outcome = CaseStructuringService(
            make_config(primary_attempts=2), fake
        ).structure(case_input())
        self.assertFalse(outcome.used_review)
        self.assertEqual(
            [route.routing_role for route in fake.calls],
            ["primary", "primary"],
        )

        fake = FakeLLMClient([invalid, model_payload()])
        outcome = CaseStructuringService(
            make_config(primary_attempts=1, review=True), fake
        ).structure(case_input())
        self.assertTrue(outcome.used_review)
        self.assertEqual(
            [route.routing_role for route in fake.calls],
            ["primary", "review"],
        )
        self.assertNotIn("auxiliary", [route.routing_role for route in fake.calls])

    def test_provider_error_does_not_escalate_by_default(self):
        fake = FakeLLMClient(
            [
                LLMClientError(
                    CASE_STRUCTURING_UNAVAILABLE,
                    "backend offline",
                    retryable=False,
                ),
                model_payload(),
            ]
        )
        with self.assertRaises(LLMClientError) as raised:
            CaseStructuringService(
                make_config(review=True, review_on_provider_error=False),
                fake,
            ).structure(case_input())
        self.assertEqual(
            raised.exception.code,
            CASE_STRUCTURING_UNAVAILABLE,
        )
        self.assertEqual(len(fake.calls), 1)

    def test_context_limit_is_explicit_and_never_truncates(self):
        config = make_config(context_tokens=10)
        client = OpenAICompatibleLLMClient(config)
        original = case_input(problem_text=PROBLEM * 20)
        with self.assertRaises(ContextLimitError) as raised:
            client.complete_case_draft(
                case_input=original,
                route=config.primary,
            )
        self.assertEqual(raised.exception.code, CASE_CONTEXT_LIMIT)
        self.assertFalse(raised.exception.metadata["truncated"])
        self.assertEqual(raised.exception.metadata["processed_portions"], [])
        self.assertEqual(original["problem_text"], PROBLEM * 20)

    def test_backend_unavailable_has_distinct_error(self):
        config = make_config()
        client = OpenAICompatibleLLMClient(config)
        with mock.patch(
            "llm_client.urlrequest.urlopen",
            side_effect=urlerror.URLError("offline"),
        ):
            with self.assertRaises(LLMClientError) as raised:
                client.complete_case_draft(
                    case_input=case_input(),
                    route=config.primary,
                )
        self.assertEqual(
            raised.exception.code,
            CASE_STRUCTURING_UNAVAILABLE,
        )

    def test_openai_compatible_adapter_parses_structured_response(self):
        config = replace(
            make_config(),
            request_options={
                "chat_template_kwargs": {"enable_thinking": False}
            },
        )
        client = OpenAICompatibleLLMClient(config)
        original = case_input(
            as_of_date="2026-09-24",
            client_reference="matter-16",
        )
        envelope = {
            "model": "primary-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            model_payload(
                                as_of_date="2026-09-24",
                                client_reference="matter-16",
                            )
                        )
                    }
                }
            ],
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(envelope).encode("utf-8")

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(),
        ) as mocked:
            payload = client.complete_case_draft(
                case_input=original,
                route=config.primary,
            )
        sent = json.loads(mocked.call_args.args[0].data)
        self.assertFalse(
            sent["chat_template_kwargs"]["enable_thinking"]
        )
        model_context = json.loads(sent["messages"][1]["content"])
        self.assertEqual(model_context["problem_text"], PROBLEM)
        self.assertEqual(
            model_context["analysis_context"]["as_of_date"],
            "2026-09-24",
        )
        self.assertNotIn("client_reference", model_context)
        draft_schema = sent["response_format"]["json_schema"]["schema"][
            "$defs"
        ]["CaseDraft"]
        for name in ("problem_text", "as_of_date", "client_reference"):
            self.assertNotIn(name, draft_schema["properties"])
            self.assertNotIn(name, draft_schema["required"])
        # The adapter restores only omitted client-owned fields from CaseInput;
        # authoritative CaseDraft validation still owns exact equality.
        self.assertEqual(payload["problem_text"], PROBLEM)
        self.assertEqual(payload["as_of_date"], "2026-09-24")
        self.assertEqual(payload["client_reference"], "matter-16")
        self.assertNotIn("model_metadata", payload)

    def test_adapter_rejects_backend_model_mismatch(self):
        config = make_config()
        client = OpenAICompatibleLLMClient(config)
        envelope = {
            "model": "unexpected-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(model_payload())
                    }
                }
            ],
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(envelope).encode("utf-8")

        with mock.patch(
            "llm_client.urlrequest.urlopen",
            return_value=Response(),
        ):
            with self.assertRaises(LLMClientError) as raised:
                client.complete_case_draft(
                    case_input=case_input(),
                    route=config.primary,
                )
        self.assertEqual(
            raised.exception.code,
            CASE_STRUCTURING_UNAVAILABLE,
        )

    def test_local_profile_does_not_auto_review_single_model_endpoint(self):
        config = load_platform_config(
            ROOT / "config" / "llm" / "local-platform.yaml"
        )
        self.assertFalse(config.review_on_invalid_output)
        self.assertIsNotNone(config.review)
        self.assertEqual(config.review.routing_role, "review")

    def test_adapter_request_options_cannot_override_owned_fields(self):
        config = replace(
            make_config(),
            request_options={"model": "forged-model"},
        )
        client = OpenAICompatibleLLMClient(config)
        with self.assertRaises(LLMClientError) as raised:
            client.complete_case_draft(
                case_input=case_input(),
                route=config.primary,
            )
        self.assertEqual(
            raised.exception.code,
            CASE_STRUCTURING_UNAVAILABLE,
        )


class Issue0016SemanticResultTests(unittest.TestCase):
    def test_complete_self_contained_result_passes_without_draft(self):
        validate_case_result(valid_result())

    def test_result_reference_integrity_matrix(self):
        mutations = [
            lambda r: r["questions"][0].update(
                depends_on_fact_refs=["fact:missing"]
            ),
            lambda r: r["supported_claims"][0].update(
                evidence_refs=["evidence:missing"]
            ),
            lambda r: r["supported_claims"][0].update(
                related_question_refs=["question:missing"]
            ),
            lambda r: r["remaining_candidate_claims"][0].update(
                related_question_refs=["question:missing"]
            ),
            lambda r: r["unresolved"][0].update(
                related_fact_refs=["fact:missing"]
            ),
            lambda r: r["unresolved"][0].update(
                related_question_refs=["question:missing"]
            ),
            lambda r: r["unresolved"][0].update(
                related_claim_refs=["claim:missing"]
            ),
            lambda r: r["evidence"][0].update(
                source_ref="source:missing"
            ),
            lambda r: r["evidence"][0].update(
                document_ref="document:missing"
            ),
            lambda r: r["evidence"][0].update(
                provision_ref="provision:missing"
            ),
            lambda r: r["provisions"][0].update(
                document_ref="document:missing"
            ),
        ]
        for mutate in mutations:
            result = valid_result()
            mutate(result)
            with self.subTest(result=result):
                with self.assertRaises(CaseContractError) as raised:
                    validate_case_result(result)
                self.assertEqual(
                    raised.exception.code,
                    INVALID_CASE_RESULT,
                )

    def test_duplicate_and_cross_collection_refs_are_invalid(self):
        result = valid_result()
        result["facts"].append(deepcopy(result["facts"][0]))
        with self.assertRaises(CaseContractError):
            validate_case_result(result)

        result = valid_result()
        result["remaining_candidate_claims"][0]["claim_ref"] = (
            result["supported_claims"][0]["claim_ref"]
        )
        with self.assertRaises(CaseContractError):
            validate_case_result(result)

    def test_wrong_typed_registry_never_cross_resolves(self):
        result = valid_result()
        result["supported_claims"][0]["related_question_refs"] = [
            "question:one"
        ]
        result["questions"] = []
        # A fact still exists, but a fact namespace can never satisfy a question.
        with self.assertRaises(CaseContractError):
            validate_case_result(result)


class Issue0016ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "state.sqlite"
        self.case_root = self.root / "cases"
        self._apply_migrations()
        self._seed_corpus(document_id="DOC-TEST")

    def tearDown(self):
        self.tmp.cleanup()

    def _apply_migrations(self):
        con = sqlite3.connect(self.db)
        try:
            for migration in sorted((ROOT / "schema").glob("*.sql")):
                con.executescript(
                    migration.read_text(encoding="utf-8")
                )
            con.commit()
        finally:
            con.close()

    def _seed_corpus(self, *, document_id: str | None):
        con = sqlite3.connect(self.db)
        try:
            if document_id is not None:
                con.execute(
                    """
                    INSERT INTO documents(
                        document_id, jurisdiction, entity, document_type,
                        title, issued_date, publication_date,
                        created_at, updated_at
                    ) VALUES (?, 'CO', 'DIAN', 'DECRETO',
                              'Documento de prueba', '2026-01-01', NULL, ?, ?)
                    """,
                    (document_id, NOW, NOW),
                )
                con.execute(
                    """
                    INSERT INTO document_identifiers(
                        identifier_id, document_id, identifier_type,
                        identifier_value, issuer, is_primary
                    ) VALUES ('ID-TEST', ?, 'number', '123', 'DIAN', 1)
                    """,
                    (document_id,),
                )
            con.execute(
                """
                INSERT INTO sources(
                    source_id, source_url, authority, source_kind,
                    discovered_from, first_seen_at, last_seen_at
                ) VALUES (
                    'SRC-TEST', 'https://example.test/source', 'DIAN',
                    'normograma_html', NULL, ?, ?
                )
                """,
                (NOW, NOW),
            )
            con.execute(
                """
                INSERT INTO manifestations(
                    manifestation_id, document_id, source_id, content_type,
                    sha256, byte_size, retrieved_at, local_path, parser_version
                ) VALUES (
                    'MAN-TEST', ?, 'SRC-TEST', 'text/html',
                    ?, 100, ?, 'raw/test', '1'
                )
                """,
                (document_id, SOURCE_SHA, NOW),
            )
            segment_text = (
                CLAIM_TEXT
                + " Texto adicional para conservar contexto oficial verificable."
            )
            segment_hash = hashlib.sha256(
                segment_text.encode("utf-8")
            ).hexdigest()
            con.execute(
                """
                INSERT INTO text_extractions(
                    extraction_id, manifestation_id, extractor_name,
                    extractor_version, normalized_sha256, byte_size,
                    char_count, segment_count, local_path, created_at, status
                ) VALUES (
                    'EXT-TEST', 'MAN-TEST', 'fixture', '1', ?, 100,
                    ?, 1, 'extracted/test', ?, 'success'
                )
                """,
                ("b" * 64, len(segment_text), NOW),
            )
            con.execute(
                """
                INSERT INTO extracted_segments(
                    extracted_segment_id, extraction_id, sequence_no,
                    segment_type, section_path, char_start, char_end,
                    text, text_sha256
                ) VALUES (
                    'SEG-TEST', 'EXT-TEST', 1, 'paragraph', NULL,
                    0, ?, ?, ?
                )
                """,
                (len(segment_text), segment_text, segment_hash),
            )
            con.execute(
                """
                INSERT INTO extracted_segments_fts(
                    extracted_segment_id, text, section_path
                ) VALUES ('SEG-TEST', ?, NULL)
                """,
                (segment_text,),
            )
            con.commit()
        finally:
            con.close()

    def _structurer(
        self,
        payload: dict | None = None,
    ) -> CaseStructuringService:
        return CaseStructuringService(
            make_config(),
            FakeLLMClient([payload or model_payload()]),
        )

    def test_dry_run_predicts_write_without_mutating_original(self):
        dry = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
            dry_run=True,
        )
        self.assertEqual(dry.persistence_mode, "dry-run")
        self.assertEqual(len(dry.result["supported_claims"]), 1)
        self.assertTrue(dry.validation["valid"])
        self.assertFalse(self.case_root.exists())

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                0,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
                0,
            )
        finally:
            con.close()

        real = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
            dry_run=False,
        )
        for field in (
            "claims_inserted",
            "evidence_inserted",
            "claims_validated_from_canonical_bindings",
        ):
            self.assertEqual(
                dry.registration[field],
                real.registration[field],
            )
        self.assertTrue(real.validation["valid"])

    def test_fixed_output_rerun_is_canonically_idempotent(self):
        first = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
        )
        second = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
        )
        self.assertEqual(first.case_id, second.case_id)
        self.assertEqual(second.registration["claims_inserted"], 0)
        self.assertEqual(second.registration["evidence_inserted"], 0)
        self.assertEqual(second.registration["claims_reused"], 1)

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    "SELECT status, requires_human_review FROM claims"
                ).fetchone(),
                ("validated", 0),
            )
        finally:
            con.close()

    def test_generated_internal_artifacts_and_materializations_validate(self):
        outcome = analyze_case(
            case_input=case_input(as_of_date="2026-09-24"),
            db_path=self.db,
            case_root=self.case_root,
            structurer=CaseStructuringService(
                make_config(),
                FakeLLMClient(
                    [model_payload(as_of_date="2026-09-24")]
                ),
            ),
        )
        case_dir = self.case_root / outcome.case_id
        for relative in (
            "query.md",
            "evidence.json",
            "claim_bindings.json",
            "case_draft.json",
            "case_result.json",
            "unresolved.json",
            "sources/manifest.json",
            "report.md",
        ):
            self.assertTrue((case_dir / relative).exists(), relative)
        self.assertTrue(outcome.validation["valid"])
        self.assertEqual(
            (case_dir / "query.md").read_text(encoding="utf-8"),
            PROBLEM,
        )

    def test_unsupported_search_hit_never_becomes_evidence(self):
        paraphrase = (
            "Las obligaciones tributarias deben examinarse mediante una "
            "conclusión diferente que no aparece literalmente en la fuente."
        )
        outcome = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(
                model_payload(claim_text=paraphrase)
            ),
            dry_run=True,
        )
        self.assertEqual(outcome.result["supported_claims"], [])
        self.assertEqual(outcome.result["evidence"], [])
        self.assertEqual(
            outcome.result["remaining_candidate_claims"][0]["status"],
            "candidate",
        )

    def test_issue64_unsupported_candidate_review_state_persists_and_is_idempotent(self):
        paraphrase = (
            "Las obligaciones tributarias deben examinarse mediante una "
            "conclusión diferente que no aparece literalmente en la fuente."
        )
        payload = model_payload(claim_text=paraphrase)

        first = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(payload),
        )
        case_dir = self.case_root / first.case_id
        bundle = json.loads(
            (case_dir / "evidence.json").read_text(encoding="utf-8")
        )
        self.assertTrue(bundle["claims"][0]["requires_human_review"])
        self.assertEqual(
            json.loads(
                (case_dir / "claim_bindings.json").read_text(
                    encoding="utf-8"
                )
            ),
            {},
        )

        con = sqlite3.connect(self.db)
        try:
            row = con.execute(
                """
                SELECT status, requires_human_review,
                       (SELECT COUNT(*) FROM evidence e
                        WHERE e.claim_id = c.claim_id)
                FROM claims c
                WHERE subject_id = ?
                """,
                (first.case_id,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("candidate", 1, 0))
        self.assertTrue(first.validation["valid"])

        second = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(payload),
        )
        self.assertEqual(second.case_id, first.case_id)
        self.assertEqual(second.registration["claims_inserted"], 0)
        self.assertEqual(second.registration["claims_reused"], 1)
        self.assertEqual(second.registration["evidence_inserted"], 0)
        self.assertTrue(second.validation["valid"])

        con = sqlite3.connect(self.db)
        try:
            rerun_row = con.execute(
                """
                SELECT status, requires_human_review
                FROM claims
                WHERE subject_id = ?
                """,
                (first.case_id,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(rerun_row, ("candidate", 1))

    def test_issue64_rerun_repairs_stale_candidate_review_state(self):
        paraphrase = (
            "Las obligaciones tributarias deben examinarse mediante una "
            "conclusión diferente que no aparece literalmente en la fuente."
        )
        payload = model_payload(claim_text=paraphrase)
        first = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(payload),
        )

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                """
                UPDATE claims
                SET requires_human_review = 0
                WHERE subject_id = ?
                """,
                (first.case_id,),
            )
            con.commit()
        finally:
            con.close()

        repaired = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(payload),
        )
        self.assertTrue(repaired.validation["valid"])
        self.assertEqual(repaired.registration["claims_inserted"], 0)
        self.assertEqual(repaired.registration["claims_reused"], 1)

        con = sqlite3.connect(self.db)
        try:
            row = con.execute(
                """
                SELECT status, requires_human_review
                FROM claims
                WHERE subject_id = ?
                """,
                (first.case_id,),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("candidate", 1))

    def test_issue64_validator_detects_review_state_disagreement(self):
        paraphrase = (
            "Las obligaciones tributarias deben examinarse mediante una "
            "conclusión diferente que no aparece literalmente en la fuente."
        )
        outcome = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(
                model_payload(claim_text=paraphrase)
            ),
        )
        case_dir = self.case_root / outcome.case_id

        con = sqlite3.connect(self.db)
        try:
            claim_id = con.execute(
                "SELECT claim_id FROM claims WHERE subject_id = ?",
                (outcome.case_id,),
            ).fetchone()[0]
            con.execute(
                """
                UPDATE claims
                SET requires_human_review = 0
                WHERE claim_id = ?
                """,
                (claim_id,),
            )
            con.commit()
            refresh_case_materializations(
                con,
                case_id=outcome.case_id,
                case_dir=case_dir,
                write=True,
            )
            validation = validate_case(
                con=con,
                case_id=outcome.case_id,
                case_dir=case_dir,
            )
        finally:
            con.close()

        self.assertFalse(validation["valid"])
        self.assertIn("claim_review_state_mismatch", validation["errors"])
        self.assertEqual(
            validation["claim_review_state_mismatches"],
            [
                {
                    "claim_id": claim_id,
                    "status": "candidate",
                    "persisted_requires_human_review": False,
                    "expected_requires_human_review": True,
                }
            ],
        )

    def test_unresolved_canonical_identity_does_not_validate(self):
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE manifestations SET document_id = NULL "
                "WHERE manifestation_id = 'MAN-TEST'"
            )
            con.commit()
        finally:
            con.close()
        outcome = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
            dry_run=True,
        )
        self.assertEqual(outcome.result["supported_claims"], [])
        categories = {
            item["category"] for item in outcome.result["unresolved"]
        }
        self.assertIn("unresolved_legal_target", categories)

    def test_text_fingerprint_mismatch_fails_safely(self):
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "UPDATE extracted_segments SET text_sha256 = ? "
                "WHERE extracted_segment_id = 'SEG-TEST'",
                ("f" * 64,),
            )
            con.commit()
        finally:
            con.close()
        with self.assertRaises(RetrievalIntegrityError):
            analyze_case(
                case_input=case_input(),
                db_path=self.db,
                case_root=self.case_root,
                structurer=self._structurer(),
                dry_run=True,
            )

    def test_missing_fact_remains_unresolved_and_result_preserves_state(self):
        missing_fact = {
            "kind": "case_fact",
            "contract_version": "3.0.0",
            "fact_ref": "fact:missing",
            "label": "Fecha efectiva",
            "state": "missing",
            "requires_confirmation": True,
            "needed_information": "Aportar fecha efectiva",
        }
        unresolved = {
            "kind": "case_unresolved",
            "contract_version": "3.0.0",
            "unresolved_ref": "unresolved:missing-fact",
            "category": "missing_fact",
            "description": "Falta la fecha efectiva",
            "related_fact_refs": ["fact:missing"],
            "needed_information": "Aportar fecha efectiva",
            "next_action": "ask_client",
        }
        payload = model_payload(
            facts=[missing_fact],
            unresolved=[unresolved],
        )
        outcome = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(payload),
            dry_run=True,
        )
        self.assertEqual(
            outcome.result["facts"][0]["state"],
            "missing",
        )
        self.assertIn(
            "missing_fact",
            {item["category"] for item in outcome.result["unresolved"]},
        )

    def test_debug_provenance_retains_manifestation_and_raw_sha(self):
        outcome = analyze_case(
            case_input=case_input(),
            db_path=self.db,
            case_root=self.case_root,
            structurer=self._structurer(),
            dry_run=True,
            include_debug_provenance=True,
        )
        debug = outcome.result["evidence"][0]["debug_provenance"]
        self.assertEqual(debug["manifestation_id"], "MAN-TEST")
        self.assertEqual(debug["extracted_segment_id"], "SEG-TEST")
        self.assertEqual(debug["source_sha256"], SOURCE_SHA)


if __name__ == "__main__":
    unittest.main()
