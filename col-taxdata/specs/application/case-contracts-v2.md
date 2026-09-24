# Case application contracts v2

## Status and authority

Status: **Active architectural/application contract**

Contract package version: **2.0.0**

Driver: GitHub issue #15, refined by GitHub issue #24.

This specification defines the stable application boundary for creating and analyzing a legal/tax case from natural-language input. It is downstream of the canonical corpus and evidence model documented in ../architecture/. It does not replace those contracts and does not claim that a final case-analysis orchestrator, MCP server, API server, or Ports-and-Adapters implementation already exists.

The companion machine-readable schema is schemas/case-contracts-v2.schema.json. The schema is normative for serialized shape; this document is normative for ownership, trust, lifecycle, cross-object semantics, and canonical-promotion rules.

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

Version 2.0.0 applies to the following public concepts:

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

### 2.1 Why issue #24 is a major-version change

v1.0.0 requires `CaseDraft.model_metadata` but does not permit any equivalent field in `CaseResult`, whose schema has `additionalProperties=false`.

Issue #24 makes `CaseResult.model_metadata` required so every v2 result exposes the structuring execution that produced its accepted draft. Adding a required field changes the valid `CaseResult` wire shape and validation semantics. Under the versioning rule established by v1, that is a breaking change and therefore uses major version **2.0.0**, not a minor v1 evolution.

The metadata shape is also strengthened so the accepted structuring execution can be understood without depending on a provider-specific backend.

### 2.2 Compatibility with v1.0.0

v1.0.0 remains a valid historical/public contract for consumers that explicitly support it. Its prose and schema are retained rather than rewritten to accept v2 objects.

A producer implementing the natural-language orchestrator in issue #16 MUST use v2.0.0 for the case-contract object graph it produces.

A consumer that supports only v1 MUST reject a v2 object explicitly rather than:

- silently dropping `CaseResult.model_metadata`;
- relabeling the object as v1;
- guessing the meaning of v2 fields;
- treating v2 metadata as canonical evidence.

No implicit v2 -> v1 down-conversion is part of this contract. A separately implemented compatibility adapter may transform representations only if it makes any loss of v2 traceability explicit and does not claim that the downgraded object still satisfies the v2 result contract.

A breaking change to meaning, ownership, required fields, trust level, or validation semantics requires another new major contract version. Backward-compatible optional fields may be introduced in a minor version only when adapters explicitly support them. Patch changes may clarify wording or constraints without changing the set or meaning of valid objects. Enum additions are treated conservatively as potentially breaking for consumers.

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
- contract_version = 2.0.0
- problem_text: non-empty natural-language request

Optional:

- as_of_date: explicit ISO 8601 calendar date supplied by the client
- client_reference: opaque client correlation value

Example:

    {
      "kind": "case_input",
      "contract_version": "2.0.0",
      "problem_text": "La sociedad está en liquidación y no tuvo movimientos en 2026. ¿Qué debe hacer para cancelar el RUT?",
      "as_of_date": "2026-09-23",
      "client_reference": "matter-42"
    }

Absence of as_of_date MUST remain absence. The application MUST NOT silently substitute "today" and then present time-sensitive conclusions as if that date had been client supplied. The application may request the missing date or represent resulting temporal uncertainty in CaseUnresolved.

CaseInput contains no canonical or persistence identifiers.

### 4.1 Immutable client payload across structuring

The client-owned payload is immutable across the `CaseInput -> CaseDraft` structuring boundary. For the specific `CaseInput` used to produce a draft, the application MUST enforce all of the following as semantic invariants:

```text
CaseDraft.problem_text     == CaseInput.problem_text
CaseDraft.as_of_date       == CaseInput.as_of_date       when present
CaseDraft.client_reference == CaseInput.client_reference when present
```

Equality means the exact parsed string value supplied by the client. Structuring MUST NOT trim, rewrite, translate, redact, Unicode-normalize, date-substitute, or otherwise replace these fields. Interpretive or normalized values belong in `CaseFact` or other candidate structures, not in the immutable client payload.

Presence is part of the invariant:

- `problem_text` is required in both objects and MUST be identical;
- if `as_of_date` is present in `CaseInput`, it MUST be present with the identical value in `CaseDraft`;
- if `as_of_date` is absent from `CaseInput`, it MUST also be absent from `CaseDraft`;
- if `client_reference` is present in `CaseInput`, it MUST be present with the identical value in `CaseDraft`;
- if `client_reference` is absent from `CaseInput`, it MUST also be absent from `CaseDraft`.

