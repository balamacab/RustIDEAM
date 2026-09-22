#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_command(args: list[str], *, expect_json: bool) -> Any:
    proc = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        raise RuntimeError(
            f"command failed with exit code {proc.returncode}: "
            + " ".join(args)
        )

    if not expect_json:
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "expected JSON from command but received:\n"
            + proc.stdout
        ) from exc


def tool(name: str) -> str:
    return str(Path(__file__).resolve().parent / name)


def require_key(obj: dict[str, Any], key: str, stage: str) -> Any:
    if key not in obj:
        raise RuntimeError(
            f"stage {stage} did not return required key: {key}"
        )
    return obj[key]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a declarative deterministic col-taxdata pipeline using "
            "the existing stage tools as the only implementation logic."
        )
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--schema-dir", default="schema")
    parser.add_argument(
        "--report-dir",
        default="data/pipeline_runs",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    pipeline_id = cfg["pipeline_id"]
    resolution_method = cfg.get(
        "resolution_method",
        "canonical_reference_resolver:1",
    )
    sources = cfg.get("sources", [])

    if not sources:
        raise RuntimeError("pipeline config has no sources")

    allowed_roles = {"compiled_target", "operative_source"}
    for source in sources:
        role = source.get("role")
        if role not in allowed_roles:
            raise RuntimeError(
                f"unsupported source role {role!r}; "
                f"expected one of {sorted(allowed_roles)}"
            )

    report: dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "config": str(config_path),
        "started_at": utc_now(),
        "resolution_method": resolution_method,
        "stages": [],
    }

    init_result = run_command(
        [
            sys.executable,
            tool("init_db.py"),
            "--db",
            args.db,
            "--schema-dir",
            args.schema_dir,
        ],
        expect_json=False,
    )
    report["stages"].append(
        {
            "stage": "init_db",
            "result": init_result,
        }
    )

    operative_runs: list[dict[str, str]] = []

    ordered_sources = sorted(
        enumerate(sources),
        key=lambda item: (
            0 if item[1]["role"] == "compiled_target" else 1,
            item[0],
        ),
    )

    for _, source in ordered_sources:
        source_id = source["source_id"]
        role = source["role"]

        fetch_result = run_command(
            [
                sys.executable,
                tool("fetch_source.py"),
                "--source-id",
                source_id,
                "--url",
                source["url"],
                "--authority",
                source["authority"],
                "--source-kind",
                source["source_kind"],
                "--db",
                args.db,
                "--data-root",
                args.data_root,
            ],
            expect_json=True,
        )
        manifestation_id = require_key(
            fetch_result,
            "manifestation_id",
            f"fetch:{source_id}",
        )
        report["stages"].append(
            {
                "stage": "fetch",
                "source_id": source_id,
                "role": role,
                "result": fetch_result,
            }
        )

        extraction_result = run_command(
            [
                sys.executable,
                tool("extract_normograma_html.py"),
                "--manifestation-id",
                manifestation_id,
                "--db",
                args.db,
                "--data-root",
                args.data_root,
            ],
            expect_json=True,
        )
        extraction_id = require_key(
            extraction_result,
            "extraction_id",
            f"extract:{source_id}",
        )
        report["stages"].append(
            {
                "stage": "extract",
                "source_id": source_id,
                "role": role,
                "result": extraction_result,
            }
        )

        if role == "compiled_target":
            register_result = run_command(
                [
                    sys.executable,
                    tool("register_compiled_provisions.py"),
                    "--extraction-id",
                    extraction_id,
                    "--db",
                    args.db,
                ],
                expect_json=True,
            )
            report["stages"].append(
                {
                    "stage": "register_compiled_provisions",
                    "source_id": source_id,
                    "result": register_result,
                }
            )

            conflict_result = run_command(
                [
                    sys.executable,
                    tool("detect_provision_conflicts.py"),
                    "--extraction-id",
                    extraction_id,
                    "--db",
                    args.db,
                ],
                expect_json=True,
            )
            report["stages"].append(
                {
                    "stage": "detect_provision_conflicts",
                    "source_id": source_id,
                    "result": conflict_result,
                }
            )
            continue

        identity_result = run_command(
            [
                sys.executable,
                tool("register_document_identity.py"),
                "--extraction-id",
                extraction_id,
                "--db",
                args.db,
            ],
            expect_json=True,
        )
        report["stages"].append(
            {
                "stage": "register_document_identity",
                "source_id": source_id,
                "result": identity_result,
            }
        )

        detection_result = run_command(
            [
                sys.executable,
                tool("detect_normative_references.py"),
                "--extraction-id",
                extraction_id,
                "--db",
                args.db,
            ],
            expect_json=True,
        )
        detection_run_id = require_key(
            detection_result,
            "detection_run_id",
            f"detect_references:{source_id}",
        )
        report["stages"].append(
            {
                "stage": "detect_normative_references",
                "source_id": source_id,
                "result": detection_result,
            }
        )
        operative_runs.append(
            {
                "source_id": source_id,
                "extraction_id": extraction_id,
                "detection_run_id": detection_run_id,
            }
        )

    for item in operative_runs:
        source_id = item["source_id"]
        extraction_id = item["extraction_id"]
        detection_run_id = item["detection_run_id"]

        resolution_result = run_command(
            [
                sys.executable,
                tool("resolve_references.py"),
                "--detection-run-id",
                detection_run_id,
                "--relations-only",
                "--db",
                args.db,
            ],
            expect_json=True,
        )
        report["stages"].append(
            {
                "stage": "resolve_references",
                "source_id": source_id,
                "result": resolution_result,
            }
        )

        explicit_relations = None
        for stage in report["stages"]:
            if (
                stage.get("stage")
                == "detect_normative_references"
                and stage.get("source_id") == source_id
            ):
                explicit_relations = stage["result"].get(
                    "relation_count"
                )
                break

        processed = resolution_result.get("mentions_processed")
        resolved = resolution_result.get("resolved")
        ambiguous = resolution_result.get("ambiguous")
        unresolved = resolution_result.get("unresolved")

        if explicit_relations is None:
            raise RuntimeError(
                f"missing relation_count for {source_id}"
            )

        if (
            processed != explicit_relations
            or resolved != explicit_relations
            or ambiguous != 0
            or unresolved != 0
        ):
            raise RuntimeError(
                "refusing promotion because explicit relations are not "
                f"fully and unambiguously resolved for {source_id}: "
                f"relations={explicit_relations}, processed={processed}, "
                f"resolved={resolved}, ambiguous={ambiguous}, "
                f"unresolved={unresolved}"
            )

        promotion_result = run_command(
            [
                sys.executable,
                tool("promote_relationships.py"),
                "--detection-run-id",
                detection_run_id,
                "--resolution-method",
                resolution_method,
                "--db",
                args.db,
            ],
            expect_json=True,
        )
        report["stages"].append(
            {
                "stage": "promote_relationships",
                "source_id": source_id,
                "result": promotion_result,
            }
        )

        temporality_result = run_command(
            [
                sys.executable,
                tool("extract_document_temporality.py"),
                "--extraction-id",
                extraction_id,
                "--db",
                args.db,
            ],
            expect_json=True,
        )
        report["stages"].append(
            {
                "stage": "extract_document_temporality",
                "source_id": source_id,
                "result": temporality_result,
            }
        )

    report["finished_at"] = utc_now()
    report["status"] = "ok"

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{pipeline_id}.latest.json"
    tmp_path = report_path.with_suffix(
        report_path.suffix + ".tmp"
    )
    tmp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(report_path)

    summary = {
        "pipeline_id": pipeline_id,
        "status": "ok",
        "started_at": report["started_at"],
        "finished_at": report["finished_at"],
        "stage_count": len(report["stages"]),
        "report_path": str(report_path),
        "operative_runs": operative_runs,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
