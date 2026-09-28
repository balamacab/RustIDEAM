from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Callable

from case_contract_validation import (
    CaseContractError,
    _assertive_client_spans,
    _fold_lexical_text,
    _missing_fact_conflicts_with_explicit_text,
    _topic_signature,
    load_contract_schema,
    source_quote_candidates,
    validate_schema_object,
)


CONTRACT_VERSION = "4.0.0"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "application"
    / "schemas"
    / "case-contracts-v4.schema.json"
)

INVALID_CASE_INPUT = "INVALID_CASE_INPUT"
INVALID_INTAKE_DRAFT = "INVALID_INTAKE_DRAFT"
INVALID_RESEARCH_PLAN = "INVALID_RESEARCH_PLAN"
INVALID_RESEARCH_RESULT = "INVALID_RESEARCH_RESULT"
INVALID_LEGAL_RESEARCH_BUNDLE = "INVALID_LEGAL_RESEARCH_BUNDLE"

# SearchHint is model-owned vocabulary. Typed application references are not
# vocabulary and would let model output select platform-owned identities.
_TYPED_REF_IN_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9._-])"
    r"(?:intake|fact|question|hint|plan|task|research|trace|authority|source|"
    r"document|provision|evidence|span|relationship|rule|evaluation|calculation|"
    r"unresolved|provenance|bundle):[A-Za-z0-9._-]+"
    r"(?:$|[^A-Za-z0-9._-])"
)

# Intake refs (fact/question/hint/intake) are legitimate model-owned graph keys.
# Platform-owned namespaces are not legitimate content in model-authored labels,
# normalized values, questions, or search vocabulary.
_PLATFORM_REF_IN_MODEL_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9._-])"
    r"(?:plan|task|research|trace|authority|source|document|provision|evidence|"
    r"span|relationship|rule|evaluation|calculation|unresolved|provenance|bundle)"
    r":[A-Za-z0-9._-]+(?:$|[^A-Za-z0-9._-])"
)

# v4 intake needs exact quotes narrow enough to support one stated fact without
# weakening downstream provenance checks.  Paragraphs remain available for facts
# whose meaning spans multiple clauses; the additional fragments are exact
# contiguous substrings and therefore never synthesize client text.
_INTAKE_QUOTE_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+|\s+y\s+")
_UVT_MEASUREMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:[0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]+(?:[.,][0-9]+)?)"
    r"\s*UVT\b",
    re.IGNORECASE,
)

# A declarative span that explicitly advertises uncertainty must not be treated
# as proof that the client supplied one unambiguous factual value.
_CLIENT_AMBIGUITY_PATTERNS = (
    " o ",
    "aproximad",
    "posiblemente",
    "tal vez",
    "no queda claro",
    "no esta claro",
    "no se sabe",
    "dudoso",
)

# #210 is a deliberately bounded exception to the general no-post-response-
# repair rule: only an already model-selected unresolved fact may be promoted,
# and only when one supported lexical fact family resolves to one exact,
# unambiguous client-owned span.  These are the two semantic keys already
# consumed by the existing bounded natural-person evaluator; no new evaluator
# vocabulary is introduced here.
_GROSS_INCOME_SEMANTIC_KEY = "col.tax.natural_person.gross_income"
_GROSS_PATRIMONY_SEMANTIC_KEY = "col.tax.natural_person.gross_patrimony"
_SUPPORTED_UVT_FAMILIES = {
    "gross_income_uvt": _GROSS_INCOME_SEMANTIC_KEY,
    "gross_patrimony_uvt": _GROSS_PATRIMONY_SEMANTIC_KEY,
}
_SUPPORTED_UVT_SEMANTIC_KEYS = frozenset(_SUPPORTED_UVT_FAMILIES.values())
_EXPLICIT_YEAR_RE = re.compile(r"\b(?:19|20)[0-9]{2}\b")

_CONFIRMATION_PREFIXES = (
    "confirmacion de que ",
    "confirmar que ",
    "confirmar ",
)

# These are instruction/meta words, not the factual content of a confirmation
# request.  Values are the same shallow stems produced by _topic_signature.
_CONFIRMATION_META_STEMS = frozenset(
    {
        "aclar",
        "confi",
        "dato",
        "deter",
        "hecho",
        "indic",
        "infor",
        "neces",
        "preci",
        "valid",
        "verif",
    }
)

_TAX_LEGAL_TOPIC_RE = re.compile(
    r"\b(?:iva|impuesto(?:s)?|tributari[oa]s?|retenci[oó]n|renta|"
    r"exportaci[oó]n\s+de\s+servicios|doble\s+imposici[oó]n|convenio|"
    r"establecimiento\s+permanente)\b",
    re.IGNORECASE,
)
_LEGAL_TREATMENT_RE = re.compile(
    r"(?:c[oó]mo\s+debe\s+analizar|tratar(?:se)?\s+como|"
    r"para\s+efectos\s+del?|si\s+procede|qu[eé]\s+efecto\s+puede\s+tener|"
    r"est[aá]\s+(?:gravado|exento|sujeto)|"
    r"debe\s+(?:pagar|declarar|retener|facturar|liquidar)|"
    r"qu[eé]\s+tarifa\b)",
    re.IGNORECASE,
)
_PURE_TEMPORAL_QUESTION_RE = re.compile(
    r"^\s*[¿(0-9).\s]*(?:desde\s+cu[aá]ndo|hasta\s+cu[aá]ndo|cu[aá]ndo|"
    r"en\s+qu[eé]\s+fecha|a\s+partir\s+de\s+qu[eé]\s+fecha|"
    r"qu[eé]\s+plazo)\b",
    re.IGNORECASE,
)

_FINGERPRINT_OPTIONAL_FIELDS = frozenset(
    {
        "corpus_snapshot_sha256",
        "schema_migration_fingerprint",
        "retrieval_config_sha256",
        "as_of_date",
    }
)

_KIND_TO_DEFINITION = {
    "case_input": "CaseInput",
    "intake_fact": "IntakeFact",
    "case_question": "CaseQuestion",
    "search_hint": "SearchHint",
    "intake_draft": "IntakeDraft",
    "research_task": "ResearchTask",
    "research_plan": "ResearchPlan",
    "research_trace_step": "ResearchTraceStep",
    "research_result": "ResearchResult",
    "official_source": "OfficialSource",
    "canonical_authority": "CanonicalAuthority",
    "evidence_span": "EvidenceSpan",
    "normative_relationship": "NormativeRelationship",
    "rule_fragment": "RuleFragment",
    "deterministic_evaluation": "DeterministicEvaluation",
    "calculation_trace": "CalculationTrace",
    "unresolved_item": "UnresolvedItem",
    "legal_research_bundle": "LegalResearchBundle",
}

# #138 owns the first concrete RuleFragment schemas. The registry intentionally
# starts empty so unknown rule families cannot pass semantic validation merely
# because their generic transport envelope is structurally valid.
_RULE_FRAGMENT_VALIDATORS: dict[
    tuple[str, str],
    Callable[[dict[str, Any]], None],
] = {}


