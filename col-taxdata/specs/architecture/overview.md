# col-taxdata architecture overview

## Purpose

`col-taxdata` is local-first legal knowledge and data infrastructure for Colombian tax and accounting research. It acquires official-source material, preserves the retrieved bytes, derives versioned text and structured legal entities, records exact evidence and provenance, and exposes derived state for retrieval and case analysis.

It is **not** “an AI that knows Colombian tax law”. An LLM may later consume retrieval, evidence, or case material, but an LLM is not the canonical authority for document identity, legal relationships, temporal state, or provenance.

This document describes the architecture implemented in the repository as of the completion of GitHub issue #9. Behavioral contracts in verified defect specifications remain authoritative for their scope. Historical audits remain measurements of the system at their recorded dates.

## Architectural principles

The implementation is organized around a small set of durable boundaries:

1. **Preserve primary evidence before interpreting it.** Retrieved source bytes are stored under a SHA-256 content-addressed path and registered as manifestations.
2. **Separate source, manifestation, and document identity.** A URL/source record, one archived byte observation, and a canonical legal document are different concepts.
3. **Derive legal facts conservatively.** Canonical identity, references, relationships, and temporal events are promoted only from deterministic/auditable evidence. Ambiguity remains unresolved.
4. **Keep provenance end to end.** Structured facts should be traceable back through exact evidence/segments/extractions to a manifestation, source URL, retrieval time, and raw SHA-256.
5. **Version rebuildable interpretation.** Text extraction, detection, resolution, relationship promotion, temporal candidate processing, FTS, and case materialization are derived state. Processor versions participate in many derived identifiers.
6. **Prefer idempotent deterministic processing.** Repeating the same processor over the same identity inputs and version should normally reuse the same derived identity or produce zero additional delta.
7. **Treat persistence as current implementation, not domain truth.** SQLite is the authoritative operational store for the MVP. The domain model is expressed relationally today; a future backend migration must preserve domain identity and provenance semantics.

## Current architecture

```text
official source
    |
    v
discovery / crawl queue
    |
    v
HTTP fetch ---------------------------> fetch attempt history
    |
    v
Source -> Manifestation -> immutable raw bytes + SHA-256
                |
                v
        Text Extraction (versioned)
                |
                v
        Extracted Segments -----------> SQLite FTS5
                |
                +--> source-family classification
                |        |
                |        v
                |   canonical Document identity
                |        |
                |        +--> Provision / observations
                |
                +--> Reference Mention
                |        |
                |        v
                |   Reference Resolution
                |        |
                |        v
                |   Explicit Relation Mention -> Relationship + provenance
                |
                +--> Temporal Candidate + Evidence
                         |
                         v
                  role Resolution
                         |
                         v
                   Temporal Event

canonical/evidence state + retrieval
                |
                v
        case registration/materialization
                |
                v
        reports / future MCP or LLM consumer
```

The arrows show conceptual dependency, not one universal executable command. `crawl_dian_normograma.py` and `run_pipeline.py` orchestrate related stages with source-specific branches. Specialized registrars exist for compiled provisions, DIAN doctrine, official guidance, and supported document families.

## Layers and responsibilities

### 1. Source acquisition and discovery

`dian_crawl_queue` and `dian_discovery_edges` represent crawl orchestration for DIAN Normograma. A `Source` records a stable source URL plus authority/source-kind metadata. Fetching is allowlisted to official domains, records every HTTP attempt in `fetches`, and does not parse legal meaning.

A source page is **not** a canonical legal document. Navigation/index pages can be valid sources with manifestations and no `document_id`.

### 2. Immutable raw evidence

A successful fetch computes SHA-256 while streaming the bytes. The physical raw artifact is stored below:

```text
data/raw/sha256/<prefix>/<sha256>.<ext>
```

A `Manifestation` identifies one source-specific archived byte observation. Its current deterministic ID includes both `source_id` and raw SHA-256. Therefore identical byte streams from two different source records may share the same physical content-addressed file while remaining distinct manifestations.

Raw bytes are immutable. Reprocessing starts from existing registered raw evidence; it does not rewrite the raw file to make a later parser result fit.

### 3. Versioned extraction and segmentation

`text_extractions` records deterministic extractor output by manifestation, extractor name, and extractor version. `extracted_segments` provides addressable spans with sequence, type, offsets, text, and text SHA-256.

The initial `segments` table remains for schema compatibility. Current Normograma extraction uses `text_extractions` and `extracted_segments`; new evidence should prefer `evidence.extracted_segment_id`.

Normalized extraction files are derived artifacts, also written under SHA-256 paths. They are reproducible/rebuildable from raw evidence with the corresponding extractor version, but they are not the primary source.

### 4. Source-family classification and canonical identity

Identity is not accepted merely because extracted text contains something that looks like `LEY ...`, `DECRETO ...`, or another legal heading.

The current identity flow:

