# col-taxdata domain model

## Purpose and authority

This document defines the cross-cutting conceptual model used by `col-taxdata`. It describes what the important entities mean independently of the current SQLite table layout while explicitly mapping to the implementation that exists today.

A conceptual entity does not imply a one-to-one table. For example, `Issuer` is a domain concept but currently has no standalone `issuers` table; issuer information is carried by normalized keys in canonical identity and fields such as `documents.entity` and `document_identifiers.issuer`.

## Core boundaries

```text
Source
  -> Manifestation
      -> Raw Evidence
      -> Text Extraction
          -> Extracted Segment
              -> Evidence

Document
  -> Provision

Reference Mention
  -> Reference Resolution

Explicit Relation Mention
  -> Relationship
      -> Relationship Provenance
          -> Evidence

Temporal Candidate
  -> Temporal Role Resolution
      -> Temporal Event
          -> Evidence
```

And the principal distinction:

```text
Source URL != Manifestation != Document

cited Document/Provision != identity of the citing Document
```

## Entity catalog

### Source

**Represents:** a known acquisition origin, currently keyed primarily by an official URL plus authority/source-kind metadata.

**Does not represent:** the bytes retrieved at one point in time, or the canonical legal document described by the page.

**Identity boundary:** `sources.source_id`. DIAN crawler sources are deterministically derived from URL; other configured sources may use an explicitly assigned `SRC-*` ID.

**Lifecycle:** discovered/configured -> fetched zero or more times -> may produce multiple manifestations over time.

**Provenance:** keeps source URL, authority, source kind, discovery link, first/last seen times. Individual HTTP attempts are in `fetches`.

**Mutability/reprocessing:** source metadata such as last-seen time may change. Reprocessing derived legal data does not create a new Source merely because a parser version changes.

**Invariants:**
- one `source_url` is unique in the current schema;
- a source may be a navigation/index page and need no canonical document identity;
- source authority is acquisition metadata, not by itself sufficient proof of the issuer of every cited norm on that page.

### Manifestation

**Represents:** one archived byte-level observation obtained from a Source.

**Does not represent:** the abstract/canonical legal work.

**Identity boundary:** `manifestations.manifestation_id`. Current fetch logic derives `MAN-*` from `source_id + raw SHA-256`.

**Lifecycle:** successful fetch -> registered immutable raw file -> zero or more versioned extractions -> optional canonical `document_id`.

**Provenance:** Source FK, SHA-256, byte size, retrieval time, content type, HTTP metadata, local path.

**Mutability/reprocessing:** raw bytes and their SHA-256 are immutable. The nullable link to a canonical document is derived interpretation and may be corrected/rebound by controlled reprocessing.

**Invariants:**
- same source + same bytes reuses manifestation identity;
- identical bytes from different sources remain different manifestations even if their content-addressed raw file path is shared;
- raw SHA-256 must remain traceable through downstream evidence.

### Raw Evidence

**Represents:** the immutable retrieved bytes plus enough registered metadata to verify where/when they were obtained and that they have not changed.

**Does not represent:** a parsed text interpretation or a legal conclusion.

**Physical/conceptual boundary:** there is no separate `raw_evidence` table. The concept is formed by the content-addressed file under `data/raw/sha256/`, the Manifestation row, Source metadata, and fetch history.

**Lifecycle:** fetched -> hashed -> atomically persisted/reused -> permanently available as the base for reprocessing.

**Provenance:** SHA-256 is the primary content integrity link.

**Mutability/reprocessing:** immutable; never rewritten by defect repair or reprocessing.

### Document

**Represents:** a canonical legal/official work independent of any single web page or file.

**Does not represent:** a source URL, manifestation, quoted norm, or arbitrary extracted heading.

**Identity boundary:** `documents.document_id`, normally derived from a canonical identity key. The canonical key is held in `document_identifiers`.

**Lifecycle:** identity candidate -> accepted canonical document or unresolved -> may accumulate manifestations, identifiers, provisions, relationships, temporal events, case references.

**Provenance:** identity signals and, where registrars provide it, `document_identifier_evidence`; Manifestations linked to the Document retain raw provenance.

**Mutability/reprocessing:** display metadata can be updated. Canonical identity must not be silently changed; identity corrections/splits use deterministic reprocessing and migration provenance where required.

**Invariants:**
- a cited norm is not the identity of the citing source;
- ambiguous identity remains unresolved;
- same type/number/year can represent distinct documents when issuers differ;
- one Document can have multiple Manifestations.

- zero linked Manifestations do not by themselves prove that a Document is stale or legally invalid;
- a source-less Document is protected while an active canonical/derived binding depends on it, or while explicit canonical-identifier evidence supports it;
- a source-less Document with neither active bindings nor identifier provenance is unsupported derived residue and may be removed only through the deterministic DEF-0009 lifecycle cleanup;
- malformed/conflicting source-less provenance is retained for review rather than treated as deletion permission.