_RULE_REF_RE = re.compile(r"^(?:authority|document|provision|evidence):[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


def _rule_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    if not isinstance(value, dict):
        raise ValueError("structured rule data must be an object")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ValueError("missing structured rule field(s): " + ", ".join(missing))
    if extra:
        raise ValueError("unsupported structured rule field(s): " + ", ".join(extra))


def _rule_ref(value: object, namespace: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(namespace + ":")
        or _RULE_REF_RE.fullmatch(value) is None
    ):
        raise ValueError(f"expected valid {namespace}: typed reference")
    return value


def _rule_refs(value: object, namespace: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{namespace} refs must be a non-empty array")
    if len(value) != len(set(value)):
        raise ValueError(f"{namespace} refs must be unique")
    return [_rule_ref(item, namespace) for item in value]


def _validate_canonical_source_statement(fragment: dict[str, Any]) -> None:
    data = fragment["structured_data"]
    _rule_keys(
        data,
        required={
            "statement_scope",
            "document_ref",
            "authority_ref",
            "evidence_refs",
            "provision_ref",
            "provision_type",
            "designation",
        },
    )
    if data["statement_scope"] != "canonical_provision":
        raise ValueError(
            "canonical_source_statement v1 is restricted to canonical provisions"
        )
    _rule_ref(data["document_ref"], "document")
    authority_ref = _rule_ref(data["authority_ref"], "authority")
    evidence_refs = _rule_refs(data["evidence_refs"], "evidence")
    _rule_ref(data["provision_ref"], "provision")
    if not isinstance(data["provision_type"], str) or not data["provision_type"]:
        raise ValueError("provision_type must be non-empty")
    if not isinstance(data["designation"], str) or not data["designation"]:
        raise ValueError("designation must be non-empty")

    if fragment["derivation"] != {
        "method": "extractive_normalization",
        "version": "1",
    }:
        raise ValueError(
            "canonical_source_statement requires extractive_normalization v1"
        )
    if fragment["authority_refs"] != [authority_ref]:
        raise ValueError(
            "canonical_source_statement authority_refs must match structured data"
        )
    if fragment["evidence_refs"] != evidence_refs:
        raise ValueError(
            "canonical_source_statement evidence_refs must match structured data"
        )
    if fragment.get("relationship_refs"):
        raise ValueError(
            "canonical_source_statement does not accept relationship refs"
        )


def _reference_member(value: object) -> tuple[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("reference member must be an object")
    _rule_keys(
        value,
        required={"provision_ref", "authority_ref", "evidence_refs"},
    )
    _rule_ref(value["provision_ref"], "provision")
    authority_ref = _rule_ref(value["authority_ref"], "authority")
    evidence_refs = _rule_refs(value["evidence_refs"], "evidence")
    return authority_ref, evidence_refs


def _validate_resolved_provision_reference(fragment: dict[str, Any]) -> None:
    data = fragment["structured_data"]
    _rule_keys(
        data,
        required={
            "source",
            "target",
            "resolution_method",
            "resolution_fingerprint_sha256",
        },
    )
    source_authority, source_evidence = _reference_member(data["source"])
    target_authority, target_evidence = _reference_member(data["target"])
    if not isinstance(data["resolution_method"], str) or not data["resolution_method"]:
        raise ValueError("resolution_method must be non-empty")
    fingerprint = data["resolution_fingerprint_sha256"]
    if (
        not isinstance(fingerprint, str)
        or _SHA256_RE.fullmatch(fingerprint) is None
    ):
        raise ValueError("resolution_fingerprint_sha256 must be SHA-256")

    if fragment["authority_refs"] != sorted(
        {source_authority, target_authority}
    ):
        raise ValueError(
            "resolved_provision_reference authority_refs do not match members"
        )
    if fragment["evidence_refs"] != sorted(
        set(source_evidence) | set(target_evidence)
    ):
        raise ValueError(
            "resolved_provision_reference must preserve all member evidence"
        )
    if fragment["derivation"] != {
        "method": "deterministic_composition",
        "version": "1",
    }:
        raise ValueError(
            "resolved_provision_reference requires deterministic_composition v1"
        )
    if fragment.get("relationship_refs"):
        raise ValueError(
            "resolved provision reference is not a NormativeRelationship"
        )


_RULE_FRAGMENT_VALIDATORS.update(
    {
        ("canonical_source_statement", "1"): _validate_canonical_source_statement,
        ("resolved_provision_reference", "1"): _validate_resolved_provision_reference,
    }
)


def _fail(code: str, path: str, detail: str) -> None:
    raise CaseContractError(code, f"{path}: {detail}")


def _validate_schema(
    value: dict[str, Any],
    definition: str,
    code: str,
) -> None:
    validate_schema_object(
        value,
        definition,
        code,
        schema_path=SCHEMA_PATH,
    )


def validate_contract_object(value: dict[str, Any]) -> None:
    """Validate the serialized shape of one named v4 contract primitive."""
    if not isinstance(value, dict):
        _fail(INVALID_LEGAL_RESEARCH_BUNDLE, "$", "expected object")
    if value.get("contract_version") != CONTRACT_VERSION:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$.contract_version",
            f"expected {CONTRACT_VERSION!r}",
        )
    kind = value.get("kind")
    definition = _KIND_TO_DEFINITION.get(kind)
    if definition is None:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$.kind",
            f"unsupported v4 contract kind {kind!r}",
        )
    _validate_schema(value, definition, INVALID_LEGAL_RESEARCH_BUNDLE)


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


def _singleton_registry(
    item: dict[str, Any],
    key: str,
) -> dict[str, dict[str, Any]]:
    return {item[key]: item}


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


def _require_optional_field_preserved(
    source: dict[str, Any],
    target: dict[str, Any],
    name: str,
    *,
    code: str,
) -> None:
    source_has = name in source
    target_has = name in target
    if source_has != target_has:
        _fail(
            code,
            f"$.{name}",
            "client field presence/absence was not preserved",
        )
    if source_has and target[name] != source[name]:
        _fail(code, f"$.{name}", "client field value was modified")


def validate_case_input(case_input: dict[str, Any]) -> None:
    """Validate a v4 caller-owned CaseInput."""
    _validate_schema(case_input, "CaseInput", INVALID_CASE_INPUT)


def _intake_source_quote_candidates(problem_text: str) -> list[str]:
    """Return bounded exact quote choices from fact-sized to coarse spans.

    v3 intentionally keeps its historical paragraph-only quote vocabulary.
    v4 adds exact sentence/clause fragments so one stated fact can retain a
    source quote without dragging unrelated measurements into the same quote.
    Every returned value is still a literal contiguous substring.
    """
    paragraphs = source_quote_candidates(problem_text)
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if value and value in problem_text and value not in seen:
            candidates.append(value)
            seen.add(value)

    for paragraph in paragraphs:
        # Preserve the historical paragraph-only generation vocabulary unless
        # one quote would contain multiple UVT measurements.  Only that case
        # needs finer exact spans so the existing bounded evaluator can retain
        # its one-measurement-per-quote provenance invariant.
        if len(_UVT_MEASUREMENT_RE.findall(paragraph)) >= 2:
            fragments = [
                fragment
                for fragment in _INTAKE_QUOTE_BOUNDARY.split(paragraph)
                if fragment.strip()
            ]
            for fragment in fragments:
                add(fragment)
        add(paragraph)

    if not candidates and problem_text:
        add(problem_text)
    return candidates


def _unambiguous_assertive_spans(problem_text: str) -> list[str]:
    result: list[str] = []
    for span in _assertive_client_spans(problem_text):
        folded = f" {_fold_lexical_text(span)} "
        if any(marker in folded for marker in _CLIENT_AMBIGUITY_PATTERNS):
            continue
        result.append(span)
    return result


def _normalization_source_spans(problem_text: str) -> list[str]:
    """Return bounded exact client spans eligible for #210 normalization.

    The normalizer deliberately works from declarative client-owned sentences,
    not model-authored paraphrases.  A sentence carrying multiple UVT amounts
    is split only at the existing exact clause boundary so each numeric fact
    can retain one-measurement provenance.  Duplicate text remains visible to
    the uniqueness check and is never guessed by occurrence.
    """
    spans: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = value.strip()
        if (
            candidate
            and candidate in problem_text
            and candidate not in seen
        ):
            spans.append(candidate)
            seen.add(candidate)

    for sentence in _assertive_client_spans(problem_text):
        if len(_UVT_MEASUREMENT_RE.findall(sentence)) >= 2:
            for fragment in _INTAKE_QUOTE_BOUNDARY.split(sentence):
                add(fragment)
        else:
            add(sentence)
    return spans


def _descriptor_family(fact: dict[str, Any]) -> str | None:
    """Classify only the bounded fact families authorized by #210.

    Matching is lexical and deterministic.  There is no similarity score,
    fuzzy matching, embedding lookup, or semantic-equivalence fallback.
    """
    text = _fold_lexical_text(
        " ".join(
            str(fact.get(name, ""))
            for name in ("label", "needed_information")
        )
    )

    # Provider descriptors may name the already-explicit tax year without
    # repeating the measurement unit.  The descriptor is only a selector:
    # promotion still requires one unique client-owned span that literally
    # carries the supported UVT family and measurement.
    if (
        re.search(r"\bingres\w*\s+brut\w*", text)
        and (
            re.search(r"\buvt\b", text)
            or _EXPLICIT_YEAR_RE.search(text)
        )
    ):
        return "gross_income_uvt"
    if (
        re.search(r"\bpatrimon\w*\s+brut\w*", text)
        and (
            re.search(r"\buvt\b", text)
            or _EXPLICIT_YEAR_RE.search(text)
        )
    ):
        return "gross_patrimony_uvt"
    if re.search(r"\bresiden\w*\s+fiscal\w*", text) and re.search(r"\bcolomb\w*", text):
        return "fiscal_residence_colombia"
    if (
        re.search(r"\bactiv\w*\s+digital\w*", text)
        and re.search(r"\bcuenta\s+propia\b", text)
    ):
        return "digital_self_employed"
    if re.search(r"\bsas\b", text) and re.search(r"\bcolombian\w*", text):
        return "colombian_sas"
    if (
        re.search(r"\bbogota\b", text)
        and re.search(r"\b(?:prest\w*|servic\w*|ejecut\w*|ubic\w*)", text)
    ):
        return "bogota_execution"
    if (
        re.search(r"\bcanada\b", text)
        and re.search(r"\b(?:client\w*|socied\w*|domicil\w*)", text)
    ):
        return "canadian_customer"
    if (
        re.search(r"\bcolombia\b", text)
        and (
            re.search(r"\b(?:ausen\w*|presen\w*)", text)
            or re.search(r"\bno\s+tiene\b", text)
        )
        and re.search(
            r"\b(?:domicil\w*|sucurs\w*|establec\w*|emplead\w*|activ\w*)",
            text,
        )
    ):
        return "no_colombia_presence"
    if (
        re.search(r"\bexclusiv\w*", text)
        and re.search(r"\b(?:us\w*|explot\w*)", text)
        and re.search(r"\bcolombia\b", text)
    ):
        return "exclusive_foreign_use"
    if (
        re.search(r"\b(?:document\w*|soport\w*)", text)
        and sum(
            bool(re.search(pattern, text))
            for pattern in (
                r"\bcontrat\w*",
                r"\bfactur\w*",
                r"\bcomprob\w*",
                r"\bentreg\w*",
                r"\bacept\w*",
            )
        ) >= 2
    ):
        return "support_documents"
    if (
        re.search(r"\bfactur\w*", text)
        and re.search(r"\bpago\b", text)
        and re.search(r"\b2026\b", text)
    ):
        return "billing_payment"
    if (
        re.search(r"\bejecut\w*", text)
        and re.search(r"\bcolombia\b", text)
    ):
        return "colombia_execution"
    return None


def _span_supports_family(family: str, span: str) -> bool:
    """Return whether one exact client span lexically supports a fact family."""
    text = _fold_lexical_text(span)

    if family == "gross_income_uvt":
        return bool(
            re.search(r"\bingres\w*\s+brut\w*", text)
            and re.search(r"\buvt\b", text)
        )
    if family == "gross_patrimony_uvt":
        return bool(
            re.search(r"\bpatrimon\w*\s+brut\w*", text)
            and re.search(r"\buvt\b", text)
        )
    if family == "fiscal_residence_colombia":
        return bool(
            re.search(r"\bresiden\w*\s+fiscal\w*", text)
            and re.search(r"\bcolomb\w*", text)
        )
    if family == "digital_self_employed":
        return bool(
            re.search(r"\bactiv\w*\s+digital\w*", text)
            and re.search(r"\bcuenta\s+propia\b", text)
        )
    if family == "colombian_sas":
        return bool(
            re.search(r"\bsas\s+colombian\w*", text)
            or (
                re.search(r"\bsas\b", text)
                and re.search(r"\bcolombian\w*", text)
            )
        )
    if family == "bogota_execution":
        return bool(
            re.search(r"\bbogota\b", text)
            and re.search(r"\b(?:prest\w*|ejecut\w*)", text)
        )
    if family == "canadian_customer":
        return bool(
            re.search(r"\bcanada\b", text)
            and re.search(r"\b(?:client\w*|socied\w*)", text)
            and re.search(r"\bdomicil\w*", text)
        )
    if family == "no_colombia_presence":
        return bool(
            re.search(r"\bno\s+tiene\b", text)
            and re.search(r"\bcolombia\b", text)
            and re.search(
                r"\b(?:domicil\w*|sucurs\w*|establec\w*|emplead\w*|activ\w*)",
                text,
            )
        )
    if family == "exclusive_foreign_use":
        return bool(
            re.search(r"\bexclusiv\w*", text)
            and re.search(r"\b(?:us\w*|explot\w*)", text)
            and re.search(r"\bcolombia\b", text)
        )
    if family == "support_documents":
        return (
            sum(
                bool(re.search(pattern, text))
                for pattern in (
                    r"\bcontrat\w*",
                    r"\bfactur\w*",
                    r"\bcomprob\w*",
                    r"\bentreg\w*",
                    r"\bacept\w*",
                )
            )
            >= 3
        )
    if family == "billing_payment":
        return bool(
            re.search(r"\bfactur\w*", text)
            and re.search(r"\bpago\b", text)
            and re.search(r"\bagosto\b", text)
            and re.search(r"\b2026\b", text)
        )
    if family == "colombia_execution":
        return bool(
            re.search(r"\bejecut\w*", text)
            and re.search(r"\bcolombia\b", text)
        )
    return False


def _unique_normalization_span(
    problem_text: str,
    family: str,
) -> str | None:
    """Resolve one supported fact family to exactly one exact client span."""
    matches: list[str] = []
    for span in _normalization_source_spans(problem_text):
        folded = f" {_fold_lexical_text(span)} "
        if any(marker in folded for marker in _CLIENT_AMBIGUITY_PATTERNS):
            continue
        if problem_text.count(span) != 1:
            continue
        if _span_supports_family(family, span):
            matches.append(span)
    if len(matches) != 1:
        return None
    return matches[0]


def _uvt_measurement_from_quote(
    quote: str,
    *,
    semantic_key: str,
) -> tuple[str, dict[str, Any]] | None:
    """Extract the already-supported UVT measurement from one exact quote."""
    measurements = list(_UVT_MEASUREMENT_RE.finditer(quote))
    years = sorted(set(_EXPLICIT_YEAR_RE.findall(quote)))
    if len(measurements) != 1 or len(years) != 1:
        return None

    numeric_match = re.search(
        r"(?:[0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]+(?:[.,][0-9]+)?)",
        measurements[0].group(0),
    )
    if numeric_match is None:
        return None
    raw = numeric_match.group(0).replace(" ", "")
    if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", raw):
        decimal_value = raw.replace(".", "")
    else:
        decimal_value = raw.replace(",", ".")

    return semantic_key, {
        "decimal_value": decimal_value,
        "unit": "UVT",
        "uvt_year": int(years[0]),
    }


def _supported_uvt_projection_from_quote(
    quote: str,
) -> tuple[str, dict[str, Any]] | None:
    """Project one exact client quote onto the bounded supported UVT vocabulary.

    A quote is usable only when exactly one existing supported fact family and
    exactly one UVT/year measurement can be derived from its literal bytes.
    This remains deterministic client-evidence parsing, not model semantics.
    """
    projections: list[tuple[str, dict[str, Any]]] = []
    for family, semantic_key in _SUPPORTED_UVT_FAMILIES.items():
        if not _span_supports_family(family, quote):
            continue
        projection = _uvt_measurement_from_quote(
            quote,
            semantic_key=semantic_key,
        )
        if projection is not None:
            projections.append(projection)
    if len(projections) != 1:
        return None
    return projections[0]



def _supported_uvt_family_from_user_fact(
    fact: dict[str, Any],
) -> str | None:
    """Select one bounded UVT family from model label + structured measurement.

    #246 closes a narrow gap in #239: for an already-user_provided fact, the
    structured measurement itself can establish that the unit is UVT even when
    the model label says only "Ingresos brutos" or "Patrimonio bruto".  The
    semantic key is deliberately not used to choose the family because it may
    be the corrupted field being recovered.  Ambiguous/generic labels remain
    unresolved so the existing consistency validator can fail closed.
    """
    family = _descriptor_family(fact)
    if family in _SUPPORTED_UVT_FAMILIES:
        return family

    measurement = fact.get("measurement")
    if not isinstance(measurement, dict) or measurement.get("unit") != "UVT":
        return None

    text = _fold_lexical_text(
        " ".join(
            str(fact.get(name, ""))
            for name in ("label", "needed_information")
        )
    )
    candidates: list[str] = []
    if re.search(r"\bingres\w*\s+brut\w*", text):
        candidates.append("gross_income_uvt")
    if re.search(r"\bpatrimon\w*\s+brut\w*", text):
        candidates.append("gross_patrimony_uvt")
    if len(candidates) != 1:
        return None
    return candidates[0]

def _recover_supported_user_uvt_fact(
    problem_text: str,
    fact: dict[str, Any],
) -> None:
    """Recover only a provably supported user-provided UVT mismatch.

    #239 extends #210's exact-source recovery to an already-user_provided fact,
    but only for the two bounded natural-person UVT concepts.  Recovery requires
    either (a) model label + declared measurement to agree with one unique exact
    client span for the same family, or (b) the current exact quote + declared
    measurement to agree and only the semantic key to be wrong.  Otherwise the
    fact remains untouched and authoritative validation rejects the mismatch.
    """
    if fact.get("state") != "user_provided":
        return

    semantic_key = fact.get("semantic_key")
    measurement = fact.get("measurement")
    quote = fact.get("source_quote")
    if (
        semantic_key not in _SUPPORTED_UVT_SEMANTIC_KEYS
        or not isinstance(measurement, dict)
        or not isinstance(quote, str)
    ):
        return

    declared = (semantic_key, measurement)
    current_projection = _supported_uvt_projection_from_quote(quote)
    if current_projection == declared:
        return

    # Prefer the same bounded lexical family selection used by #210.  The model
    # label is only a selector; the replacement values are re-derived from one
    # unique exact client span, and the declared numeric measurement must agree.
    family = _supported_uvt_family_from_user_fact(fact)
    expected_key = _SUPPORTED_UVT_FAMILIES.get(family)
    if expected_key is not None:
        recovered_quote = _unique_normalization_span(problem_text, family)
        if recovered_quote is not None:
            recovered_projection = _supported_uvt_projection_from_quote(
                recovered_quote
            )
            if (
                recovered_projection is not None
                and recovered_projection[0] == expected_key
                and recovered_projection[1] == measurement
            ):
                fact["source_quote"] = recovered_quote
                fact["semantic_key"] = recovered_projection[0]
                fact["measurement"] = deepcopy(recovered_projection[1])
                return

    # If the exact client quote and declared numeric measurement already agree,
    # correcting only the bounded semantic key is unambiguous.
    if (
        current_projection is not None
        and current_projection[1] == measurement
    ):
        fact["semantic_key"] = current_projection[0]
        fact["measurement"] = deepcopy(current_projection[1])


def normalize_intake_draft(
    case_input: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any]:
    """Apply the narrow exact-source recovery/consistency rules from #210/#239.

    This function is intentionally not a general model-output repair layer.  It
    never creates a fact, never guesses between spans, never infers legal
    meaning, and never uses similarity/fuzzy matching.  Unsupported or
    non-unique cases are returned untouched so authoritative validation can
    preserve/reject them under the normal v4 contract.
    """
    if case_input.get("contract_version") != CONTRACT_VERSION:
        return deepcopy(draft)

    normalized = deepcopy(draft)
    problem_text = str(case_input.get("problem_text", ""))

    for fact in normalized.get("facts", []):
        state = fact.get("state")
        if state == "user_provided":
            _recover_supported_user_uvt_fact(problem_text, fact)
            continue
        if state not in {"missing", "ambiguous"}:
            continue

        family = _descriptor_family(fact)
        if family is None:
            continue
        quote = _unique_normalization_span(problem_text, family)
        if quote is None:
            continue

        semantic: tuple[str, dict[str, Any]] | None = None
        if family == "gross_income_uvt":
            semantic = _uvt_measurement_from_quote(
                quote,
                semantic_key=_GROSS_INCOME_SEMANTIC_KEY,
            )
            if semantic is None:
                continue
        elif family == "gross_patrimony_uvt":
            semantic = _uvt_measurement_from_quote(
                quote,
                semantic_key=_GROSS_PATRIMONY_SEMANTIC_KEY,
            )
            if semantic is None:
                continue

        fact["state"] = "user_provided"
        fact["source_quote"] = quote
        fact["requires_confirmation"] = False
        fact.pop("needed_information", None)
        # An unresolved model fact may carry advisory semantic metadata.  Once
        # exact client text becomes the authority for promotion, only the two
        # explicitly supported deterministic UVT semantics may survive.
        fact.pop("semantic_key", None)
        fact.pop("measurement", None)
        if semantic is not None:
            fact["semantic_key"], fact["measurement"] = semantic

    return normalized


def _fact_downgrade_conflicts_with_explicit_text(
    fact: dict[str, Any],
    problem_text: str,
) -> bool:
    """Reject a high-confidence downgrade of a stated client fact.

    This is a contradiction guard, not extraction or repair.  It never creates
    a fact/source quote.  It only rejects a model draft when either its own fact
    label faithfully restates one unambiguous client assertion or its
    confirmation request substantially repeats an assertion already supplied.
    """
    state = fact.get("state")
    if state not in {"missing", "ambiguous"}:
        return False

    spans = _unambiguous_assertive_spans(problem_text)
    label_signature = _topic_signature(str(fact.get("label", "")))
    if len(label_signature) >= 2 and any(
        label_signature.issubset(_topic_signature(span))
        for span in spans
    ):
        return True

    needed = str(fact.get("needed_information", ""))
    folded_needed = _fold_lexical_text(needed).strip()
    if not any(folded_needed.startswith(prefix) for prefix in _CONFIRMATION_PREFIXES):
        return False

    needed_signature = _topic_signature(needed) - _CONFIRMATION_META_STEMS
    if len(needed_signature) < 2:
        return False

    for span in spans:
        span_signature = _topic_signature(span)
        overlap = len(needed_signature.intersection(span_signature))
        if overlap < 2:
            continue
        # Confirmation requests often change grammatical voice ("se emitió"
        # versus "factura") while retaining the concrete factual anchors.
        if overlap / len(needed_signature) >= 0.60:
            return True
    return False


def _question_category_conflicts(question: dict[str, Any]) -> bool:
    """Detect high-confidence tax/legal treatment questions miscategorized.

    Date/effective-period questions remain eligible for the temporal category.
    The function does not infer an answer or rewrite the category; invalid
    model output is rejected through the normal intake validation path.
    """
    if question.get("category") == "legal":
        return False
    text = str(question.get("text", ""))
    if (
        _TAX_LEGAL_TOPIC_RE.search(text)
        and _LEGAL_TREATMENT_RE.search(text)
    ):
        return True
    if _PURE_TEMPORAL_QUESTION_RE.search(text):
        return False
    return False


def intake_draft_generation_schema(
    case_input: dict[str, Any],
) -> dict[str, Any]:
    """Return the constrained model-facing schema for one v4 IntakeDraft.

    Caller-owned root fields and model metadata are application-owned and are
    therefore omitted from generation. Literal/normalized intake facts are
    constrained to exact contiguous CaseInput spans. Conditional IntakeFact
    semantics are expressed as explicit oneOf branches because the admitted
    llama.cpp structured-generation backend does not reliably enforce if/then.
    """
    validate_case_input(case_input)
    root = load_contract_schema(SCHEMA_PATH)
    # Give the intake model only the vocabulary it is authorized to produce.
    # Platform research/evidence/rule definitions remain absent even as unused
    # $defs so they cannot become prompt-visible pseudo-authority.
    allowed_definitions = (
        "IntakeDraft",
        "IntakeFact",
        "FactMeasurement",
        "DecimalString",
        "CaseQuestion",
        "SearchHint",
    )
    definitions = {
        name: deepcopy(root["$defs"][name])
        for name in allowed_definitions
    }
    draft = definitions["IntakeDraft"]

    for name in (
        "problem_text",
        "as_of_date",
        "client_reference",
        "caller_metadata",
        "model_metadata",
    ):
        draft["properties"].pop(name, None)
        draft["required"] = [
            item for item in draft["required"] if item != name
        ]

    fact = definitions["IntakeFact"]
    fact_properties = deepcopy(fact["properties"])
    fact_required = list(fact["required"])
    candidates = _intake_source_quote_candidates(case_input["problem_text"])

    def fact_variant(
        state: str,
        *,
        requires_confirmation: bool,
        source_quote: bool = False,
        needed_information: bool = False,
    ) -> dict[str, Any]:
        properties = deepcopy(fact_properties)
        properties["state"] = {"const": state}
        properties["requires_confirmation"] = {
            "const": requires_confirmation
        }
        required = list(fact_required)

        if source_quote:
            properties["source_quote"] = {
                "type": "string",
                "enum": deepcopy(candidates),
            }
            if "source_quote" not in required:
                required.append("source_quote")
        else:
            properties.pop("source_quote", None)
            required = [
                item for item in required if item != "source_quote"
            ]

        if needed_information:
            if "needed_information" not in required:
                required.append("needed_information")
        else:
            properties.pop("needed_information", None)
            required = [
                item for item in required
                if item != "needed_information"
            ]

        if not source_quote:
            # Missing/ambiguous facts may carry a semantic_key describing what
            # is needed, but they cannot carry a numeric measurement that the
            # client did not actually provide.
            properties.pop("measurement", None)
            required = [
                item for item in required
                if item != "measurement"
            ]

        return {
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
        }

    definitions["IntakeFact"] = {
        "oneOf": [
            fact_variant(
                "user_provided",
                requires_confirmation=False,
                source_quote=True,
            ),
            fact_variant(
                "llm_normalized",
                requires_confirmation=True,
                source_quote=True,
            ),
            fact_variant(
                "missing",
                requires_confirmation=True,
                needed_information=True,
            ),
            fact_variant(
                "ambiguous",
                requires_confirmation=True,
                needed_information=True,
            ),
        ]
    }

    return {
        "$schema": root["$schema"],
        "$defs": definitions,
        "$ref": "#/$defs/IntakeDraft",
    }


def _missing_fact_duplicates_question(
    fact: dict[str, Any],
    questions: list[dict[str, Any]],
) -> bool:
    """Reject high-confidence duplication of a research question as a missing fact.

    Missing facts represent absent client-supplied factual inputs. A legal/factual/
    procedural question is a research target, not a missing value merely because
    its answer is unknown. The comparison is deliberately lexical and conservative
    so ambiguity is preserved rather than semantically reclassified.
    """
    if fact.get("state") != "missing":
        return False

    missing_signature = _topic_signature(
        " ".join(
            str(value)
            for value in (
                fact.get("label", ""),
                fact.get("needed_information", ""),
            )
            if value
        )
    )
    if len(missing_signature) < 2:
        return False

    for question in questions:
        question_signature = _topic_signature(str(question.get("text", "")))
        if len(question_signature) < 2:
            continue
        smaller = min(len(missing_signature), len(question_signature))
        overlap = len(missing_signature.intersection(question_signature))
        if (
            missing_signature == question_signature
            or (
                overlap >= 2
                and overlap == smaller
                and abs(
                    len(missing_signature) - len(question_signature)
                ) <= 1
            )
        ):
            return True
    return False


def _validate_supported_user_uvt_consistency(
    fact: dict[str, Any],
    *,
    index: int,
    problem_text: str,
) -> None:
    """Reject supported UVT semantics that contradict their exact client quote."""
    if fact.get("state") != "user_provided":
        return
    semantic_key = fact.get("semantic_key")
    measurement = fact.get("measurement")
    quote = fact.get("source_quote")
    if semantic_key not in _SUPPORTED_UVT_SEMANTIC_KEYS:
        return
    if not isinstance(measurement, dict) or not isinstance(quote, str):
        return

    projection = _supported_uvt_projection_from_quote(quote)
    if projection is None:
        _fail(
            INVALID_INTAKE_DRAFT,
            f"$.facts[{index}].source_quote",
            (
                "supported natural-person UVT mapping is not uniquely "
                "supported by its exact client quote"
            ),
        )
    if projection != (semantic_key, measurement):
        _fail(
            INVALID_INTAKE_DRAFT,
            f"$.facts[{index}].semantic_key",
            (
                "supported natural-person UVT semantic_key, measurement, "
                "and exact source_quote contradict each other"
            ),
        )


def validate_intake_draft(
    case_input: dict[str, Any],
    draft: dict[str, Any],
) -> None:
    """Validate the complete model-owned v4 intake boundary.

    This function deliberately validates only intake structure. It does not
    accept platform research/evidence/authority objects and never upgrades
    model prose into a legal conclusion.
    """
    validate_case_input(case_input)
    _validate_schema(draft, "IntakeDraft", INVALID_INTAKE_DRAFT)

    if draft["problem_text"] != case_input["problem_text"]:
        _fail(
            INVALID_INTAKE_DRAFT,
            "$.problem_text",
            "client problem_text was modified",
        )

    for name in ("as_of_date", "client_reference", "caller_metadata"):
        _require_optional_field_preserved(
            case_input,
            draft,
            name,
            code=INVALID_INTAKE_DRAFT,
        )

    facts = _registry(
        draft["facts"],
        "fact_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.facts",
    )
    questions = _registry(
        draft["questions"],
        "question_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.questions",
    )
    hints = _registry(
        draft["search_hints"],
        "hint_ref",
        code=INVALID_INTAKE_DRAFT,
        owner="$.search_hints",
    )
    del hints

    for index, fact in enumerate(draft["facts"]):
        if "measurement" in fact and "semantic_key" not in fact:
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.facts[{index}].measurement",
                "structured measurement requires a semantic_key",
            )
        if (
            fact["state"] in {"missing", "ambiguous"}
            and "measurement" in fact
        ):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.facts[{index}].measurement",
                "missing/ambiguous facts cannot carry a numeric measurement",
            )

        if _missing_fact_duplicates_question(fact, draft["questions"]):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.facts[{index}].state",
                (
                    "research question was duplicated as a missing fact; "
                    "missing facts must describe absent client inputs"
                ),
            )
        if (
            _missing_fact_conflicts_with_explicit_text(
                fact,
                case_input["problem_text"],
            )
            or _fact_downgrade_conflicts_with_explicit_text(
                fact,
                case_input["problem_text"],
            )
        ):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.facts[{index}].state",
                (
                    "missing/ambiguous fact conflicts with information "
                    "already stated in explicit client text"
                ),
            )
        if fact["state"] in {"user_provided", "llm_normalized"}:
            quote = fact["source_quote"]
            if quote not in case_input["problem_text"]:
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.facts[{index}].source_quote",
                    "source quote is not present verbatim in CaseInput.problem_text",
                )
        _validate_supported_user_uvt_consistency(
            fact,
            index=index,
            problem_text=case_input["problem_text"],
        )
        for name in ("label", "value", "needed_information"):
            value = fact.get(name)
            if isinstance(value, str) and _PLATFORM_REF_IN_MODEL_TEXT.search(value):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.facts[{index}].{name}",
                    "model-authored intake content attempted to inject a platform-owned identifier",
                )

    for index, question in enumerate(draft["questions"]):
        if _question_category_conflicts(question):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.questions[{index}].category",
                (
                    "substantive tax/legal-treatment question has an "
                    "incompatible non-legal category"
                ),
            )
        if _PLATFORM_REF_IN_MODEL_TEXT.search(question["text"]):
            _fail(
                INVALID_INTAKE_DRAFT,
                f"$.questions[{index}].text",
                "model-authored question attempted to inject a platform-owned identifier",
            )
        _require_refs(
            question.get("depends_on_fact_refs", []),
            facts,
            code=INVALID_INTAKE_DRAFT,
            path=f"$.questions[{index}].depends_on_fact_refs",
        )

    for index, hint in enumerate(draft["search_hints"]):
        _require_refs(
            hint["related_question_refs"],
            questions,
            code=INVALID_INTAKE_DRAFT,
            path=f"$.search_hints[{index}].related_question_refs",
        )
        for term_index, term in enumerate(hint["terms"]):
            if _TYPED_REF_IN_TEXT.search(term):
                _fail(
                    INVALID_INTAKE_DRAFT,
                    f"$.search_hints[{index}].terms[{term_index}]",
                    "model search vocabulary attempted to inject a typed application identifier",
                )


