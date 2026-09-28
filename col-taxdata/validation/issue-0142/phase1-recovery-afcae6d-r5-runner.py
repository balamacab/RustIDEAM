#!/usr/bin/env python3
"""Execute issue #142 Phase-1 validation without patching product code.

The runner is deliberately external to the application. It snapshots the live
corpus with SQLite's online backup API, builds exact-main images, runs exactly
one fresh A/B/C research execution each through REST/web/MCP respectively, and
leaves the isolated stack running for Phase-2 operator acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

EXPECTED_MAIN = "afcae6d71090307cdb5f573414cc4a455c35a49f"
BACKEND_NAME = "col-taxdata-issue142-r5-backend"
WEB_NAME = "col-taxdata-issue142-r5-web"
MCP_NAME = "col-taxdata-issue142-r5-mcp"
BACKEND_IMAGE = "col-taxdata-issue142-r5-backend:afcae6d"
WEB_IMAGE = "col-taxdata-issue142-r5-web:afcae6d"
MCP_IMAGE = "col-taxdata-issue142-r5-mcp:afcae6d"
REST_PORT = 18767
WEB_PORT = 18082
MCP_PORT = 18002
VALIDATION_NETWORK = "col-taxdata-issue142-r5-net"
PROVIDER_CONTAINER_URL = "http://col-taxdata-llm-gemma4-e2b:8080/v1"
EXPECTED_TOOLS = [
    "research_case",
    "get_case_research",
    "get_authority",
    "get_provision",
    "get_evidence",
    "get_normative_relationships",
    "get_calculation",
]


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run(command: list[str], *, cwd: Path | None = None, check: bool = True,
        timeout: float | None = None, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        check=check,
        timeout=timeout,
        input=input_text,
        capture_output=True,
        text=True,
    )


def git_head(path: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()


def online_backup(source: Path, target: Path) -> None:
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst, pages=4096)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, target)


def raw_manifestation_fingerprint(db: Path) -> tuple[int, str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT manifestation_id, sha256 FROM manifestations "
            "ORDER BY manifestation_id"
        ).fetchall()
    finally:
        con.close()
    return len(rows), sha256_bytes(canonical_bytes(rows))


def wait_tcp(host: str, port: int, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError as exc:
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"TCP {host}:{port} did not become ready: {last}")


def get_json(url: str, timeout: float = 15.0) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_text(url: str, timeout: float = 15.0) -> tuple[int, str]:
    """Fetch a UTF-8 text response without assuming JSON."""
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def wait_text_ready(
    url: str,
    *,
    expected_status: int = 200,
    expected_text: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, str]:
    """Wait for a real HTTP text readiness contract such as #143 /healthz."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, body = get_text(url, timeout=1.0)
            if status == expected_status and (
                expected_text is None or body == expected_text
            ):
                return status, body
            last = (status, body)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"HTTP text readiness failed for {url}: {last}")


