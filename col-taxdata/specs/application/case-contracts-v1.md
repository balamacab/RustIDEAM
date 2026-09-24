# Case application contracts v1

## Status and authority

Status: **Active architectural/application contract**

Contract package version: **1.0.0**

Driver: GitHub issue #15.

This specification defines the stable application boundary for creating and analyzing a legal/tax case from natural-language input. It is downstream of the canonical corpus and evidence model documented in ../architecture/. It does not replace those contracts and does not claim that a final case-analysis orchestrator, MCP server, API server, or Ports-and-Adapters implementation already exists.

The companion machine-readable schema is schemas/case-contracts-v1.schema.json. The schema is normative for serialized shape; this document is normative for ownership, trust, lifecycle, cross-object semantics, and canonical-promotion rules.

## 1. Goal and boundary

A normal client supplies the legal/tax problem in ordinary language, with optional explicit metadata such as an as-of date:

    natural-language CaseInput
              |
              v
    provider-neutral case structuring model
              |
              v
    CaseDraft (candidate state only)
              |
              v
    deterministic application validation
              |
              v
    canonical corpus services
              |
              v
    CaseResult (evidence-backed state)

The normal client interface MUST NOT require the client to know or construct:

- CASE-*, CLM-*, DOC-*, SEG-*, EVD-* or MAN-* identifiers;
- relationship identifiers;
- extracted-segment sequence numbers;
- text or raw SHA-256 values;
- source manifests;
- SQLite table/row identifiers;
- internal provenance graph edges.

Those values remain useful for persistence, provenance, audit and debugging. They are not normal client inputs.

CLI, HTTP/API and future MCP transports are adapters over the same conceptual Case Application Service contract:

    CLI ----\
    API -----> Case Application Service
    MCP ----/

The protocol layer MUST NOT duplicate or redefine case semantics.

## 2. Contract versioning

Version 1.0.0 applies to the following public concepts:

- CaseInput
- CaseDraft
- CaseFact
- CaseQuestion
- CandidateClaim
- CaseEvidence
- CaseUnresolved
- CaseResult

Every serialized root/domain object includes:

- kind: stable object discriminator;
- contract_version: exact version understood by the producer.

A breaking change to meaning, ownership, required fields, trust level, or validation semantics requires a new major contract version. Backward-compatible optional fields may be introduced in a minor version only when adapters explicitly support them. Patch changes may clarify wording or constraints without changing the set or meaning of valid objects. Enum additions are treated conservatively as potentially breaking for consumers.

Internal storage refactoring alone does not change the application contract version. A persistence adapter may change without redefining a CaseInput or CaseResult.

A consumer that does not support the supplied major version MUST reject it explicitly rather than guessing how to interpret it.

## 3. Trust and ownership model

| Layer | May produce | Trust meaning | Normal client visibility |
| --- | --- | --- | --- |
| Client | CaseInput and explicitly supplied facts/metadata | Declared by client, not independently verified | Yes |
| Structuring model | CaseDraft, normalized/inferred facts, questions, CandidateClaim objects | Candidate interpretation only | Yes |
| Deterministic application/corpus logic | resolved canonical targets, supported claims, CaseEvidence, CaseResult | Accepted under current deterministic/provenance rules | Yes |
| Persistence/provenance internals | canonical IDs, manifestation IDs, segment IDs, hashes, sequence numbers, relationship IDs | Audit and implementation detail | Debug/audit only |
| Presentation adapter | report/CLI/API/MCP rendering | View of CaseResult; no new legal authority | Yes |

The LLM may structure and propose. It MUST NOT be the canonical authority for Document or Provision identity, issuer identity, Reference Resolution, Relationship truth, Temporal Event/state, Evidence provenance, or validation of a legal claim.

User-provided information is not automatically canonical legal truth either. It remains a case fact with explicit origin until supported or otherwise handled by deterministic/human workflow.

## 4. CaseInput

CaseInput is the only required client-side starting point.

Required:

- kind = case_input
- contract_version = 1.0.0
- problem_text: non-empty natural-language request

Optional:

- as_of_date: explicit ISO 8601 calendar date supplied by the client
- client_reference: opaque client correlation value

Example:

    {
      "kind": "case_input",
      "contract_version": "1.0.0",
      "problem_text": "La sociedad está en liquidación y no tuvo movimientos en 2026. ¿Qué debe hacer para cancelar el RUT?",
      "as_of_date": "2026-09-23",
      "client_reference": "matter-42"
    }

Absence of as_of_date MUST remain absence. The application MUST NOT silently substitute "today" and then present time-sensitive conclusions as if that date had been client supplied. The application may request the missing date or represent resulting temporal uncertainty in CaseUnresolved.

