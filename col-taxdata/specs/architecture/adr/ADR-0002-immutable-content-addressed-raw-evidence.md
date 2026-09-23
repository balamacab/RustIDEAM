# ADR-0002 — Raw manifestations are immutable and content-addressed by SHA-256

## Status

Accepted and implemented.

## Context

Legal interpretation can be corrected only if the project retains the source bytes that were actually fetched. Parsers, canonicalizers, relationship logic and temporal logic can change; source evidence must remain independently verifiable.

## Decision

Successful source bytes are hashed with SHA-256 and stored beneath a content-addressed raw path. A Manifestation registers the source-specific observation, raw SHA-256, byte size, retrieval metadata and path.

Raw bytes and their registered SHA-256 are immutable. Defect fixes and reprocessing operate from preserved evidence into derived state; they do not rewrite the source to fit a new interpretation.

Manifestation identity currently includes both Source identity and SHA-256, so byte-identical responses from different Sources can remain provenance-distinct while sharing content-addressed physical bytes.

## Alternatives considered

The project has explicitly rejected repairing derived defects by editing/redownloading raw evidence when the archived source is already the intended evidence. No alternative mutable-evidence model is accepted.

## Consequences / trade-offs

- Storage retains historical bytes even when a newer parser supersedes older derived output.
- Integrity checks can compare registered and physical SHA-256 values.
- Reprocessing is possible without relying on the upstream site still serving the same content.
- Correcting a wrong canonical identity can require significant derived-state rebuilding while raw hashes remain unchanged.

## Related specs/issues

- `tools/fetch_source.py`
- DEF-0001 through DEF-0004 provenance/reprocessing rules.
- 2026-09-22 corpus audit.
- ADR-0004 ambiguity preservation.