def _validate_case_as_of_date(
    case_input: dict[str, Any],
    plan: dict[str, Any],
    *,
    code: str,
) -> None:
    """Prevent a platform plan from inventing or losing caller as-of context."""
    if "as_of_date" in case_input:
        if plan.get("as_of_date") != case_input["as_of_date"]:
            _fail(code, "$.as_of_date", "plan does not preserve CaseInput.as_of_date")
    elif "as_of_date" in plan:
        _fail(code, "$.as_of_date", "plan invented an absent CaseInput.as_of_date")


def validate_research_plan(
    intake_draft: dict[str, Any],
    plan: dict[str, Any],
    *,
    case_input: dict[str, Any] | None = None,
) -> None:
    """Validate platform-owned v4 research intent and its typed intake graph."""
    _validate_schema(plan, "ResearchPlan", INVALID_RESEARCH_PLAN)

    if plan["intake_ref"] != intake_draft["intake_ref"]:
        _fail(
            INVALID_RESEARCH_PLAN,
            "$.intake_ref",
            "does not resolve to the accepted IntakeDraft",
        )
    if case_input is not None:
        _validate_case_as_of_date(
            case_input,
            plan,
            code=INVALID_RESEARCH_PLAN,
        )

    facts = _registry(
        intake_draft["facts"],
        "fact_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.facts",
    )
    questions = _registry(
        intake_draft["questions"],
        "question_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.questions",
    )
    hints = _registry(
        intake_draft["search_hints"],
        "hint_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.intake_draft.search_hints",
    )
    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=INVALID_RESEARCH_PLAN,
        owner="$.tasks",
    )
    del tasks

    platform_required_questions: set[str] = set()
    for index, task in enumerate(plan["tasks"]):
        _require_refs(
            [task["question_ref"]],
            questions,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].question_ref",
        )
        _require_refs(
            task.get("generated_from_fact_refs", []),
            facts,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].generated_from_fact_refs",
        )
        _require_refs(
            task.get("hint_refs", []),
            hints,
            code=INVALID_RESEARCH_PLAN,
            path=f"$.tasks[{index}].hint_refs",
        )
        if task["origin"] == "platform_required":
            platform_required_questions.add(task["question_ref"])

    for question in intake_draft["questions"]:
        if (
            question["category"] == "legal"
            and question["status"] == "open"
            and question["question_ref"] not in platform_required_questions
        ):
            _fail(
                INVALID_RESEARCH_PLAN,
                "$.tasks",
                (
                    "every open legal question requires at least one "
                    f"platform_required task; missing {question['question_ref']!r}"
                ),
            )


