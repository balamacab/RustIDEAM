from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
for path in (TESTS, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from case_attempt_evidence import (
    GenerationEvidence,
    canonical_json_bytes,
    sha256_hex,
)
from case_contract_validation import CaseContractError
from llm_client import (
    CaseStructuringService,
    LLMClientError,
    LLMPlatformConfig,
    load_platform_config,
)
from openai_compatible_intake_adapter import OpenAICompatibleIntakeAdapter
from test_issue0210_intake_recovery import (
    CASE_A,
    CASE_B,
    CASE_C,
    case_input,
)


PROFILE_PATH = ROOT / "config" / "llm" / "case-migration-rtx3070-v1.yaml"
EXPECTED_PROFILE_ID = "case-migration-rtx3070-v1"
EXPECTED_ADMISSION_ISSUE = 133
CASE_TEXTS = {"A": CASE_A, "B": CASE_B, "C": CASE_C}
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationRunnerError(RuntimeError):
    """Fail-closed error for #237 runner configuration/invariant violations."""


class RawCandidateObserver:
    """Observe one adapter candidate without changing request/response behavior.

    The wrapper deliberately exposes the same capability and identity attributes
    consumed by CaseStructuringService. It returns the delegate object unchanged,
    while retaining a deep-copied RAW_PROVIDER view for diagnostic comparison.
    A second provider invocation is rejected before reaching the delegate.
    """

    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.structured_generation_capability = (
            delegate.structured_generation_capability
        )
        self.adapter_id = delegate.adapter_id
        self.provider_id = delegate.provider_id
        self.provider_calls = 0
        self.raw_candidate: dict[str, Any] | None = None
        self.generation_evidence: GenerationEvidence | None = None

    def structure_intake(
        self,
        *,
        case_input: dict[str, Any],
        route: Any,
    ) -> dict[str, Any]:
        if self.provider_calls != 0:
            raise ValidationRunnerError(
                "#237 permits exactly one provider inference per case"
            )
        self.provider_calls += 1
        try:
            candidate = self.delegate.structure_intake(
                case_input=case_input,
                route=route,
            )
        except Exception as exc:
            observed = getattr(exc, "generation_evidence", None)
            if isinstance(observed, GenerationEvidence):
                self.generation_evidence = observed
            raise

        observed = getattr(candidate, "generation_evidence", None)
        if isinstance(observed, GenerationEvidence):
            self.generation_evidence = observed
        self.raw_candidate = deepcopy(dict(candidate))
        return candidate


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold()


def _canonical_sha(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(value))


def _profile_document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationRunnerError("LLM profile root must be an object")
    return value


def load_issue0237_profile(
    path: Path = PROFILE_PATH,
) -> tuple[dict[str, Any], LLMPlatformConfig]:
    """Load and fail-close on the exact #133 one-attempt runtime policy."""
    profile = _profile_document(path)
    config = load_platform_config(path)

    if profile.get("profile_id") != EXPECTED_PROFILE_ID:
        raise ValidationRunnerError(
            f"expected profile_id {EXPECTED_PROFILE_ID!r}"
        )
    admission = profile.get("admission")
    if not isinstance(admission, dict) or admission.get("issue_number") != EXPECTED_ADMISSION_ISSUE:
        raise ValidationRunnerError("profile is not the runtime admitted by issue #133")
    if config.adapter != "openai-compatible":
        raise ValidationRunnerError("#237 requires the admitted OpenAI-compatible adapter")
    if config.primary_attempts != 1:
        raise ValidationRunnerError("#237 requires primary_attempts=1")
    if config.review_on_invalid_output or config.review_on_provider_error:
        raise ValidationRunnerError("#237 forbids review/retry fallback")
    if config.request_options.get("n", 1) != 1:
        raise ValidationRunnerError("#237 requires exactly one completion candidate")
    if config.request_options.get("stream", False):
        raise ValidationRunnerError("#237 requires a single non-streaming candidate")
    return profile, config


def _fact_summary(fact: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "fact_ref",
        "label",
        "state",
        "requires_confirmation",
        "needed_information",
        "source_quote",
        "semantic_key",
        "measurement",
    )
    return {name: deepcopy(fact[name]) for name in fields if name in fact}


def _question_summary(question: dict[str, Any]) -> dict[str, Any]:
    fields = ("question_ref", "text", "category", "status")
    return {name: deepcopy(question[name]) for name in fields if name in question}


def _boundary_summary(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if draft is None:
        return None
    return {
        "facts": [_fact_summary(fact) for fact in draft.get("facts", [])],
        "questions": [
            _question_summary(question) for question in draft.get("questions", [])
        ],
    }


def _valid_user_fact(fact: dict[str, Any], problem_text: str) -> bool:
    quote = fact.get("source_quote")
    return (
        fact.get("state") == "user_provided"
        and fact.get("requires_confirmation") is False
        and "needed_information" not in fact
        and isinstance(quote, str)
        and bool(quote)
        and quote in problem_text
    )


def _user_facts_matching(
    intake: dict[str, Any],
    problem_text: str,
    predicate: Callable[[str], bool],
) -> list[dict[str, Any]]:
    result = []
    for fact in intake.get("facts", []):
        if not _valid_user_fact(fact, problem_text):
            continue
        quote = str(fact["source_quote"])
        if predicate(_fold(quote)):
            result.append(fact)
    return result


def _unresolved_matching(
    intake: dict[str, Any],
    predicate: Callable[[str], bool],
) -> list[dict[str, Any]]:
    result = []
    for fact in intake.get("facts", []):
        if fact.get("state") not in {"missing", "ambiguous"}:
            continue
        descriptor = " ".join(
            str(fact.get(name, "")) for name in ("label", "needed_information")
        )
        if predicate(_fold(descriptor)):
            result.append(fact)
    return result


def _contains_all(*terms: str) -> Callable[[str], bool]:
    folded_terms = tuple(_fold(term) for term in terms)
    return lambda text: all(term in text for term in folded_terms)


def _score_case_a(intake: dict[str, Any], problem_text: str) -> list[str]:
    failures: list[str] = []

    residence = _user_facts_matching(
        intake,
        problem_text,
        _contains_all("residente fiscal", "colombia"),
    )
    if not residence:
        failures.append("A: Colombian fiscal residence is not a proven user_provided fact")

    activity = _user_facts_matching(
        intake,
        problem_text,
        _contains_all("actividades digitales", "cuenta propia"),
    )
    if not activity:
        failures.append("A: self-employed digital activity is not a proven user_provided fact")

    expected_semantics = {
        "col.tax.natural_person.gross_income": {
            "decimal_value": "1100",
            "unit": "UVT",
            "uvt_year": 2025,
        },
        "col.tax.natural_person.gross_patrimony": {
            "decimal_value": "3900",
            "unit": "UVT",
            "uvt_year": 2025,
        },
    }
    for semantic_key, measurement in expected_semantics.items():
        matches = [
            fact
            for fact in intake.get("facts", [])
            if _valid_user_fact(fact, problem_text)
            and fact.get("semantic_key") == semantic_key
            and fact.get("measurement") == measurement
        ]
        if not matches:
            failures.append(
                f"A: {semantic_key} did not preserve its supported UVT measurement"
            )

    for name, predicate in (
        ("residence", _contains_all("residen", "fiscal", "colomb")),
        ("gross income", _contains_all("ingres", "brut", "uvt")),
        ("gross patrimony", _contains_all("patrimon", "brut", "uvt")),
        ("digital activity", _contains_all("activ", "digital", "cuenta propia")),
    ):
        unresolved = _unresolved_matching(intake, predicate)
        if unresolved:
            failures.append(
                f"A: explicit {name} still remains missing/ambiguous after normalization"
            )
    return failures


def _b_expectations() -> tuple[tuple[str, Callable[[str], bool]], ...]:
    return (
        ("Colombian SAS", _contains_all("sas colombiana")),
        (
            "Bogota execution",
            lambda text: "bogota" in text and ("presta" in text or "ejecut" in text),
        ),
        (
            "Canadian domiciled customer",
            _contains_all("sociedad domiciliada", "canada"),
        ),
        (
            "absence of Colombian presence",
            lambda text: all(
                term in text
                for term in ("no tiene", "domicilio", "sucursal", "empleados", "activos", "colombia")
            ),
        ),
        (
            "execution from Colombia",
            _contains_all("ejecuta desde colombia"),
        ),
        (
            "exclusive foreign use",
            lambda text: "exclusiv" in text and "colombia" in text and ("usan" in text or "explot" in text),
        ),
        (
            "retained support documents",
            lambda text: sum(
                term in text
                for term in ("contrato", "facturas", "comprobantes", "entregables", "aceptacion")
            ) >= 3,
        ),
        (
            "August 2026 billing/payment",
            lambda text: "agosto" in text and "2026" in text and "factur" in text and "pago" in text,
        ),
    )


def _score_case_b(intake: dict[str, Any], problem_text: str) -> list[str]:
    failures: list[str] = []
    for name, predicate in _b_expectations():
        matches = _user_facts_matching(intake, problem_text, predicate)
        if not matches:
            failures.append(f"B: {name} is not a proven user_provided fact")
            continue
        for fact in matches:
            if "semantic_key" in fact or "measurement" in fact:
                failures.append(
                    f"B: unsupported semantic_key/measurement synthesized for {name}"
                )
        unresolved = _unresolved_matching(intake, predicate)
        if unresolved:
            failures.append(
                f"B: {name} still remains a generic missing/ambiguous confirmation"
            )
    return failures


def _score_case_c(intake: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    iva_questions = [
        question
        for question in intake.get("questions", [])
        if "iva" in _fold(str(question.get("text", "")))
    ]
    if not iva_questions:
        failures.append("C: no substantive IVA question survived intake")
        return failures
    if not any(question.get("category") == "legal" for question in iva_questions):
        failures.append("C: substantive IVA question was not preserved as category=legal")
    if any(question.get("category") != "legal" for question in iva_questions):
        failures.append("C: an IVA treatment question was degraded/relabelled from legal")
    return failures


def score_boundary(case_id: str, intake: dict[str, Any]) -> list[str]:
    """Score only the intake boundary criteria explicitly owned by #237."""
    problem_text = CASE_TEXTS[case_id]
    if case_id == "A":
        return _score_case_a(intake, problem_text)
    if case_id == "B":
        return _score_case_b(intake, problem_text)
    if case_id == "C":
        return _score_case_c(intake)
    raise ValidationRunnerError(f"unsupported #237 case {case_id!r}")


def recovery_path_exercised(
    raw: dict[str, Any] | None,
    final: dict[str, Any] | None,
    problem_text: str,
) -> bool:
    """Detect an actual same-fact RAW unresolved -> FINAL explicit recovery."""
    if raw is None or final is None:
        return False
    final_by_ref = {
        fact.get("fact_ref"): fact
        for fact in final.get("facts", [])
        if isinstance(fact.get("fact_ref"), str)
    }
    for raw_fact in raw.get("facts", []):
        if raw_fact.get("state") not in {"missing", "ambiguous"}:
            continue
        final_fact = final_by_ref.get(raw_fact.get("fact_ref"))
        if final_fact is not None and _valid_user_fact(final_fact, problem_text):
            return True
    return False


def _error_record(exc: BaseException) -> dict[str, Any]:
    record: dict[str, Any] = {"type": type(exc).__name__}
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        record["code"] = code
    stage = getattr(exc, "failure_stage", None)
    if isinstance(stage, str):
        record["failure_stage"] = stage
    path = getattr(exc, "failure_path", None)
    if isinstance(path, str):
        record["failure_path"] = path
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str):
        record["detail"] = detail
    else:
        record["detail"] = str(exc)
    return record


def execute_case(
    case_id: str,
    *,
    config: LLMPlatformConfig,
    profile_id: str,
    protected_main_sha: str,
    adapter: Any,
    require_provider_evidence: bool,
) -> dict[str, Any]:
    """Run one and only one provider→intake boundary attempt for A, B or C."""
    problem_text = CASE_TEXTS[case_id]
    ci = case_input(problem_text)
    observer = RawCandidateObserver(adapter)
    service = CaseStructuringService(config, observer)
    final: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    try:
        final = service.structure(ci).intake
    except (CaseContractError, LLMClientError, ValidationRunnerError) as exc:
        error = _error_record(exc)
    except Exception as exc:  # keep one bounded result; never retry a surprise failure
        error = _error_record(exc)

    raw = observer.raw_candidate
    evidence = observer.generation_evidence
    failures: list[str] = []
    if observer.provider_calls != 1:
        failures.append(
            f"expected exactly one provider call, observed {observer.provider_calls}"
        )
    if require_provider_evidence and (
        evidence is None or evidence.provider_contacted is not True
    ):
        failures.append("real provider contact evidence is absent")
    if error is not None:
        failures.append("boundary execution failed: " + error.get("detail", error["type"]))
    elif final is None:
        failures.append("boundary execution returned no final IntakeDraft")
    else:
        failures.extend(score_boundary(case_id, final))

    result = {
        "case": case_id,
        "protected_main_sha": protected_main_sha,
        "profile_id": profile_id,
        "provider": config.provider,
        "requested_model": config.primary.name,
        "served_model": evidence.served_model if evidence is not None else None,
        "provider_request_sha256": (
            evidence.provider_request_sha256 if evidence is not None else None
        ),
        "case_input_canonical_sha256": _canonical_sha(ci),
        "candidate_raw_sha256": _canonical_sha(raw) if raw is not None else None,
        "final_intake_sha256": _canonical_sha(final) if final is not None else None,
        "usage": deepcopy(evidence.usage) if evidence is not None else None,
        "finish_reason": evidence.finish_reason if evidence is not None else None,
        "provider_calls": observer.provider_calls,
        "RAW_PROVIDER": _boundary_summary(raw),
        "FINAL_INTAKE": _boundary_summary(final),
        "RECOVERY_PATH_EXERCISED": recovery_path_exercised(
            raw,
            final,
            problem_text,
        ),
        "status": "PASS" if not failures else "FAIL",
        "failure_cause": failures,
    }
    if error is not None:
        result["error"] = error
    return result


def run_validation(
    *,
    protected_main_sha: str,
    profile_path: Path = PROFILE_PATH,
    adapter_factory: Callable[[LLMPlatformConfig, str], Any] | None = None,
    require_provider_evidence: bool = True,
) -> dict[str, Any]:
    """Execute exactly A, B and C once each and return a non-persistent report."""
    if _SHA40_RE.fullmatch(protected_main_sha) is None:
        raise ValidationRunnerError("protected_main_sha must be a lowercase 40-hex SHA")

    profile, config = load_issue0237_profile(profile_path)
    profile_id = str(profile["profile_id"])
    factory = adapter_factory or (
        lambda current_config, _case_id: OpenAICompatibleIntakeAdapter(current_config)
    )

    results = []
    for case_id in ("A", "B", "C"):
        adapter = factory(config, case_id)
        results.append(
            execute_case(
                case_id,
                config=config,
                profile_id=profile_id,
                protected_main_sha=protected_main_sha,
                adapter=adapter,
                require_provider_evidence=require_provider_evidence,
            )
        )

    total_calls = sum(int(result["provider_calls"]) for result in results)
    return {
        "issue": 237,
        "boundary": "provider->CASE-v4-intake",
        "protected_main_sha": protected_main_sha,
        "profile_id": profile_id,
        "provider": config.provider,
        "requested_model": config.primary.name,
        "total_provider_calls": total_calls,
        "expected_provider_calls": 3,
        "status": (
            "PASS"
            if total_calls == 3 and all(result["status"] == "PASS" for result in results)
            else "FAIL"
        ),
        "cases": results,
    }


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run issue #237's focused real-provider CASE v4 intake boundary validation"
        )
    )
    parser.add_argument(
        "--protected-main-sha",
        required=True,
        help="exact converged protected-main SHA being validated",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=PROFILE_PATH,
        help="admitted #133 runtime profile (default: repository profile)",
    )
    args = parser.parse_args(argv)

    current_head = _git_head()
    if current_head != args.protected_main_sha:
        raise ValidationRunnerError(
            "checkout HEAD does not match --protected-main-sha; refusing provider calls"
        )

    report = run_validation(
        protected_main_sha=args.protected_main_sha,
        profile_path=args.profile,
        require_provider_evidence=True,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
