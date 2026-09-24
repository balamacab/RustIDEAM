from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
V1_SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v1.schema.json"
V2_SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v2.schema.json"
V2_CONTRACT_PATH = ROOT / "specs" / "application" / "case-contracts-v2.md"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metadata_shape_accepts(metadata: object, schema: dict) -> bool:
    """Check the closed-object constraints relevant to StructuringModelMetadata."""
    if not isinstance(metadata, dict):
        return False

    required = set(schema["required"])
    properties = schema["properties"]
    keys = set(metadata)

    if not required.issubset(keys):
        return False
    if schema.get("additionalProperties") is False and not keys.issubset(properties):
        return False

    for name, value in metadata.items():
        rule = properties[name]
        if "const" in rule and value != rule["const"]:
            return False
        if rule.get("type") == "string":
            if not isinstance(value, str):
                return False
            if len(value) < rule.get("minLength", 0):
                return False

    return True


class Issue0024CaseResultMetadataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_schema(V1_SCHEMA_PATH)
        cls.v2 = load_schema(V2_SCHEMA_PATH)
        cls.metadata_schema = cls.v2["$defs"]["StructuringModelMetadata"]

    def test_v1_compatibility_contract_remains_separate(self):
        v1_result = self.v1["$defs"]["CaseResult"]
        self.assertEqual(v1_result["properties"]["contract_version"]["const"], "1.0.0")
        self.assertNotIn("model_metadata", v1_result["properties"])
        self.assertNotIn("model_metadata", v1_result["required"])

    def test_v2_requires_same_metadata_shape_on_draft_and_result(self):
        draft = self.v2["$defs"]["CaseDraft"]
        result = self.v2["$defs"]["CaseResult"]

        self.assertEqual(draft["properties"]["model_metadata"], {"$ref": "#/$defs/StructuringModelMetadata"})
        self.assertEqual(result["properties"]["model_metadata"], {"$ref": "#/$defs/StructuringModelMetadata"})
        self.assertIn("model_metadata", draft["required"])
        self.assertIn("model_metadata", result["required"])
        self.assertEqual(draft["properties"]["contract_version"]["const"], "2.0.0")
        self.assertEqual(result["properties"]["contract_version"]["const"], "2.0.0")

    def test_valid_structuring_metadata_shape_is_accepted(self):
        metadata = {
            "adapter": "openai-compatible",
            "provider": "local",
            "model": "example-model",
            "schema_version": "2.0.0",
            "prompt_template_id": "case-structuring",
            "prompt_template_version": "3",
            "run_reference": "run:test-001",
            "generated_at": "2026-09-24T02:30:00Z",
            "routing_role": "primary",
        }
        self.assertTrue(metadata_shape_accepts(metadata, self.metadata_schema))

    def test_missing_required_metadata_is_rejected(self):
        metadata = {
            "adapter": "openai-compatible",
            "provider": "local",
            "model": "example-model",
            "schema_version": "2.0.0",
            "prompt_template_id": "case-structuring",
            "prompt_template_version": "3",
            "generated_at": "2026-09-24T02:30:00Z",
            "routing_role": "primary",
        }
        self.assertFalse(metadata_shape_accepts(metadata, self.metadata_schema))

    def test_unsupported_secret_field_is_rejected(self):
        metadata = {
            "adapter": "openai-compatible",
            "provider": "local",
            "model": "example-model",
            "schema_version": "2.0.0",
            "prompt_template_id": "case-structuring",
            "prompt_template_version": "3",
            "run_reference": "run:test-001",
            "generated_at": "2026-09-24T02:30:00Z",
            "routing_role": "review",
            "api_key": "must-not-be-serialized",
        }
        self.assertFalse(metadata_shape_accepts(metadata, self.metadata_schema))
        self.assertFalse(self.metadata_schema["additionalProperties"])

    def test_provider_model_and_routing_values_are_descriptive_strings(self):
        properties = self.metadata_schema["properties"]
        for name in ("adapter", "provider", "model", "routing_role"):
            self.assertEqual(properties[name]["type"], "string")
            self.assertNotIn("enum", properties[name])

    def test_schema_and_prompt_identity_are_explicit_without_full_prompt(self):
        properties = self.metadata_schema["properties"]
        self.assertEqual(properties["schema_version"]["const"], "2.0.0")
        self.assertIn("prompt_template_id", properties)
        self.assertIn("prompt_template_version", properties)
        for forbidden in ("api_key","token","password","secret","credentials","prompt","prompt_text"):
            self.assertNotIn(forbidden, properties)

    def test_prose_defines_draft_result_link_and_issue11_boundary(self):
        contract = V2_CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertIn("CaseResult.model_metadata == accepted CaseDraft.model_metadata", contract)
        self.assertIn("issue #11", contract)
        self.assertIn("not legal evidence", contract)
        self.assertIn("supports only v1 MUST reject a v2 object explicitly", contract)


if __name__ == "__main__":
    unittest.main()
