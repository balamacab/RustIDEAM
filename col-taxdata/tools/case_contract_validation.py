from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


CONTRACT_VERSION = "3.0.0"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "specs" / "application" / "schemas" / "case-contracts-v3.schema.json"

INVALID_CASE_INPUT = "INVALID_CASE_INPUT"
INVALID_CASE_DRAFT = "INVALID_CASE_DRAFT"
INVALID_CASE_RESULT = "INVALID_CASE_RESULT"

_FORBIDDEN_INTERNAL_HINT = re.compile(
    r"^(?:CASE|CLM|DOC|PROV|EVD|MAN|SEG|REL|EXT|SRC)-[A-Za-z0-9._-]+$",
    re.IGNORECASE,
)


class CaseContractError(ValueError):
    """Transport-neutral application-contract validation failure."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def load_contract_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _fail(code: str, path: str, detail: str) -> None:
    raise CaseContractError(code, f"{path}: {detail}")


def _is_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise RuntimeError(f"unsupported schema reference: {ref}")
    node: Any = root
    for component in ref[2:].split("/"):
        node = node[component.replace("~1", "/").replace("~0", "~")]
    if not isinstance(node, dict):
        raise RuntimeError(f"schema reference is not an object: {ref}")
    return node


def _format_valid(value: str, format_name: str) -> bool:
    try:
        if format_name == "date":
            date.fromisoformat(value)
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
        if format_name == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "T" in value
        if format_name == "uri":
            parsed = urlparse(value)
            return bool(parsed.scheme)
    except ValueError:
        return False
    return True


def _validate_node(
    value: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any],
    code: str,
    path: str,
) -> None:
    if "$ref" in schema:
        _validate_node(
            value,
            _resolve_ref(root, schema["$ref"]),
            root=root,
            code=code,
            path=path,
        )
        return

    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate_node(
                    value,
                    option,
                    root=root,
                    code=code,
                    path=path,
                )
            except CaseContractError:
                continue
            matches += 1
        if matches != 1:
            _fail(code, path, f"expected exactly one schema match, got {matches}")
        return

    if "const" in schema and value != schema["const"]:
        _fail(code, path, f"must equal {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        _fail(code, path, f"unsupported value {value!r}")

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_is_json_type(value, item) for item in expected_types):
            _fail(code, path, f"expected type {expected_types}, got {type(value).__name__}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                _fail(code, path, f"missing required field {name!r}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                _fail(code, path, f"unexpected field(s): {', '.join(extras)}")

        for name, item in value.items():
            rule = properties.get(name)
            if rule is not None:
                _validate_node(
                    item,
                    rule,
                    root=root,
                    code=code,
                    path=f"{path}.{name}",
                )

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            _fail(code, path, f"requires at least {min_items} item(s)")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            _fail(code, path, f"allows at most {max_items} item(s)")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(encoded) != len(set(encoded)):
                _fail(code, path, "contains duplicate items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_node(
                    item,
                    item_schema,
                    root=root,
                    code=code,
                    path=f"{path}[{index}]",
                )

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            _fail(code, path, f"requires at least {min_length} character(s)")
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            _fail(code, path, f"allows at most {max_length} character(s)")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            _fail(code, path, f"does not match required pattern {pattern!r}")
        format_name = schema.get("format")
        if format_name and not _format_valid(value, format_name):
            _fail(code, path, f"invalid {format_name}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            _fail(code, path, f"must be >= {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            _fail(code, path, f"must be <= {maximum}")

    for rule in schema.get("allOf", []):
        condition = rule.get("if")
        if condition is None:
            _validate_node(value, rule, root=root, code=code, path=path)
            continue
        try:
            _validate_node(value, condition, root=root, code=code, path=path)
            condition_matches = True
        except CaseContractError:
            condition_matches = False
        if condition_matches and "then" in rule:
            _validate_node(value, rule["then"], root=root, code=code, path=path)
        elif not condition_matches and "else" in rule:
            _validate_node(value, rule["else"], root=root, code=code, path=path)


def validate_schema_object(value: dict[str, Any], definition: str, code: str) -> None:
    """Validate one v3 public object with the repository JSON Schema.

    The project intentionally has no runtime Python dependencies. This validator
    implements the JSON-Schema vocabulary used by the checked-in v3 contract so
    the executable application path validates the authoritative schema rather
    than maintaining a second handwritten field list.
    """
    root = load_contract_schema()
    definition_schema = root["$defs"][definition]
    _validate_node(value, definition_schema, root=root, code=code, path="$")


def _registry(
    items: list[dict[str, Any]],
    key: str,
    *,
    code: str,
    owner: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        ref = item[key]
        if ref in result:
            _fail(code, owner, f"duplicate declared ref {ref!r}")
        result[ref] = item
    return result


def _require_refs(
    refs: list[str],
    registry: dict[str, dict[str, Any]],
    *,
    code: str,
    path: str,
) -> None:
    for ref in refs:
        if ref not in registry:
            _fail(code, path, f"dangling or wrong-type ref {ref!r}")


def validate_case_input(case_input: dict[str, Any]) -> None:
    validate_schema_object(case_input, "CaseInput", INVALID_CASE_INPUT)


def validate_case_draft(
    case_input: dict[str, Any],
    draft: dict[str, Any],
) -> None:
    """Validate a model draft before any corpus/case mutation is allowed."""
    validate_case_input(case_input)
    validate_schema_object(draft, "CaseDraft", INVALID_CASE_DRAFT)

    if draft["problem_text"] != case_input["problem_text"]:
        _fail(INVALID_CASE_DRAFT, "$.problem_text", "client problem_text was modified")

    for name in ("as_of_date", "client_reference"):
        input_has = name in case_input
        draft_has = name in draft
        if input_has != draft_has:
            _fail(
                INVALID_CASE_DRAFT,
                f"$.{name}",
                "client field presence/absence was not preserved",
            )
        if input_has and draft[name] != case_input[name]:
            _fail(INVALID_CASE_DRAFT, f"$.{name}", "client field value was modified")

    for index, fact in enumerate(draft["facts"]):
        if fact["state"] == "user_provided":
            quote = fact["source_quote"]
            if quote not in case_input["problem_text"]:
                _fail(
                    INVALID_CASE_DRAFT,
                    f"$.facts[{index}].source_quote",
                    "user_provided quote is not present verbatim in CaseInput.problem_text",
                )

    for index, claim in enumerate(draft["candidate_claims"]):
        for hint in claim.get("target_hints", []):
            if _FORBIDDEN_INTERNAL_HINT.fullmatch(hint.strip()):
                _fail(
                    INVALID_CASE_DRAFT,
                    f"$.candidate_claims[{index}].target_hints",
                    "model output attempted to inject a persistence/canonical identifier",
                )

    facts = _registry(
        draft["facts"], "fact_ref", code=INVALID_CASE_DRAFT, owner="$.facts"
    )
    questions = _registry(
        draft["questions"],
        "question_ref",
        code=INVALID_CASE_DRAFT,
        owner="$.questions",
    )
    claims = _registry(
        draft["candidate_claims"],
        "claim_ref",
        code=INVALID_CASE_DRAFT,
        owner="$.candidate_claims",
    )
    _registry(
        draft["unresolved"],
        "unresolved_ref",
        code=INVALID_CASE_DRAFT,
        owner="$.unresolved",
    )

    for index, question in enumerate(draft["questions"]):
        _require_refs(
            question.get("depends_on_fact_refs", []),
            facts,
            code=INVALID_CASE_DRAFT,
            path=f"$.questions[{index}].depends_on_fact_refs",
        )
    for index, claim in enumerate(draft["candidate_claims"]):
        _require_refs(
            claim.get("related_question_refs", []),
            questions,
            code=INVALID_CASE_DRAFT,
            path=f"$.candidate_claims[{index}].related_question_refs",
        )
    for index, item in enumerate(draft["unresolved"]):
        _require_refs(
            item.get("related_fact_refs", []),
            facts,
            code=INVALID_CASE_DRAFT,
            path=f"$.unresolved[{index}].related_fact_refs",
        )
        _require_refs(
            item.get("related_question_refs", []),
            questions,
            code=INVALID_CASE_DRAFT,
            path=f"$.unresolved[{index}].related_question_refs",
        )
        _require_refs(
            item.get("related_claim_refs", []),
            claims,
            code=INVALID_CASE_DRAFT,
            path=f"$.unresolved[{index}].related_claim_refs",
        )


def validate_case_result(result: dict[str, Any]) -> None:
    """Validate a standalone v3 CaseResult graph without an originating draft."""
    validate_schema_object(result, "CaseResult", INVALID_CASE_RESULT)

    facts = _registry(
        result["facts"], "fact_ref", code=INVALID_CASE_RESULT, owner="$.facts"
    )
    questions = _registry(
        result["questions"],
        "question_ref",
        code=INVALID_CASE_RESULT,
        owner="$.questions",
    )
    supported = _registry(
        result["supported_claims"],
        "claim_ref",
        code=INVALID_CASE_RESULT,
        owner="$.supported_claims",
    )
    remaining = _registry(
        result["remaining_candidate_claims"],
        "claim_ref",
        code=INVALID_CASE_RESULT,
        owner="$.remaining_candidate_claims",
    )
    overlap = set(supported).intersection(remaining)
    if overlap:
        _fail(
            INVALID_CASE_RESULT,
            "$.claims",
            f"claim ref appears in supported and remaining collections: {sorted(overlap)[0]}",
        )
    claims = {**supported, **remaining}
    unresolved = _registry(
        result["unresolved"],
        "unresolved_ref",
        code=INVALID_CASE_RESULT,
        owner="$.unresolved",
    )
    del unresolved
    evidence = _registry(
        result["evidence"],
        "evidence_ref",
        code=INVALID_CASE_RESULT,
        owner="$.evidence",
    )
    sources = _registry(
        result["sources"],
        "source_ref",
        code=INVALID_CASE_RESULT,
        owner="$.sources",
    )
    documents = _registry(
        result["documents"],
        "document_ref",
        code=INVALID_CASE_RESULT,
        owner="$.documents",
    )
    provisions = _registry(
        result["provisions"],
        "provision_ref",
        code=INVALID_CASE_RESULT,
        owner="$.provisions",
    )

    for index, question in enumerate(result["questions"]):
        _require_refs(
            question.get("depends_on_fact_refs", []),
            facts,
            code=INVALID_CASE_RESULT,
            path=f"$.questions[{index}].depends_on_fact_refs",
        )
    for index, claim in enumerate(result["supported_claims"]):
        _require_refs(
            claim["evidence_refs"],
            evidence,
            code=INVALID_CASE_RESULT,
            path=f"$.supported_claims[{index}].evidence_refs",
        )
        _require_refs(
            claim.get("related_question_refs", []),
            questions,
            code=INVALID_CASE_RESULT,
            path=f"$.supported_claims[{index}].related_question_refs",
        )
    for index, claim in enumerate(result["remaining_candidate_claims"]):
        _require_refs(
            claim.get("related_question_refs", []),
            questions,
            code=INVALID_CASE_RESULT,
            path=f"$.remaining_candidate_claims[{index}].related_question_refs",
        )
    for index, item in enumerate(result["unresolved"]):
        _require_refs(
            item.get("related_fact_refs", []),
            facts,
            code=INVALID_CASE_RESULT,
            path=f"$.unresolved[{index}].related_fact_refs",
        )
        _require_refs(
            item.get("related_question_refs", []),
            questions,
            code=INVALID_CASE_RESULT,
            path=f"$.unresolved[{index}].related_question_refs",
        )
        _require_refs(
            item.get("related_claim_refs", []),
            claims,
            code=INVALID_CASE_RESULT,
            path=f"$.unresolved[{index}].related_claim_refs",
        )
    for index, item in enumerate(result["evidence"]):
        _require_refs(
            [item["source_ref"]],
            sources,
            code=INVALID_CASE_RESULT,
            path=f"$.evidence[{index}].source_ref",
        )
        if "document_ref" in item:
            _require_refs(
                [item["document_ref"]],
                documents,
                code=INVALID_CASE_RESULT,
                path=f"$.evidence[{index}].document_ref",
            )
        if "provision_ref" in item:
            _require_refs(
                [item["provision_ref"]],
                provisions,
                code=INVALID_CASE_RESULT,
                path=f"$.evidence[{index}].provision_ref",
            )
    for index, item in enumerate(result["provisions"]):
        _require_refs(
            [item["document_ref"]],
            documents,
            code=INVALID_CASE_RESULT,
            path=f"$.provisions[{index}].document_ref",
        )


def validate_result_preserves_draft(
    draft: dict[str, Any],
    result: dict[str, Any],
) -> None:
    for name in ("facts", "questions", "model_metadata"):
        if result[name] != draft[name]:
            _fail(
                INVALID_CASE_RESULT,
                f"$.{name}",
                "CaseResult does not preserve the accepted CaseDraft field-for-field",
            )


def case_draft_response_schema() -> dict[str, Any]:
    """Return the model-facing CaseDraft schema without app-owned run metadata."""
    root = load_contract_schema()
    definitions = deepcopy(root["$defs"])
    draft = definitions["CaseDraft"]
    app_owned_fields = {
        "problem_text",
        "as_of_date",
        "client_reference",
        "model_metadata",
    }
    draft["required"] = [
        name for name in draft["required"] if name not in app_owned_fields
    ]
    for name in app_owned_fields:
        draft["properties"].pop(name, None)

    # llama.cpp constrained generation does not reliably enforce JSON-Schema
    # conditional if/then branches. Preserve the authoritative CaseFact
    # semantics while expressing them to the model as explicit oneOf variants.
    fact = definitions["CaseFact"]
    fact_properties = deepcopy(fact["properties"])
    fact_required = list(fact["required"])

    def fact_variant(
        state: str,
        *,
        requires_confirmation: bool,
        additional_required: list[str] | None = None,
    ) -> dict[str, Any]:
        properties = deepcopy(fact_properties)
        properties["state"] = {"const": state}
        properties["requires_confirmation"] = {"const": requires_confirmation}
        required = list(fact_required)
        for name in additional_required or []:
            if name not in required:
                required.append(name)
        return {
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
        }

    definitions["CaseFact"] = {
        "oneOf": [
            fact_variant(
                "user_provided",
                requires_confirmation=False,
                additional_required=["source_quote"],
            ),
            fact_variant("llm_normalized", requires_confirmation=True),
            fact_variant("llm_inferred", requires_confirmation=True),
            fact_variant(
                "missing",
                requires_confirmation=True,
                additional_required=["needed_information"],
            ),
            fact_variant(
                "ambiguous",
                requires_confirmation=True,
                additional_required=["needed_information"],
            ),
        ]
    }
    return {
        "$schema": root["$schema"],
        "$defs": definitions,
        "$ref": "#/$defs/CaseDraft",
    }
