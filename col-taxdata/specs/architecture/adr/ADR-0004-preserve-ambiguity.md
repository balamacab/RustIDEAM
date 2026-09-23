# ADR-0004 — Ambiguous legal facts remain unresolved instead of guessed

## Status

Accepted and implemented across current identity, reference, relationship and temporal workflows.

## Context

Official legal pages contain quotations, historical annotations, duplicated dates, incomplete identifiers and references that can match more than one canonical target. Choosing a convenient result can create false legal provenance.

## Decision

When deterministic evidence is insufficient to select one result, `col-taxdata` represents the state explicitly as unresolved, ambiguous, conflicting, or reviewable rather than guessing.

This rule applies at least to:

- source/document identity;
- issuer-sensitive reference resolution;
- relationship promotion;
- temporal candidate resolution;
- case claims that lack canonical support.

Absence of detected evidence is not converted into a substantive legal conclusion.

## Alternatives considered

Rules such as “take the first match”, “take the earliest/latest date”, “choose the only document type that looks close”, or “infer repeal/effectiveness from chronology” are rejected for canonical legal state.

## Consequences / trade-offs

- Coverage can be lower than a heuristic system, but false certainty is reduced.
- Review queues and unresolved states are first-class data.
- Downstream MCP/RAG/LLM clients must be able to surface uncertainty.
- Additional corpus coverage can later resolve some references without changing the original mention/evidence.

## Related specs/issues

- DEF-0001 — identity false positives.
- DEF-0002 — issuer-aware ambiguity.
- DEF-0004 — temporal candidates/resolutions.
- `specs/architecture/domain-model.md`.
