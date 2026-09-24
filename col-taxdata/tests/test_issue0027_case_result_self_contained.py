from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
V1_SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v1.schema.json"
V2_SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v2.schema.json"
V3_SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v3.schema.json"
V3_CONTRACT_PATH = ROOT / "specs" / "application" / "case-contracts-v3.md"
README_PATH = ROOT / "specs" / "README.md"

INVALID_CASE_RESULT = "INVALID_CASE_RESULT"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry(items: list[dict], key: str) -> dict[str, dict] | None:
    registry: dict[str, dict] = {}
    for item in items:
        ref = item[key]
        if ref in registry:
            return None
        registry[ref] = item
    return registry


def validate_result_graph(result: dict) -> str | None:
    """Minimal contract-test validator for the typed v3 CaseResult graph."""
    facts = _registry(result["facts"], "fact_ref")
    questions = _registry(result["questions"], "question_ref")
    supported = _registry(result["supported_claims"], "claim_ref")
    remaining = _registry(result["remaining_candidate_claims"], "claim_ref")
    unresolved = _registry(result["unresolved"], "unresolved_ref")
    evidence = _registry(result["evidence"], "evidence_ref")
    sources = _registry(result["sources"], "source_ref")
    documents = _registry(result["documents"], "document_ref")
    provisions = _registry(result["provisions"], "provision_ref")

    registries = (facts, questions, supported, remaining, unresolved, evidence, sources, documents, provisions)
    if any(registry is None for registry in registries):
        return INVALID_CASE_RESULT
    if set(supported).intersection(remaining):
        return INVALID_CASE_RESULT

    claims = {**supported, **remaining}

    for question in result["questions"]:
        if any(ref not in facts for ref in question.get("depends_on_fact_refs", [])):
            return INVALID_CASE_RESULT

    for claim in result["supported_claims"]:
        if any(ref not in evidence for ref in claim["evidence_refs"]):
            return INVALID_CASE_RESULT
        if any(ref not in questions for ref in claim.get("related_question_refs", [])):
            return INVALID_CASE_RESULT

    for claim in result["remaining_candidate_claims"]:
        if any(ref not in questions for ref in claim.get("related_question_refs", [])):
            return INVALID_CASE_RESULT

    for item in result["unresolved"]:
        if any(ref not in facts for ref in item.get("related_fact_refs", [])):
            return INVALID_CASE_RESULT
        if any(ref not in questions for ref in item.get("related_question_refs", [])):
            return INVALID_CASE_RESULT
        if any(ref not in claims for ref in item.get("related_claim_refs", [])):
            return INVALID_CASE_RESULT

    for item in result["evidence"]:
        if item["source_ref"] not in sources:
            return INVALID_CASE_RESULT
        if item.get("document_ref") is not None and item["document_ref"] not in documents:
            return INVALID_CASE_RESULT
        if item.get("provision_ref") is not None and item["provision_ref"] not in provisions:
            return INVALID_CASE_RESULT

    for provision in result["provisions"]:
        if provision["document_ref"] not in documents:
            return INVALID_CASE_RESULT

    return None