**Source-less lifecycle boundary:** `document_identifier_evidence` is the current explicit provenance mechanism for a canonical identifier that is supported by evidence from another Manifestation. Active reference resolutions are also protected dependencies and carry their own mention/extraction/Manifestation provenance chain. Other active direct or polymorphic Document bindings block cleanup even when separate identity evidence is absent; their owning subsystem must be resolved first. Cleanup classifies database support state only and never infers that the underlying legal instrument does not exist.


### Issuer

**Represents:** the normalized authority that issued the canonical document, such as `DIAN`, `BANREP_JD`, `CORTE_CONSTITUCIONAL`, `CONGRESO`, or `PRESIDENCIA`.

**Does not represent:** merely the website hosting the content, nor free-form display wording.

**Identity boundary:** normalized issuer keys defined by current identity logic. There is no standalone issuer table.

**Lifecycle:** derived from trusted source-family constraints and/or compatible document metadata during identity assessment.

**Provenance:** current implementation carries issuer in identity signals, canonical keys for issuer-scoped types, `documents.entity`, and `document_identifiers.issuer`.

**Mutability/reprocessing:** issuer normalization changes are identity-sensitive and require controlled migration/reprocessing rather than ad-hoc row edits.

### Canonical Identity

**Represents:** the normalized identity rule that says which observations belong to the same Document.

**Does not represent:** a title string, first matching heading, URL alone, or citation found inside another document.

**Identity boundary:** a canonical key. For issuer-scoped document types the implemented form is generally:

```text
CO:<issuer_key>:<document_type>:<number>:<year>
```

For families whose issuer is intrinsic to the supported national document type, current helpers retain the established non-issuer-qualified form:

```text
CO:<document_type>:<number>:<year>
```

Other official-document families may use a family-specific canonical key, for example the DIAN RUT cancellation guidance registrar.

**Lifecycle:** trusted source-family signal + compatible family content -> accepted; conflict/incompleteness -> unresolved/review.

**Invariants:** deterministic where supported; issuer-aware where type/number/year is not unique; never guessed through ambiguous evidence.

### Document Identifier

**Represents:** a typed identifier attached to a canonical Document, including the primary canonical key and compatible aliases.

**Does not represent:** a separate legal document merely because the textual identifier differs.

**Identity boundary:** `document_identifiers.identifier_id`, with uniqueness on `(document_id, identifier_type, identifier_value)`.

**Lifecycle:** created during document registration/migration; may retain legacy non-primary aliases when useful.

**Provenance:** `document_identifier_evidence` can bind an identifier to exact evidence. The `issuer` field records issuer context where applicable.

**Mutability/reprocessing:** primary/alias status can be migrated; provenance must be retained.

### Provision

**Represents:** a stable addressable subdivision of a Document, currently especially articles.

**Does not represent:** the particular wording observed in one extraction.

**Identity boundary:** `provisions.provision_id`, currently deterministic from Document identity plus normalized provision kind/designation.

**Lifecycle:** canonical provision registration -> one or more `provision_observations` from extraction segments -> references/relationships can target it.

**Provenance:** observations bind provision identity to extraction/segment text and hashes.

**Mutability/reprocessing:** the Provision identity is canonical; observations are derived and reprocessable. Conflicting observations are recorded in `provision_designation_conflicts` rather than silently overwriting legal text.

### Text Extraction

**Represents:** one versioned normalized text result produced from a Manifestation by a named extractor/version.

**Does not represent:** raw source bytes or a canonical document.

**Identity boundary:** `text_extractions.extraction_id`; current Normograma `EXT-*` includes manifestation + extractor name + version.

**Lifecycle:** verify raw file size/SHA -> parse/normalize -> write content-addressed normalized output -> create segments/FTS.

**Provenance:** Manifestation FK, extractor name/version, normalized SHA-256, output path and counts.

**Mutability/reprocessing:** derived. A changed extractor version produces a separate extraction identity; the raw manifestation remains untouched.

**Invariant:** if the same extraction identity would produce different registered output, extraction fails rather than silently overwriting it.

### Extracted Segment

**Represents:** an addressable portion of a specific Text Extraction, with type, sequence, offsets, text and text hash.

**Does not represent:** a canonical Provision by itself. Multiple segments/observations can relate to the same Provision.

**Identity boundary:** `extracted_segments.extracted_segment_id`, currently `SEG-*` derived from extraction + sequence + text SHA.

**Lifecycle:** created with extraction -> indexed in FTS -> used by evidence, references, provisions, doctrine/guidance and temporal candidates.

