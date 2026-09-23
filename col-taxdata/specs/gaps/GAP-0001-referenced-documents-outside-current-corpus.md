---
id: GAP-0001
type: coverage-gap
status: specified
priority: P2
area: corpus-coverage
baseline: 2026-09-22-corpus-audit
---

# GAP-0001 — Normograma references 1,268 canonical documents absent from the current corpus

## Summary

The current Normograma corpus cites many legal instruments that are not themselves present as canonical downloaded documents. This is a corpus-coverage limitation, not evidence corruption and not necessarily a resolver defect.

## Observed behavior

Open `TARGET_DOCUMENT_NOT_FOUND` review items correspond to 1,268 distinct canonical document keys:

- 675 Decretos;
- 332 Leyes;
- 259 Resoluciones;
- 1 Oficio;
- 1 Concepto.

Examples with many incoming mentions include Decreto 117/2017, Decreto 1242/2013, Decreto 1836/2015, Resolución 7941/2008 and Ley 2080/2021.

## Impact

- a substantial part of the reference graph cannot close;
- provision-level relationships cannot resolve when target source documents are absent;
- an MCP/LLM client may find a citation but not the cited primary text locally.

## Proposed direction

Add additional official-source adapters incrementally, driven by unresolved reference demand.

Prioritize sources that can supply:
- national laws;
- national decrees;
- DIAN resolutions missing from Normograma;
- jurisprudence where required.

Requirements for every new source adapter:

- official-domain allowlist;
- immutable raw SHA-256 preservation;
- canonical identity compatible with issuer-aware DEF-0002 design;
- provenance distinguishing source authority and manifestation;
- no silent substitution of unofficial mirrors.

Use unresolved-reference frequency to prioritize acquisition, not to infer missing legal text.

## Acceptance criteria

This gap is reduced iteratively rather than "fixed" in one change.

Each new source integration should demonstrate:
- previously unresolved canonical keys become resolvable;
- target text comes from an approved official source;
- no existing raw evidence is overwritten;
- graph reconciliation closes corresponding review items deterministically.

## Dependencies / ordering

Address after DEF-0001 and DEF-0002 so newly acquired documents enter a stable canonical identity model.
