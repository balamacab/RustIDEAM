# ADR-0008 — The legal knowledge graph is conceptual and does not require a graph database

## Status

Accepted as the current representation model.

## Context

`col-taxdata` models entities and typed connections: Documents contain Provisions; references resolve to targets; Relationships connect legal entities; Temporal Events affect entities; Evidence supports assertions.

That structure is naturally graph-like, but the current implementation is relational SQLite with explicit tables, foreign keys, provenance joins and FTS5.

## Decision

Use “knowledge graph” or “legal knowledge representation” to describe the conceptual node/edge model without implying a graph database.

SQLite remains the current implementation. A graph database is neither required by the domain model nor implemented by issue #9.

## Alternatives considered

No repository decision establishes Neo4j, RDF, or another graph database as current infrastructure. Those technologies are therefore not recorded as evaluated/selected alternatives.

## Consequences / trade-offs

- Developers can reason in nodes/edges while preserving current relational implementation.
- Relationship provenance remains explicit and queryable with SQL.
- Future persistence work may introduce adapters/capabilities without redefining legal identity.
- Documentation must not call the current store a graph database.

## Related specs/issues

- ADR-0001.
- `schema/004_reference_mentions.sql`
- `schema/007_relationship_provenance.sql`
- GitHub issue #10.
