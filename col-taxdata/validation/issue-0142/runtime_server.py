#!/usr/bin/env python3
"""Issue #142 isolated REST runtime over the exact validated main source tree.

This is validation harness code, not product implementation. It composes the
already-merged CASE v4 application and #144 REST adapter against an isolated
database/case root and the #133 admitted intake profile.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

APP_ROOT = Path(os.environ.get("ISSUE142_APP_ROOT", "/app"))
sys.path.insert(0, str(APP_ROOT / "tools"))

from case_application import ResearchAnalysisOutcome, analyze_case  # noqa: E402
from case_attempt_evidence import RejectedStructuringEvidenceStore  # noqa: E402
from case_intake_factory import build_case_intake_composition  # noqa: E402
from case_rest_api import CaseRESTApplication, CaseRESTServer  # noqa: E402


def main() -> None:
    db_path = Path(os.environ["ISSUE142_DB_PATH"])
    case_root = Path(os.environ["ISSUE142_CASE_ROOT"])
    config_path = Path(os.environ["ISSUE142_CONFIG"])
    host = os.environ.get("ISSUE142_REST_HOST", "0.0.0.0")
    port = int(os.environ.get("ISSUE142_REST_PORT", "8765"))

    audit_root = case_root / "_audit" / "rejected-structuring-attempts"
    composition = build_case_intake_composition(
        config_path,
        evidence_store=RejectedStructuringEvidenceStore(audit_root),
    )

    def research(case_input, *, request_fingerprints=None):
        outcome = analyze_case(
            case_input=case_input,
            db_path=db_path,
            case_root=case_root,
            structurer=composition.structurer,
            dry_run=False,
            request_fingerprints=request_fingerprints,
        )
        if not isinstance(outcome, ResearchAnalysisOutcome):
            raise RuntimeError("issue #142 runtime unexpectedly left CASE v4 path")
        return outcome.bundle

    server = CaseRESTServer(
        (host, port),
        CaseRESTApplication(research, forward_request_fingerprints=True),
    )
    print(
        f"issue142_rest_ready host={host} port={port} "
        f"provider={composition.provider} model={composition.primary_model}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