A model may return those fields as part of the serialized `CaseDraft`, but it has no authority to choose or modify their values. The application retains the original `CaseInput` and validates the returned draft against that specific input.

This is a cross-object semantic invariant. The companion JSON Schema can validate each object independently, but it cannot prove equality or presence preservation between a separately validated `CaseInput` and `CaseDraft`. Conformance therefore requires application-level semantic validation in addition to JSON Schema validation.

## 5. CaseDraft

CaseDraft is the structured interpretation returned by the case-structuring model and accepted by schema/application validation.

It contains:

- the immutable original `problem_text` from `CaseInput`;
- optional `as_of_date` and `client_reference` preserved exactly, including presence/absence, from `CaseInput`;
- facts: CaseFact objects;
- questions: CaseQuestion objects;
- candidate_claims: CandidateClaim objects;
- unresolved: CaseUnresolved objects already visible at intake;
- model_metadata: required provider-neutral structuring execution metadata for traceability.

`model_metadata` uses the shared `StructuringModelMetadata` contract defined in §11.1. It identifies the specific accepted structuring execution; it is candidate/intake traceability, not legal evidence.

CaseDraft is **never canonical state**. A syntactically valid CaseDraft means only that the candidate structure can enter deterministic processing.

### 5.1 Draft validation

Before deterministic corpus work, the application MUST:

1. validate the output against the supported schema version;
2. compare the returned `CaseDraft` with the exact `CaseInput` used for that model execution and enforce the immutable-client-payload rules in §4.1;
3. reject unknown required semantics rather than silently dropping them;
4. verify that every fact marked `user_provided` and carrying a `source_quote` is traceable to the `CaseInput` text;
5. preserve missing/ambiguous information as unresolved state;
6. verify every `CandidateClaim` still has status `candidate`;
7. reject attempts by model output to inject canonical IDs, evidence IDs, hashes, sequence numbers, or a `validated` claim state into candidate structures;
8. validate the typed CaseDraft reference graph and ref uniqueness rules defined in §14 before deterministic corpus work.

A mismatch in `problem_text`, `as_of_date`, or `client_reference` — including a missing optional field that was supplied or a manufactured optional field that was absent — is a semantic validation failure and MUST produce `INVALID_CASE_DRAFT`. The application MUST reject the draft before deterministic corpus work or case/canonical mutation. It MUST NOT repair the mismatch by accepting the model's value as a replacement for the client payload.

Issue #16 MUST implement this validation outside JSON Schema. Its acceptance tests MUST cover, at minimum: exact `problem_text` preservation; exact supplied `as_of_date`; exact supplied `client_reference`; optional-field absence remaining absence; rejection of modified `problem_text`; rejection of modified `as_of_date`; rejection of a manufactured missing `as_of_date`; and rejection of modified `client_reference`.

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
- model_metadata: required metadata for the structuring execution that produced the accepted CaseDraft;
- generated_at: timestamp for production of the CaseResult itself.

A supported claim is intentionally distinct from CandidateClaim. It has:

- status validated or human_verified;
- at least one supporting evidence_ref;
- no implication that the claim is universal truth outside its stated case scope.

analysis_status = complete does not mean "all law is known"; it means the application completed the requested workflow without unresolved items that block the represented result. partial/blocked states are valid outcomes.

### 11.1 StructuringModelMetadata

`StructuringModelMetadata` is a provider-neutral description of the **single structuring execution whose CaseDraft was accepted** for the result.

Required fields:

- `adapter`: application adapter/backend identifier, without provider-specific implementation assumptions in the domain semantics;
- `provider`: descriptive provider identifier;
- `model`: descriptive configured model identifier;
- `schema_version`: exact case-structuring schema/contract version; for this contract it is `2.0.0`;
- `prompt_template_id`: stable identifier for the prompt/template family, not the prompt contents;
- `prompt_template_version`: exact template revision/version used;
- `run_reference`: opaque execution correlation reference for this structuring attempt;
- `generated_at`: timestamp when that CaseDraft execution was produced;
- `routing_role`: descriptive routing role, such as `primary`, `review`, or another configured role.

Optional:

- `revision`: provider/model revision identifier when available.

The values of `adapter`, `provider`, `model`, `revision`, and `routing_role` are descriptive execution metadata only. They do not grant authority, change claim status, validate evidence, or alter canonical identity.

The serialized metadata MUST NOT require or expose credentials, API keys, bearer tokens, passwords, private keys, or other secrets. It MUST NOT require storing full prompts or template expansions containing client text. The template identifier/version is sufficient for this application-contract boundary.

### 11.2 CaseDraft -> CaseResult execution identity

