# ADR-0005 — LLM output is not canonical legal authority

## Status

Accepted.

## Context

`col-taxdata` may be consumed by an LLM, RAG workflow or future MCP integration. Generative models are useful for analysis and candidate generation, but their outputs are not sufficiently deterministic/auditable to define canonical legal identity, temporal state or provenance by themselves.

## Decision

LLM output may assist classification, propose candidates, summarize evidence, or support user-facing analysis. It must not be the canonical authority for:

- Document identity;
- issuer identity;
- Reference Resolution;
- Relationship truth;
- Temporal state/events;
- evidence provenance.

Canonical promotion must remain tied to deterministic/auditable rules and preserved evidence, with unresolved state when those rules cannot decide.

## Alternatives considered

Making a model answer the final source-of-truth decision is explicitly rejected by the project principles.

## Consequences / trade-offs

- Consumer layers must preserve citations/provenance and uncertainty.
- Some facts require deterministic rules or human review before canonical promotion.
- Future model upgrades do not silently rewrite the legal corpus.
- RAG/MCP remain downstream consumers of canonical/evidence layers.

## Related specs/issues

- `specs/README.md`
- `specs/architecture/overview.md`
- GitHub issue #9.
