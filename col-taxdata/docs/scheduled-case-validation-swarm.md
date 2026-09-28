# Scheduled stateless case-validation swarm

Status: **operational/controller contract**

This document defines how the long-running Col-taxdata legal-case validation effort is coordinated through short-lived scheduled workers. It does not change CASE application semantics, canonical legal-data behavior, corpus provenance rules, or any public API contract.

The design exists because long-running conversational agents are not a reliable execution primitive for an iterative process expected to continue for many hours or days. Worker chat context is therefore disposable. Durable state lives in GitHub and repository-backed coordination records.

## 1. Operating model

The system is a **scheduled stateless swarm**:

```text
scheduled invocation
        ↓
reconstruct current state
        ↓
perform one bounded sweep/work unit
        ↓
persist observable result
        ↓
terminate
```

Workers do not remain alive waiting for dependencies, CI, other agents, or future work. A later scheduled invocation re-reads durable state and continues from what is actually true at that time.

Normal cadence is hourly. Exact minute offsets are deployment configuration, but the intended ordering within a cycle is:

```text
Case Generator
      ↓
Case Tester
      ↓
Developer 1 ─┐
Developer 2  │
Developer 3  ├─ parallel
Developer 4  │
Developer 5 ─┘
```

The Controller Monitor is not part of the ordinary dispatch path. It supervises architecture, ownership, deadlocks, exceptional conflicts and changes to the orchestration contract.

## 2. Authority model

The system has deliberately separate authorities.

### GitHub live state

GitHub live is authoritative for:

- issue state and issue ownership;
- issue dependencies encoded by the current project workflow;
- branches;
- pull requests;
- CI/check state;
- merge state;
- current protected `main`;
- post-merge convergence;
- comments/evidence recorded in issue development logs.

A cached file or previous worker observation must never override current GitHub state.

### Case-pool coordination state

Repository-backed case-pool state is authoritative only for:

- legal test-case identity;
- case lifecycle state;
- complexity/domain metadata;
- which case run was last attempted;
- which defect issues currently block a case;
- scheduling/discovery metadata;
- references to immutable sweep/run records.

It may record the last observed GitHub state for audit, but that observation is not authoritative once time has advanced.

### Immutable run evidence

Every executed case run is historical evidence. Once frozen, its identity and result must not be rewritten merely because product behavior later changes.

A later fix creates a later run.

```text
TC-004 / R-003 = FAIL     historical fact
          ↓ defects fixed
TC-004 / R-004 = PASS     new historical fact
```

Never:

```text
R-003 FAIL → PASS
```

### Conversational/task memory

Worker chat history, scheduled-task context and model memory are non-authoritative. A worker must be able to start from an empty conversational context and recover enough state from GitHub plus the case-pool records to act correctly.

CM1 controller memory remains a separate historical/controller continuity mechanism. It must not be repurposed as the live case-pool queue.

## 3. Worker roles

### 3.1 Controller Monitor

Cardinality: normally one interactive controller thread.

Responsibilities:

- preserve the global dependency/ownership graph;
- resolve ambiguous issue ownership;
- intervene when parallel work is semantically unsafe;
- detect duplicate or circular work;
- decide architectural decomposition when a test exposes a systemic problem;
- authorize exceptional runtime/production actions where the project contract requires authorization;
- repair case-pool orchestration state when normal workers cannot do so safely;
- preserve historical failed validation evidence;
- revalidate live state before making controller decisions.

The Controller Monitor is **not** the ordinary dispatcher for scheduled workers and should not be required for a normal Generator → Tester → Developer → Tester cycle.

### 3.2 Case Generator

Cardinality: one scheduled worker.

Purpose: maintain a useful and diverse supply of legal cases so the Tester can continue discovering independent defects across different domains and complexities.

Each invocation performs one bounded inventory sweep:

1. read current case-pool state;
2. revalidate relevant case issues against GitHub live where needed;
3. determine whether sufficient NEW/READY case inventory exists;
4. create only the case work needed to restore useful inventory;
5. persist the new case definitions/references;
6. terminate.

The generator should favor diversity. When replenishing a depleted pool, the default target is a small batch spanning:

- simple;
- medium;
- high complexity;

and, where practical, different legal/tax domains rather than three near-duplicates exercising the same subsystem.