CaseInput contains no canonical or persistence identifiers.

## 5. CaseDraft

CaseDraft is the structured interpretation returned by the case-structuring model and accepted by schema/application validation.

It contains:

- the original problem_text;
- optional as_of_date and client_reference copied from CaseInput;
- facts: CaseFact objects;
- questions: CaseQuestion objects;
- candidate_claims: CandidateClaim objects;
- unresolved: CaseUnresolved objects already visible at intake;
- model_metadata: provider/model execution metadata for traceability.

CaseDraft is **never canonical state**. A syntactically valid CaseDraft means only that the candidate structure can enter deterministic processing.

### 5.1 Draft validation

Before deterministic corpus work, the application MUST:

1. validate the output against the supported schema version;
2. reject unknown required semantics rather than silently dropping them;
3. verify that every fact marked user_provided and carrying a source_quote is traceable to the CaseInput text;
4. preserve missing/ambiguous information as unresolved state;
5. verify every CandidateClaim still has status candidate;
6. reject attempts by model output to inject canonical IDs, evidence IDs, hashes, sequence numbers, or a "validated" claim state into candidate structures.

Malformed or semantically invalid model output does not mutate canonical/case state.

## 6. CaseFact

CaseFact distinguishes information origin and certainty.

The state field is one of:

- user_provided: explicitly stated by the client;
- llm_normalized: faithful normalization of a user statement, for example a normalized date or entity spelling;
- llm_inferred: a model inference not explicitly stated by the client;
- missing: a fact needed for analysis but not available;
- ambiguous: more than one interpretation remains plausible.

Important fields:

- fact_ref: application-local opaque reference, not a persistence ID;
- label and value;
- state;
- source_quote when traceability to client text is applicable;
- requires_confirmation;
- needed_information for missing/ambiguous facts.

Rules:

- user_provided facts MUST NOT be relabeled as inferred;
- llm_normalized and llm_inferred facts remain distinguishable from user_provided facts;
- llm_inferred facts MUST require confirmation unless a later deterministic/human process establishes the fact;
- missing and ambiguous facts MUST identify what information is needed where practical;
- normalization MUST NOT manufacture content absent from CaseInput.

## 7. CaseQuestion

CaseQuestion is a legal or operational question extracted from the request.

Fields include:

- question_ref: application-local reference;
- text;
- category: legal, factual, procedural, temporal, evidentiary, or other;
- status: open or blocked;
- depends_on_fact_refs: optional references to facts whose resolution is required.

A blocked question remains visible; the model/application must not answer it by guessing a missing fact.

## 8. CandidateClaim

CandidateClaim is a proposed legal conclusion or hypothesis.

Required semantics:

- status is exactly candidate;
- requires_canonical_validation is exactly true;
- claim_ref is application-local and MUST NOT be treated as claims.claim_id;
- text contains the proposed conclusion;
- target_hints may contain human-readable legal references but not forced canonical IDs;
- model_confidence, when present, is advisory model metadata and never evidence.

A CandidateClaim MUST NOT become supported merely because:

- the LLM generated it;
- the wording sounds legally plausible;
- a source was retrieved with similar text;
- the client supplied an internal-looking identifier.

Promotion requires deterministic canonical support under the existing corpus/evidence rules or an explicitly modeled human-verification path.

## 9. CaseEvidence

CaseEvidence is the application-facing representation of canonical evidence support.

Normal public fields include:

- evidence_ref: opaque application-facing reference;
- source_ref: opaque application-facing reference to a source entry;
- document_ref and provision_ref when a canonical target is safely exposable through the application contract;
- exact_quote;
- source_url where appropriate;
- retrieved_at where appropriate;
- support_status: validated or human_verified;
- provenance_ref: opaque handle allowing audit/debug expansion.

The public evidence object intentionally does not require a client to understand how evidence is stored.

### 9.1 Debug/audit provenance

An implementation MAY expose an output-only debug_provenance object to authorized diagnostic/audit consumers. It may include internal identifiers such as evidence_id, manifestation_id, extracted_segment_id, document_id, relationship_id, source_sha256, or sequence_no.

debug_provenance:

- is never required for normal analysis;
- is never accepted as normal CaseInput or CaseDraft authority;
- does not allow a caller to bypass canonical resolution;
- must preserve the existing provenance chain if exposed.

## 10. CaseUnresolved

CaseUnresolved is first-class output for uncertainty and missing support.

Categories include:

- missing_fact
- ambiguous_fact
- unresolved_legal_target
- ambiguous_evidence
- corpus_gap
- temporal_uncertainty
- conflicting_evidence
- unsupported_claim
- other