**Provenance:** direct Extraction FK; Extraction leads to Manifestation/Source/raw SHA.

**Mutability/reprocessing:** derived/version-scoped. A new extraction can produce different segment IDs without changing raw evidence.

### Claim

**Represents:** a structured assertion. In the current repository it is actively used by registered case bundles and their canonical evidence bindings.

**Does not represent:** a universally accepted legal fact merely because a row exists or because an LLM emitted text.

**Identity boundary:** `claims.claim_id`. Current case-bundle registration accepts claim IDs supplied by the bundle; there is no repository-wide deterministic claim-ID algorithm that issue #9 can guarantee.

**Lifecycle:** candidate/declared -> supported through evidence or canonical relationships -> validated/human-verified, rejected, conflicting, or unresolved according to workflow.

**Provenance:** evidence can point directly to the claim; case items can also bind canonical relationships/evidence supporting it.

**Mutability/reprocessing:** case-analysis derived state. Claims are not used as the universal canonical storage for Document identity, Reference Resolution, Relationship, or Temporal Event.

### Evidence

**Represents:** an exact evidentiary binding from a structured assertion/relationship/event/identifier/case claim to a source span.

**Does not represent:** the source file as a whole; that is Raw Evidence/Manifestation.

**Identity boundary:** `evidence.evidence_id`. Multiple generators create deterministic `EVD-*` IDs from generator-specific material; there is no single universal evidence-ID formula.

**Lifecycle:** created by registrars/promoters/temporal processors/case binding -> referenced by canonical/derived entities -> retained for auditability.

**Provenance:** manifestation, preferred extracted segment, exact quote, offsets, source URL, source SHA-256, retrieval time, extraction method/version.

**Mutability/reprocessing:** derived, but already-established provenance should not be destroyed merely to replace a derived interpretation. New processor versions may create new evidence identities.

**Invariant:** validated/canonical assertions should remain traceable to evidence and ultimately raw SHA-256.

### Reference Mention

**Represents:** one detected textual reference to a document or article in an Extracted Segment.

**Does not represent:** a successfully identified target.

**Identity boundary:** `reference_mentions.reference_mention_id`, deterministic for detector run + segment + span + normalized reference.

**Lifecycle:** detected as candidate -> separately resolved/unresolved/ambiguous.

**Provenance:** detection run, extraction, segment, raw/context text, offsets, detector method/version.

**Mutability/reprocessing:** derived/versioned through the detection run.

### Reference Resolution

**Represents:** the outcome of resolving a Reference Mention to a canonical Document and optionally Provision.

**Does not represent:** a reference mention itself, nor a guessed target.

**Identity boundary:** `reference_resolutions.reference_resolution_id`, currently deterministic from mention + resolution method.

**Lifecycle:** resolution attempt -> `resolved`, `unresolved`, or `ambiguous`; review item where required.

**Provenance:** retains the Reference Mention and resolution method; downstream relationship provenance also links the exact resolution used.

**Mutability/reprocessing:** derived and rerunnable when corpus coverage or resolver logic changes. Ambiguity stays explicit.

### Explicit Relation Mention

**Represents:** explicit language in a segment indicating a typed relation such as modification/repeal/other supported relation against a detected reference.

**Does not represent:** the promoted canonical Relationship.

**Identity boundary:** `explicit_relation_mentions.relation_mention_id`.

**Lifecycle:** detector identifies trigger + target reference mention -> candidate -> used by a relationship promoter only when target resolution meets requirements.

**Provenance:** detection run, extraction, segment, trigger/context text and target Reference Mention.

**Mutability/reprocessing:** derived/versioned.

### Relationship

**Represents:** a promoted typed edge between canonical legal entities, currently documents/provisions.

**Does not represent:** chronology-based inference or every citation.

**Identity boundary:** `relationships.relationship_id`; current promoters use deterministic material including source, relation type, target, relation mention and promoter version.

**Lifecycle:** explicit relation mention + resolved target + promoter -> candidate/validated relationship according to the promoter path; may later be rebuilt/rebound after identity changes.

**Provenance:** direct evidence plus `relationship_provenance` linking the relation mention and reference resolution. Temporal bases may additionally link relationship dates to temporal events.

**Mutability/reprocessing:** derived; safe rebuilding must preserve/reconstruct provenance and must not manufacture unresolved relationships.

**Invariant:** ambiguous relationships remain unresolved/not promoted; absence of a relationship is not proof that no legal relationship exists.

### Temporal Candidate

**Represents:** one observed date or commencement-rule span that might satisfy a temporal role for a Document.

**Does not represent:** a validated document-level date/event merely because it matched text.

**Identity boundary:** `temporal_candidates.temporal_candidate_id` (`TCA-*`) is versioned by extraction, role, segment/span and processor.

