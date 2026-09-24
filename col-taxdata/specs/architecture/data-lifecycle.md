# col-taxdata data lifecycle

## Lifecycle at a glance

```text
official source
  -> discovery
  -> fetch
  -> immutable raw manifestation
  -> SHA-256 registration
  -> extraction
  -> segmentation
  -> source-family classification
  -> canonical identity
  -> provisions
  -> references
  -> resolution
  -> relationships
  -> temporal candidates / role resolutions / events
  -> retrieval / index
  -> case analysis
  -> future MCP / LLM consumer
```

This is a conceptual data lifecycle. Individual tools can combine or order compatible derived stages differently, and source-specific registrars exist. The invariant is the dependency and provenance boundary: no downstream interpretation may rewrite primary raw evidence.

## The fundamental boundary

```text
IMMUTABLE EVIDENCE
Source acquisition
  -> Manifestation registration
  -> raw bytes
  -> raw SHA-256 / byte size / retrieval metadata

----------------------- provenance boundary -----------------------

REBUILDABLE DERIVED STATE
Extraction / segments / FTS
  -> identity / provisions
  -> reference detections / resolutions
  -> relationships
  -> temporal candidates / events
  -> case claims / materialized reports
```

“Rebuildable” does not mean disposable without care. Derived rows can be referenced by other derived entities. Controlled reprocessing must rebuild/rebind/supersede dependent state deterministically and preserve the provenance chain.

## Stage contracts

### 1. Official source / discovery

**Input:** configured seed URLs or links discovered from an allowlisted official page.

**Output:** Source records, crawl-queue entries, and discovery edges.

**State type:** Source/orchestration metadata, not raw legal evidence.

**Provenance:** source URL, authority/source kind, `discovered_from`, discovery edges.

**Failure behavior:** invalid/out-of-scope URLs are not queued; queue items can become `error` and be retried according to crawler policy.

**Ambiguity behavior:** navigation/index pages are allowed to remain non-documents.

**Idempotency:** queue URL is a primary key and discovery edges are unique pairs, so repeated discovery does not create unlimited duplicates.

### 2. Fetch

**Input:** Source URL/ID plus allowlisted-domain configuration.

**Output:** one `fetches` attempt record; on success, a Manifestation and raw file.

**State type:** HTTP attempt history + immutable raw evidence.

**Provenance:** requested/final URL, timestamps, HTTP status/metadata, byte size, SHA-256, errors.

**Failure behavior:** failed HTTP/acquisition attempts are recorded when possible; no successful manifestation is fabricated.

**Ambiguity behavior:** none at the legal-identity layer; fetch does not decide what legal document the bytes represent.

**Idempotency:** `FETCH-*` identifies an attempt and is intentionally new per attempt. Successful same-source/same-bytes content reuses deterministic Manifestation identity.

### 3. Immutable raw manifestation and SHA-256 registration

**Input:** downloaded bytes.

**Output:** content-addressed raw file + `manifestations` row.

**State type:** **immutable evidence**.

**Provenance:** Source FK, SHA-256, byte size, retrieval time, content type, local path and HTTP metadata.

**Failure behavior:** raw integrity mismatch later causes extraction/reprocessing to fail rather than proceed from mutated evidence.

**Ambiguity behavior:** a Manifestation can remain unbound to a Document.

**Idempotency:** same `source_id + sha256` maps to the same current `MAN-*`; the raw physical path is content-addressed by SHA-256.

### 4. Text extraction

**Input:** a Manifestation whose raw file passes registered size/SHA checks.

**Output:** normalized text file + `text_extractions` row.

**State type:** derived/versioned.

**Provenance:** Manifestation, extractor name/version, normalized SHA-256, output path and counts.

**Failure behavior:** unsupported content or parser failure stops that extraction; raw bytes are unchanged. If an existing extraction ID would have different output, the extractor raises rather than overwriting.

**Ambiguity behavior:** extraction may expose multiple headings/dates/references; it should preserve text rather than decide legal meaning prematurely.

**Idempotency:** extraction identity includes manifestation + extractor name/version. Rerun with the same identity reuses matching registered output.

### 5. Segmentation

**Input:** normalized extraction text.

**Output:** ordered `extracted_segments`, each with type, offsets, text and SHA-256; FTS rows are populated from segments.

**State type:** derived/version-scoped.

**Provenance:** each segment points to one extraction, which points to one manifestation.

**Failure behavior:** inconsistent offset calculation or extraction invariants fail the stage.

**Ambiguity behavior:** segment classification is structural, not canonical legal identity.

**Idempotency:** current segment IDs include extraction, sequence and text hash.

### 6. Source-family classification

**Input:** source URL/path plus extracted segments as needed.

