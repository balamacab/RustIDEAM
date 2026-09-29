# col-taxdata specification-driven development

This directory is the authoritative planning and behavioral-contract layer for changes to `col-taxdata`.

The runtime database and crawler output describe what the system currently does. Specs describe what the system must do, why a change is required, how correctness will be measured, and which evidence justified the change. Cross-cutting architecture documents define the shared domain vocabulary and invariants that issue-specific work must preserve.

## Documentation roles

```text
README     = current project orientation / operational entry point
specs      = authoritative behavioral contracts
audits     = measured state at a point in time
ADRs       = durable architectural decisions and trade-offs
```

Historical audits are not rewritten after fixes. A newer implementation or audit can supersede a historical conclusion without changing the old record.

## Required architecture context

Before changing behavior that touches shared legal-data concepts, read the relevant architecture documentation:

- [`architecture/overview.md`](architecture/overview.md) — system purpose, layers, invariants, and current-vs-deferred architecture.
- [`architecture/domain-model.md`](architecture/domain-model.md) — authoritative definitions and boundaries for Source, Manifestation, Document, Provision, Evidence, references, relationships, temporality, review state, and derived state.
- [`architecture/data-lifecycle.md`](architecture/data-lifecycle.md) — immutable evidence versus rebuildable derived state and stage-by-stage reprocessing behavior.
- [`architecture/glossary.md`](architecture/glossary.md) — shared terminology.
- [`architecture/identifier-semantics.md`](architecture/identifier-semantics.md) — identifier derivation/stability expectations.
- [`architecture/adr/`](architecture/adr/) — established architectural decisions and trade-offs.

These documents are required context when an issue depends on those concepts; they do not replace the selected issue/spec or its acceptance criteria.

## Principles

1. **Evidence before implementation.** A defect spec must include reproducible evidence from the corpus, database, source document, or code path.
2. **Primary evidence is immutable.** Fixes must never rewrite archived raw manifestations. Reprocessing creates or updates derived state only.
3. **No inferred legal truth.** Ambiguous identity, temporal state, or relationships remain unresolved rather than being guessed.
4. **Deterministic acceptance criteria.** Every spec defines machine-checkable acceptance criteria where possible.
5. **Reprocessing is explicit.** A fix must state which existing derived artifacts require replay and which tables/files are expected to change.
6. **Compatibility matters.** Database migrations are append-only and existing provenance must remain traceable.
7. **LLMs are not authorities.** LLM assistance is limited by the active application contract; canonical legal identity, temporal state, relationships and provenance remain deterministic/auditable. In the accepted CASE v4 target, the internal LLM is intake-only and does not author candidate legal conclusions.
8. **Source, manifestation and document are distinct.** A source page or quoted norm must not be silently promoted to the wrong canonical Document.
9. **Retrieval is downstream.** FTS/RAG-style retrieval consumes evidence/canonical layers; it must not overwrite them.

## Layout

```text
specs/
├── README.md
├── architecture/
│   ├── overview.md
│   ├── domain-model.md
│   ├── data-lifecycle.md
│   ├── glossary.md
│   ├── identifier-semantics.md
│   └── adr/
│       └── ADR-NNNN-*.md
├── application/
│   ├── case-contracts-v1.md
│   ├── case-contracts-v2.md
│   ├── case-contracts-v3.md
│   ├── case-contracts-v4.md
│   ├── case-rest-api-v1.md
│   ├── case-mcp-gateway-v1.md
│   ├── openapi/
│   │   └── case-rest-api-v1.openapi.json
│   ├── examples/
│   │   └── case-rest-v1/
│   └── schemas/
│       ├── case-contracts-v1.schema.json
│       ├── case-contracts-v2.schema.json
│       ├── case-contracts-v3.schema.json
│       ├── case-contracts-v4.schema.json
│       └── case-rest-api-v1.schema.json
├── audits/
│   └── YYYY-MM-DD-<audit>.md
├── defects/
│   ├── README.md
│   └── DEF-NNNN-<slug>.md
├── gaps/
│   └── GAP-NNNN-<slug>.md
└── manifest.yaml
```