**Lifecycle:** detect -> classify context/trusted structure -> persist with exact Evidence -> participate in role resolution.

**Provenance:** exact segment, offsets/quote, Evidence, manifestation/document, processor name/version.

**Mutability/reprocessing:** derived and explicitly rebuildable under DEF-0004.

### Temporal Role Resolution

**Represents:** the decision for one extraction/document temporal role (`publication_date`, `issued_date`, `commencement_rule`): resolved, unresolved, or ambiguous.

**Does not represent:** a legal event itself.

**Identity boundary:** `temporal_role_resolutions.temporal_resolution_id` (`TRS-*`) by extraction + role + processor/version.

**Lifecycle:** evaluate all role candidates -> promote exactly one trusted candidate only when uniquely supported -> otherwise leave unresolved/ambiguous.

**Provenance:** candidate counts and optional promoted candidate.

**Mutability/reprocessing:** derived/versioned.

### Temporal Event

**Represents:** a structured evidence-backed event affecting a document/entity, such as issued, published, effective-from, modified, repealed, suspended, annulled, or doctrinal events where supported.

**Does not represent:** a permanent Boolean status.

**Identity boundary:** `temporal_events.temporal_event_id` (`TEV-*` in current processors). Exact derivation is processor-specific and often includes processor/parser version.

**Lifecycle:** promoted from sufficiently supported temporal evidence -> validated/candidate/etc. Older processor events may be retained and superseded rather than erased.

**Provenance:** primary `evidence_id` plus zero or more `temporal_event_evidence` roles; relationship temporal bases can reference events.

**Mutability/reprocessing:** derived. Reprocessing may supersede/rebuild events while retaining historical evidence/provenance.

**Invariant:** ambiguous temporal state remains unresolved; absence of an event is not proof of legal non-effect.

### Review Queue Item

**Represents:** a durable indication that a machine decision is unresolved, ambiguous, conflicting, or otherwise needs review.

**Does not represent:** evidence of a legal conclusion.

**Identity boundary:** `review_queue.review_id`; current generators use deterministic `REV-*` IDs with subsystem-specific inputs.

**Lifecycle:** opened/reopened by an unresolved condition -> may be resolved by deterministic reprocessing or human/system review metadata.

**Provenance:** points to the entity under review and a reason code.

**Mutability/reprocessing:** workflow state is mutable. Reprocessing should reopen/resolve the same deterministic review identity where the underlying condition is the same rather than creating uncontrolled duplicates.

### Derived State

**Represents:** any state computed from preserved evidence and processing rules rather than being the immutable fetched bytes themselves.

Examples include:

- normalized text extractions and segments;
- FTS indexes;
- identity signals and canonical bindings;
- provisions/observations;
- reference detections/resolutions;
- relationships/provenance;
- temporal candidates/resolutions/events;
- review items;
- case claims/materialized reports;
- crawler processing metadata.

**Does not represent:** a license to delete provenance. “Rebuildable” means the system can recompute it from preserved inputs and rules; replacement must remain auditable.

**Identity boundary:** depends on the derived entity.

**Mutability/reprocessing:** generally reprocessable, often versioned, and expected to be deterministic/idempotent where applicable.

## Knowledge representation, not graph database

The domain naturally contains nodes and edges:

```text
Document / Provision
        |
        +<---- Relationship ---->+
        |                        |
Document / Provision        Document / Provision
```

SQLite tables and foreign keys implement that representation today. “Knowledge graph” in project discussions describes the legal knowledge structure, not a requirement for Neo4j, RDF, or another graph database.

## Immutable versus derived summary

| Concept | Immutable? | Rebuildable/reprocessable? |
| --- | --- | --- |
| Source URL record | No; metadata evolves | Not normally rebuilt from parser output |
| Manifestation raw bytes + registered SHA | **Yes** | **No rewriting** |
| Fetch history | Audit history; append-oriented | Not a legal derived fact |
| Text Extraction / Extracted Segment | No | Yes, by extractor version |
| Canonical Document identity | Canonical derived identity, not raw | Controlled reprocessing/migration only |
| Provision / observation | Derived | Yes, with identity/provenance constraints |
| Evidence row | Derived binding, provenance-sensitive | May be regenerated/versioned; do not destroy traceability |
| Reference/Resolution | Derived | Yes |
| Relationship | Derived | Yes |
| Temporal Candidate/Resolution/Event | Derived | Yes; retain evidence/history as specified |
| FTS index | Derived | Yes |
| Case report/source manifest | Derived materialization | Yes from canonical case state |

The immutable boundary is the archived raw manifestation and its integrity/provenance record. Canonical/derived layers may change as parsers and legal-data rules improve, but they must remain traceable to that boundary.