**Output:** a source-family identity signal such as normative act, DIAN Concepto/Oficio, Constitutional Court Sentencia C, CONPES, Constitución, jurisprudence, or unknown.

**State type:** derived.

**Provenance:** `document_identity_signals` stores source URL and compatible content signals.

**Failure behavior:** unsupported/incomplete family remains unresolved; it does not fall through to a quoted generic norm.

**Ambiguity behavior:** family/content conflicts produce review state such as `SOURCE_IDENTITY_CONFLICT`.

**Idempotency:** signal IDs are deterministic for manifestation/extraction/origin/raw signal.

### 7. Canonical document identity

**Input:** trusted source-family constraints plus compatible family-specific/generic content evidence.

**Output:** accepted Document + identifiers + manifestation binding, or explicit unresolved review state.

**State type:** canonical derived state.

**Provenance:** identity signals, canonical/alias identifiers, identifier evidence where supported, manifestation/source chain.

**Failure behavior:** conflict/incomplete issuer/ambiguous family remains unresolved; an existing conflicting manifestation binding is not silently retained.

**Ambiguity behavior:** **never guess**. A cited norm cannot become the citing document's identity. Issuer ambiguity remains unresolved.

**Idempotency:** canonical keys and most `DOC-*` registration paths are deterministic. Identity migrations can split/rebind prior derived state while recording migration provenance.

**Zero-Manifestation lifecycle:** absence of a linked Manifestation is not a deletion rule. A source-less Document is retained while an active binding depends on it (including an active reference-resolution target) or while its primary canonical identifier has valid `document_identifier_evidence` backed by the registered Manifestation SHA. Broken/malformed provenance is retained as a conflict. Only a source-less Document with one primary canonical key, no active direct/polymorphic binding and no identifier evidence is stale derived residue eligible for `tools/cleanup_unreferenced_documents.py`. The cleanup is dry-run by default, discovers current direct Document FKs from SQLite metadata, rechecks candidates inside an immediate transaction on apply, and verifies the Manifestation registry digest is unchanged.


### 8. Provision registration

**Input:** canonical Document + qualifying structural segments.

**Output:** canonical `provisions` and version/extraction-specific `provision_observations`; conflicts where duplicate designations disagree.

**State type:** derived/canonical legal structure.

**Provenance:** provision observations point to exact extraction segments and hashes.

**Failure behavior:** malformed/unsupported structure can fail registration without changing raw evidence.

**Ambiguity behavior:** conflicting observed texts are represented as conflicts, not silently chosen.

**Idempotency:** provision identity is deterministic from document + normalized designation in current registrars; observation identity includes extraction/segment/parser context.

### 9. Reference detection

**Input:** Extracted Segments.

**Output:** deterministic `reference_detection_runs`, `reference_mentions`, and `explicit_relation_mentions`.

**State type:** derived/versioned.

**Provenance:** detector name/version, extraction, segment, offsets, raw/context text.

**Failure behavior:** detector failure leaves canonical state unchanged.

**Ambiguity behavior:** detection creates candidates; a mention is not treated as a resolved target.

**Idempotency:** same extraction + detector/version reuses the same detection-run identity.

### 10. Reference resolution

**Input:** Reference Mentions + current canonical Document/Provision inventory.

**Output:** `reference_resolutions` with `resolved`, `unresolved`, or `ambiguous` status; review items where needed.

**State type:** derived.

**Provenance:** resolution method and original mention are retained.

**Failure behavior:** missing target or insufficient issuer context stays unresolved; multiple valid targets stay ambiguous.

**Ambiguity behavior:** **never select a target just to complete the graph**.

**Idempotency:** current resolution IDs are deterministic from mention + resolution method and can be updated/recomputed when corpus coverage changes.

### 11. Relationship promotion

**Input:** Explicit Relation Mention + acceptable Reference Resolution + source Document identity.

**Output:** canonical/derived `relationships`, exact Evidence, and `relationship_provenance`.

**State type:** derived legal knowledge representation.

**Provenance:** relationship -> provenance -> explicit relation mention + reference resolution; relationship evidence -> segment -> extraction -> manifestation/raw SHA.

**Failure behavior:** unresolved source/target prevents promotion. Identity migrations may require relationship deletion/rebuild/rebinding because endpoints changed.

**Ambiguity behavior:** ambiguous relationships remain unpromoted/unresolved.

**Idempotency:** relationship IDs include semantic endpoints, relation mention, and promoter version in current promoters.

### 12. Temporal candidates, resolutions and events

**Input:** canonical Document + extraction segments.

**Output:** all `temporal_candidates` with Evidence; one `temporal_role_resolution` per processed role/version; only uniquely trusted evidence may produce validated `temporal_events`.

