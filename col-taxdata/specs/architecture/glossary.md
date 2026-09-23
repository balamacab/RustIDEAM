# col-taxdata glossary

This glossary defines recurring project terms for an experienced Data Engineer who does not need prior Legal Informatics terminology.

## A–C

### Ambiguity

A state where available evidence supports more than one plausible interpretation or target and the deterministic rules cannot select exactly one. In `col-taxdata`, ambiguity is data to preserve, not a reason to guess. Examples include multiple issuer-compatible reference targets or multiple trusted temporal candidates.

### Canonical

The normalized project representation chosen to identify or structure the same domain thing consistently. “Canonical” does **not** mean that a row is legally infallible; it means the project has accepted it under its deterministic rules and provenance requirements.

### Canonical identity

The rule/key that determines which observations belong to the same logical Document. For issuer-scoped document types it includes a normalized issuer key so, for example, two `Resolución 1 de 2018` instruments from different issuers do not collapse into one Document.

### Corpus

The collected body of Sources, Manifestations, extracted text, canonical/derived entities, indexes and supporting provenance that `col-taxdata` operates on. The raw corpus is preserved evidence; the interpreted corpus includes rebuildable derived state.

## D–F

### Derived state

Data computed from preserved inputs rather than the original retrieved bytes. Examples: normalized text, segments, FTS entries, canonical bindings, provisions, reference resolutions, relationships and temporal candidates/events. Derived state can be rebuilt, but dependent provenance must be preserved/reconstructed correctly.

### Deterministic processing

Processing in which the same defined inputs, rules and processor version produce the same decision/result identity. Many current IDs use UUIDv5 over explicit identity material. Determinism is preferred for canonical legal facts because it is testable and auditable.

### Dry-run

A preview execution that runs the same decision logic intended for an apply operation but commits no persistent mutation. It reports expected changes, conflicts, unresolved cases and counts. Issue #9 itself is documentation-only, so reprocessing dry-run is N/A.

### Evidence

A structured binding to an exact source span that supports a claim, identifier, relationship or temporal event. Current evidence rows carry an exact quote/offsets plus the manifestation/source SHA chain. Do not confuse **Evidence** with **Raw Evidence**.

### FTS

Full-Text Search. The current implementation uses SQLite FTS5 over extracted segments. FTS is a derived retrieval index; a search hit is not a canonical legal fact.

## I–M

### Idempotency

The property that repeating the same operation with the same defined inputs/version does not create unintended additional state or change the result. Example: the same Normograma extraction ID is reused when its registered output matches; post-DEF-0004 temporal reprocessing was verified to produce zero delta on a second run.

### Information extraction

Turning source text into structured candidates/entities such as segments, document identity signals, references, relation mentions or temporal candidates. Extraction answers “what structure can be observed in the text?” and does not by itself prove legal truth.

### Information retrieval

Finding relevant already-ingested material, for example with FTS. Retrieval answers “what stored text/entities are relevant to this query?” It is downstream of preservation/extraction and must not rewrite canonical or evidence state.

### Issuer-aware identity

Canonical identity that accounts for the authority issuing the instrument when type/number/year alone can collide. It is the DEF-0002 rule preventing distinct issuer instruments from sharing one canonical Document.

### Knowledge graph

A graph-shaped view of knowledge where entities are nodes and typed relationships are edges. In `col-taxdata` this is a **conceptual/legal representation**. It does not imply a graph database.

### Knowledge representation

The structured model used to encode legal entities and their supported connections: Documents, Provisions, References, Relationships, Temporal Events, Evidence, etc. SQLite relational tables implement this representation today.

### Manifestation

One concrete archived byte observation of a Source. A page changing over time can produce multiple Manifestations. A Manifestation has its own SHA-256 provenance and is not the same thing as a canonical Document.

### MCP

Model Context Protocol. In this project it refers to a possible future interface through which an AI/application can access structured/retrieved data and tools. MCP is not currently the authority that creates legal truth; a future MCP layer must consume the canonical/evidence layers.

