# Case-validation control state

> **Tester execution policy:** the scheduled Tester executes from a clean ephemeral snapshot of current protected main and performs full-platform E2E validation before any GitHub bookkeeping. Open issues/branches/PRs, CI/convergence state, Developer/Generator ownership and prior sweep integration do not block execution. The Tester starts/composes the existing CASE v4 + REST v1 + Web + MCP stack with isolated writable state, runs active non-RETIRED cases through their required outer public surfaces, records outcomes, tears down, and only then persists repository evidence. Historical sections below that imply pre-execution Tester PR/CI/overlap admission are superseded for execution.

This directory is the durable coordination surface for the scheduled stateless case-validation swarm.

It is **not** a replacement for GitHub live state. GitHub remains authoritative for issue, branch, pull-request, CI, merge and convergence state. Records here own only test-case identity/lifecycle, Tester sweep membership and immutable run evidence.

## Layout

```text
automation/case-validation/
├── TestCasePool.yaml
├── cases/
│   └── TC-<id>/
│       ├── case.yaml
│       └── state.yaml
├── sweeps/
│   └── SW-<utc>-<suffix>/
│       ├── discovery.yaml
│       └── result.yaml
├── runs/
│   └── TC-<id>/
│       └── R-<utc>-<suffix>/
│           ├── snapshot.yaml
│           └── result.yaml
├── schemas/
│   └── control-state.schema.json
└── templates/
    ├── case-definition.yaml
    ├── case-state.yaml
    ├── sweep-discovery.yaml
    ├── sweep-result.yaml
    ├── run-snapshot.yaml
    └── run-result.yaml
```

## Mutable versus immutable records

| Record | Writer | Mutability |
| --- | --- | --- |
| `TestCasePool.yaml` | Case Generator | mutable, optimistic concurrency |
| `cases/*/case.yaml` | Case Generator | create-only / immutable |
| `cases/*/state.yaml` | Case Tester | mutable, optimistic concurrency |
| `sweeps/*/discovery.yaml` | Case Tester | create-only / immutable |
| `sweeps/*/result.yaml` | Case Tester | create-only / immutable |
| `runs/*/*/snapshot.yaml` | Case Tester | create-only / immutable |
| `runs/*/*/result.yaml` | Case Tester | create-only / immutable |
| Developer workers | none | must not write case-pool lifecycle state |
| Controller Monitor | exceptional repair only | evidence-driven |

Mutable writes MUST use the exact Git blob SHA/version read by the worker. A conflicting write is a failed claim/update, never permission to force-overwrite another worker.

`generation` fields provide an additional logical version. They do not replace optimistic concurrency against the repository blob.

## Case definition and state

A case definition is frozen at creation. If the legal problem itself must materially change, create a new case identity or explicitly retire/supersede the old case; do not rewrite historical runs against a changed definition.

Case lifecycle is stored separately in `state.yaml` so the Tester may transition NEW/READY/RUNNING/BLOCKED/CLOSED without mutating the legal test definition.

Blocking issue numbers may be recorded in case state, but their cached status is never authoritative. Before unblocking a case the Tester re-reads GitHub live and verifies the issue-specific convergence requirement.

## Tester sweep

At wake-up the Tester creates one immutable `discovery.yaml` containing every case eligible at discovery time. That candidate set does not grow during the sweep.

Immediately before each candidate is executed, live eligibility is revalidated. If still eligible, the Tester creates the run `snapshot.yaml` **before** execution and binds the run to the exact main/runtime/corpus/harness/control identities. The final outcome is written once to `result.yaml`.

A case that becomes eligible after discovery waits for the next sweep. A case that became ineligible is recorded as skipped in the sweep result.

## Historical evidence

Sweep discovery/result records and run snapshot/result records are append-only historical evidence.

Never:
- convert an old FAIL to PASS;
- overwrite a run after a product fix;
- retry until a scored attempt passes;
- relabel a run as testing a newer main SHA.

A later attempt always gets a new run ID and new execution snapshot.

## Imported pre-scheduler validation

Existing validation evidence may be bootstrapped into this control surface without pretending it was produced by a scheduled sweep.

For an imported historical run:
- `origin: imported_historical_validation` distinguishes it from a normal scheduled attempt;
- `sweep_id` is `null` because no scheduler discovery snapshot existed;
- timestamps that are not supported by preserved evidence remain `null` rather than being inferred;
- the run keeps exact source references and cryptographic identities from the original validation record;
- a current imported case definition may be linked to the historical run, but it must not be falsely described as a file that existed at execution time;
- the historical PASS/FAIL remains immutable and never authorizes a retry-until-pass;
- the Controller Monitor may perform the one-time bootstrap write, after which normal Generator/Tester ownership applies.

The first bootstrap is the existing #142 controlled A/B/C validation campaign. Its imported runs remain historical FAIL evidence while current case state separately records live blocking issues that must be revalidated against GitHub before any future run.


