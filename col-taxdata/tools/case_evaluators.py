from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable

from case_contract_validation_v4 import CONTRACT_VERSION, validate_contract_object


EVALUATOR_ID = "colombia.natural_person.non_filer_thresholds"
EVALUATOR_VERSION = "1"
CALCULATOR_ID = EVALUATOR_ID + ".threshold_margin"
CALCULATOR_VERSION = "1"
SUPPORTED_RULE_TYPE = "canonical_source_statement"
SUPPORTED_RULE_SCHEMA_VERSION = "1"

GROSS_INCOME_KEY = "col.tax.natural_person.gross_income"
GROSS_PATRIMONY_KEY = "col.tax.natural_person.gross_patrimony"
_REQUIRED_FACT_KEYS = (GROSS_INCOME_KEY, GROSS_PATRIMONY_KEY)

# This evaluator deliberately recognizes only narrow, extractive threshold language.
# Broader legal interpretation remains outside canonical deterministic state.
_THRESHOLD_PATTERNS: dict[str, re.Pattern[str]] = {
    GROSS_INCOME_KEY: re.compile(
        r"ingresos\s+brutos.{0,220}?"
        r"(?P<operator>inferiores?\s+a|no\s+excedan?(?:\s+de)?|"
        r"no\s+sean?\s+superiores?\s+a)\s+"
        r"(?P<value>[0-9]{1,3}(?:[.\s][0-9]{3})*|[0-9]+)\s*UVT\b",
        re.IGNORECASE | re.DOTALL,
    ),
    GROSS_PATRIMONY_KEY: re.compile(
        r"patrimonio\s+bruto.{0,220}?"
        r"(?P<operator>inferior\s+a|no\s+exceda(?:\s+de)?|"
        r"no\s+sea\s+superior\s+a)\s+"
        r"(?P<value>[0-9]{1,3}(?:[.\s][0-9]{3})*|[0-9]+)\s*UVT\b",
        re.IGNORECASE | re.DOTALL,
    ),
}

_FACT_QUOTE_TERMS = {
    GROSS_INCOME_KEY: ("ingresos", "brutos"),
    GROSS_PATRIMONY_KEY: ("patrimonio", "bruto"),
}


@dataclass(frozen=True)
class EvaluationOutcome:
    """Read-only deterministic output to add to a LegalResearchBundle."""

    evaluations: tuple[dict[str, Any], ...]
    calculations: tuple[dict[str, Any], ...]
    unresolved: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ThresholdCondition:
    semantic_key: str
    operator: str
    threshold: Decimal


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_ref(namespace: str, *parts: object) -> str:
    digest = hashlib.sha256(_json(parts).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest[:32]}"


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold()


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite decimals are not supported")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -int(exponent))


def _parse_grouped_integer(token: str) -> Decimal:
    raw = token.replace(" ", "").replace(".", "")
    if not raw.isdigit():
        raise ValueError(f"unsupported UVT threshold token {token!r}")
    return Decimal(raw)


def _operator_code(text: str) -> str:
    folded = _fold(text)
    if "inferior" in folded:
        return "lt"
    if "exced" in folded or "superior" in folded:
        return "lte"
    raise ValueError(f"unsupported threshold operator {text!r}")


