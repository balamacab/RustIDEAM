#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from case_application import (
    CaseAnalysisIntegrityError,
    analyze_case,
)
from case_contract_validation import CaseContractError, CONTRACT_VERSION
from case_retrieval import RetrievalIntegrityError
from llm_client import (
    ContextLimitError,
    LLMClientError,
    OpenAICompatibleLLMClient,
    CaseStructuringService,
    load_platform_config,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "llm" / "local-platform.yaml"


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, ContextLimitError):
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
    return {
        "error": "CASE_ANALYSIS_INTEGRITY_FAILURE",
        "detail": str(exc),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a natural-language legal/tax case through the v3 case "
            "application service without requiring internal corpus IDs."
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
            "Execute the same registration/materialization path against a "
            "temporary SQLite snapshot and discard it."
        ),
    )
    parser.add_argument(
        "--debug-provenance",
        action="store_true",
        help="Include output-only internal provenance detail in CaseEvidence.",
    )
    args = parser.parse_args()

    problem_text = Path(args.input).read_text(encoding="utf-8")
    case_input: dict[str, object] = {
        "kind": "case_input",
        "contract_version": CONTRACT_VERSION,
        "problem_text": problem_text,
    }
    if args.as_of_date is not None:
        case_input["as_of_date"] = args.as_of_date
    if args.client_reference is not None:
        case_input["client_reference"] = args.client_reference

    try:
        config = load_platform_config(Path(args.config))
        client = OpenAICompatibleLLMClient(config)
        structurer = CaseStructuringService(config, client)
        outcome = analyze_case(
            case_input=case_input,
            db_path=Path(args.db),
            case_root=Path(args.case_root),
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

    payload: dict[str, object] = {
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
