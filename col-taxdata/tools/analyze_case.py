#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from case_application import (
    AnalysisOutcome,
    CaseAnalysisIntegrityError,
    ResearchAnalysisOutcome,
    analyze_case,
)
from case_attempt_evidence import RejectedStructuringEvidenceStore
from case_intake_factory import build_case_intake_composition
from case_contract_dispatch import V4_CONTRACT_VERSION
from case_contract_validation import CaseContractError
from case_retrieval import RetrievalIntegrityError
from llm_client import (
    ContextLimitError,
    OutputLimitError,
    LLMClientError,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "llm" / "local-platform.yaml"


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, (ContextLimitError, OutputLimitError)):
        return {
            "error": exc.code,
            "detail": exc.detail,
            "context": exc.metadata,
        }
    if isinstance(exc, CaseContractError):
        return {"error": exc.code, "detail": exc.detail}
    if isinstance(exc, LLMClientError):
        return {"error": exc.code, "detail": exc.detail}
    if isinstance(exc, RetrievalIntegrityError):
        return {
            "error": "CASE_EVIDENCE_INTEGRITY_FAILURE",
            "detail": str(exc),
        }
    if isinstance(exc, CaseAnalysisIntegrityError):
        return {"error": exc.code, "detail": exc.detail}
    return {
        "error": "CASE_ANALYSIS_INTEGRITY_FAILURE",
        "detail": str(exc),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Structure a natural-language legal/tax case and run the v4 "
            "platform-owned evidence-first research stage."
        )
    )
    parser.add_argument("--input", required=True, help="UTF-8 natural-language case file")
    parser.add_argument("--as-of-date")
    parser.add_argument("--client-reference")
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--case-root", default="data/cases")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compatibility option. v4 research is intrinsically read-only and "
            "performs no CASE claim registration/materialization."
        ),
    )
    parser.add_argument(
        "--debug-provenance",
        action="store_true",
        help=(
            "Compatibility option for the historical v3 path. v4 research "
            "already returns explicit internal query/hit provenance candidates."
        ),
    )
    args = parser.parse_args()

    problem_text = Path(args.input).read_text(encoding="utf-8")
    case_input: dict[str, object] = {
        "kind": "case_input",
        "contract_version": V4_CONTRACT_VERSION,
        "problem_text": problem_text,
    }
    if args.as_of_date is not None:
        case_input["as_of_date"] = args.as_of_date
    if args.client_reference is not None:
        case_input["client_reference"] = args.client_reference

    try:
        case_root = Path(args.case_root)
        evidence_store = RejectedStructuringEvidenceStore(
            case_root / "_audit" / "rejected-structuring-attempts"
        )
        composition = build_case_intake_composition(
            Path(args.config),
            evidence_store=evidence_store,
        )
        structurer = composition.structurer
        outcome = analyze_case(
            case_input=case_input,
            db_path=Path(args.db),
            case_root=case_root,
            structurer=structurer,
            dry_run=args.dry_run,
            include_debug_provenance=args.debug_provenance,
        )
    except (
        CaseContractError,
        LLMClientError,
        RetrievalIntegrityError,
        CaseAnalysisIntegrityError,
        OSError,
        ValueError,
    ) as exc:
        print(
            json.dumps(_error_payload(exc), ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 2

    if isinstance(outcome, ResearchAnalysisOutcome):
        payload: dict[str, object] = {
            "case_ref": outcome.case_ref,
            "intake_draft": outcome.intake_draft,
            "research_plan": outcome.research_plan,
            "research_result": outcome.research_result,
            "research_evidence_candidates": list(outcome.evidence_candidates),
            "canonical_authorities": list(outcome.authorities),
            "normative_relationships": list(outcome.relationships),
            "unresolved": list(outcome.unresolved),
            "persistence": {
                "mode": outcome.persistence_mode,
                "claims_persisted": 0,
                "research_state_persisted": False,
            },
        }
    else:
        assert isinstance(outcome, AnalysisOutcome)
        payload = {
            "case_ref": outcome.case_ref,
            "case_result": outcome.result,
            "persistence": {
                "mode": outcome.persistence_mode,
                "case_reused": outcome.registration["case_reused"],
                "claims_inserted": outcome.registration["claims_inserted"],
                "claims_reused": outcome.registration["claims_reused"],
                "evidence_inserted": outcome.registration["evidence_inserted"],
                "materializations_updated": outcome.materialization["updated_count"],
                "bundle_valid": outcome.validation["valid"],
            },
        }
        if args.debug_provenance:
            payload["debug"] = {"internal_case_id": outcome.case_id}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