## Application contracts

Stable application-facing contracts live under [`application/`](application/). They define consumer/domain boundaries downstream of canonical corpus evidence without claiming that deferred transports or orchestrators are already implemented.

The #130 migration is split at explicit compatibility boundaries. The historical/default REST v1 structuring path still uses the v4 **intake-only** contract and remains the frozen CASE v4.0.0 compatibility boundary. Issue #285 publishes the version-isolated CASE v5.0.0 durable/public boundary through REST v2 for complete validated v5 bundles; this does not change v4 interpretation, authorize consumer inference write-back, or import deferred pagination/UI/MCP semantics. Historical versions remain interpretable under their declared contracts and are never silently relabeled:

- [`application/case-contracts-v5.md`](application/case-contracts-v5.md) — v5.0.0 successor architecture from #279, with executable primitives/planning/context/coverage from #280–#283 and the version-isolated durable/public boundary from #285.
- [`application/schemas/case-contracts-v5.schema.json`](application/schemas/case-contracts-v5.schema.json) — machine-readable v5 design vocabulary plus stable semantic-invariant codes used by #279 examples and future #280 validation.
- [`application/examples/case-v5/research-coverage-examples.json`](application/examples/case-v5/research-coverage-examples.json) — focused machine-checkable positive/negative coverage vectors for broad, narrow, mixed, ambiguous, unsupported and invalid-reference/status cases.
- [`architecture/adr/ADR-0011-case-v5-research-aspect-coverage.md`](architecture/adr/ADR-0011-case-v5-research-aspect-coverage.md) — accepted v5 versioning, coverage, budget, identity and #159 admission decision.
- [`application/case-contracts-v4.md`](application/case-contracts-v4.md) — v4.0.0 evidence-first contract. Intake (#136), bounded canonical research (#137), citable EvidenceSpan/registered RuleFragment construction (#138), bounded deterministic evaluation/calculation (#139), and ownership-aware durable LegalResearchBundle persistence/materialization (#140) are active; external consumer inference remains non-canonical.
- [`application/schemas/case-contracts-v4.schema.json`](application/schemas/case-contracts-v4.schema.json) — machine-readable target v4 schema/delta used by downstream implementation issue #134.
- [`application/case-rest-api-v1.md`](application/case-rest-api-v1.md) — authoritative external REST v1 transport contract from #144; `POST /v1/cases` transports validated v4 LegalResearchBundle objects without exposing backend implementation or persistence internals.
- [`application/case-rest-api-v2.md`](application/case-rest-api-v2.md) — REST 2.0.0 public boundary for validated CASE 5.0.0 bundles; preserves v5 aspect/task/evidence/coverage refs and keeps caller authority identical to v1.
- [`application/case-mcp-gateway-v2.md`](application/case-mcp-gateway-v2.md) — #287 versioned MCP adapter contract; preserves the seven-tool surface, keeps v4/REST-v1 compatibility, explicitly admits v5/REST-v2 coverage projections, and exposes no canonical inference write-back path.
- [`application/case-mcp-gateway-v1.md`](application/case-mcp-gateway-v1.md) — frozen #145 historical MCP contract for REST v1 / CASE v4.
- [`application/openapi/case-rest-api-v1.openapi.json`](application/openapi/case-rest-api-v1.openapi.json) — OpenAPI 3.1 contract consumed by independent web/MCP clients; standalone examples live under [`application/examples/case-rest-v1/`](application/examples/case-rest-v1/).
- [`application/schemas/case-rest-api-v1.schema.json`](application/schemas/case-rest-api-v1.schema.json) — closed public request/success/error transport schemas referencing the authoritative v4 application schema.
- [`architecture/adr/ADR-0010-case-v4-evidence-first-authority.md`](architecture/adr/ADR-0010-case-v4-evidence-first-authority.md) — accepted authority/dependency decision for the #130 program.
- [`application/case-contracts-v3.md`](application/case-contracts-v3.md) — frozen historical compatibility contract. Explicit v3 inputs remain interpretable and may use the historical v3 analysis path, but normal new structuring no longer emits v3 CaseDraft candidate-claim authority.
- [`application/schemas/case-contracts-v3.schema.json`](application/schemas/case-contracts-v3.schema.json) — machine-readable JSON Schema for the v3 serialized contracts.
- [`application/case-contracts-v2.md`](application/case-contracts-v2.md) — retained v2.0.0 compatibility contract; its CaseResult does not serialize facts/questions and therefore may require its originating accepted CaseDraft for fact/question ref validation.
- [`application/schemas/case-contracts-v2.schema.json`](application/schemas/case-contracts-v2.schema.json) — retained machine-readable v2 schema.
- [`application/case-contracts-v1.md`](application/case-contracts-v1.md) — retained v1.0.0 compatibility contract.
- [`application/schemas/case-contracts-v1.schema.json`](application/schemas/case-contracts-v1.schema.json) — retained machine-readable v1 schema.

Issue #24 introduced required result structuring metadata as the v2 breaking change. Issue #27 introduced v3 because required CaseResult facts/questions and standalone result-owned fact/question reference namespaces are another breaking wire/validation change. Issue #132 defines v4 as a breaking **ownership** change: model-authored `CandidateClaim` semantics are replaced by intake-only model output plus platform-owned evidence-first research. Issue #279 defines v5 as a breaking **research-coverage interpretation** change because closed v4 objects cannot safely acquire required aspect/coverage fields or stricter `complete` semantics in place. Historical v1/v2/v3/v4 contracts remain frozen under their declared versions.

CLI/API adapters must preserve the applicable contract semantics rather than embedding their own case logic. Issue #144 now publishes REST v1 as the external transport for v4 LegalResearchBundle objects; #145 implements the independent MCP consumer of that boundary, while #143 owns the separate web-console consumer. The historical #66 v3 HTTP adapter remains compatibility evidence and is not silently relabeled as v4. External LLM synthesis through MCP is consumer-owned and never canonical col-taxdata authority.

Case report/source materialization freshness is governed by [`architecture/data-lifecycle.md` §14](architecture/data-lifecycle.md#14-case-analysis-and-materialization). The 2026-09-23 post-P1 audit remains the historical record of the CASE-0001 six-line drift; DEF-0008 / issue #18 subsequently refreshed CASE-0001 through the canonical `tools/rematerialize_case.py` path. Canonical case/corpus state remains authoritative over these generated materializations.

## Source-of-truth order for issue work

When sources appear to disagree:

1. read the selected issue and its authoritative spec;
2. inspect current schema/code/tests to establish implemented behavior;
3. use architecture/ADRs for cross-cutting semantics and established decisions;
4. treat audits as historical measurements at their recorded date;
5. document a real conflict instead of silently reconciling it;
6. never weaken an acceptance criterion to match current implementation.

Planned/deferred architecture must not be described as current behavior. In particular, Ports and Adapters remains deferred to GitHub issue #10; full execution provenance is issue #11; the corpus doctor is issue #12.

## Defect lifecycle

`observed -> specified -> implementing -> verified -> closed`

A defect is **verified** only after the verification requirements applicable to that defect have passed, including regression/acceptance validation and any required controlled corpus reprocessing. When reprocessing applies, raw SHA-256 evidence must remain unchanged.

## Required defect sections

Each `DEF-NNNN` spec contains:

- Summary
- Observed behavior
- Evidence
- Impact
- Root-cause hypothesis
- Proposed solution
- Non-goals
- Reprocessing plan
- Acceptance criteria
- Regression tests
- Dependencies / ordering

## Prioritization

- **P0** — corrupts primary evidence or makes provenance unreliable.
- **P1** — can produce materially wrong legal identity, state, or retrieval.
- **P2** — materially reduces coverage or quality but evidence remains recoverable.
- **P3** — operational/efficiency issue without loss of legal correctness.

The corpus audit dated 2026-09-22 is the historical baseline for the first defect set. DEF-0001 through DEF-0004 are recorded as `verified` in [`manifest.yaml`](manifest.yaml); later audits/specs should be used for current findings without rewriting that baseline.