def wait_rest_ready(url: str, timeout: float = 60.0) -> None:
    """Wait for the actual #144 HTTP adapter, not merely Docker's published port."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, payload = get_json(url, timeout=1.0)
            if (
                status == 405
                and payload.get("error", {}).get("code")
                == "CASE_API_METHOD_NOT_ALLOWED"
            ):
                return
            last = (status, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"CASE REST adapter did not become ready: {last}")


def wait_json_ready(
    url: str,
    *,
    expected_status: int = 200,
    expected_items: dict[str, object] | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict]:
    """Wait for a real HTTP/JSON readiness contract, never only a TCP socket."""
    deadline = time.monotonic() + timeout
    last: object = None
    expected_items = expected_items or {}
    while time.monotonic() < deadline:
        try:
            status, payload = get_json(url, timeout=1.0)
            if status == expected_status and all(
                payload.get(key) == value for key, value in expected_items.items()
            ):
                return status, payload
            last = (status, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"HTTP readiness failed for {url}: {last}")


def post_json(url: str, payload: dict, timeout: float = 900.0) -> tuple[int, dict, dict]:
    raw = canonical_bytes(payload)
    req = Request(
        url,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, body, headers
    except HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        headers = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, body, headers


def docker_rm(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def docker_inspect(name: str) -> dict:
    return json.loads(run(["docker", "inspect", name]).stdout)[0]


def image_identity(name: str) -> dict:
    data = json.loads(run(["docker", "image", "inspect", name]).stdout)[0]
    return {
        "id": data["Id"],
        "repo_digests": data.get("RepoDigests") or [],
        "created": data.get("Created"),
    }


def verify_control_plan(plan: dict) -> dict:
    verified = {}
    for key in ("A", "B", "C"):
        item = plan["cases"][key]
        input_actual = sha256_bytes(item["problem_text"].encode("utf-8"))
        control_actual = sha256_bytes(canonical_bytes(item["control"]))
        verified[key] = {
            "problem_text_sha256": input_actual,
            "problem_text_match": input_actual == item["problem_text_sha256"],
            "control_sha256": control_actual,
            "control_match": control_actual == item["control_sha256"],
        }
        if not verified[key]["problem_text_match"] or not verified[key]["control_match"]:
            raise RuntimeError(f"control commitment mismatch for case {key}")
    return verified


def request_for(plan: dict, key: str) -> dict:
    item = plan["cases"][key]
    return {
        "problem_text": item["problem_text"],
        "as_of_date": item["as_of_date"],
        "client_reference": f"issue142-{key.lower()}",
        "caller_metadata": {"validation_issue": 142, "case": key},
    }


def summarize_bundle(bundle: dict) -> dict:
    intake = bundle.get("intake_draft") or {}
    plan = bundle.get("research_plan") or {}
    result = bundle.get("research_result") or {}
    questions = intake.get("questions") or []
    tasks = plan.get("tasks") or []
    evidence = bundle.get("evidence_spans") or []
    authorities = bundle.get("authorities") or []
    evals = bundle.get("deterministic_evaluations") or []
    calcs = bundle.get("calculation_traces") or []
    unresolved = bundle.get("unresolved") or []

    forbidden_intake = sorted(
        set(intake).intersection(
            {
                "candidate_claims", "legal_conclusion", "final_answer",
                "authorities", "evidence_spans", "rule_fragments",
                "deterministic_evaluations", "calculation_traces",
            }
        )
    )
    evidence_hash_ok = all(
        isinstance(span.get("exact_text"), str)
        and sha256_bytes(span["exact_text"].encode("utf-8")) == span.get("text_sha256")
        and isinstance(span.get("source_sha256"), str)
        and len(span["source_sha256"]) == 64
        for span in evidence
    )
    open_legal = {
        q.get("question_ref")
        for q in questions
        if q.get("category") == "legal" and q.get("status") == "open"
    }
    platform_required = {
        t.get("question_ref")
        for t in tasks
        if t.get("origin") == "platform_required"
    }
    authority_metadata_ok = all(
        {
            "authority_ref", "document_ref", "legal_function",
            "classification_state", "temporal_state", "publication_metadata",
            "evidence_refs", "source_refs",
        }.issubset(a)
        for a in authorities
    )
    evaluator_ids = sorted({e.get("evaluator_id") for e in evals if e.get("evaluator_id")})
    calculator_ids = sorted({c.get("calculator_id") for c in calcs if c.get("calculator_id")})
    return {
        "bundle_ref": bundle.get("bundle_ref"),
        "status": bundle.get("status"),
        "bundle_sha256": sha256_bytes(canonical_bytes(bundle)),
        "intake_question_count": len(questions),
        "research_task_count": len(tasks),
        "platform_required_question_coverage": sorted(open_legal.issubset(platform_required) and open_legal or []),
        "all_open_legal_questions_have_platform_task": open_legal.issubset(platform_required),
        "forbidden_model_authority_fields_in_intake": forbidden_intake,
        "source_count": len(bundle.get("sources") or []),
        "authority_count": len(authorities),
        "evidence_span_count": len(evidence),
        "relationship_count": len(bundle.get("normative_relationships") or []),
        "rule_fragment_count": len(bundle.get("rule_fragments") or []),
        "evaluation_count": len(evals),
        "calculation_count": len(calcs),
        "unresolved_count": len(unresolved),
        "unresolved_categories": sorted({u.get("category") for u in unresolved if u.get("category")}),
        "evidence_text_and_sha256_reproducible": evidence_hash_ok,
        "authority_metadata_complete": authority_metadata_ok,
        "evaluator_ids": evaluator_ids,
        "calculator_ids": calculator_ids,
        "research_context": result.get("research_context"),
        "authority_displays": [a.get("display_name") for a in authorities],
        "authority_document_types": sorted({a.get("document_type") for a in authorities if a.get("document_type")}),
        "authority_legal_functions": sorted({a.get("legal_function") for a in authorities if a.get("legal_function")}),
        "evidence_excerpt": [
            {
                "evidence_ref": e.get("evidence_ref"),
                "authority_ref": e.get("authority_ref"),
                "provision_ref": e.get("provision_ref"),
                "text_sha256": e.get("text_sha256"),
                "source_sha256": e.get("source_sha256"),
                "exact_text": (e.get("exact_text") or "")[:700],
            }
            for e in evidence[:8]
        ],
    }


def mcp_case(container: str, payload: dict) -> dict:
    encoded = base64.b64encode(canonical_bytes(payload)).decode("ascii")
    client_code = f"""
