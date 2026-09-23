# ADR-0001 — SQLite is the MVP authoritative operational store

## Status

Accepted for the MVP.

## Context

`col-taxdata` currently persists Sources, Manifestations, canonical Documents/Provisions, provenance, references, relationships, temporality, review state, crawler state, FTS, and case state in SQLite. Existing tools issue SQL directly and migrations target SQLite.

Issue #10 explicitly defers persistence decoupling until post-MVP. PostgreSQL, Redis, or another backend must therefore not be described as current infrastructure.

## Decision

SQLite remains the authoritative operational store for the current MVP.

Exports, reports, case materializations, FTS results, and future consumer views are derived from or reconciled with canonical/evidence state; they do not replace the authoritative operational store.

## Alternatives considered

No repository evidence establishes that another backend was implemented or selected for the MVP. PostgreSQL and other adapters are future possibilities under issue #10, not current alternatives that issue #9 claims were prototyped.

## Consequences / trade-offs

- Current tools may depend directly on SQLite and SQL semantics.
- SQLite FTS5 is the current retrieval index.
- Domain identity must not be defined by SQLite row order or backend-specific surrogate behavior.
- A future backend migration must preserve canonical identity, evidence/provenance, ambiguity semantics, and migration history.
- Persistence decoupling remains deferred rather than being mixed into architecture documentation.

## Related specs/issues

- GitHub issue #9 — architecture baseline.
- GitHub issue #10 — deferred Ports and Adapters refactor.
- `schema/001_initial.sql` through current append-only migrations.
