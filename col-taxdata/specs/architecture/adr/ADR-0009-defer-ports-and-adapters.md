# ADR-0009 — Persistence decoupling with Ports and Adapters is deferred post-MVP

## Status

Accepted architectural direction; implementation deferred.

## Context

Current tools access SQLite directly in multiple modules. Issue #10 proposes capability/domain-oriented persistence ports and adapters so later storage implementations can vary without spreading SQL concerns through domain/application logic.

The project deliberately sequences legal-semantic stabilization and architecture documentation before this refactor.

## Decision

Do **not** implement Hexagonal Architecture / Ports and Adapters as part of issue #9.

Record it as the accepted post-MVP direction owned by issue #10. Until that issue is implemented:

- direct SQLite access remains current reality;
- repository/unit-of-work abstractions must not be described as existing;
- PostgreSQL/Redis adapters must not be described as implemented;
- current architecture documentation must describe SQLite truthfully.

## Alternatives considered

Implementing persistence decoupling during MVP stabilization was explicitly deferred to avoid combining legal-semantic changes with a broad persistence refactor.

## Consequences / trade-offs

- Current code remains coupled to SQLite.
- The domain terminology and identifier semantics documented by issue #9 become constraints for the future refactor.
- Issue #10 can inventory real persistence access patterns before defining ports.
- Deferral avoids unrelated runtime/schema change in this documentation task.

## Related specs/issues

- GitHub issue #9 — current architecture baseline.
- GitHub issue #10 — post-MVP Ports and Adapters implementation.
- ADR-0001 — current SQLite store.