def _numeric_values_in_quote(quote: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for token in re.findall(
        r"(?<![A-Za-z0-9])(?:[0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]+(?:[.,][0-9]+)?)(?![A-Za-z0-9])",
        quote,
    ):
        compact = token.replace(" ", "")
        try:
            if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", compact):
                values.add(Decimal(compact.replace(".", "")))
            elif "," in compact and "." not in compact:
                values.add(Decimal(compact.replace(",", ".")))
            else:
                values.add(Decimal(compact))
        except InvalidOperation:
            continue
    return values


def _threshold_conditions(
    *,
    rule: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> tuple[ThresholdCondition, ...] | None:
    if (
        rule.get("rule_type") != SUPPORTED_RULE_TYPE
        or rule.get("rule_schema_version") != SUPPORTED_RULE_SCHEMA_VERSION
        or rule.get("derivation")
        != {"method": "extractive_normalization", "version": "1"}
    ):
        return None

    evidence_refs = rule.get("evidence_refs", [])
    if not evidence_refs:
        return None

    exact_parts: list[str] = []
    for evidence_ref in evidence_refs:
        span = evidence.get(evidence_ref)
        if span is None:
            return None
        exact_text = span["exact_text"]
        if _text_sha(exact_text) != span["text_sha256"]:
            raise ValueError(
                f"evidence text fingerprint mismatch for {evidence_ref}"
            )
        exact_parts.append(exact_text)

    exact_text = "\n".join(exact_parts)
    conditions: list[ThresholdCondition] = []
    for semantic_key in _REQUIRED_FACT_KEYS:
        matches = list(_THRESHOLD_PATTERNS[semantic_key].finditer(exact_text))
        if len(matches) != 1:
            return None
        match = matches[0]
        conditions.append(
            ThresholdCondition(
                semantic_key=semantic_key,
                operator=_operator_code(match.group("operator")),
                threshold=_parse_grouped_integer(match.group("value")),
            )
        )
    return tuple(conditions)


def _unresolved(
    *,
    category: str,
    description: str,
    next_action: str,
    fact_refs: Iterable[str] = (),
    question_refs: Iterable[str] = (),
    authority_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    rule_refs: Iterable[str] = (),
    needed_information: str | None = None,
) -> dict[str, Any]:
    payload = {
        "category": category,
        "description": description,
        "next_action": next_action,
        "fact_refs": sorted(set(fact_refs)),
        "question_refs": sorted(set(question_refs)),
        "authority_refs": sorted(set(authority_refs)),
        "evidence_refs": sorted(set(evidence_refs)),
        "rule_refs": sorted(set(rule_refs)),
        "needed_information": needed_information,
    }
    item: dict[str, Any] = {
        "kind": "unresolved_item",
        "contract_version": CONTRACT_VERSION,
        "unresolved_ref": _stable_ref("unresolved", "evaluation", payload),
        "stage": "evaluation",
        "category": category,
        "description": description,
        "next_action": next_action,
    }
    if payload["fact_refs"]:
        item["related_fact_refs"] = payload["fact_refs"]
    if payload["question_refs"]:
        item["related_question_refs"] = payload["question_refs"]
    if payload["authority_refs"]:
        item["related_authority_refs"] = payload["authority_refs"]
    if payload["evidence_refs"]:
        item["related_evidence_refs"] = payload["evidence_refs"]
    if payload["rule_refs"]:
        item["related_rule_refs"] = payload["rule_refs"]
    if needed_information:
        item["needed_information"] = needed_information
    validate_contract_object(item)
    return item


def _related_questions(
    questions: Iterable[dict[str, Any]],
    fact_refs: Iterable[str],
) -> list[str]:
    required = set(fact_refs)
    return sorted(
        question["question_ref"]
        for question in questions
        if question["status"] == "open"
        and required
        and required.issubset(set(question.get("depends_on_fact_refs", [])))
    )


def _fact_measurement(
    fact: dict[str, Any],
    *,
    semantic_key: str,
) -> tuple[Decimal, int] | None:
    if (
        fact.get("semantic_key") != semantic_key
        or fact.get("state") != "user_provided"
        or fact.get("requires_confirmation") is not False
    ):
        return None
    measurement = fact.get("measurement")
    if not isinstance(measurement, dict):
        return None
    if measurement.get("unit") != "UVT":
        return None
    uvt_year = measurement.get("uvt_year")
    if not isinstance(uvt_year, int):
        return None
    try:
        decimal_value = Decimal(measurement["decimal_value"])
    except (InvalidOperation, KeyError):
        return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None

    # A model may structure facts, but it cannot invent a canonical calculation
    # input. The amount and fact topic must be verifiable from the exact caller
    # text preserved by the intake-fidelity boundary.
    quote = fact.get("source_quote")
    if not isinstance(quote, str):
        return None
    folded_quote = _fold(quote)
    if not all(term in folded_quote for term in _FACT_QUOTE_TERMS[semantic_key]):
        return None
    if decimal_value not in _numeric_values_in_quote(quote):
        return None
    return decimal_value, uvt_year


def _condition_passes(
    observed: Decimal,
    condition: ThresholdCondition,
) -> bool:
    if condition.operator == "lt":
        return observed < condition.threshold
    if condition.operator == "lte":
        return observed <= condition.threshold
    raise ValueError(f"unsupported operator {condition.operator!r}")


def _calculation(
    *,
    fact: dict[str, Any],
    rule: dict[str, Any],
    evidence_refs: list[str],
    condition: ThresholdCondition,
    observed: Decimal,
    uvt_year: int,
    generated_at: str,
) -> dict[str, Any]:
    margin = condition.threshold - observed
    unit = f"UVT@{uvt_year}"
    inputs = [
        {
            "name": "observed",
            "decimal_value": _decimal_text(observed),
            "unit": unit,
            "source_fact_ref": fact["fact_ref"],
        },
        {
            "name": "threshold",
            "decimal_value": _decimal_text(condition.threshold),
            "unit": unit,
            "source_rule_ref": rule["rule_ref"],
        },
    ]
    calculation: dict[str, Any] = {
        "kind": "calculation_trace",
        "contract_version": CONTRACT_VERSION,
        "calculation_ref": _stable_ref(
            "calculation",
            CALCULATOR_ID,
            CALCULATOR_VERSION,
            condition.semantic_key,
            condition.operator,
            inputs,
        ),
        "calculator_id": CALCULATOR_ID,
        "calculator_version": CALCULATOR_VERSION,
        "inputs": inputs,
        "formula": "threshold - observed",
        "formula_language": "decimal-arithmetic/v1",
        "steps": [
            {
                "label": "threshold_margin",
                "expression": "threshold - observed",
                "result_decimal": _decimal_text(margin),
                "unit": unit,
            }
        ],
        "result": {
            "decimal_value": _decimal_text(margin),
            "unit": unit,
        },
        "rounding": {
            "mode": "NONE",
            "scale": max(
                _decimal_places(observed),
                _decimal_places(condition.threshold),
            ),
        },
        "rule_refs": [rule["rule_ref"]],
        "evidence_refs": evidence_refs,
        "generated_at": generated_at,
    }
    validate_contract_object(calculation)
    return calculation


def _blocked_evaluation(
    *,
    rule_refs: list[str],
    evidence_refs: list[str],
    fact_refs: list[str],
    question_refs: list[str],
    unresolved_refs: list[str],
    as_of_date: str | None,
    generated_at: str,
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {
        "kind": "deterministic_evaluation",
        "contract_version": CONTRACT_VERSION,
        "evaluation_ref": _stable_ref(
            "evaluation",
            EVALUATOR_ID,
            EVALUATOR_VERSION,
            "blocked",
            rule_refs,
            evidence_refs,
            fact_refs,
            question_refs,
            unresolved_refs,
            as_of_date,
        ),
        "evaluator_id": EVALUATOR_ID,
        "evaluator_version": EVALUATOR_VERSION,
        "status": "blocked",
        "question_refs": question_refs,
        "fact_refs": fact_refs,
        "rule_refs": rule_refs,
        "evidence_refs": evidence_refs,
        "calculation_trace_refs": [],
        "unresolved_refs": unresolved_refs,
        "generated_at": generated_at,
    }
    if as_of_date is not None:
        evaluation["as_of_date"] = as_of_date
    validate_contract_object(evaluation)
    return evaluation


def evaluate_supported_rules(
    *,
    case_input: dict[str, Any],
    intake_draft: dict[str, Any],
    authorities: Iterable[dict[str, Any]],
    evidence_spans: Iterable[dict[str, Any]],
    rule_fragments: Iterable[dict[str, Any]],
    generated_at: str,
) -> EvaluationOutcome:
    """Run only explicitly registered deterministic evaluators.

    The representative evaluator handles a narrow Colombian natural-person
    threshold-condition family. It never turns the result into a universal
    filing conclusion and never falls back to an LLM.
    """
    authority_by_ref = {
        item["authority_ref"]: item for item in authorities
    }
    evidence_by_ref = {
        item["evidence_ref"]: item for item in evidence_spans
    }
    rules = list(rule_fragments)
    facts = list(intake_draft["facts"])
    questions = list(intake_draft["questions"])

    parsed: list[tuple[dict[str, Any], tuple[ThresholdCondition, ...]]] = []
    for rule in rules:
        conditions = _threshold_conditions(rule=rule, evidence=evidence_by_ref)
        if conditions is not None:
            parsed.append((rule, conditions))

    produced_unresolved: dict[str, dict[str, Any]] = {}
    evaluations: list[dict[str, Any]] = []
    calculations: list[dict[str, Any]] = []
    handled_questions: set[str] = set()

    if len(parsed) > 1:
        rule_refs = sorted(rule["rule_ref"] for rule, _ in parsed)
        evidence_refs = sorted(
            {
                ref
                for rule, _ in parsed
                for ref in rule["evidence_refs"]
            }
        )
        authority_refs = sorted(
            {
                ref
                for rule, _ in parsed
                for ref in rule["authority_refs"]
            }
        )
        item = _unresolved(
            category="conflicting_authority",
            description=(
                "More than one independently supported filing-threshold rule "
                "matches the bounded evaluator; applicability cannot be selected "
                "deterministically."
            ),
            next_action="external_interpretive_synthesis",
            authority_refs=authority_refs,
            evidence_refs=evidence_refs,
            rule_refs=rule_refs,
        )
        produced_unresolved[item["unresolved_ref"]] = item
        evaluations.append(
            _blocked_evaluation(
                rule_refs=rule_refs,
                evidence_refs=evidence_refs,
                fact_refs=[],
                question_refs=[],
                unresolved_refs=[item["unresolved_ref"]],
                as_of_date=case_input.get("as_of_date"),
                generated_at=generated_at,
            )
        )

    elif len(parsed) == 1:
        rule, conditions = parsed[0]
        rule_refs = [rule["rule_ref"]]
        evidence_refs = sorted(rule["evidence_refs"])
        authority_refs = sorted(rule["authority_refs"])
        as_of_date = case_input.get("as_of_date")

        temporal_ok = (
            as_of_date is not None
            and rule.get("as_of_date") == as_of_date
            and all(
                authority_by_ref.get(ref, {})
                .get("temporal_state", {})
                .get("resolution_state") == "resolved"
                and authority_by_ref[ref]["temporal_state"].get("effective")
                is True
                for ref in authority_refs
            )
        )
        if not temporal_ok:
            item = _unresolved(
                category="temporal_uncertainty",
                description=(
                    "The filing-threshold rule cannot be evaluated because its "
                    "as-of temporal/legal applicability is not resolved and effective."
                ),
                next_action="human_review",
                authority_refs=authority_refs,
                evidence_refs=evidence_refs,
                rule_refs=rule_refs,
            )
            produced_unresolved[item["unresolved_ref"]] = item
            evaluations.append(
                _blocked_evaluation(
                    rule_refs=rule_refs,
                    evidence_refs=evidence_refs,
                    fact_refs=[],
                    question_refs=[],
                    unresolved_refs=[item["unresolved_ref"]],
                    as_of_date=as_of_date,
                    generated_at=generated_at,
                )
            )
        else:
            facts_by_key: dict[str, list[dict[str, Any]]] = {}
            for fact in facts:
                semantic_key = fact.get("semantic_key")
                if isinstance(semantic_key, str):
                    facts_by_key.setdefault(semantic_key, []).append(fact)

            selected: dict[str, tuple[dict[str, Any], Decimal, int]] = {}
            blocking_refs: list[str] = []
            related_fact_refs: list[str] = []
            for semantic_key in _REQUIRED_FACT_KEYS:
                candidates = facts_by_key.get(semantic_key, [])
                related_fact_refs.extend(
                    fact["fact_ref"] for fact in candidates
                )
                if len(candidates) != 1:
                    category = (
                        "missing_fact" if not candidates else "ambiguous_fact"
                    )
                    item = _unresolved(
                        category=category,
                        description=(
                            f"The deterministic evaluator requires exactly one "
                            f"confirmed {semantic_key} fact."
                        ),
                        next_action="ask_client",
                        fact_refs=[
                            fact["fact_ref"] for fact in candidates
                        ],
                        rule_refs=rule_refs,
                        evidence_refs=evidence_refs,
                        needed_information=(
                            f"Provide one explicit {semantic_key} amount in UVT "
                            "with its UVT year."
                        ),
                    )
                    produced_unresolved[item["unresolved_ref"]] = item
                    blocking_refs.append(item["unresolved_ref"])
                    continue

                fact = candidates[0]
                measured = _fact_measurement(
                    fact,
                    semantic_key=semantic_key,
                )
                if measured is None:
                    item = _unresolved(
                        category=(
                            "ambiguous_fact"
                            if fact.get("state") == "ambiguous"
                            else "missing_fact"
                        ),
                        description=(
                            f"Fact {fact['fact_ref']} is not a confirmed, "
                            "source-verifiable UVT measurement usable by the "
                            "deterministic evaluator."
                        ),
                        next_action="ask_client",
                        fact_refs=[fact["fact_ref"]],
                        rule_refs=rule_refs,
                        evidence_refs=evidence_refs,
                        needed_information=(
                            f"Confirm {semantic_key} as an explicit UVT amount "
                            "and UVT year in the case text."
                        ),
                    )
                    produced_unresolved[item["unresolved_ref"]] = item
                    blocking_refs.append(item["unresolved_ref"])
                    continue
                selected[semantic_key] = (fact, measured[0], measured[1])

            fact_refs = sorted(set(related_fact_refs))
            question_refs = _related_questions(questions, fact_refs)
            handled_questions.update(question_refs)

            if len(selected) == len(_REQUIRED_FACT_KEYS):
                uvt_years = {
                    item[2] for item in selected.values()
                }
                if len(uvt_years) != 1:
                    item = _unresolved(
                        category="ambiguous_fact",
                        description=(
                            "The confirmed threshold facts use different UVT years; "
                            "the evaluator will not compare mixed UVT-year semantics."
                        ),
                        next_action="ask_client",
                        fact_refs=fact_refs,
                        question_refs=question_refs,
                        rule_refs=rule_refs,
                        evidence_refs=evidence_refs,
                        needed_information=(
                            "Provide gross income and gross patrimony using the same "
                            "explicit UVT year."
                        ),
                    )
                    produced_unresolved[item["unresolved_ref"]] = item
                    blocking_refs.append(item["unresolved_ref"])

            if blocking_refs:
                evaluations.append(
                    _blocked_evaluation(
                        rule_refs=rule_refs,
                        evidence_refs=evidence_refs,
                        fact_refs=fact_refs,
                        question_refs=question_refs,
                        unresolved_refs=sorted(blocking_refs),
                        as_of_date=as_of_date,
                        generated_at=generated_at,
                    )
                )
            else:
                condition_by_key = {
                    condition.semantic_key: condition
                    for condition in conditions
                }
                condition_results: list[bool] = []
                calc_refs: list[str] = []
                for semantic_key in _REQUIRED_FACT_KEYS:
                    fact, observed, uvt_year = selected[semantic_key]
                    condition = condition_by_key[semantic_key]
                    trace = _calculation(
                        fact=fact,
                        rule=rule,
                        evidence_refs=evidence_refs,
                        condition=condition,
                        observed=observed,
                        uvt_year=uvt_year,
                        generated_at=generated_at,
                    )
                    calculations.append(trace)
                    calc_refs.append(trace["calculation_ref"])
                    condition_results.append(
                        _condition_passes(observed, condition)
                    )

                result = {
                    "code": "non_filer_threshold_conditions_met",
                    "value": all(condition_results),
                }
                evaluation: dict[str, Any] = {
                    "kind": "deterministic_evaluation",
                    "contract_version": CONTRACT_VERSION,
                    "evaluation_ref": _stable_ref(
                        "evaluation",
                        EVALUATOR_ID,
                        EVALUATOR_VERSION,
                        sorted(fact_refs),
                        rule_refs,
                        evidence_refs,
                        sorted(calc_refs),
                        as_of_date,
                        result,
                    ),
                    "evaluator_id": EVALUATOR_ID,
                    "evaluator_version": EVALUATOR_VERSION,
                    "status": "determined",
                    "question_refs": question_refs,
                    "fact_refs": fact_refs,
                    "rule_refs": rule_refs,
                    "evidence_refs": evidence_refs,
                    "calculation_trace_refs": sorted(calc_refs),
                    "unresolved_refs": [],
                    "as_of_date": as_of_date,
                    "result": result,
                    "generated_at": generated_at,
                }
                validate_contract_object(evaluation)
                evaluations.append(evaluation)

    evaluated_question_refs = {
        ref
        for evaluation in evaluations
        if evaluation["status"] == "determined"
        for ref in evaluation["question_refs"]
    }
    handled_questions.update(evaluated_question_refs)

    # Questions that have no explicit evaluator mapping remain research material.
    # Their prose is not inspected to guess a legal outcome.
    for question in questions:
        if (
            question["status"] != "open"
            or question["question_ref"] in handled_questions
        ):
            continue
        item = _unresolved(
            category="requires_interpretive_synthesis",
            description=(
                "No explicit deterministic evaluator owns this open question; "
                "canonical evidence remains available for external synthesis."
            ),
            next_action="external_interpretive_synthesis",
            question_refs=[question["question_ref"]],
        )
        produced_unresolved[item["unresolved_ref"]] = item

    evaluations.sort(key=lambda item: item["evaluation_ref"])
    calculations.sort(key=lambda item: item["calculation_ref"])
    unresolved_items = sorted(
        produced_unresolved.values(),
        key=lambda item: item["unresolved_ref"],
    )
    return EvaluationOutcome(
        evaluations=tuple(evaluations),
        calculations=tuple(calculations),
        unresolved=tuple(unresolved_items),
    )
