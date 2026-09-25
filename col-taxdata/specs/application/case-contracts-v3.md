# Case application contracts v3

## Status and authority

Status: **Active architectural/application contract**

Contract package version: **3.0.0**

Driver: GitHub issue #15, refined by GitHub issues #23, #24, #25, #27 and #76.

This specification defines the stable application boundary for creating and analyzing a legal/tax case from natural-language input. It is downstream of the canonical corpus and evidence model documented in ../architecture/. It does not replace those contracts and does not claim that a final case-analysis orchestrator, MCP server, API server, or Ports-and-Adapters implementation already exists.

The companion machine-readable schema is schemas/case-contracts-v3.schema.json. The schema is normative for serialized shape; this document is normative for ownership, trust, lifecycle, cross-object semantics, and canonical-promotion rules.

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

Version 3.0.0 applies to the following public concepts:

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

### 2.1 Why issue #27 is a major-version change

v2.0.0 correctly requires provider-neutral structuring metadata and typed semantic reference validation, but its `CaseResult` does not serialize `facts` or `questions`. Result-level fact/question refs therefore depend on the originating accepted `CaseDraft` from the same execution.

Issue #27 makes `CaseResult.facts` and `CaseResult.questions` required and changes result graph validation so those namespaces are owned by the serialized result itself. This changes required fields and validation semantics, so it is a breaking wire-contract change and uses major version **3.0.0**.

Making these fields optional would not satisfy the contract: a valid v3 result must be semantically self-contained for fact/question application refs.

### 2.2 Compatibility with v1.0.0 and v2.0.0

v1.0.0 and v2.0.0 remain valid historical/public compatibility contracts for consumers that explicitly support them. Their prose and schemas are retained unchanged rather than rewritten to accept v3 objects.

A producer implementing the natural-language orchestrator in issue #16 MUST use v3.0.0 for the case-contract object graph it produces.

A consumer that supports only v1 or v2 MUST reject a v3 object explicitly rather than:

- silently dropping required `CaseResult.facts` or `CaseResult.questions`;
- relabeling the object as an older major version;
- guessing the meaning of v3 fields or reference ownership;
- treating structuring metadata as canonical evidence.

No implicit v3 -> v2 or v3 -> v1 down-conversion is part of this contract. A separately implemented compatibility adapter may transform representations only if it makes loss of self-contained result semantics explicit and does not claim the downgraded object still satisfies the v3 result contract.

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
- contract_version = 3.0.0
- problem_text: non-empty natural-language request

Optional:

- as_of_date: explicit ISO 8601 calendar date supplied by the client
- client_reference: opaque client correlation value