## P–R

### Provenance

The traceable history showing where a piece of data came from and how it was derived. The key evidence chain is conceptually:

```text
structured fact
  -> Evidence / exact segment
  -> Text Extraction
  -> Manifestation
  -> Source URL
  -> raw SHA-256 + retrieval metadata
```

Some derived entities add detector/resolver/promoter/processor versions to that chain.

### Provision

An addressable subdivision of a canonical Document, such as an article. The Provision identity is separate from the text observed in a particular extraction; `provision_observations` records those manifestation/extraction-specific observations.

### RAG

Retrieval-Augmented Generation. A future RAG workflow would retrieve relevant `col-taxdata` evidence/canonical material and provide it to a generative model. The generated answer is downstream output; it must not overwrite or become the canonical legal authority.

### Raw evidence

The immutable fetched bytes plus their registered integrity/provenance metadata. Raw evidence is stored content-addressed by SHA-256 and must never be rewritten by a parser, migration or defect fix.

### Reference mention

A detected textual mention that appears to cite a document or article. It is only a candidate reference until resolution.

### Reference resolution

The separate decision that binds a Reference Mention to a canonical Document/Provision or records it as unresolved/ambiguous. Detection and resolution are intentionally separate so a regex match cannot silently become a legal target.

### Relationship

A typed, provenance-backed connection between canonical legal entities, for example a supported modification/repeal/other relation. A Relationship is promoted from explicit relation evidence plus a resolved target; chronology alone is not enough.

### Reprocessing

Running processing again over preserved inputs to rebuild/correct derived state, normally because parser/rules/version changed. Preferred form:

```text
existing immutable raw -> processor/version -> rebuilt derived state
```

Reprocessing must not rewrite raw evidence.

### Review Queue Item

A durable record that a machine decision needs review or remains unresolved/ambiguous/conflicting. It carries a reason code and entity reference; it is not itself a legal conclusion.

## S–T

### Source

A known acquisition origin, usually an official URL plus authority/source-kind metadata. The Source is the place/endpoint from which data is obtained; it is not the downloaded bytes and not automatically the canonical legal Document.

### Source family

A deterministic classification of a source URL/path used to constrain identity parsing, such as normative act, DIAN Concepto/Oficio, Constitutional Court Sentencia C, CONPES or Constitución. Source-family validation prevents quoted legal instruments from becoming the page's own identity.

### Temporal candidate

One observed date/rule span that might satisfy a temporal role such as publication date, issued date or commencement rule. Candidates preserve evidence/context even when no single candidate can be selected.

### Temporal event

A structured, evidence-backed legal/doctrinal event such as issued, published, effective-from, modified, repealed, suspended or annulled where supported. It is not equivalent to a permanent `vigente` flag.

### Temporal state

The effective state of a document/provision at an `as_of` date as derived from supported Temporal Events plus known unresolved facts. It is a computation, not a timeless Boolean stored as legal truth.

## Additional project terms

### Canonical key

The normalized string used by current registrars to encode Document identity. The exact shape is family-dependent; issuer-scoped legal acts commonly use `CO:<issuer>:<type>:<number>:<year>`.

### Extracted Segment

An addressable span inside a particular versioned Text Extraction. It carries sequence/type/offsets/text hash and is the preferred anchor for current Evidence.

### Explicit Relation Mention

Detected text that contains both a target reference and an explicit relation trigger. It is an input to relationship promotion, not the Relationship itself.

### Issuer

The normalized issuing authority of a Document. It differs from the website host or source authority. The current schema does not have a standalone issuer table.

### Rebuildable

Capable of being regenerated from preserved inputs and declared processing rules. Rebuildable does not mean provenance can be discarded.

### Resolved

A state in which the deterministic rules have exactly enough supported information to select a target/result. It does not mean “certain for all legal purposes”.

### Unresolved

A deliberate state used when evidence is missing or insufficient. Unresolved is preferable to filling the gap with a guess.