import asyncio, base64, json
from mcp import Client
payload = json.loads(base64.b64decode({encoded!r}).decode('utf-8'))
async def main():
    async with Client('http://127.0.0.1:8000/mcp', read_timeout_seconds=900) as client:
        tools = await client.list_tools()
        prompts = await client.list_prompts()
        resources = await client.list_resources()
        result = await client.call_tool('research_case', payload)
        if result.is_error:
            raise RuntimeError(str(result.content))
        structured = result.structured_content
        follow = await client.call_tool(
            'get_case_research',
            {{'bundle_handle': structured['bundle_handle']}},
        )
        evidence_view = None
        evidence = structured['bundle'].get('evidence_spans') or []
        if evidence:
            evidence_result = await client.call_tool(
                'get_evidence',
                {{
                    'bundle_handle': structured['bundle_handle'],
                    'evidence_ref': evidence[0]['evidence_ref'],
                }},
            )
            if evidence_result.is_error:
                raise RuntimeError(str(evidence_result.content))
            evidence_view = evidence_result.structured_content
        print('ISSUE142_JSON=' + json.dumps({{
            'tools': [tool.name for tool in tools.tools],
            'prompts': [p.name for p in prompts.prompts],
            'resources': [str(r.uri) for r in resources.resources],
            'research': structured,
            'followup': follow.structured_content,
            'evidence_view': evidence_view,
        }}, ensure_ascii=False, separators=(',', ':')))