The generator does not execute cases, diagnose product failures, implement defects or consume work from the developer queue.

### 3.3 Case Tester

Cardinality: one scheduled worker.

Purpose: maximize horizontal validation/discovery and generate a sufficiently broad defect front for the developer workers.

Each invocation performs **one sweep over all cases eligible at the beginning of that sweep**.

There is no fixed limit such as three cases. If seven case issues are eligible at discovery time, the Tester attempts all seven, subject to per-case revalidation immediately before execution.

A failure in one case does not stop the sweep.

For each eligible case, the Tester:

1. revalidates whether the case is still executable;
2. captures an execution snapshot;
3. performs exactly one new case run;
4. freezes the run outcome/evidence;
5. creates or reuses the appropriate defect issue(s);
6. records blockers against the case;
7. continues to the next case in the discovery snapshot.

The Tester must never patch product code inside a validation run to make the case pass.

### 3.4 Developer workers

Cardinality: five scheduled workers.

Purpose: provide high horizontal implementation throughput over independent defect issues discovered by validation.

Each Developer invocation may select **at most one** eligible defect issue.

A Developer must:

1. read GitHub live;
2. select one issue whose dependencies are satisfied and whose ownership does not conflict with active work;
3. acquire/establish issue ownership using the project workflow;
4. work only that selected issue;
5. persist implementation/PR/CI state as required by the issue lifecycle;
6. terminate.

If the selected issue exposes additional child defects, the Developer may record/create those issues when within the established controller contract, but it must not switch to implementing a second issue in the same invocation.

If no eligible independent issue exists, the worker exits without inventing work.

Five workers are a **capacity ceiling**, not a requirement that five issues always run in parallel. Dependency and semantic-domain safety take precedence over utilization.

Developers do not directly mutate the case-pool lifecycle. They communicate progress through GitHub issue/PR/CI state. The next Tester sweep observes that live state and decides whether blocked cases have become runnable.

## 4. Case lifecycle

Case state and run result are different concepts.

Recommended case lifecycle:

```text
NEW
 │
 ▼
READY
 │
 ▼
RUNNING
 ├──────────────► CLOSED
 │                    latest required run PASS
 │
 └──────────────► BLOCKED
                       │
                       │ blockers converge
                       ▼
                     READY
```

Definitions:

- `NEW`: generated but not yet executed.
- `READY`: eligible for a new run.
- `RUNNING`: a run is currently being executed by the Tester.
- `BLOCKED`: the latest relevant run found one or more blocking product issues that have not yet converged.
- `CLOSED`: the case's latest required validation run passed under its acceptance contract.
- `RETIRED` may be used only when a case is intentionally superseded or no longer applicable, with rationale preserved.

Run outcome is recorded separately, for example:

- `PASS`
- `FAIL`
- `NOT_EXECUTED` when preflight/revalidation proves that a valid run never began.

A `BLOCKED` case becomes `READY` only after the Tester independently verifies that its blocking issue set has actually converged according to GitHub live state and any issue-specific acceptance requirement.

Issue closure alone is not sufficient evidence if the project lifecycle requires merge/convergence or additional runtime acceptance.

## 5. Tester discovery snapshot

At the beginning of every Tester invocation, the Tester constructs a **discovery snapshot**.

Its purpose is only to freeze which cases belong to this sweep.

The candidate set contains all cases that are, based on the state observed at discovery time:

- `NEW`;
- `READY`;
- or `BLOCKED` but whose recorded blockers now appear converged after live GitHub revalidation.

A discovery snapshot should record at least:

- unique sweep ID;
- discovery timestamp;
- main SHA observed at discovery time;
- candidate case IDs;
- candidate case issue IDs;
- why each case was considered eligible;
- references to the blocker observations used for previously blocked cases.

The discovery `main` SHA is audit context only. It does **not** freeze one code revision for the entire sweep.

### Stable sweep boundary

The candidate set is fixed once the discovery snapshot is created.

A case that becomes eligible after the snapshot was taken waits until the next scheduled Tester invocation.

This prevents recursive/unbounded behavior:

```text
run case
  → merge changes state
  → newly eligible case
  → run newly eligible case
  → more changes
  → ...
```

The Tester therefore drains the complete front known at sweep start without turning one scheduled invocation into a long-lived event loop.