def _validate_research_context(
    context: dict[str, Any],
    plan: dict[str, Any],
    *,
    code: str,
    path: str,
) -> None:
    unavailable = set(context["unavailable_fields"])
    for name in _FINGERPRINT_OPTIONAL_FIELDS:
        is_null = context[name] is None
        is_unavailable = name in unavailable
        if is_null != is_unavailable:
            _fail(
                code,
                f"{path}.{name}",
                "null availability must match unavailable_fields exactly",
            )

    if context["planner_version"] != plan["planner_version"]:
        _fail(
            code,
            f"{path}.planner_version",
            "does not match ResearchPlan.planner_version",
        )

    expected_as_of = plan.get("as_of_date")
    if context["as_of_date"] != expected_as_of:
        _fail(
            code,
            f"{path}.as_of_date",
            "does not match ResearchPlan.as_of_date",
        )


def validate_research_result(
    plan: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Validate one platform-owned research execution record."""
    _validate_schema(result, "ResearchResult", INVALID_RESEARCH_RESULT)

    if result["plan_ref"] != plan["plan_ref"]:
        _fail(
            INVALID_RESEARCH_RESULT,
            "$.plan_ref",
            "does not resolve to the ResearchPlan",
        )

    tasks = _registry(
        plan["tasks"],
        "task_ref",
        code=INVALID_RESEARCH_RESULT,
        owner="$.research_plan.tasks",
    )
    _registry(
        result["trace"],
        "trace_ref",
        code=INVALID_RESEARCH_RESULT,
        owner="$.trace",
    )
    for index, step in enumerate(result["trace"]):
        _require_refs(
            [step["task_ref"]],
            tasks,
            code=INVALID_RESEARCH_RESULT,
            path=f"$.trace[{index}].task_ref",
        )

    _validate_research_context(
        result["research_context"],
        plan,
        code=INVALID_RESEARCH_RESULT,
        path="$.research_context",
    )


def _validate_registered_rule_fragment(
    fragment: dict[str, Any],
    *,
    code: str,
    path: str,
) -> None:
    key = (fragment["rule_type"], fragment["rule_schema_version"])
    validator = _RULE_FRAGMENT_VALIDATORS.get(key)
    if validator is None:
        _fail(
            code,
            path,
            (
                "unregistered RuleFragment type/schema version "
                f"{key[0]!r}/{key[1]!r}; unknown rule semantics fail closed"
            ),
        )
    try:
        validator(fragment)
    except CaseContractError:
        raise
    except (TypeError, ValueError) as exc:
        _fail(code, path, f"registered RuleFragment validation failed: {exc}")


def _validate_bundle_graph(bundle: dict[str, Any]) -> None:
    code = INVALID_LEGAL_RESEARCH_BUNDLE

    intake = bundle["intake_draft"]
    plan = bundle["research_plan"]
    result = bundle["research_result"]

    facts = _registry(intake["facts"], "fact_ref", code=code, owner="$.intake_draft.facts")
    questions = _registry(
        intake["questions"],
        "question_ref",
        code=code,
        owner="$.intake_draft.questions",
    )
    hints = _registry(
        intake["search_hints"],
        "hint_ref",
        code=code,
        owner="$.intake_draft.search_hints",
    )
    tasks = _registry(plan["tasks"], "task_ref", code=code, owner="$.research_plan.tasks")
    traces = _registry(
        result["trace"],
        "trace_ref",
        code=code,
        owner="$.research_result.trace",
    )
    del hints, traces

    sources = _registry(bundle["sources"], "source_ref", code=code, owner="$.sources")
    authorities = _registry(
        bundle["authorities"],
        "authority_ref",
        code=code,
        owner="$.authorities",
    )
    evidence = _registry(
        bundle["evidence_spans"],
        "evidence_ref",
        code=code,
        owner="$.evidence_spans",
    )
    span_refs = _registry(
        bundle["evidence_spans"],
        "span_ref",
        code=code,
        owner="$.evidence_spans",
    )
    del span_refs
    relationships = _registry(
        bundle["normative_relationships"],
        "relationship_ref",
        code=code,
        owner="$.normative_relationships",
    )
    rules = _registry(
        bundle["rule_fragments"],
        "rule_ref",
        code=code,
        owner="$.rule_fragments",
    )
    evaluations = _registry(
        bundle["deterministic_evaluations"],
        "evaluation_ref",
        code=code,
        owner="$.deterministic_evaluations",
    )
    calculations = _registry(
        bundle["calculation_traces"],
        "calculation_ref",
        code=code,
        owner="$.calculation_traces",
    )
    unresolved = _registry(
        bundle["unresolved"],
        "unresolved_ref",
        code=code,
        owner="$.unresolved",
    )

    for index, step in enumerate(result["trace"]):
        _require_refs(
            [step["task_ref"]],
            tasks,
            code=code,
            path=f"$.research_result.trace[{index}].task_ref",
        )
        _require_refs(
            step["authority_refs"],
            authorities,
            code=code,
            path=f"$.research_result.trace[{index}].authority_refs",
        )
        _require_refs(
            step["unresolved_refs"],
            unresolved,
            code=code,
            path=f"$.research_result.trace[{index}].unresolved_refs",
        )

    _require_refs(
        result["authority_refs"],
        authorities,
        code=code,
        path="$.research_result.authority_refs",
    )
    _require_refs(
        result["unresolved_refs"],
        unresolved,
        code=code,
        path="$.research_result.unresolved_refs",
    )

    for index, authority in enumerate(bundle["authorities"]):
        _require_refs(
            authority["source_refs"],
            sources,
            code=code,
            path=f"$.authorities[{index}].source_refs",
        )
        _require_refs(
            authority["evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].evidence_refs",
        )
        _require_refs(
            authority["relationship_refs"],
            relationships,
            code=code,
            path=f"$.authorities[{index}].relationship_refs",
        )
        _require_refs(
            authority["temporal_state"]["basis_evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].temporal_state.basis_evidence_refs",
        )
        _require_refs(
            authority["publication_metadata"]["evidence_refs"],
            evidence,
            code=code,
            path=f"$.authorities[{index}].publication_metadata.evidence_refs",
        )

    for index, item in enumerate(bundle["evidence_spans"]):
        _require_refs(
            [item["source_ref"]],
            sources,
            code=code,
            path=f"$.evidence_spans[{index}].source_ref",
        )
        _require_refs(
            [item["authority_ref"]],
            authorities,
            code=code,
            path=f"$.evidence_spans[{index}].authority_ref",
        )
        authority = authorities[item["authority_ref"]]
        if item["document_ref"] != authority["document_ref"]:
            _fail(
                code,
                f"$.evidence_spans[{index}].document_ref",
                "does not match the owning CanonicalAuthority document_ref",
            )
        if (
            "provision_ref" in item
            and item["provision_ref"] not in authority["provision_refs"]
        ):
            _fail(
                code,
                f"$.evidence_spans[{index}].provision_ref",
                "does not belong to the owning CanonicalAuthority",
            )

    for index, relationship in enumerate(bundle["normative_relationships"]):
        _require_refs(
            [
                relationship["source_authority_ref"],
                relationship["target_authority_ref"],
            ],
            authorities,
            code=code,
            path=f"$.normative_relationships[{index}]",
        )
        _require_refs(
            relationship["evidence_refs"],
            evidence,
            code=code,
            path=f"$.normative_relationships[{index}].evidence_refs",
        )

    for index, fragment in enumerate(bundle["rule_fragments"]):
        _require_refs(
            fragment["authority_refs"],
            authorities,
            code=code,
            path=f"$.rule_fragments[{index}].authority_refs",
        )
        _require_refs(
            fragment["evidence_refs"],
            evidence,
            code=code,
            path=f"$.rule_fragments[{index}].evidence_refs",
        )
        _require_refs(
            fragment.get("relationship_refs", []),
            relationships,
            code=code,
            path=f"$.rule_fragments[{index}].relationship_refs",
        )
        _validate_registered_rule_fragment(
            fragment,
            code=code,
            path=f"$.rule_fragments[{index}]",
        )

    for index, evaluation in enumerate(bundle["deterministic_evaluations"]):
        _require_refs(
            evaluation["fact_refs"],
            facts,
            code=code,
            path=f"$.deterministic_evaluations[{index}].fact_refs",
        )
        _require_refs(
            evaluation["question_refs"],
            questions,
            code=code,
            path=f"$.deterministic_evaluations[{index}].question_refs",
        )
        _require_refs(
            evaluation["rule_refs"],
            rules,
            code=code,
            path=f"$.deterministic_evaluations[{index}].rule_refs",
        )
        _require_refs(
            evaluation["evidence_refs"],
            evidence,
            code=code,
            path=f"$.deterministic_evaluations[{index}].evidence_refs",
        )
        _require_refs(
            evaluation["calculation_trace_refs"],
            calculations,
            code=code,
            path=f"$.deterministic_evaluations[{index}].calculation_trace_refs",
        )
        _require_refs(
            evaluation["unresolved_refs"],
            unresolved,
            code=code,
            path=f"$.deterministic_evaluations[{index}].unresolved_refs",
        )

    for index, calculation in enumerate(bundle["calculation_traces"]):
        for input_index, calculation_input in enumerate(calculation["inputs"]):
            if "source_fact_ref" in calculation_input:
                _require_refs(
                    [calculation_input["source_fact_ref"]],
                    facts,
                    code=code,
                    path=(
                        f"$.calculation_traces[{index}].inputs"
                        f"[{input_index}].source_fact_ref"
                    ),
                )
            if "source_rule_ref" in calculation_input:
                _require_refs(
                    [calculation_input["source_rule_ref"]],
                    rules,
                    code=code,
                    path=(
                        f"$.calculation_traces[{index}].inputs"
                        f"[{input_index}].source_rule_ref"
                    ),
                )
        _require_refs(
            calculation["rule_refs"],
            rules,
            code=code,
            path=f"$.calculation_traces[{index}].rule_refs",
        )
        _require_refs(
            calculation["evidence_refs"],
            evidence,
            code=code,
            path=f"$.calculation_traces[{index}].evidence_refs",
        )

    for index, item in enumerate(bundle["unresolved"]):
        references = (
            ("related_fact_refs", facts),
            ("related_question_refs", questions),
            ("related_authority_refs", authorities),
            ("related_evidence_refs", evidence),
            ("related_rule_refs", rules),
            ("related_evaluation_refs", evaluations),
            ("related_calculation_refs", calculations),
        )
        for name, registry in references:
            _require_refs(
                item.get(name, []),
                registry,
                code=code,
                path=f"$.unresolved[{index}].{name}",
            )


def validate_legal_research_bundle(bundle: dict[str, Any]) -> None:
    """Validate the complete v4 platform-owned integration object.

    Validation is read-only. It checks serialized shape, the accepted intake
    fidelity boundary, research ownership, fingerprint availability, and every
    cross-object typed reference required by the v4 contract.
    """
    _validate_schema(
        bundle,
        "LegalResearchBundle",
        INVALID_LEGAL_RESEARCH_BUNDLE,
    )

    case_input = bundle["case_input"]
    intake = bundle["intake_draft"]
    plan = bundle["research_plan"]
    result = bundle["research_result"]

    try:
        validate_intake_draft(case_input, intake)
        validate_research_plan(intake, plan, case_input=case_input)
        validate_research_result(plan, result)
    except CaseContractError as exc:
        _fail(
            INVALID_LEGAL_RESEARCH_BUNDLE,
            "$",
            f"embedded v4 contract invalid: {exc.code}: {exc.detail}",
        )

    _validate_bundle_graph(bundle)


def validated_copy(value: dict[str, Any]) -> dict[str, Any]:
    """Return a defensive copy after shape validation without mutating input."""
    validate_contract_object(value)
    return deepcopy(value)
