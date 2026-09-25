# Controller orchestration policy

This document defines the durable responsibilities of a **controller thread** for `col-taxdata`.

A controller is the orchestration layer that interprets a requested change, understands the current project state, decides whether work belongs in an existing issue or a new one, defines dependency/blocker relationships, and launches implementation work.

This policy is intentionally separate from the implementation-agent contract. Global project coordination is a controller responsibility.

## 1. Controller responsibility

Before creating, splitting, modifying, closing or launching any non-trivial implementation issue, the controller MUST understand enough of the current project graph to define the work safely.

The controller MUST inspect, as applicable:

- the relevant current specifications and architecture;
- the selected or related GitHub issues;
- open and recently merged pull requests;
- active branches when materially relevant;
- known runtime/validation state;
- dependencies already encoded in specs, issues or prior accepted architecture;
- historical audits/evidence that must not be rewritten.

The controller MUST NOT delegate this global reconstruction to the implementation agent.

## 2. Critical evaluation before mutation

A user question, hypothesis or proposed decomposition is not automatically authorization to mutate GitHub.

Before acting, the controller MUST determine whether the user is:

- asking a question;
- proposing an architecture/decomposition for evaluation;
- requesting a recommendation;
- or explicitly ordering a mutation/execution.

The controller MUST critically evaluate proposed work rather than mechanically accepting it.

It must call out and correct, before issue creation when possible:

- duplicate ownership;
- wrong issue boundaries;
- unnecessary dependencies;
- circular dependencies;
- architecture derived from temporary hardware/provider/runtime circumstances;
- attempts to optimize only for the next immediate unblock;
- historical/spec rewriting for present convenience;
- mixing evidence, provider-specific defects, cross-cutting contracts, operations and validation into one owner.

Agreement is not the objective; coherent project architecture is.

## 3. Classify the work before creating an issue

The controller MUST identify what kind of work is actually being requested.

Distinguish at minimum:

- concrete defect/evidence;
- provider/runtime-specific limitation;
- cross-cutting architectural or application contract;
- operational/runtime preparation;
- validation/benchmark execution;
- documentation/reconciliation;
- production mutation/reprocessing.

One observed failure may justify more than one issue only when those issues have genuinely different owners and lifecycles. Do not split merely to make work appear parallel.

## 4. Dependency and concurrency analysis

Before launching work, the controller MUST determine:

- existing related issues;
- hard dependencies;
- ordering dependencies that are not hard blockers;
- what the issue blocks;
- what blocks the issue;
- concurrent work in the same semantic/domain boundary;
- ownership of shared boundaries;
- whether parallel execution is allowed, conditional or prohibited;
- required merge/rebase/current-main ordering when parallel work is conditional;
- runtime or production mutation ownership.

Separate issues do not imply parallel safety.

No textual Git conflict does not imply semantic independence.

If the controller cannot determine a material dependency safely, record it as unknown and keep the affected action blocked rather than guessing.

## 5. Required controller definition for issues

Every new non-trivial controller-created implementation issue MUST contain enough information to locate it unambiguously in the project graph.

Use the following semantics, with formatting adapted as needed:

```text
Controller definition

Purpose / owner scope:
Authoritative spec or contract:
Out of scope / non-goals:

Existing related issues:
Hard dependencies:
Ordering dependencies:
Blocks:
Blocked by:

Concurrent work:
Parallel execution:
  allowed | conditional | prohibited

If conditional/prohibited:
  ownership boundary:
  required ordering:
  merge/rebase/current-main expectation:

Shared architectural/domain boundaries:
Likely affected paths/modules:
Must not modify:

Runtime/production authorization:
Completion/unblocking condition:
```

The controller owns the correctness of this definition at creation time.

Implementation agents may report that live facts differ, but they are not expected to invent the global coordination model that the controller omitted.

## 6. Ownership and scope rules

Each issue should have one coherent owner responsibility.

The controller MUST:

- keep operational preparation separate from durable architecture when they have different lifecycles;
- keep provider-specific evidence separate from provider-neutral contracts;
- keep validation execution separate from implementation that would contaminate the validation;
- keep historical benchmark/audit evidence immutable;
- avoid moving unrelated cleanup into an issue merely because the same files are nearby;
- avoid turning currently available hardware into a system requirement without architectural justification.

When an issue reveals a broader systemic rule, determine whether the broader rule belongs in the same owner or a separate cross-cutting issue before changing GitHub.

## 7. Changes discovered while work is active

The controller must monitor material new information from active issues.

If new evidence changes dependency, ownership, scope or sequencing:

1. re-read the affected live issues/PRs;
2. update the controller graph;
3. change blockers/order explicitly where necessary;
4. do not silently reinterpret an older issue;
5. do not rewrite historical evidence;
6. prevent newly created work from duplicating ownership already in flight.

A closed provider-specific defect may remain evidence for a separate general contract. Closing the evidence issue does not erase the finding or automatically implement the general rule.

## 8. Production and validation boundaries

The controller must state whether an issue may mutate:

- production runtime;
- database state;
- corpus-derived state;
- immutable raw evidence;
- benchmark/validation inputs.

Absence of explicit authorization means no such mutation.

Validation issues that require blind/frozen inputs must not be consumed by prerequisite implementation or environment-preparation work.

## 9. Handoff between controller threads

A controller handoff is context, not authority.

Every new controller thread MUST:

1. read this policy before mutating GitHub;
2. use the controller handoff as a starting snapshot;
3. revalidate material facts against live GitHub/repository state;
4. reconstruct active dependencies, blockers and execution order;
5. preserve historical evidence and already accepted architecture;
6. continue from the live graph, not blindly from stale handoff text.

If handoff and live GitHub state disagree, live state wins and the discrepancy must be resolved explicitly.

Use `controller-handoff-template.md` for reusable handoffs.

## 10. Relationship to implementation agents

Implementation agents remain responsible for executing their selected issue correctly: reading its spec, respecting scope, testing, validating, documenting findings and reporting blockers.

They are **not** the primary owner of:

- deciding whether the issue should exist;
- deciding whether another active issue owns the same work;
- designing the global issue dependency graph;
- choosing project-wide sequencing;
- inferring missing controller authorization.

Those decisions belong to the controller.

## 11. Controller completion check

Before launching or materially changing issue work, the controller should be able to answer:

```text
Why does this issue exist?
What spec/contract owns the behavior?
Does an existing issue already own it?
What does it depend on?
What depends on it?
What related work is active?
Can it run concurrently?
What boundary does it own?
What must it not touch?
What must happen before it can integrate or unblock downstream work?
What evidence will allow it to close?
```

If a missing answer materially affects correctness, resolve it before launching work.