## 6. Per-case revalidation

Discovery eligibility is not an instruction to execute blindly.

Immediately before each candidate case, the Tester must revalidate current live state.

A snapshotted case may be skipped if, since discovery:

- one of its blockers was reopened or ceased to be converged;
- a new hard dependency was established;
- the case was already taken/closed by another valid process;
- required runtime/corpus prerequisites are unavailable;
- executing it would violate an updated controller/runtime safety constraint.

The skip is recorded with its reason. It is not silently removed from history.

Conversely, a case that becomes eligible only after discovery is not added to the current sweep; it waits for the next one.

This preserves the controller invariant:

```text
NO ASUMA, CONFIRME.
```

## 7. Per-case execution snapshot

Immediately before a case actually starts, the Tester captures an **execution snapshot**.

This is the reproducibility identity of that specific run.

The snapshot must include the applicable identities/fingerprints, including at minimum where relevant:

- case ID;
- case-definition version/hash;
- case issue ID;
- run ID;
- exact protected `main` commit SHA selected for the run;
- CASE/application contract version;
- validation harness identity/version/hash;
- independent control-packet identity/hash when the case uses one;
- corpus/research-context fingerprint;
- database/snapshot identity where a frozen database copy is used;
- runtime profile;
- container/image digest;
- model/provider identity and admitted model hash where an internal model is exercised;
- API/MCP/web contract versions where those surfaces are under test;
- blockers/dependencies observed as satisfied immediately before execution;
- exact configuration identities needed to reproduce the run.

The snapshot should reference large artifacts rather than copying them into one state file.

### Main may change between cases

One Tester sweep may legitimately contain:

```text
TC-A → PASS @ main 1000aaa
TC-B → FAIL @ main 2000bbb
TC-C → PASS @ main 3000ccc
TC-D → FAIL @ main 3000ccc
```

This is acceptable because each run has its own execution snapshot.

Freezing `main` for an entire hourly sweep would unnecessarily test later cases against stale code after valid changes have already converged.

### Main may not change inside one run

After a run starts, its selected main SHA is immutable for that run.

If `main` advances while TC-A is executing:

```text
TC-A starts @ abc123
main advances to def456
TC-A finishes FAIL
```

the valid historical result is:

```text
TC-A / run N = FAIL @ abc123
```

It must not be relabeled as evidence for `def456`.

A later run may test `def456`.

## 8. One run per case per sweep

For every case in the discovery snapshot, the Tester may create at most one new executed run in that sweep.

No retry-until-pass is allowed.

A provider/network/runtime failure must be classified according to the applicable validation/failure protocol; it must not trigger repeated scored attempts until one succeeds.

If a product change later affects the case, a new scheduled sweep creates a new run.

This rule protects attribution and prevents scheduled validation from biasing results by repeated sampling.

## 9. Failure-to-defect workflow

When a run fails, the Tester determines whether the observed failure corresponds to:

- an existing open defect;
- a previously closed defect that has genuinely regressed;
- a new defect;
- a harness/runtime/environment problem rather than a product defect;
- or an ownership/architecture ambiguity requiring Controller intervention.

Before creating a new defect, the Tester should search for equivalent ownership and evidence to avoid duplicate issues.

A defect record should be tied to the failing case/run and the exact execution snapshot that exposed it.

The case remains `BLOCKED` by the relevant defect set.

The Tester may continue executing all other cases in the same discovery snapshot regardless of that failure.

## 10. Developer selection and parallelism

Developer workers choose from live defect issues, not from cached case-pool status alone.

An issue is eligible only when:

- it is open/ready for implementation;
- hard dependencies are satisfied;
- no existing active implementation already owns the same issue;
- concurrent work does not violate a shared semantic/domain boundary;
- no required exclusive runtime/production mutation conflicts with another worker.

Separate files or separate GitHub issues do not by themselves prove parallel safety.

A worker that cannot find a safe issue exits normally.

This architecture intentionally prefers unused developer capacity over unsafe parallelism.

## 11. Coordination-state write ownership

The concrete serialization of case-pool state is an implementation concern, but write ownership must avoid a many-writer shared-file race.

The intended ownership model is:

