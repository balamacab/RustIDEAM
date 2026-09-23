# Initial data model

> **Status:** implementation-oriented historical context. This file describes the project's initial data-model framing and is retained because it explains schema history. The authoritative cross-cutting architecture/domain semantics are now [`../specs/architecture/domain-model.md`](../specs/architecture/domain-model.md), [`../specs/architecture/data-lifecycle.md`](../specs/architecture/data-lifecycle.md), and the related ADRs. Where this initial description omits later implemented concepts (for example issuer-aware identity or DEF-0004 temporal candidates/resolutions), use the current schema, verified specs, and architecture documents rather than inferring the old model is still complete.

## Core principle

The model separates:

- **document**: logical legal/accounting document;
- **manifestation**: a concrete downloaded HTML/PDF/file;
- **segment**: addressable fragment of extracted text;
- **claim**: structured assertion extracted from the source;
- **evidence**: exact source fragment supporting a claim or relationship;
- **relationship**: typed edge between legal entities;
- **temporal event**: dated legal/doctrinal event;
- **review item**: unresolved or ambiguous machine result.

This separation prevents a parser or LLM extraction from becoming the source of truth.

## Identity

A document receives an internal stable ID independent of its legal number.

Legal numbers, internal DIAN numbers, radicados, case numbers, etc. are stored in `document_identifiers`.

A single document can have multiple manifestations, for example:

```text
Concepto DIAN X
├── HTML Normograma
└── PDF DIAN
```

Each manifestation has its own SHA-256.

## Claims

Claims are atomic structured assertions such as:

```text
Concepto A --reconsiders--> Concepto B
Concepto A --interprets--> Artículo 107 ET
```

A claim is not considered proven merely because an LLM emitted it.

Initial claim statuses:

- candidate
- validated
- rejected
- conflicting
- unresolved
- human_verified

## Evidence

Evidence points to an exact segment and may additionally preserve page number and character offsets.

A validated claim should normally have at least one evidence record referring back to a manifestation with a SHA-256 and source URL.

## Relationships

Initial controlled relation families include:

Reference:
- cites
- references
- interprets
- applies
- regulates
- based_on

Normative:
- modifies
- adds
- substitutes
- repeals
- partially_repeals
- suspends_effects
- restores_effects

Jurisprudential:
- annuls
- partially_annuls
- provisionally_suspends
- unifies_case_law

Doctrinal:
- reiterates
- clarifies
- adds_doctrine
- modifies_doctrine
- reconsiders
- revokes_doctrine
- replaces_doctrine

A later document does **not** imply repeal or reconsideration by chronology alone.

## Temporal model

Temporal state is event-based rather than a permanent `vigente=true` field.

Examples:

- issued
- published
- effective_from
- modified
- partially_modified
- repealed
- partially_repealed
- suspended
- annulled
- reconsidered
- clarified
- superseded

The effective state of an entity is computed for an `as_of` date from supported events.

Normative status and doctrinal status must remain distinct.

## Human review

Low-confidence extraction is only one reason for review.

Other review reasons include:

- AMBIGUOUS_DOCUMENT_ID
- TARGET_DOCUMENT_NOT_FOUND
- CONFLICTING_DATES
- RELATION_UNCONFIRMED
- SOURCE_CONFLICT
- OCR_LOW_QUALITY
- TEMPORAL_STATUS_UNKNOWN
- LLM_DISAGREEMENT

## Provenance chain

The intended audit chain is:

```text
claim
  -> evidence
      -> segment
          -> manifestation
              -> source URL
              -> SHA-256
              -> retrieval timestamp
```

LLM runs will later also store model hash, prompt/schema version and raw structured output.

## Versioned text extraction

The initial `segments` table is retained for schema compatibility but is not used by the first production extraction path.

Canonical extracted text is versioned through:

- `text_extractions`: one deterministic output per manifestation + extractor + extractor version;
- `extracted_segments`: addressable segments tied to a specific extraction;
- `extracted_segments_fts`: derived full-text index.

This avoids overwriting segment offsets when the parser changes. Evidence should prefer `evidence.extracted_segment_id` for newly generated records.

For the Normograma DIAN adapter, extraction is deterministic and deliberately excludes page chrome before the first legal-document heading and after the DIAN compilation footer. The immutable raw HTML remains the primary preserved source.