For a result derived from an accepted CaseDraft:

```text
CaseResult.model_metadata == accepted CaseDraft.model_metadata
```

Equality is field-for-field equality of the parsed metadata object. The deterministic application layer MUST copy/preserve it; it MUST NOT invent a different provider/model/run identity after the draft has been accepted.

If a primary attempt fails and a later review/retry draft is the one accepted, the result carries the metadata of that accepted draft. Earlier failed attempts, retry history, host/container identity, Git revision, config hashes, migration fingerprints, raw input hashes, and replay manifests belong to broader execution provenance (issue #11), not to this field.

`model_metadata.generated_at` describes the accepted structuring execution. `CaseResult.generated_at` describes result production and may therefore be later.

This metadata is not legal evidence, is not canonical provenance, and cannot by itself promote a CandidateClaim or resolve any legal/domain ambiguity.

## 12. Provider-neutral structuring-model interface

The structuring-model adapter receives:

- exactly one schema-valid CaseInput;
- the supported contract version;
- implementation policy/instructions needed to produce CaseDraft.

It returns:

- exactly one CaseDraft object;
- `model_metadata` conforming to `StructuringModelMetadata`, including adapter, provider, model, schema version, prompt-template identity/version, run reference, timestamp and routing role.

The domain contract does not name or require any LLM provider or one concrete local backend. Provider/backend-specific settings remain adapter/configuration concerns.

Issue #16 MUST preserve the accepted draft's `model_metadata` unchanged into the resulting `CaseResult`.

### 12.1 Failure handling

If model output is malformed, incomplete, uses an unsupported contract version, changes/manufactures immutable client-payload fields, violates source-quote traceability, attempts to promote a claim, injects forbidden canonical internals, or omits/violates required `model_metadata`:

- the draft is invalid;
- no canonical promotion is performed from that draft;
- no canonical evidence/provenance is overwritten;
- the application returns/records a structuring error according to its transport;
- an adapter may retry operationally, but a retry is a new model execution, not evidence.

Structuring metadata is execution/intake traceability, not legal evidence.

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

### 14.1 JSON Schema and semantic-validation boundary

The companion JSON Schema is normative for serialized shape. It can validate matters such as required fields, allowed fields, value types, ref-prefix syntax, enums, and local `uniqueItems` constraints on an array.

JSON Schema MUST NOT be represented as sufficient proof of application graph integrity. In particular, schema validation alone does not establish:

- that a referenced object exists;
- that exactly one object owns the referenced ref;
- that the target is the required object type;
- that ref-valued identity properties are unique across an owning collection;
- that refs shared across lifecycle objects point to the originating object graph allowed by this contract.

Application semantic validation is therefore normative for cross-object referential integrity. A schema-valid `CaseDraft` or `CaseResult` is not a valid application graph until the semantic validator passes.

The semantic validator MUST use typed ref registries. It MUST NOT search all objects by raw string and accept whichever object happens to match. A ref must resolve to exactly one object in the namespace and lifecycle location allowed below.

### 14.2 Ref uniqueness and typed namespaces

Application-facing refs are opaque identifiers, but each ref field has a semantic type.

For `CaseDraft`, the application MUST build and validate these owning namespaces:

- `facts[*].fact_ref`;
- `questions[*].question_ref`;
- `candidate_claims[*].claim_ref`;
- `unresolved[*].unresolved_ref`.

Each declared ref MUST be unique within its owning collection.

For `CaseResult`, the application MUST build and validate these owning namespaces:

- `supported_claims[*].claim_ref` and `remaining_candidate_claims[*].claim_ref` as one shared result-level claim namespace;
- `unresolved[*].unresolved_ref`;
- `evidence[*].evidence_ref`;
- `sources[*].source_ref`;
- `documents[*].document_ref`;
- `provisions[*].provision_ref`.

Each declared ref MUST be unique within its owning namespace. In particular, the same `claim_ref` MUST NOT appear once as supported and again as remaining candidate in the same result. A promoted candidate may retain its application-local claim ref, but the result contains that ref in exactly one claim collection.

Duplicate refs are invalid even when the duplicated objects are byte-for-byte equal. A local array-level `uniqueItems` check on fields such as `evidence_refs` or `related_*_refs` does not replace these owning-collection uniqueness rules.

### 14.3 CaseDraft lifecycle graph integrity

A `CaseDraft` is a self-contained candidate graph except for its explicit immutable link back to its originating `CaseInput` in §4.1.

The following refs MUST resolve to exactly one object inside the same `CaseDraft`:

| Ref-bearing field | Required target |
| --- | --- |
| `CaseQuestion.depends_on_fact_refs[*]` | one `CaseFact` in `facts` with matching `fact_ref` |
| `CandidateClaim.related_question_refs[*]` | one `CaseQuestion` in `questions` with matching `question_ref` |
| `CaseUnresolved.related_fact_refs[*]` | one `CaseFact` in `facts` with matching `fact_ref` |
| `CaseUnresolved.related_question_refs[*]` | one `CaseQuestion` in `questions` with matching `question_ref` |
| `CaseUnresolved.related_claim_refs[*]` | one `CandidateClaim` in `candidate_claims` with matching `claim_ref` |

A draft ref MUST NOT be satisfied by an object that exists only in a later `CaseResult`, another case, another model execution, persistence state, or a presentation artifact. `CaseDraft` has no valid evidence/source/document/provision reference namespace.

Any dangling, duplicate, or wrong-type draft ref makes the draft semantically invalid and produces `INVALID_CASE_DRAFT` before deterministic corpus processing.

### 14.4 CaseResult lifecycle graph integrity

A `CaseResult` is validated in the context of the exact accepted `CaseDraft` from the same case-analysis execution. This is explicit cross-stage behavior; it does not authorize refs to arbitrary drafts or prior results.

The following refs MUST resolve to exactly one target inside the same `CaseResult`:

| Ref-bearing field | Required target |
| --- | --- |
| `SupportedClaim.evidence_refs[*]` | one `CaseEvidence` in `evidence` |
| `CaseEvidence.source_ref` | one `PublicSourceRef` in `sources` |
| `CaseEvidence.document_ref`, when present | one `PublicDocumentRef` in `documents` |
| `CaseEvidence.provision_ref`, when present | one `PublicProvisionRef` in `provisions` |
| `PublicProvisionRef.document_ref` | one `PublicDocumentRef` in `documents` |
| `CaseUnresolved.related_claim_refs[*]` | exactly one claim in the shared result-level `supported_claims + remaining_candidate_claims` namespace |

Because v1 `CaseResult` does not serialize facts or questions, the following are the only cross-stage application refs defined by this contract:

| CaseResult ref-bearing field | Required target in originating accepted CaseDraft |
| --- | --- |
| `CaseUnresolved.related_fact_refs[*]` | one `CaseFact` in `CaseDraft.facts` |
| `CaseUnresolved.related_question_refs[*]` | one `CaseQuestion` in `CaseDraft.questions` |
| `SupportedClaim.related_question_refs[*]` | one `CaseQuestion` in `CaseDraft.questions` |
| `CandidateClaim.related_question_refs[*]` for remaining candidates | one `CaseQuestion` in `CaseDraft.questions` |

If the originating accepted draft is unavailable when one of those cross-stage refs is present, semantic validation cannot be completed safely and the result MUST be rejected as `INVALID_CASE_RESULT`.

No other implicit cross-stage lookup is allowed. In particular, a result-level `related_claim_ref` MUST NOT be satisfied by a candidate that existed only in the draft but is absent from both result claim collections.

Transformation, promotion, filtering, or presentation MUST NOT leave stale refs. Presentation logic MUST NOT hide a dangling object/reference and then treat the reduced output as a valid result.

### 14.5 Transport-neutral failure semantics

Transport-neutral symbolic error semantics are:

| Condition | Application meaning |
| --- | --- |
| Invalid/missing CaseInput fields | INVALID_CASE_INPUT |
| Structuring provider unavailable | CASE_STRUCTURING_UNAVAILABLE |
| Model output fails schema/semantic validation | INVALID_CASE_DRAFT |
| CaseDraft changes, omits, or manufactures immutable CaseInput payload fields | INVALID_CASE_DRAFT |
| CaseDraft contains duplicate, dangling, or wrong-type application refs | INVALID_CASE_DRAFT |
| user_provided quote does not match CaseInput | INVALID_CASE_DRAFT |
| CaseResult contains duplicate, dangling, stale, cross-stage-invalid, or wrong-type application refs | INVALID_CASE_RESULT |
| Missing/ambiguous required fact in an otherwise valid graph | CaseUnresolved |
| Legal target cannot be resolved uniquely in an otherwise valid graph | CaseUnresolved |
| Corpus lacks required source/target | CaseUnresolved category corpus_gap |
| Candidate claim lacks canonical support | remains candidate and/or CaseUnresolved unsupported_claim |
| Required as_of_date absent for a time-sensitive decision | CaseUnresolved temporal_uncertainty |
| Canonical provenance/integrity check fails | block supported result; surface system/integrity failure |

`INVALID_CASE_DRAFT` and `INVALID_CASE_RESULT` are system/contract validation conditions, not legal uncertainty. The application MUST NOT convert a broken application graph into `CaseUnresolved`.

A `CaseResult` MUST pass schema validation and semantic graph validation before it is accepted as valid, registered as accepted application state, materialized, or rendered as a valid result. Transport adapters map these meanings without changing domain semantics; the symbolic values are not HTTP status codes or MCP error codes.

### 14.6 Required semantic-integrity test matrix for issue #16

Issue #16 MUST implement application semantic validation and, at minimum, cover this matrix:

| Test | Expected result |
| --- | --- |
| Complete internally consistent CaseResult graph, with every present ref resolving exactly once to the required type and permitted lifecycle target | PASS |
| Supported claim references missing `evidence_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `source_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `document_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `provision_ref` | `INVALID_CASE_RESULT` |
| PublicProvisionRef references missing `document_ref` | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing related fact in originating accepted CaseDraft | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing related question in originating accepted CaseDraft | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing related claim in the result-level claim namespace | `INVALID_CASE_RESULT` |
| Duplicate declared ref inside an owning collection | reject at semantic validation (`INVALID_CASE_DRAFT` or `INVALID_CASE_RESULT` by lifecycle) |
| Same `claim_ref` appears in both supported and remaining-candidate result collections | `INVALID_CASE_RESULT` |
| Draft question/candidate/unresolved ref points to a missing draft fact/question/claim | `INVALID_CASE_DRAFT` |
| A syntactically valid ref is looked up against or satisfied from the wrong typed registry | reject; never coerce/cross-resolve types |
| Result fact/question ref attempts to resolve against a different/stale draft or result-only object | `INVALID_CASE_RESULT` |
| Semantic validation repeated over the same immutable objects/context | same deterministic validation outcome |

Where a malformed ref is already rejected by JSON Schema (for example, a wrong namespace prefix), the test may fail at the schema boundary first; the application MUST still never implement a fallback that coerces that ref to another object type.

## 15. Mapping to current CASE-0001 infrastructure

The existing bundle is a valid internal/audit representation but does not define the client interface.

| Existing artifact/tool | v2 application-contract role |
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
- non-secret provider-neutral `model_metadata` for the accepted structuring step.

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
- Structuring execution metadata cannot validate claims or become canonical legal/evidence provenance.
- Result metadata stores template identity/version, not full prompts or secrets.
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
- redefine canonical identity, evidence, relationships, or temporality;
- implement the broader run/execution provenance manifest owned by issue #11.

## 19. Acceptance invariants

An implementation conforming to v2 must preserve all of these:

1. A client can begin with natural-language `problem_text` and optional explicit metadata, without internal IDs/hashes.
2. `CaseDraft` preserves the exact client-owned `problem_text`, `as_of_date`, and `client_reference` values and optional-field presence/absence from its originating `CaseInput`; any mismatch is `INVALID_CASE_DRAFT`.
3. The required case concepts have stable versioned serialized contracts.
4. User-provided facts remain distinguishable from model normalization/inference and cannot rewrite the immutable client payload.
5. Every model-generated legal conclusion begins as `CandidateClaim`.
6. `CandidateClaim` cannot be treated as validated solely by model output.
7. Canonical evidence/provenance and legal identity/state remain controlled by deterministic corpus logic.
8. Internal persistence/provenance identifiers are not mandatory client inputs.
9. `CaseDraft.model_metadata` and `CaseResult.model_metadata` are both required and use the same provider-neutral shape.
10. `CaseResult.model_metadata` preserves the accepted `CaseDraft.model_metadata` field-for-field, including `run_reference`.
11. Structuring metadata is descriptive execution/intake traceability only; it is not legal evidence or canonical authority.
12. No credential/secret field or full prompt text is required/exposed by the metadata contract.
13. Broader run provenance remains outside this contract and owned by issue #11.
14. CASE-0001's current bundle/tools have an explicit mapping to the application boundary.
15. CLI/API/future MCP transports can share the same Case Application Service contract.
16. Missing or ambiguous information remains explicit unresolved state.
17. Contract use does not require runtime/corpus mutation.
18. Persistence changes are not implied by this specification.

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
- GitHub issue #11 — broader execution provenance (explicitly outside this contract)
- ../audits/2026-09-23-post-p1-corpus-audit.md

Where a future implementation needs a new persistence abstraction, protocol transport, execution-provenance model, or materialization-refresh lifecycle, that work belongs to its owning issue rather than being inferred from this application contract.