- Generator: may add/update case inventory records.
- Tester: owns case lifecycle transitions, sweep records and run references.
- Developers: do **not** write case-pool lifecycle state; they update GitHub issues/branches/PRs.
- Controller: exceptional repair/administrative writes only.

If a mutable repository file such as `TestCasePool.yaml` is used, writes must use optimistic concurrency against the exact blob/version that was read. No worker may force-overwrite another worker's update.

A practical implementation should keep mutable current-state records small and store sweep/run history as append-only records rather than growing one monolithic file indefinitely.

For example, an implementation may choose a structure similar to:

```text
automation/case-validation/
├── TestCasePool.yaml          mutable current coordination index
├── sweeps/
│   └── SW-<timestamp>.yaml    append-only discovery snapshots
└── runs/
    └── TC-<id>/
        └── R-<id>.yaml        append-only execution snapshots/results
```

This path is illustrative until the implementation issue fixes the storage layout. The semantics in this document are mandatory regardless of serialization.

## 12. Recommended scheduled-cycle ordering

The exact minute offsets are deliberately not fixed here, but an hourly deployment should normally stage work so that the producer/consumer order is observable:

```text
hour N
  Generator sweep
       ↓
  Tester sweep
       ↓
  Developer 1..5 in parallel
       ↓
hour N+1
  Generator revalidates inventory
       ↓
  Tester observes converged/unblocked work
       ↓
  next developer wave
```

Workers must not poll continuously waiting for the next stage.

If a developer finishes after the current Tester discovery snapshot, that case simply waits for the next hourly Tester sweep.

## 13. Failure recovery and stale work

Because workers are short-lived, a worker may terminate unexpectedly.

Recovery must rely on durable observable state, not on the missing worker's conversation.

A later invocation should determine whether work is actually active by checking GitHub live state and any explicit claim metadata.

Stale ownership may be released only when there is affirmative evidence that no valid active branch/PR/run still owns the work. Time passage alone is not sufficient if repository evidence shows ongoing execution.

No scheduled worker may delete historical run/sweep evidence as part of recovery.

## 14. Safety boundaries

Unless a selected issue explicitly grants additional authority:

- scheduled validation is read-only against production corpus/raw evidence;
- raw evidence and registered hashes are immutable;
- no worker uses production state as a development sandbox;
- Tester does not patch product code;
- Generator does not execute or implement cases;
- Developers do not rewrite failed validation history;
- no model output becomes canonical legal authority;
- no historical FAIL is converted into PASS;
- no missing GitHub evidence is interpreted as authorization;
- no worker bypasses required branch/PR/CI/convergence policy for convenience.

## 15. Controller-intervention conditions

Normal scheduled workers should stop and surface the condition when they encounter:

- ambiguous issue ownership;
- duplicate competing implementations;
- dependency cycles;
- semantic-domain collisions that make parallel execution unsafe;
- disagreement between case-pool state and GitHub that cannot be reconciled deterministically;
- a required production/runtime mutation without explicit authorization;
- repeated regressions suggesting a broader architectural owner;
- a corrupted or conflicting coordination-state write;
- inability to identify the exact execution snapshot for a proposed run.

These are controller problems, not opportunities for a worker to guess.

## 16. Core invariants

The scheduled swarm is correct only if all of the following remain true:

1. workers are disposable; durable state is external to the chat;
2. GitHub live overrides stale cached operational observations;
3. Tester processes all cases in the discovery snapshot, not an arbitrary fixed count;
4. the discovery snapshot freezes the sweep membership but not one global main SHA;
5. each case is revalidated before execution;
6. each executed run has its own exact execution snapshot;
7. main may advance between cases but never changes the identity of an already-started run;
8. one case receives at most one executed run per Tester sweep;
9. failed runs remain immutable historical evidence;
10. no retry-until-pass;
11. each Developer handles at most one issue per invocation;
12. five Developers represent maximum available parallelism, not permission to violate dependencies;
13. Developers do not directly mutate case lifecycle state;
14. blocked cases are rerun only after independent live verification of blocker convergence;
15. a case becoming eligible after discovery waits for the next scheduled sweep;
16. Controller intervention is exceptional and evidence-driven.

This contract is intended to let Col-taxdata run a long iterative validation/development process without relying on a single long-lived agent while preserving reproducibility, auditability and architectural ownership.
