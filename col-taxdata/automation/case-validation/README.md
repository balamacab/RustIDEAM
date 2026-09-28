# Case-validation control state

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

## Public-repository boundary

Only synthetic/public-safe case descriptions belong here. Do not store secrets, private client payloads, credentials, tokens or confidential case documents.

## Schema

`schemas/control-state.schema.json` defines the record shapes and shared enums. YAML records are JSON-data-model compatible and are validated against the corresponding `$defs` entry by the future worker implementation.