asyncio.run(main())
"""
    cp = run(
        ["docker", "exec", "-i", container, "python3", "-"],
        input_text=client_code,
        timeout=1200,
    )
    marker = next(
        (line[len("ISSUE142_JSON="):] for line in cp.stdout.splitlines()
         if line.startswith("ISSUE142_JSON=")),
        None,
    )
    if marker is None:
        raise RuntimeError("MCP client did not emit result marker")
    return json.loads(marker)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-root", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--llm-base-url", required=True)
    args = parser.parse_args()

    validation_root = Path(args.validation_root).resolve()
    repo_source = validation_root / "source"
    project = repo_source / "col-taxdata"
    source_db = Path(args.source_db).resolve()
    state_dir = validation_root / "state"
    case_root = validation_root / "case-state"
    artifacts = validation_root / "artifacts"
    logs = validation_root / "logs"
    for path in (state_dir, case_root, artifacts, logs):
        path.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "issue": 142,
        "phase": 1,
        "started_at_epoch": time.time(),
        "main_sha": git_head(repo_source),
        "errors": [],
    }
    if summary["main_sha"] != EXPECTED_MAIN:
        raise RuntimeError(f"wrong source main SHA: {summary['main_sha']}")

    plan = json.loads((validation_root / "control-plan.json").read_text(encoding="utf-8"))
    summary["controls"] = verify_control_plan(plan)

    provider_origin = args.llm_base_url[:-3] if args.llm_base_url.endswith("/v1") else args.llm_base_url
    health_status, provider_health = get_json(provider_origin.rstrip("/") + "/health")
    model_status, provider_models = get_json(args.llm_base_url.rstrip("/") + "/models")
    props_status, provider_props = get_json(provider_origin.rstrip("/") + "/props")
    summary["provider"] = {
        "configured_profile": "case-migration-rtx3070-v1",
        "expected_model_artifact_sha256": "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8",
        "expected_image_digest": "ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6",
        "health_status": health_status,
        "health": provider_health,
        "models_status": model_status,
        "models": provider_models,
        "props_status": props_status,
        "props": provider_props,
    }

    observed_ctx = provider_props["default_generation_settings"]["n_ctx"]
    observed_alias = provider_props["model_alias"]
    if observed_ctx != 16384 or observed_alias != "gemma-4-E2B-it-Q4_K_M":
        raise RuntimeError(
            f"#133 host provider identity drift: ctx={observed_ctx} alias={observed_alias}"
        )

    db = state_dir / "taxdata.sqlite"
    online_backup(source_db, db)
    before_count, before_digest = raw_manifestation_fingerprint(db)
    summary["snapshot"] = {
        "source_db_size": source_db.stat().st_size,
        "snapshot_db_sha256_before_validation": sha256_bytes(db.read_bytes()),
        "manifestation_count_before": before_count,
        "manifestation_sha_registry_fingerprint_before": before_digest,
    }

    # Build exact-main images before any live case execution.
    run(["docker", "build", "-t", BACKEND_IMAGE, "."], cwd=project, timeout=1200)
    run(["docker", "build", "-t", WEB_IMAGE, "."], cwd=project / "web/case-console", timeout=1200)
    run(["docker", "build", "-t", MCP_IMAGE, "."], cwd=project / "mcp_gateway", timeout=1200)
    summary["images"] = {
        "backend": image_identity(BACKEND_IMAGE),
        "web": image_identity(WEB_IMAGE),
        "mcp": image_identity(MCP_IMAGE),
    }

    migration = run(
        [
            "docker", "run", "--rm",
            "-v", f"{state_dir}:/validation/state",
            BACKEND_IMAGE,
            "python3", "tools/init_db.py",
            "--db", "/validation/state/taxdata.sqlite",
        ],
        timeout=600,
    )
    (logs / "isolated-migrations.log").write_text(
        migration.stdout + migration.stderr, encoding="utf-8"
    )

    # Current implementation tests are evidence, not a replacement for live E2E.
    tests = run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_issue01*.py"],
        cwd=project,
        check=False,
        timeout=1800,
    )
    (logs / "repository-tests.log").write_text(
        tests.stdout + tests.stderr, encoding="utf-8"
    )
    summary["repository_tests"] = {
        "returncode": tests.returncode,
        "tail": (tests.stdout + tests.stderr)[-4000:],
    }

    runtime_server = validation_root / "runtime_server.py"
    for name in (BACKEND_NAME, WEB_NAME, MCP_NAME):
        docker_rm(name)

    backend = run(
        [
            "docker", "run", "-d",
            "--name", BACKEND_NAME,
            "--restart", "unless-stopped",
            "--network", VALIDATION_NETWORK,
            "--label", "col-taxdata.issue=142",
            "-e", f"COL_TAXDATA_LLM_BASE_URL={PROVIDER_CONTAINER_URL}",
            "-e", "ISSUE142_APP_ROOT=/app",
            "-e", "ISSUE142_DB_PATH=/validation/state/taxdata.sqlite",
            "-e", "ISSUE142_CASE_ROOT=/validation/cases",
            "-e", "ISSUE142_CONFIG=/app/config/llm/case-migration-rtx3070-v1.yaml",
            "-e", "ISSUE142_REST_HOST=0.0.0.0",
            "-e", "ISSUE142_REST_PORT=8765",
            "-v", f"{state_dir}:/validation/state",
            "-v", f"{case_root}:/validation/cases",
            "-v", f"{runtime_server}:/validation/runtime_server.py:ro",
            "-p", f"{REST_PORT}:8765",
            BACKEND_IMAGE,
            "python3", "/validation/runtime_server.py",
        ]
    ).stdout.strip()
    wait_rest_ready(f"http://127.0.0.1:{REST_PORT}/v1/cases", 60)

    # Mandatory pre-score network/runtime probe from the same CASE backend
    # container that will execute A/B/C.  This proves the #133 provider is
    # reachable in-container and still has its admitted identity before any
    # scored model request is submitted.
    provider_probe_code = r"""