**State type:** derived/versioned.

**Provenance:** candidate and event evidence retain exact segment/span/raw SHA chain; events can have multiple evidence roles.

**Failure behavior:** candidate cardinality zero or greater than one is not a document-level failure. Processor execution errors remain errors, but missing/ambiguous legal evidence becomes structured unresolved state.

**Ambiguity behavior:**
- one uniquely trusted candidate -> `resolved`;
- multiple candidates/trusted candidates -> `ambiguous` where applicable;
- no sufficient candidate -> `unresolved`;
- publication is not silently equated to effectiveness.

**Idempotency:** candidate/resolution/event IDs include processor/parser version. DEF-0004 reprocessing supports dry-run and was verified idempotent against the corpus.

### 13. Retrieval / FTS index

**Input:** Extracted Segments.

**Output:** SQLite FTS5 rows in `extracted_segments_fts`.

**State type:** derived index.

**Provenance:** FTS result IDs point back to extracted segments and through extraction to raw manifestation.

**Failure behavior:** retrieval/index issues do not justify rewriting extracted or raw evidence.

**Ambiguity behavior:** search ranking is relevance behavior, not legal truth. Duplicate equivalent text is a retrieval concern tracked separately by DEF-0005.

**Idempotency/reprocessing:** index may be rebuilt from extracted segments. Rebuild must not change canonical evidence/identity merely to improve ranking.

### 14. Case analysis and materialization

**Input:** canonical documents/relationships/evidence, extracted segments, case query and explicit case bindings.

**Output:** `cases`, `case_items`, supported `claims`, case evidence, source manifests and reports.

**State type:** derived case-analysis layer.

**Provenance:** validated case claims require canonical evidence or relationship support; materialized source/report files can be checked against SQLite state.

**Failure behavior:** missing bindings, unsupported validated claims, orphan case items, manifest drift or report drift cause case validation failures.

**Ambiguity behavior:** unresolved case facts remain unresolved; a report must not manufacture canonical support.

**Idempotency:** case registration/materialization is designed to reuse deterministic bindings and reproduce files from canonical state.

**Materialization freshness contract:** checked-in case materializations are caches of canonical case state, never an authority over it. A case source manifest or report is **current** only when its exact UTF-8 content equals the output of the repository's canonical materializer for the same case, canonical SQLite state, and declared case-local materializer inputs such as `unresolved.json`. Equality of source IDs or continued existence of claims is not sufficient. Any case-visible canonical change — including relationship evidence rebinding, evidence replacement, source-kind normalization, identity/reprocessing changes, or future temporal/reference replay that changes rendered case output — makes the affected materialization stale.

Freshness is detected by deterministic render-and-compare. Refresh must use `tools/rematerialize_case.py`: preview is the default and performs no writes; `--write` applies exactly the previewed canonical renders and immediately verifies convergence. Generated report/source lines must not be hand-edited to follow canonical IDs or labels. Repeating refresh with unchanged inputs must produce zero writes and byte-identical files. Materialization hashes may be reported as comparison aids, but they do not replace the underlying evidence/provenance chain.

### 15. Future MCP / LLM consumer

**Input:** retrieval results, canonical entities, evidence and/or validated case material.

**Output:** future user-facing retrieval/analysis responses or proposed candidates.

**State type:** consumer/application layer; **not currently a canonical authority**.

**Provenance:** consumers should surface/use the existing evidence chain rather than replace it.

**Failure/ambiguity behavior:** uncertain legal facts remain uncertain. LLM output must not silently write canonical identity/state/provenance.

**Idempotency:** not specified by current implementation; execution-level reproducibility is future issue #11.

## Safe reprocessing rules

The preferred pattern is:

```text
existing immutable raw
    -> new/existing parser version
    -> new/rebuilt derived state
```

Safe reprocessing must:

- verify the raw input still matches its registered SHA-256;
- execute deterministic decision logic for the chosen processor/version;
- use dry-run/preview for state-changing reprocessing workflows where implemented/required;
- preserve explicit unresolved/ambiguous outcomes;
- rebuild dependent derived state when canonical endpoints change;
- preserve or supersede provenance instead of erasing the evidence trail;
- avoid redownloading when the existing immutable manifestation is the intended input.

## What must never be inferred

The lifecycle deliberately refuses these shortcuts:

- source page == canonical Document;
- first legal-looking heading == source identity;
- cited norm == citing Document;
- same type/number/year == same Document across issuers;
- missing temporal evidence == “not effective”;
- publication date == effective date without an explicit rule;
- later document == repeal/reconsideration merely by chronology;
- no detected relationship == proof that no relationship exists;
- LLM output == canonical legal fact.
