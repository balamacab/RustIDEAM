# Controller handoff template

Use this template when handing `col-taxdata` orchestration to another controller thread.

The receiving controller MUST read `controller-orchestration.md` before mutating GitHub and MUST revalidate this snapshot against live GitHub/repository state.

## Controller role

```text
Mode: CONTROLLER / ORCHESTRATION
Repository: balamacab/RustIDEAM
Project scope: col-taxdata/
```

The controller coordinates issues, specs, dependencies, blockers, execution order and validation boundaries. It does not assume that a proposed decomposition is correct merely because it was proposed.

## Stable project invariants

Record only durable invariants needed for orchestration, for example:

- immutable raw evidence is never rewritten;
- SHA-256/provenance guarantees remain intact;
- ambiguous legal identity/state/relationships remain unresolved;
- LLM output is not canonical legal authority;
- historical audits/benchmarks are not rewritten to match later results.

Do not duplicate large specifications here; link/reference their authoritative repository location.

## Live orchestration snapshot

### Current main

```text
main SHA:
validated at:
```

### Active issues

For each materially active issue:

```text
#N — title
owner scope:
state:
branch/PR:
hard dependencies:
ordering dependencies:
blocks:
blocked by:
parallel relationship:
must not touch:
next safe action:
```

### Active pull requests

```text
PR:
issue:
head SHA:
base/main relationship:
semantic/domain scope:
known overlap:
integration ordering:
CI/convergence state:
```

### Blocked work

```text
work item:
blocked by:
exact unblock condition:
what must NOT be done while blocked:
```

### Validation / frozen-input boundaries

```text
validation issue:
frozen input/artifact:
already consumed?:
who may consume it:
prerequisites:
prohibited prerequisite actions:
```

### Runtime / production state relevant to orchestration

Include only facts that affect sequencing or authorization.

```text
runtime baseline:
production mutation authorized for:
production mutation prohibited for:
known frozen snapshots:
```

## Decisions already made

Record accepted decisions with the issue/spec/ADR that owns them.

Do not convert temporary runtime facts into architecture.

```text
decision:
owner/reference:
scope:
what it does NOT imply:
```

## Open controller questions

Only unresolved orchestration decisions belong here.

```text
question:
why it matters:
affected issues:
safe state until resolved:
```

## Next safe actions

List actions in dependency order.

```text
1.
2.
3.
```

Do not list a blocked action as executable.

## Mandatory receiving-controller preflight

Before creating, closing, splitting, modifying or launching an issue, the receiving controller must:

- inspect live related issues and PRs;
- verify whether the proposed work already has an owner;
- verify hard and ordering dependencies;
- verify concurrent work and ownership boundaries;
- determine allowed/conditional/prohibited parallelism;
- distinguish user analysis questions from mutation instructions;
- challenge the handoff itself if live evidence shows its decomposition is wrong.

The handoff is a convenience for continuity. It never overrides current repository truth.