def producer_preservation_error(draft: dict, result: dict) -> str | None:
    if result["facts"] != draft["facts"]:
        return INVALID_CASE_RESULT
    if result["questions"] != draft["questions"]:
        return INVALID_CASE_RESULT
    if result["model_metadata"] != draft["model_metadata"]:
        return INVALID_CASE_RESULT
    return None


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
                "fact_ref": "fact:user",
                "label": "User fact",
                "value": "Declared value",
                "state": "user_provided",
                "source_quote": "Declared value",
                "requires_confirmation": False,
            },
            {
                "kind": "case_fact",
                "contract_version": "3.0.0",
                "fact_ref": "fact:missing",
                "label": "Missing fact",
                "state": "missing",
                "requires_confirmation": True,
                "needed_information": "Provide missing fact",
            },
        ],
        "questions": [
            {
                "kind": "case_question",
                "contract_version": "3.0.0",
                "question_ref": "question:main",
                "text": "What applies?",
                "category": "legal",
                "status": "blocked",
                "depends_on_fact_refs": ["fact:missing"],
            }
        ],
        "supported_claims": [
            {
                "claim_ref": "claim:supported",
                "text": "Supported conclusion",
                "status": "validated",
                "evidence_refs": ["evidence:one"],
                "related_question_refs": ["question:main"],
            }
        ],
        "remaining_candidate_claims": [
            {
                "kind": "candidate_claim",
                "contract_version": "3.0.0",
                "claim_ref": "claim:candidate",
                "text": "Candidate conclusion",
                "status": "candidate",
                "requires_canonical_validation": True,
                "related_question_refs": ["question:main"],
            }
        ],
        "unresolved": [
            {
                "kind": "case_unresolved",
                "contract_version": "3.0.0",
                "unresolved_ref": "unresolved:one",
                "category": "missing_fact",
                "description": "More information is required",
                "related_fact_refs": ["fact:missing"],
                "related_question_refs": ["question:main"],
                "related_claim_refs": ["claim:candidate"],
                "needed_information": "Provide missing fact",
                "next_action": "ask_client",
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
                "exact_quote": "Exact official text",
                "support_status": "validated",
                "provenance_ref": "audit:one",
            }
        ],
        "sources": [
            {
                "source_ref": "source:one",
                "authority": "DIAN",
                "source_url": "https://example.invalid/source",
            }
        ],
        "documents": [
            {
                "document_ref": "document:one",
                "display_name": "Example document",
            }
        ],
        "provisions": [
            {
                "provision_ref": "provision:one",
                "document_ref": "document:one",
                "display_name": "Article 1",
            }
        ],
        "model_metadata": {
            "adapter": "openai-compatible",
            "provider": "local",
            "model": "example-model",
            "schema_version": "3.0.0",
            "prompt_template_id": "case-structuring",
            "prompt_template_version": "1",
            "run_reference": "run:test",
            "generated_at": "2026-09-24T04:00:00Z",
            "routing_role": "primary",
        },
        "generated_at": "2026-09-24T04:01:00Z",
    }


