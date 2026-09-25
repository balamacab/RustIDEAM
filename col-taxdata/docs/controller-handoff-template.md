# Controller handoff template

Controller handoffs for `col-taxdata` are intentionally small. Durable detail belongs in immutable CM1 session capsules, not in an ever-growing natural-language prompt.

The receiving controller MUST read `controller-orchestration.md` before mutating GitHub.

## Minimal handoff envelope

```text
Mode: CONTROLLER
Repo: balamacab/RustIDEAM
Scope: col-taxdata/
Main: <40-hex SHA>
ETHOS: col-taxdata/controller-memory/ETHOS.cm
CM: col-taxdata/controller-memory/INDEX.cm
SID: <latest/new CM1 session id>
```

Do not append a full project history to this handoff.

## Receiving-controller bootstrap

1. Read `controller-orchestration.md`.
2. Load `controller-memory/ETHOS.cm` plus `controller-memory/INDEX.cm` (or run `python3 tools/controller_memory.py bootstrap` when a checkout is available).
3. Apply the ethos as operating guidance, then inspect live GitHub state for the task being considered.
4. Query only relevant memory keys, for example:
   - `i67` for issue #67;
   - `p82` for PR #82;
   - `d42` for controller decision 42;
   - a compact `t...` topic key.
5. Load only the session records returned by that exact-key query.
6. Treat live GitHub/repository state as authoritative for current status.

If the current controller does not need historical detail, it should not load session capsules. ETHOS remains part of every bootstrap.

## Creating the next handoff

At a material controller checkpoint:

1. encode only durable deltas in one new `CM1|S` session;
2. include decision/dependency/blocker/invariant/restriction/validation-boundary/conditional-action records as applicable;
3. do not persist transcript filler;
4. add the session create-only using:
   `python3 tools/controller_memory.py handoff <prepared-session.cm>`;
5. run:
   `python3 tools/controller_memory.py verify`;
6. commit the new session plus rebuilt `INDEX.cm`;
7. hand the next controller only the minimal envelope above.

Existing `sessions/*.cm` files are immutable. A later session supersedes prior knowledge by reference; it never edits the prior bytes.

## Retrieval contract

See `controller-memory.md` for CM1 wire semantics.

The compact format is for token and retrieval efficiency. It is not encryption and must not contain information unsuitable for the public repository.

The handoff is a pointer into controller memory. It never overrides current repository truth.