Fields include:

- unresolved_ref;
- category;
- description;
- related fact/question/claim references;
- needed_information where known;
- next_action: ask_client, human_review, corpus_expansion, deterministic_resolution, or none.

An unresolved item MUST NOT be silently converted into a supported conclusion. Additional evidence or client information may resolve it later without rewriting the original user input or raw evidence.

## 11. CaseResult

CaseResult is the application-facing result after deterministic/canonical processing has run as far as the available information allows.

It contains:

- case_ref: opaque application-facing case reference;
- optional client_reference;
- optional as_of_date;
- analysis_status: complete, partial, or blocked;
- supported_claims;
- remaining_candidate_claims;
- unresolved;
- evidence;
- relevant sources;
- relevant documents;
- relevant provisions;
- generated_at.

A supported claim is intentionally distinct from CandidateClaim. It has:

- status validated or human_verified;
- at least one supporting evidence_ref;
- no implication that the claim is universal truth outside its stated case scope.

analysis_status = complete does not mean "all law is known"; it means the application completed the requested workflow without unresolved items that block the represented result. partial/blocked states are valid outcomes.

## 12. Provider-neutral structuring-model interface

The structuring-model adapter receives:

- exactly one schema-valid CaseInput;
- the supported contract version;
- implementation policy/instructions needed to produce CaseDraft.

It returns:

- exactly one CaseDraft object;
- model_metadata containing provider, model, generated_at, and optional provider-specific revision/run metadata.

The domain contract does not name or require any LLM provider.

### 12.1 Failure handling

If model output is malformed, incomplete, uses an unsupported contract version, violates source-quote traceability, attempts to promote a claim, or injects forbidden canonical internals:

- the draft is invalid;
- no canonical promotion is performed from that draft;
- no canonical evidence/provenance is overwritten;
- the application returns/records a structuring error according to its transport;
- an adapter may retry operationally, but a retry is a new model execution, not evidence.

Provider/model metadata is execution metadata, not legal evidence.

## 13. Deterministic boundary after the model

After CaseDraft validation, deterministic corpus/application services alone may establish:

- canonical Document/Provision targets;
- reference resolutions;
- relationships and their provenance;
- temporal candidates/resolutions/events;
- evidence bindings;
- whether a CandidateClaim has enough canonical support to become a supported claim.

A model-generated target hint is search/resolution input only. It cannot force a DOC-*, provision, relationship, evidence, or temporal identity.

If deterministic logic cannot resolve exactly one supported target under the current rules, the result remains unresolved/ambiguous.

## 14. Validation and error semantics

Transport-neutral symbolic error semantics are:

| Condition | Application meaning |
| --- | --- |
| Invalid/missing CaseInput fields | INVALID_CASE_INPUT |
| Structuring provider unavailable | CASE_STRUCTURING_UNAVAILABLE |
| Model output fails schema/semantic validation | INVALID_CASE_DRAFT |
| user_provided quote does not match CaseInput | INVALID_CASE_DRAFT |
| Missing/ambiguous required fact | CaseUnresolved |
| Legal target cannot be resolved uniquely | CaseUnresolved |
| Corpus lacks required source/target | CaseUnresolved category corpus_gap |
| Candidate claim lacks canonical support | remains candidate and/or CaseUnresolved unsupported_claim |
| Required as_of_date absent for a time-sensitive decision | CaseUnresolved temporal_uncertainty |
| Canonical provenance/integrity check fails | block supported result; surface system/integrity failure |

These are application meanings, not HTTP status codes and not MCP error codes. Transport adapters map them without changing domain semantics.

## 15. Mapping to current CASE-0001 infrastructure

The existing bundle is a valid internal/audit representation but does not define the client interface.

| Existing artifact/tool | v1 application-contract role |
| --- | --- |
| cases/CASE-0001/query.md | Source for CaseInput.problem_text and the current case query; its case ID remains an internal workflow identifier |
| cases/CASE-0001/evidence.json | Legacy bundle serialization of case claims/status/source references; conceptually maps to candidate/supported claim material, not a client payload |
| cases/CASE-0001/claim_bindings.json | Internal deterministic support instructions using document/evidence/relationship/segment/hash details; never normal client input |
| cases/CASE-0001/sources/manifest.json | Internal materialized canonical source/provenance view backing public CaseEvidence/source references |
| cases/CASE-0001/unresolved.json | Existing unresolved case facts map to CaseUnresolved |
| cases/CASE-0001/report.md | Presentation/materialization of case state; not the application contract |
| tools/register_case_bundle.py | Current internal adapter that registers the implementation-facing bundle into SQLite |
| tools/case_support_graph.py | Current deterministic support graph used to derive canonical case sources |
| tools/materialize_case_sources.py | Internal source/provenance materializer |
| tools/materialize_case_report.py | Presentation materializer over canonical case state |
| tools/validate_case_bundle.py | Internal structural/materialization validator; distinct from CaseInput/CaseDraft schema validation |