class Issue0027CaseResultSelfContainedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_schema(V1_SCHEMA_PATH)
        cls.v2 = load_schema(V2_SCHEMA_PATH)
        cls.v3 = load_schema(V3_SCHEMA_PATH)

    def test_v1_and_v2_remain_separate_compatibility_contracts(self):
        self.assertEqual(self.v1["$defs"]["CaseResult"]["properties"]["contract_version"]["const"], "1.0.0")
        self.assertEqual(self.v2["$defs"]["CaseResult"]["properties"]["contract_version"]["const"], "2.0.0")
        self.assertNotIn("facts", self.v2["$defs"]["CaseResult"]["properties"])
        self.assertNotIn("questions", self.v2["$defs"]["CaseResult"]["properties"])

    def test_v3_result_requires_facts_questions_and_model_metadata(self):
        result = self.v3["$defs"]["CaseResult"]
        for field in ("facts", "questions", "model_metadata"):
            self.assertIn(field, result["required"])
            self.assertIn(field, result["properties"])
        self.assertEqual(result["properties"]["facts"]["items"]["$ref"], "#/$defs/CaseFact")
        self.assertEqual(result["properties"]["questions"]["items"]["$ref"], "#/$defs/CaseQuestion")
        self.assertEqual(result["properties"]["contract_version"]["const"], "3.0.0")
        self.assertEqual(self.v3["$defs"]["StructuringModelMetadata"]["properties"]["schema_version"]["const"], "3.0.0")

    def test_v3_is_current_and_issue16_is_directed_to_v3(self):
        readme = README_PATH.read_text(encoding="utf-8")
        contract = V3_CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertIn("case-contracts-v3.md", readme)
        self.assertIn("current contract for new implementations", readme)
        self.assertIn("v2.0.0", readme)
        self.assertIn("issue #16 MUST use v3.0.0", contract)

    def test_complete_result_validates_without_external_draft(self):
        self.assertIsNone(validate_result_graph(valid_result()))

    def test_unresolved_missing_result_fact_is_invalid(self):
        result = valid_result()
        result["unresolved"][0]["related_fact_refs"] = ["fact:absent"]
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_unresolved_missing_result_question_is_invalid(self):
        result = valid_result()
        result["unresolved"][0]["related_question_refs"] = ["question:absent"]
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_supported_claim_missing_result_question_is_invalid(self):
        result = valid_result()
        result["supported_claims"][0]["related_question_refs"] = ["question:absent"]
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_remaining_candidate_missing_result_question_is_invalid(self):
        result = valid_result()
        result["remaining_candidate_claims"][0]["related_question_refs"] = ["question:absent"]
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_duplicate_result_fact_ref_is_invalid(self):
        result = valid_result()
        duplicate = deepcopy(result["facts"][0])
        result["facts"].append(duplicate)
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_duplicate_result_question_ref_is_invalid(self):
        result = valid_result()
        duplicate = deepcopy(result["questions"][0])
        result["questions"].append(duplicate)
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_wrong_type_lookup_is_not_cross_resolved(self):
        result = valid_result()
        result["supported_claims"][0]["related_question_refs"] = ["question:user"]
        # A fact with the same local suffix exists, but typed lookup must not satisfy a question ref.
        self.assertIn("fact:user", {f["fact_ref"] for f in result["facts"]})
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_question_dependency_missing_result_fact_is_invalid(self):
        result = valid_result()
        result["questions"][0]["depends_on_fact_refs"] = ["fact:absent"]
        self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_other_result_graph_refs_remain_typed_and_enforced(self):
        mutations = [
            lambda r: r["supported_claims"][0].update(evidence_refs=["evidence:absent"]),
            lambda r: r["evidence"][0].update(source_ref="source:absent"),
            lambda r: r["evidence"][0].update(document_ref="document:absent"),
            lambda r: r["evidence"][0].update(provision_ref="provision:absent"),
            lambda r: r["provisions"][0].update(document_ref="document:absent"),
            lambda r: r["unresolved"][0].update(related_claim_refs=["claim:absent"]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                result = valid_result()
                mutate(result)
                self.assertEqual(validate_result_graph(result), INVALID_CASE_RESULT)

    def test_draft_result_fact_question_and_metadata_preservation(self):
        result = valid_result()
        draft = {
            "facts": deepcopy(result["facts"]),
            "questions": deepcopy(result["questions"]),
            "model_metadata": deepcopy(result["model_metadata"]),
        }
        self.assertIsNone(producer_preservation_error(draft, result))

        states = [fact["state"] for fact in result["facts"]]
        self.assertEqual(states, ["user_provided", "missing"])

        changed = deepcopy(result)
        changed["facts"][0]["state"] = "llm_inferred"
        self.assertEqual(producer_preservation_error(draft, changed), INVALID_CASE_RESULT)

        changed = deepcopy(result)
        changed["facts"][0]["fact_ref"] = "fact:rewritten"
        self.assertEqual(producer_preservation_error(draft, changed), INVALID_CASE_RESULT)

        changed = deepcopy(result)
        changed["questions"][0]["question_ref"] = "question:rewritten"
        self.assertEqual(producer_preservation_error(draft, changed), INVALID_CASE_RESULT)

        changed = deepcopy(result)
        changed["model_metadata"]["run_reference"] = "run:other"
        self.assertEqual(producer_preservation_error(draft, changed), INVALID_CASE_RESULT)

    def test_contract_distinguishes_producer_invariant_from_standalone_validity(self):
        contract = V3_CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertIn("CaseResult.facts          == accepted CaseDraft.facts", contract)
        self.assertIn("CaseResult.questions      == accepted CaseDraft.questions", contract)
        self.assertIn("CaseResult.model_metadata == accepted CaseDraft.model_metadata", contract)
        self.assertIn("producer lifecycle invariants", contract)
        self.assertIn("standalone CaseResult graph validity", contract)
        self.assertIn("MUST NOT require fetching the originating CaseDraft", contract)


if __name__ == "__main__":
    unittest.main()