```text
source URL/path
    -> source-family classification
    -> family-specific or generic family-safe parser
    -> compare trusted source constraints with content signal
    -> accepted canonical identity
       OR explicit unresolved/review state
```

Verified DEF-0001 prevents a cited norm from becoming the identity of the citing page. DEF-0002 makes canonical identity issuer-aware where type/number/year is not globally sufficient. DEF-0003 adds family-specific identity handling for DIAN Conceptos/Oficios, Constitutional Court `Sentencia C`, CONPES, and Constitución pages.

A canonical `Document` is a logical legal/official work. One document may have multiple manifestations. A manifestation may legitimately remain without a document identity.

### 5. Provisions

`provisions` creates stable addressable units such as articles within a canonical document. `provision_observations` records the text observed in a particular extraction/segment. This separates the canonical provision identity from the text observed in one manifestation.

Provision conflicts are represented explicitly rather than resolved by silently overwriting text.

### 6. References and relationships

Reference processing separates three ideas:

- a **Reference Mention** is text that appears to refer to a document/provision;
- a **Reference Resolution** records whether that mention resolves to a canonical target, remains unresolved, or is ambiguous;
- an **Explicit Relation Mention** records relation language in the source text.

A canonical `Relationship` is promoted only when the required source and target identities are sufficiently resolved. `relationship_provenance` binds the relationship back to the explicit relation mention and the reference resolution. Evidence records bind it further to the exact extracted segment and raw manifestation.

The resulting relational data is graph-like: documents/provisions are nodes in the conceptual legal knowledge representation and relationships are typed edges. The current implementation does **not** use or require a graph database.

### 7. Temporality

Temporal state is event/evidence based, not a single `vigente=true` field.

After DEF-0004, extraction persists all relevant `temporal_candidates` with exact evidence and classifies their context. `temporal_role_resolutions` records each role as `resolved`, `unresolved`, or `ambiguous`. Only a uniquely supported trusted candidate is promoted to validated temporal events.

Zero candidates are not an exception. Multiple plausible candidates are not collapsed by choosing the first/earliest/latest. Publication does not imply effectiveness without supporting commencement evidence.

Derived “state as of a date” is therefore a computation over supported events and unresolved facts, not a permanently stored legal truth.

### 8. Retrieval

Current retrieval infrastructure is SQLite FTS5 over `extracted_segments_fts`. The FTS index is derived from extracted segments and can be rebuilt; it does not replace evidence or canonical identity.

The historical 2026-09-22 audit recorded correct FTS/index cardinality while also identifying duplicate/equivalent segment-result issues now tracked separately as DEF-0005. Retrieval quality/ranking is downstream of evidence preservation.

### 9. Case analysis

`cases`, `case_items`, `claims`, and evidence/relationship bindings support registered case bundles such as `CASE-0001`. Case registration validates claims only when explicit canonical support exists. Case source manifests and reports can be materialized from SQLite canonical support/evidence state and then validated for drift.

A case claim is a case-analysis assertion. It is not automatically legal truth, and it is not a substitute for canonical document/relationship/temporal entities.

### 10. Future MCP/LLM consumption

MCP and RAG are consumer/integration directions, not canonicalization layers currently implemented by issue #9.

The intended boundary is:

```text
immutable evidence
    -> deterministic canonical/derived legal state
        -> retrieval / case context
            -> future MCP / RAG / LLM consumer
```

A consumer may read, rank, summarize, explain, or propose candidates. It must not overwrite raw evidence or become the authority that decides canonical legal identity, relationship truth, temporal state, or provenance.

## Current versus deferred architecture

| Area | Current state |
| --- | --- |
| Authoritative MVP operational store | SQLite |
| Raw evidence | SHA-256 registered and content-addressed; immutable |
| Text extraction | Versioned `text_extractions` / `extracted_segments` |
| Search | SQLite FTS5 derived from extracted segments |
| Canonical identity | Source-family validated; issuer-aware where required |
| References/relationships | Mention -> resolution -> provenance-backed relationship |
| Temporality | Candidate/resolution/event model from DEF-0004 |
| Case analysis | SQLite-backed case items/claims/evidence plus materialized bundle files |
| Graph database | **Not used**; relational model is graph-like conceptually |
| Ports and Adapters | **Deferred** to issue #10 |
| PostgreSQL / Redis persistence | **Not implemented**; possible future adapters/capabilities only |
| Full execution provenance manifest | **Deferred** to issue #11 |
| Corpus doctor/invariant validator | **Deferred** to issue #12 |
| MCP server / RAG application | Future consumer/integration work; not canonical authority |

## Documentation authority

Use the repository documentation layers as follows:

```text
README     = current project orientation / operational entry point
specs      = authoritative behavioral contracts
audits     = measured state at a point in time
ADRs       = durable architectural decisions and trade-offs
```

This architecture area is cross-cutting specification context. It does not rewrite historical audits, defect specifications, or migration history.