Example:

    {
      "kind": "case_input",
      "contract_version": "3.0.0",
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
5. preserve genuinely missing/ambiguous information as unresolved state;
6. reject a `missing` classification when a conservative deterministic intake-fidelity check can establish that the model is generically requesting information about a fact/topic already directly stated in assertive client text; rejection MUST NOT auto-promote, normalize, infer, or manufacture a fact/source quote and instead follows the normal structuring retry/review path;
7. verify every `CandidateClaim` still has status `candidate`;
8. reject attempts by model output to inject canonical IDs, evidence IDs, hashes, sequence numbers, or a `validated` claim state into candidate structures;
9. validate the typed CaseDraft reference graph and ref uniqueness rules defined in §14 before deterministic corpus work.

A mismatch in `problem_text`, `as_of_date`, or `client_reference` — including a missing optional field that was supplied or a manufactured optional field that was absent — is a semantic validation failure and MUST produce `INVALID_CASE_DRAFT`. The application MUST reject the draft before deterministic corpus work or case/canonical mutation. It MUST NOT repair the mismatch by accepting the model's value as a replacement for the client payload.

Issue #16 MUST implement this validation outside JSON Schema. Its acceptance tests MUST cover, at minimum: exact `problem_text` preservation; exact supplied `as_of_date`; exact supplied `client_reference`; optional-field absence remaining absence; rejection of modified `problem_text`; rejection of modified `as_of_date`; rejection of a manufactured missing `as_of_date`; and rejection of modified `client_reference`.

Malformed or semantically invalid model output does not mutate canonical/case state.

### 5.2 Structured-generation backend compatibility

CASE structuring has two separate validation gates. They MUST NOT be collapsed into one another.

**Generation compatibility** asks whether the selected backend/adapter can produce the CaseDraft candidate through a supported constrained or structured-generation mechanism at the backend/model boundary. A CASE-compatible structuring backend MUST:

- constrain generation against the model-facing CaseDraft schema for the active contract version, or provide an equivalent structured-generation mechanism with the same semantic guarantees;
- return one directly parseable structured object, not prose that merely contains JSON-like text;
- preserve the requested CaseDraft semantic field names, types, enum values, required fields, and unknown-field policy at generation time to the extent promised by that mechanism;
- require no post-response semantic or JSON repair before the object can be handed to application validation.

CASE MUST fail closed when an adapter/backend cannot provide those guarantees. An unavailable, unsupported, or rejected structured-generation mechanism is a structuring-compatibility failure; CASE MUST NOT silently retry by weakening the schema contract or switching to unconstrained prose generation.

Compatibility MUST NOT depend on provider or model identity. A provider-specific transport feature is acceptable when the adapter can truthfully declare that it provides the required constrained-generation guarantees. Equivalent mechanisms from different providers are compatible when they preserve this boundary. The application contract does not require one vendor-specific request syntax, API family, model name, GPU/NPU/CPU runtime, or server implementation.

CASE structuring MUST NOT repair arbitrary model text into a candidate draft. In particular, it MUST NOT:

- strip Markdown or code fences around JSON;
- extract a JSON-looking substring from surrounding prose;
- heuristically repair malformed JSON;
- rename model-produced fields to match the contract;
- insert or delete semantic fields after generation merely to satisfy schema;
- coerce field types or enum values;
- silently drop unknown or unsupported fields;
- relax the authoritative CaseDraft contract for a particular provider.

A directly parseable object that violates the CaseDraft schema or semantics is still invalid. Generation compatibility only permits the object to reach the second gate.

**Application validity** is the mandatory authoritative validation performed after generation. The application MUST validate the returned candidate against the v3 schema and all semantic invariants in this specification, including immutable CaseInput preservation, source-quote traceability, fact-state rules, typed references, canonical-ID injection prohibitions, and every other CaseDraft constraint. Backend-side constrained generation assists correctness but never replaces or bypasses this validation.

The intended boundary is:

    CASE-compatible structuring backend
            |
            +-- constrained / structured generation
            |      -> directly parseable structured object
            |      -> model-facing CaseDraft schema contract
            |
            +-- authoritative application validation
                   -> accepted CaseDraft
                   OR
                   -> INVALID_CASE_DRAFT

A backend that cannot satisfy the generation-compatibility gate is not available for CASE structuring under this contract version. It may still be used for unrelated or experimental tasks that do not claim to produce a CASE CaseDraft.

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
- facts: required application-facing `CaseFact` objects preserved from the accepted CaseDraft;
- questions: required application-facing `CaseQuestion` objects preserved from the accepted CaseDraft;
- supported_claims;
- remaining_candidate_claims;
- unresolved;
- evidence;
- relevant sources;
- relevant documents;
- relevant provisions;
- model_metadata: required metadata for the structuring execution that produced the accepted CaseDraft;
- generated_at: timestamp for production of the CaseResult itself.

The result owns its `fact_ref` and `question_ref` namespaces. A normal serialized CaseResult is therefore sufficient to inspect the interpreted case context and validate all result-level application refs without loading an execution-local CaseDraft.

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
- `schema_version`: exact case-structuring schema/contract version; for this contract it is `3.0.0`;
- `prompt_template_id`: stable identifier for the prompt/template family, not the prompt contents;
- `prompt_template_version`: exact template revision/version used;
- `run_reference`: opaque execution correlation reference for this structuring attempt;
- `generated_at`: timestamp when that CaseDraft execution was produced;
- `routing_role`: descriptive routing role, such as `primary`, `review`, or another configured role.

Optional:

- `revision`: provider/model revision identifier when available.

The values of `adapter`, `provider`, `model`, `revision`, and `routing_role` are descriptive execution metadata only. They do not grant authority, change claim status, validate evidence, or alter canonical identity.

The serialized metadata MUST NOT require or expose credentials, API keys, bearer tokens, passwords, private keys, or other secrets. It MUST NOT require storing full prompts or template expansions containing client text. The template identifier/version is sufficient for this application-contract boundary.

### 11.2 CaseDraft -> CaseResult preservation invariants

For a result produced from an accepted CaseDraft, the producer lifecycle MUST preserve:

```text
CaseResult.facts          == accepted CaseDraft.facts
CaseResult.questions      == accepted CaseDraft.questions
CaseResult.model_metadata == accepted CaseDraft.model_metadata
```

Equality is field-for-field equality of the parsed arrays/objects, including ordering. The baseline v3 producer copies **all** accepted draft facts and questions, not only those currently referenced by claims or unresolved items.

Consequences:

- every accepted `fact_ref` remains the same in the result;
- every accepted `question_ref` remains the same in the result;
- `CaseFact.state` is not silently relabeled while constructing the result, including `user_provided`, `llm_normalized`, `llm_inferred`, `missing`, and `ambiguous`;
- question status/category/dependencies are not silently rewritten;
- structuring `run_reference` and all other metadata fields remain tied to the accepted draft execution.

Deterministic/canonical processing may support or reject claims, add evidence/canonical public references, and add/update result-level unresolved state according to the rest of this contract. It does not rewrite the accepted structuring-stage fact/question interpretation in the baseline v3 contract. Any future contract that intentionally permits post-draft fact/question evolution must define explicit versioned transition semantics rather than making that evolution implicit.

These equality rules are **producer lifecycle invariants**. They may be checked when both the accepted CaseDraft and newly constructed CaseResult are available.

They are distinct from **standalone CaseResult graph validity**: once serialized, a v3 CaseResult is semantically validated using the namespaces contained in that result. The semantic validator MUST NOT require fetching the originating CaseDraft merely to resolve result fact/question application refs.

If a primary attempt fails and a later review/retry draft is the one accepted, the result preserves facts, questions, and metadata from that accepted draft. Earlier failed attempts, retry history, host/container identity, Git revision, config hashes, migration fingerprints, raw input hashes, and replay manifests belong to broader execution provenance (issue #11), not to these fields.

`model_metadata.generated_at` describes the accepted structuring execution. `CaseResult.generated_at` describes result production and may therefore be later.

Structuring metadata and structured facts/questions are not canonical legal evidence by themselves and cannot promote a CandidateClaim or resolve canonical legal/domain ambiguity.

## 12. Provider-neutral structuring-model interface

The structuring-model adapter receives:

- exactly one schema-valid CaseInput;
- the supported contract version;
- implementation policy/instructions needed to produce CaseDraft.

It returns:

- exactly one CaseDraft object;
- `model_metadata` conforming to `StructuringModelMetadata`, including adapter, provider, model, schema version, prompt-template identity/version, run reference, timestamp and routing role.

The domain contract does not name or require any LLM provider or one concrete local backend. Provider/backend-specific settings remain adapter/configuration concerns.

Issue #16 MUST preserve the accepted draft's `facts`, `questions`, and `model_metadata` unchanged into the resulting `CaseResult`.

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
- that a ref is resolved only inside the namespace and lifecycle graph allowed by this contract.

Application semantic validation is therefore normative for cross-object referential integrity. A schema-valid `CaseDraft` or `CaseResult` is not a valid application graph until the semantic validator passes.

The semantic validator MUST use typed ref registries. It MUST NOT search all objects by raw string or suffix and accept whichever object happens to look similar. A ref resolves only in the typed namespace allowed below.

### 14.2 Ref uniqueness and typed namespaces

Application-facing refs are opaque identifiers, but each ref field has a semantic type.

For `CaseDraft`, the application MUST build and validate these owning namespaces:

- `facts[*].fact_ref`;
- `questions[*].question_ref`;
- `candidate_claims[*].claim_ref`;
- `unresolved[*].unresolved_ref`.

Each declared ref MUST be unique within its owning collection.

For `CaseResult`, the application MUST build and validate these owning namespaces:

- `facts[*].fact_ref`;
- `questions[*].question_ref`;
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

### 14.4 CaseResult standalone graph integrity

A v3 `CaseResult` is a self-contained application graph for all application-facing refs represented by this contract. Standalone semantic validation MUST use only the serialized result graph and MUST NOT require the originating CaseDraft to resolve fact/question refs.

The following refs MUST resolve to exactly one target inside the same `CaseResult`:

| Ref-bearing field | Required target |
| --- | --- |
| `CaseQuestion.depends_on_fact_refs[*]` | one `CaseFact` in `facts` |
| `SupportedClaim.evidence_refs[*]` | one `CaseEvidence` in `evidence` |
| `SupportedClaim.related_question_refs[*]` | one `CaseQuestion` in `questions` |
| `CandidateClaim.related_question_refs[*]` for remaining candidates | one `CaseQuestion` in `questions` |
| `CaseUnresolved.related_fact_refs[*]` | one `CaseFact` in `facts` |
| `CaseUnresolved.related_question_refs[*]` | one `CaseQuestion` in `questions` |
| `CaseUnresolved.related_claim_refs[*]` | exactly one claim in the shared result-level `supported_claims + remaining_candidate_claims` namespace |
| `CaseEvidence.source_ref` | one `PublicSourceRef` in `sources` |
| `CaseEvidence.document_ref`, when present | one `PublicDocumentRef` in `documents` |
| `CaseEvidence.provision_ref`, when present | one `PublicProvisionRef` in `provisions` |
| `PublicProvisionRef.document_ref` | one `PublicDocumentRef` in `documents` |

No result ref may be satisfied from an external Draft, prior Result, another case, persistence lookup, presentation artifact, or untyped registry fallback. The CaseDraft remains valuable candidate-state audit/replay material, but it is not a hidden dependency for ordinary v3 result validation or rendering.

Producer-side construction MAY and normally SHOULD enforce the §11.2 Draft -> Result preservation invariants while both objects are available. Failure of those producer invariants is a construction/contract error. It does not change the standalone rule above.

Transformation, promotion, filtering, caching, export, or presentation MUST NOT leave stale refs. Presentation logic MUST NOT hide a dangling object/reference and then treat the reduced output as a valid result.

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
| CaseResult contains duplicate, dangling, stale, external-graph-dependent, or wrong-type application refs | INVALID_CASE_RESULT |
| Producer constructs a result that does not preserve accepted Draft facts/questions/model_metadata as required by §11.2 | INVALID_CASE_RESULT |
| Missing/ambiguous required fact in an otherwise valid graph | CaseUnresolved |
| Legal target cannot be resolved uniquely in an otherwise valid graph | CaseUnresolved |
| Corpus lacks required source/target | CaseUnresolved category corpus_gap |
| Candidate claim lacks canonical support | remains candidate and/or CaseUnresolved unsupported_claim |
| Required as_of_date absent for a time-sensitive decision | CaseUnresolved temporal_uncertainty |
| Canonical provenance/integrity check fails | block supported result; surface system/integrity failure |

`INVALID_CASE_DRAFT` and `INVALID_CASE_RESULT` are system/contract validation conditions, not legal uncertainty. The application MUST NOT convert a broken application graph into `CaseUnresolved`.

A `CaseResult` MUST pass schema validation and standalone semantic graph validation before it is accepted as valid, registered as accepted application state, materialized, cached/exported, or rendered as a valid result. Transport adapters map these meanings without changing domain semantics; the symbolic values are not HTTP status codes or MCP error codes.

### 14.6 Required semantic-integrity test matrix for issue #16

Issue #16 MUST implement application semantic validation and, at minimum, cover this matrix for v3:

| Test | Expected result |
| --- | --- |
| Complete internally consistent CaseResult with facts/questions and every present ref resolving exactly once inside the result graph; no CaseDraft supplied to result validator | PASS |
| CaseQuestion references missing result fact | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing result fact | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing result question | `INVALID_CASE_RESULT` |
| SupportedClaim references missing result question | `INVALID_CASE_RESULT` |
| Remaining CandidateClaim references missing result question | `INVALID_CASE_RESULT` |
| SupportedClaim references missing `evidence_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `source_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `document_ref` | `INVALID_CASE_RESULT` |
| CaseEvidence references missing `provision_ref` | `INVALID_CASE_RESULT` |
| PublicProvisionRef references missing `document_ref` | `INVALID_CASE_RESULT` |
| CaseUnresolved references missing related claim in result claim namespace | `INVALID_CASE_RESULT` |
| Duplicate result `fact_ref` | `INVALID_CASE_RESULT` |
| Duplicate result `question_ref` | `INVALID_CASE_RESULT` |
| Duplicate declared ref inside another owning namespace | reject at semantic validation (`INVALID_CASE_DRAFT` or `INVALID_CASE_RESULT` by lifecycle) |
| Same `claim_ref` appears in supported and remaining-candidate result collections | `INVALID_CASE_RESULT` |
| Draft question/candidate/unresolved ref points to a missing draft fact/question/claim | `INVALID_CASE_DRAFT` |
| A syntactically valid ref is looked up against or satisfied from the wrong typed registry | reject; never coerce/cross-resolve types |
| Result validator is called with no originating CaseDraft | validation outcome depends only on the self-contained result graph |
| Producer copies accepted Draft facts/questions/model_metadata field-for-field | PASS |
| Producer relabels a `CaseFact.state` or changes a preserved fact/question ref while constructing result | `INVALID_CASE_RESULT` |
| Semantic validation repeated over the same immutable result | same deterministic validation outcome |

Where a malformed ref is already rejected by JSON Schema (for example, a wrong namespace prefix), the test may fail at the schema boundary first; the application MUST still never implement a fallback that coerces that ref to another object type.

## 15. Mapping to current CASE-0001 infrastructure

The existing bundle is a valid internal/audit representation but does not define the client interface.

| Existing artifact/tool | v3 application-contract role |
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
| tools/rematerialize_case.py | Canonical preview/write path for deterministic report and source-manifest freshness |
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

### 15.1 Materialization drift history and current freshness contract

The 2026-09-23 post-P1 audit recorded that CASE-0001's canonical support graph was structurally valid while the checked-in `report.md` differed from the deterministic materializer on six generated lines. That remains a historical audit observation and MUST NOT be rewritten to match later system state.

At issue #15 completion, that drift was intentionally left to dedicated lifecycle work. DEF-0008 / issue #18 subsequently established deterministic materialization freshness/rematerialization behavior and refreshed CASE-0001's `report.md` and `sources/manifest.json` from canonical state. The six-line drift is therefore historical, not current unresolved operational state.

Canonical case/corpus state remains authoritative. `report.md` and source manifests are derived deterministic materializations and never become canonical truth. Current/stale detection and refresh are governed by [the case-analysis/materialization freshness contract](../architecture/data-lifecycle.md#14-case-analysis-and-materialization): exact canonical render-and-compare, non-mutating preview by default, and explicit refresh through `tools/rematerialize_case.py --write`. Historical audit observations remain preserved even after the generated artifacts are refreshed.

## 16. Client/internal exposure policy

Safe and expected normal inputs:

- problem_text;
- explicit as_of_date;
- opaque client_reference.

Safe application outputs include:

- interpreted `CaseFact` and `CaseQuestion` objects preserved from the accepted draft;
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
- perform case-materialization remediation itself (the historical CASE-0001 drift was subsequently resolved by DEF-0008 / issue #18);
- implement CASE-0002;
- mutate or reprocess the production corpus;
- redefine canonical identity, evidence, relationships, or temporality;
- implement the broader run/execution provenance manifest owned by issue #11.

## 19. Acceptance invariants

An implementation conforming to v3 must preserve all of these:

1. A client can begin with natural-language `problem_text` and optional explicit metadata, without internal IDs/hashes.
2. `CaseDraft` preserves the exact client-owned `problem_text`, `as_of_date`, and `client_reference` values and optional-field presence/absence from its originating `CaseInput`; any mismatch is `INVALID_CASE_DRAFT`.
3. The required case concepts have stable versioned serialized contracts.
4. User-provided facts remain distinguishable from model normalization/inference and cannot rewrite the immutable client payload.
5. Every model-generated legal conclusion begins as `CandidateClaim`.
6. `CandidateClaim` cannot be treated as validated solely by model output.
7. Canonical evidence/provenance and legal identity/state remain controlled by deterministic corpus logic.
8. Internal persistence/provenance identifiers are not mandatory client inputs.
9. `CaseDraft.model_metadata` and `CaseResult.model_metadata` are both required and use the same provider-neutral shape.
10. `CaseResult.facts`, `CaseResult.questions`, and `CaseResult.model_metadata` preserve the accepted CaseDraft values field-for-field under the baseline v3 producer lifecycle.
11. `CaseResult` owns its result-level fact/question namespaces and is semantically validatable without loading the originating CaseDraft.
12. All result-level application refs resolve only inside the same typed CaseResult graph.
13. Structuring metadata is descriptive execution/intake traceability only; it is not legal evidence or canonical authority.
14. No credential/secret field or full prompt text is required/exposed by the metadata contract.
15. Broader run provenance remains outside this contract and owned by issue #11.
16. CASE-0001's current bundle/tools have an explicit mapping to the application boundary.
17. CLI/API/future MCP transports can share the same portable Case Application Service result contract.
18. Missing or ambiguous information remains explicit unresolved state.
19. v1.0.0 and v2.0.0 compatibility artifacts remain separate and unchanged; consumers must not silently reinterpret v3 as an older version.
20. Contract use does not require runtime/corpus mutation.
21. Persistence changes are not implied by this specification.

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

Where a future implementation needs a new persistence abstraction, protocol transport, or execution-provenance model, that work belongs to its owning issue rather than being inferred from this application contract. Existing case-materialization freshness/rematerialization behavior is governed by `../architecture/data-lifecycle.md` §14 and must be reused rather than redefined here.
