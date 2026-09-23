# ADR-0007 — Temporal state is candidate/evidence/event based

## Status

Accepted and implemented by DEF-0004.

## Context

Real compiled legal documents can contain zero, one, or many publication dates, issued dates and commencement references. The former exact-one extractor converted normal evidence cardinality into document-level failures and risked encouraging arbitrary selection.

A permanent `vigente=true` field would also hide how a legal state was established and at what date.

## Decision

Temporal processing:

1. collects all candidate spans;
2. preserves exact evidence/context;
3. classifies trusted structural context;
4. records a per-role resolution as `resolved`, `unresolved`, or `ambiguous`;
5. promotes a Temporal Event only when the role has uniquely supported trusted evidence.

Legal state for an `as_of` date is conceptually computed from supported events and known uncertainty, not represented as an unconditional timeless Boolean.

## Alternatives considered

- Exact-one match as an extraction precondition — rejected by DEF-0004.
- First/earliest/latest matching date — rejected because cardinality is not legal priority.
- Publication date automatically equals effective date — rejected without explicit commencement evidence.

## Consequences / trade-offs

- Multiple candidates increase explicit ambiguity rather than causing parser failure.
- Consumers must tolerate incomplete temporal state.
- Candidate/resolution/event tables add storage but preserve auditability.
- Reprocessing can supersede older derived events while retaining evidence history.

## Related specs/issues

- DEF-0004.
- `schema/014_temporal_candidates.sql`.
- 2026-09-23 DEF-0004 reprocessing audit.