Current SQLite concepts map as follows:

| Current implementation | Contract concept |
| --- | --- |
| cases.query_text / cases.as_of_date | persisted representation of the request and explicit temporal context |
| claims with candidate status | candidate claim state |
| claims validated/human_verified plus evidence/relationship support | supported-claim backing state |
| case_items | internal graph of case-linked canonical/derived items |
| evidence and relationship provenance | backing for CaseEvidence |
| canonical_case_source_records | backing for public source/document references |
| unresolved.json today | current materialized unresolved-case representation |

No new persistence mapping is required by this issue.

### 15.1 Existing materialization drift

The 2026-09-23 post-P1 audit reports that CASE-0001's canonical support graph is structurally valid while the checked-in report.md differs from the current deterministic materializer on six lines.

Issue #15 does not repair or rematerialize that report. The condition demonstrates why a presentation artifact cannot be the client/domain contract. A dedicated materialization lifecycle/refresh change owns that concern.

## 16. Client/internal exposure policy

Safe and expected normal inputs:

- problem_text;
- explicit as_of_date;
- opaque client_reference.

Safe application outputs include:

- application-local fact/question/claim/unresolved/evidence references;
- supported claim text and status;
- evidence quotations and official source URLs;
- public document/provision descriptions;
- unresolved/corpus-gap information;
- provider/model metadata for the structuring step.

Internal/audit-only details include, unless a diagnostic endpoint deliberately exposes them output-only:

- SQLite row knowledge;
- canonical persistence identifiers;
- manifestation and extracted-segment identifiers;
- relationship/evidence identifiers;
- segment sequence numbers;
- raw/text hashes;
- source-manifest storage layout.

A field looking like an internal ID in user text is still just text until deterministic resolution validates it.

## 17. Security and integrity implications

This contract adds no authority path around existing corpus guarantees.

- Raw evidence remains immutable.
- SHA-256/provenance guarantees remain owned by canonical corpus logic.
- Case structuring cannot overwrite canonical entities.
- Candidate state cannot masquerade as validated state.
- Ambiguity is retained rather than guessed.
- Provider changes cannot silently rewrite legal/canonical state.
- The normal public contract avoids coupling clients to persistence internals.

## 18. Non-goals

This specification does not:

- implement MCP;
- implement an HTTP API or CLI;
- implement the final natural-language analysis orchestrator;
- implement Ports and Adapters or issue #10;
- decouple SQLite persistence;
- add PostgreSQL, Redis, or another database;
- add or change database migrations;
- modify CASE-0001 data;
- resolve its report materialization drift;
- implement CASE-0002;
- mutate or reprocess the production corpus;
- redefine canonical identity, evidence, relationships, or temporality.

## 19. Acceptance invariants

An implementation conforming to v1 must preserve all of these:

1. A client can begin with natural-language problem_text and optional explicit metadata, without internal IDs/hashes.
2. The required case concepts have stable versioned serialized contracts.
3. User-provided facts remain distinguishable from model normalization/inference.
4. Every model-generated legal conclusion begins as CandidateClaim.
5. CandidateClaim cannot be treated as validated solely by model output.
6. Canonical evidence/provenance and legal identity/state remain controlled by deterministic corpus logic.
7. Internal persistence/provenance identifiers are not mandatory client inputs.
8. CASE-0001's current bundle/tools have an explicit mapping to the application boundary.
9. CLI/API/future MCP transports can share the same Case Application Service contract.
10. Missing or ambiguous information remains explicit unresolved state.
11. Contract use does not require runtime/corpus mutation.
12. Persistence changes are not implied by this specification.

## 20. Related authoritative contracts

This specification must be read consistently with:

- ../README.md
- ../architecture/overview.md
- ../architecture/domain-model.md
- ../architecture/data-lifecycle.md
- ../architecture/glossary.md
- ../architecture/identifier-semantics.md
- ../architecture/adr/ADR-0004-preserve-ambiguity.md
- ../architecture/adr/ADR-0005-llm-not-canonical-authority.md
- ../architecture/adr/ADR-0009-defer-ports-and-adapters.md
- ../audits/2026-09-23-post-p1-corpus-audit.md

Where a future implementation needs a new persistence abstraction, protocol transport, execution-provenance model, or materialization-refresh lifecycle, that work belongs to its owning issue rather than being inferred from this application contract.