import json
from urllib.request import urlopen
base = "http://col-taxdata-llm-gemma4-e2b:8080"
out = {}
for name, path in (("health", "/health"), ("props", "/props"), ("models", "/v1/models")):
    with urlopen(base + path, timeout=5) as response:
        out[name] = {"status": response.status, "body": json.loads(response.read())}
print("ISSUE142_PROVIDER_PROBE=" + json.dumps(out, separators=(",", ":")))
"""
    probe_cp = run(
        ["docker", "exec", "-i", BACKEND_NAME, "python3", "-"],
        input_text=provider_probe_code,
        timeout=30,
    )
    marker = next(
        (line[len("ISSUE142_PROVIDER_PROBE="):] for line in probe_cp.stdout.splitlines()
         if line.startswith("ISSUE142_PROVIDER_PROBE=")),
        None,
    )
    if marker is None:
        raise RuntimeError("backend provider preflight did not emit marker")
    backend_provider_probe = json.loads(marker)
    probe_props = backend_provider_probe["props"]["body"]
    probe_models = backend_provider_probe["models"]["body"]
    probe_ctx = probe_props["default_generation_settings"]["n_ctx"]
    probe_alias = probe_props["model_alias"]
    probe_model_ids = [item.get("id") for item in probe_models.get("data", [])]
    if probe_ctx != 16384 or probe_alias != "gemma-4-E2B-it-Q4_K_M" or probe_alias not in probe_model_ids:
        raise RuntimeError(
            f"#133 provider identity drift before scored run: ctx={probe_ctx} alias={probe_alias} models={probe_model_ids}"
        )
    summary["backend_provider_preflight"] = backend_provider_probe

    web = run(
        [
            "docker", "run", "-d",
            "--name", WEB_NAME,
            "--restart", "unless-stopped",
            "--network", VALIDATION_NETWORK,
            "--label", "col-taxdata.issue=142",
            "--add-host", "host.docker.internal:host-gateway",
            "-e", f"CASE_API_UPSTREAM=http://{BACKEND_NAME}:8765",
            "-p", f"{WEB_PORT}:8080",
            WEB_IMAGE,
        ]
    ).stdout.strip()
    mcp = run(
        [
            "docker", "run", "-d",
            "--name", MCP_NAME,
            "--restart", "unless-stopped",
            "--network", VALIDATION_NETWORK,
            "--label", "col-taxdata.issue=142",
            "--read-only",
            "--tmpfs", "/tmp",
            "--security-opt", "no-new-privileges:true",
            "--add-host", "host.docker.internal:host-gateway",
            "-e", f"CASE_REST_BASE_URL=http://{BACKEND_NAME}:8765",
            "-e", "MCP_HOST=0.0.0.0",
            "-e", "MCP_PORT=8000",
            "-e", "MCP_PATH=/mcp",
            "-e", "MCP_TRANSPORT=streamable-http",
            "-e", "CASE_REST_TIMEOUT_SECONDS=900",
            "-p", f"{MCP_PORT}:8000",
            MCP_IMAGE,
        ]
    ).stdout.strip()
    wait_text_ready(
        f"http://127.0.0.1:{WEB_PORT}/healthz",
        expected_text="ok\n",
        timeout=60,
    )
    wait_json_ready(
        f"http://127.0.0.1:{MCP_PORT}/readyz",
        expected_items={"status": "ready"},
        timeout=60,
    )
    summary["containers"] = {
        "backend": backend,
        "web": web,
        "mcp": mcp,
    }

    # A: direct public REST. Exactly one provider-reaching research execution.
    a_request = request_for(plan, "A")
    a_status, a_response, a_headers = post_json(
        f"http://127.0.0.1:{REST_PORT}/v1/cases", a_request
    )
    (artifacts / "case-A-rest.json").write_text(
        json.dumps(a_response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary["case_A"] = {
        "transport": "REST /v1/cases",
        "http_status": a_status,
        "api_version_header": a_headers.get("x-col-taxdata-api-version"),
        "request_sha256": sha256_bytes(canonical_bytes(a_request)),
    }
    if a_status == 200 and "bundle" in a_response:
        summary["case_A"].update(summarize_bundle(a_response["bundle"]))

    # B: real browser deployment boundary via the independent #143 nginx proxy.
    b_request = request_for(plan, "B")
    b_status, b_response, _b_headers = post_json(
        f"http://127.0.0.1:{WEB_PORT}/api/v1/cases", b_request
    )
    (artifacts / "case-B-web.json").write_text(
        json.dumps(b_response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary["case_B"] = {
        "transport": "web console same-origin proxy /api/v1/cases",
        "http_status": b_status,
        "request_sha256": sha256_bytes(canonical_bytes(b_request)),
    }
    if b_status == 200 and "bundle" in b_response:
        summary["case_B"].update(summarize_bundle(b_response["bundle"]))

    # Render the real B payload through the same pure view-model module used by UI.
    node = shutil.which("node")
    summary["web_view_model"] = {"node_available": bool(node)}
    if node and b_status == 200:
        node_script = """
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[1]).href);
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const views = mod.buildViewModels(payload);
if (!views.result || !views.intake || !views.research || !views.evidence ||
    !views.evaluations || !views.unresolved || !views.raw) {
  throw new Error('real E2E response did not produce all operator views');
}
console.log(JSON.stringify(Object.keys(views).sort()));
"""
        rendered = run(
            [
                node, "--input-type=module", "-e", node_script,
                str(project / "web/case-console/app-core.mjs"),
                str(artifacts / "case-B-web.json"),
            ],
            timeout=30,
        )
        summary["web_view_model"].update({
            "real_response_rendered": True,
            "views": rendered.stdout.strip(),
        })

    # C: real MCP Streamable HTTP client -> #145 -> #144 REST -> same backend.
    c_request = request_for(plan, "C")
    mcp_result = mcp_case(MCP_NAME, c_request)
    (artifacts / "case-C-mcp.json").write_text(
        json.dumps(mcp_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    mcp_bundle = mcp_result["research"]["bundle"]
    followup_bundle = mcp_result["followup"]["bundle"]
    summary["case_C"] = {
        "transport": "MCP Streamable HTTP research_case",
        "request_sha256": sha256_bytes(canonical_bytes(c_request)),
        "tool_names": mcp_result["tools"],
        "prompts": mcp_result["prompts"],
        "resources": mcp_result["resources"],
        "exact_tool_surface": mcp_result["tools"] == EXPECTED_TOOLS,
        "followup_bundle_exact_match": followup_bundle == mcp_bundle,
        "first_evidence_projection_exact_match": (
            mcp_result["evidence_view"] is None
            or mcp_result["evidence_view"].get("evidence_span")
            == (mcp_bundle.get("evidence_spans") or [None])[0]
        ),
    }
    summary["case_C"].update(summarize_bundle(mcp_bundle))

    # Lifecycle independence without rebuilding either client.
    run(["docker", "restart", WEB_NAME], timeout=60)
    web_health_status, web_health = wait_text_ready(
        f"http://127.0.0.1:{WEB_PORT}/healthz",
        expected_text="ok\n",
        timeout=60,
    )
    run(["docker", "restart", BACKEND_NAME], timeout=60)
    wait_rest_ready(f"http://127.0.0.1:{REST_PORT}/v1/cases", 60)
    web_health_after_backend_status, web_health_after_backend = wait_text_ready(
        f"http://127.0.0.1:{WEB_PORT}/healthz",
        expected_text="ok\n",
        timeout=60,
    )
    mcp_ready_status, mcp_ready = wait_json_ready(
        f"http://127.0.0.1:{MCP_PORT}/readyz",
        expected_items={"status": "ready"},
        timeout=60,
    )
    summary["independent_lifecycle"] = {
        "web_health_after_web_restart": [web_health_status, web_health],
        "web_health_after_backend_restart": [
            web_health_after_backend_status,
            web_health_after_backend,
        ],
        "mcp_ready": [mcp_ready_status, mcp_ready],
    }

    after_count, after_digest = raw_manifestation_fingerprint(db)
    summary["snapshot"].update({
        "manifestation_count_after": after_count,
        "manifestation_sha_registry_fingerprint_after": after_digest,
        "manifestation_registry_unchanged": (
            before_count == after_count and before_digest == after_digest
        ),
    })

    backend_inspect = docker_inspect(BACKEND_NAME)
    web_inspect = docker_inspect(WEB_NAME)
    mcp_inspect = docker_inspect(MCP_NAME)
    summary["mount_boundaries"] = {
        "backend": [
            {"source": m.get("Source"), "destination": m.get("Destination"), "rw": m.get("RW")}
            for m in backend_inspect.get("Mounts", [])
        ],
        "web": [
            {"source": m.get("Source"), "destination": m.get("Destination"), "rw": m.get("RW")}
            for m in web_inspect.get("Mounts", [])
        ],
        "mcp": [
            {"source": m.get("Source"), "destination": m.get("Destination"), "rw": m.get("RW")}
            for m in mcp_inspect.get("Mounts", [])
        ],
    }

    summary["contracts"] = {
        "case_contract_version": "4.0.0",
        "rest_api_version": "1.0.0",
        "mcp_protocol": "Streamable HTTP",
        "mcp_path": "/mcp",
        "web_proxy_path": "/api/v1/cases",
    }
    summary["stack"] = {
        "rest_local": f"http://127.0.0.1:{REST_PORT}/v1/cases",
        "web_local": f"http://127.0.0.1:{WEB_PORT}/",
        "mcp_local": f"http://127.0.0.1:{MCP_PORT}/mcp",
        "state_identity": sha256_bytes(canonical_bytes({
            "main_sha": EXPECTED_MAIN,
            "snapshot_manifestations": before_digest,
            "control_commitments": {
                k: plan["cases"][k]["control_sha256"] for k in ("A", "B", "C")
            },
        })),
        "left_running_for_operator": True,
    }
    summary["completed_at_epoch"] = time.time()

    out = artifacts / "phase1-summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PHASE1_EXECUTION_COMPLETE",
        "summary": str(out),
        "case_A_status": summary.get("case_A", {}).get("status"),
        "case_B_status": summary.get("case_B", {}).get("status"),
        "case_C_status": summary.get("case_C", {}).get("status"),
        "tests_returncode": summary["repository_tests"]["returncode"],
        "manifestation_registry_unchanged": summary["snapshot"]["manifestation_registry_unchanged"],
        "stack": summary["stack"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