## Generator batch persistence

When one Generator sweep creates one or more cases, the new immutable `case.yaml` files, their initial `state.yaml` files and the corresponding `TestCasePool.yaml` generation update form **one logical batch**.

The preferred GitHub persistence path is one atomic Git tree/commit on a dedicated Generator branch:

1. read protected `main`, the exact pool blob and its `generation`;
2. decide the permitted case set from that snapshot;
3. prepare all new case definitions/states plus the complete next pool content;
4. create one Git tree based on the exact observed main tree;
5. create one commit whose parent is the exact observed main SHA;
6. move only the dedicated Generator branch to that commit with a non-forced ref update;
7. open the normal integration PR;
8. revalidate that protected main/pool did not advance incompatibly before integration.

A Generator MUST NOT use Morichal/SSH or another runtime filesystem as a second writer for repository coordination state. If GitHub persistence cannot be completed safely, the sweep aborts without changing the authoritative pool and without retry loops.

A branch created before persistence but still identical to its base is only an abandoned operational artifact. It is not a generated case, active lifecycle state, Tester work or implementation ownership.

## Public-repository boundary

Only synthetic/public-safe case descriptions belong here. Do not store secrets, private client payloads, credentials, tokens or confidential case documents.

## Schema

`schemas/control-state.schema.json` defines the record shapes and shared enums. YAML records are JSON-data-model compatible and are validated against the corresponding `$defs` entry by the future worker implementation.


## Tester runtime admission and CI integration

Before a non-empty scheduled Tester sweep creates its discovery snapshot or consumes any candidate, the Tester MUST preflight the exact harness/runtime path it will use.

Mandatory preflight:

- resolve the current CASE, REST and MCP contracts from protected `main`;
- for normal newly generated cases, use the current CASE v4 / REST v1 path unless the case definition explicitly pins a historical compatibility contract;
- never execute a v4 case through the historical v3 compatibility adapter;
- verify harness dependencies in the exact execution environment before discovery;
- validate harness-generated public request fields against the active public contract before discovery, including external correlation/client-reference fields;
- never use a reserved internal CASE identifier as a public client correlation value when the active contract rejects it;
- if any harness/runtime prerequisite fails, abort before discovery/run creation and report a preflight failure rather than consuming a candidate as `NOT_EXECUTED`.

Repository integration must also obey the current trusted CI policy. Each non-empty Tester sweep therefore creates one **validation-only integration issue** and uses a CI-compliant branch of the form:

`agent/issue-<issue-number>-case-tester-sweep-<slug>`

The sweep PR must close only that validation-only issue and must carry normal `col-taxdata-agent-metadata`. This issue is coordination/audit ownership for the sweep, not a product defect and not Developer implementation work.

The validation-only issue exists so the required trusted `CI Gate` and autonomous merge/convergence workflow can operate without weakening repository branch/PR policy.


### Dedicated Tester harness container

The scheduled Tester MUST execute its harness/preflight work in the project-owned `case-tester` Compose service, not in the normal `taxdata` service.

The normal `taxdata` image intentionally remains dependency-minimal. Tester-only dependencies are exact-version pinned in:

`requirements-case-tester.txt`

The required preflight is:

```bash
docker compose build case-tester
docker compose run --rm case-tester \
  python3 tools/case_tester_preflight.py
```

A successful preflight prints one JSON object with `status=PASS`, CASE contract `4.0.0`, REST API `1.0.0`, endpoint `/v1/cases`, and exact installed/declared versions for `yaml`/PyYAML, `jsonschema`, and `requests`.

If the command fails, the activation stops before discovery exactly as required by the Tester contract. Do not fall back to `docker compose run --rm taxdata`, do not install packages ad hoc, and do not weaken or bypass the preflight.

## Canonical writable CASE v4 REST bootstrap

Issue #255 makes schema readiness part of the product-owned runtime boundary. After
the Tester creates an isolated writable SQLite copy, it MUST start CASE v4 REST
through:

```bash
python3 tools/case_rest_runtime.py \
  --db /validation/state/taxdata.sqlite \
  --case-root /validation/cases \
  --config config/llm/case-migration-rtx3070-v1.yaml \
  --host 0.0.0.0 \
  --port 8765
```

The runtime uses the same append-only, SHA-256-checked migration engine as
`tools/init_db.py`, verifies migration
`016_case_v4_bundle_persistence.sql` and its required v4 tables, and only then
binds the REST socket. A migration/hash/schema failure is a pre-execution
startup failure; it MUST NOT consume a scored case.

For copied validation state, migrate only the isolated copy. Do not migrate the
source/production corpus merely to run Tester validation. The harness MUST NOT
replace this startup boundary with an ad-hoc REST wrapper that can bind before
schema readiness is established.

