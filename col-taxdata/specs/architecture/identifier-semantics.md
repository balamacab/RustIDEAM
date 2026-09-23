# col-taxdata identifier semantics

## Purpose

Prefixes in `col-taxdata` are operational conventions, not self-describing guarantees. This document records the semantics actually implemented today and distinguishes **domain/evidence identity** from **processing/execution identity**.

Most deterministic IDs use UUIDv5 with `uuid.NAMESPACE_URL`, but the exact identity material is generator-specific. A future persistence-backend migration must preserve domain identity semantics; changing SQLite to another backend must not itself require new `DOC-*`, `PROV-*`, `MAN-*`, etc.

“Expected backend stability” below is an architectural expectation when the same identity rules are preserved. Issue #10 has not yet implemented backend-independent ports, and issue #11 has not yet implemented complete execution reproducibility.

## Stability classes

- **Domain/evidence identity:** identifies a conceptual/preserved entity such as Source, Manifestation, Document or Provision.
- **Derived identity:** identifies a versioned interpretation artifact such as Extraction, Reference Mention, Relationship or Temporal Candidate.
- **Processing/execution identity:** identifies an attempt or deterministic processing run rather than the legal entity itself.

## Core families

| Prefix/family | Identifies | Class | Current derivation | Rerun/reprocessing stability | New ID when | Must not create new ID merely because |
| --- | --- | --- | --- | --- | --- | --- |
| `SRC-*` / `SRC-DIAN-*` | Source | Domain/acquisition | Not uniform. DIAN crawler uses UUIDv5 of canonical URL; configured pipelines may supply IDs such as `SRC-0004`. | Stable when the configured Source identity/URL rule is unchanged. | A genuinely different Source identity is registered. | Parser version, document classification, or DB backend changes. |
| `MAN-*` | Manifestation | Evidence identity | UUIDv5 of `source_id + raw sha256`. DB also enforces unique `(sha256, source_id)`. | Stable across reprocessing; same source+same bytes reuses it. | Source differs or bytes/SHA differ. | Extraction/parser version or canonical document binding changes. |
| `DOC-*` | Canonical Document | Domain | Usually UUIDv5 of accepted canonical key. Identity migration code can preserve an existing ID for established semantic equivalence/backfill, or create issuer-split IDs and record migration provenance. | Stable when canonical identity is semantically unchanged. | Canonical identity genuinely changes/splits, subject to migration rules. | New manifestation, extraction version, title formatting, or persistence backend. |
| `ID-*` | Document Identifier row | Derived/domain-support | UUIDv5 of document + identifier type/value (some registrars use equivalent canonical material). | Stable for same Document/identifier value. | Identifier value/type or owning Document changes. | Re-fetch/re-extract only. |
| `PROV-*` | Canonical Provision | Domain | Current registrars use UUIDv5 of document + provision kind/designation. | Stable while Document identity and normalized designation remain stable. | Owning Document identity or canonical designation changes. | New observation/extraction of same provision. |
| `EXT-*` | Text Extraction | Derived/versioned | Normograma uses UUIDv5 of manifestation + extractor name + extractor version. | Stable for same manifestation/extractor/version. New extractor version intentionally creates a new identity. | Manifestation, extractor, or extractor version changes. | Rerun of the same version with identical registered output. |
| `SEG-*` | Extracted Segment | Derived/versioned | UUIDv5 of extraction + sequence + text SHA in current Normograma extractor. | Stable inside the same Extraction. | Extraction, sequence or text hash changes. | DB backend changes. |
| `EVD-*` | Evidence binding | Derived/provenance | **No single universal formula.** Registrars/promoters/processors use deterministic generator-specific material, often including segment/candidate/relationship and processor version/role. | Stable only under the same generator identity contract. | Supporting binding, role, processor/version, or generator-defined identity material changes. | Storage backend alone. |

### Raw-byte sharing versus Manifestation identity

Physical raw storage is content-addressed by SHA-256. Two different Sources that return identical bytes can therefore refer to the same physical raw content path. They do **not** automatically share `MAN-*`, because Manifestation identity includes `source_id`.

This is intentional: byte equality does not erase acquisition provenance.

## Reference and relationship families

| Prefix | Identifies | Class | Current derivation/stability |
| --- | --- | --- | --- |
| `RDR-*` | Reference detection run | Processing/derived run | UUIDv5 of extraction + detector name/version. Same input/version reuses the run; detector version changes create a new run. |
| `REF-*` | Reference Mention | Derived | UUIDv5 of detection run + segment + mention type + span + normalized reference. Stable within same detector run and text positions. |
| `RLM-*` | Explicit Relation Mention | Derived | UUIDv5 of detection run + segment + target mention + relation type. New detector/run or changed relation interpretation can create a new ID. |
| `RRES-*` | Reference Resolution | Derived | UUIDv5 of reference mention + resolution method. The row can be updated as corpus coverage changes; method change creates a separate identity. |
| `REL-*` | Promoted Relationship | Derived legal representation | Current canonical promoter includes source document, relation type, target provision, relation mention and promoter version. Stable for same inputs/version; new promoter version or changed endpoints may create/rebuild IDs. |

A `REF-*` is not a target identity. A `RRES-*` records the resolution state. A `REL-*` is only promoted when the required source/target evidence meets the promoter contract.

## Temporal families

| Prefix | Identifies | Class | Current derivation/stability |
| --- | --- | --- | --- |
| `TCA-*` | Temporal Candidate | Derived/versioned | UUIDv5 of extraction + role + segment + absolute span + processor name/version. New processor version intentionally creates a new candidate namespace. |
| `TRS-*` | Temporal Role Resolution | Derived/versioned | UUIDv5 of extraction + temporal role + processor name/version. Same input/version must not resolve to different data under the same ID. |
| `TEV-*` | Temporal Event | Derived legal representation | Processor-specific. DEF-0004 event promotion includes document + event type/date/effective-from + processor version. Other registrars can include scope/parser version. Do not assume one universal `TEV-*` formula. |

Temporal IDs being deterministic does not make the underlying date legally resolved. Candidate/resolution status and evidence determine whether promotion is allowed.

## Other significant deterministic entity IDs

| Prefix | Meaning | Notes |
| --- | --- | --- |
| `IDSIG-*` | Document identity signal | UUIDv5 over manifestation + extraction + signal origin + raw signal value. |
| `REV-*` | Review Queue Item | Deterministic, but subsystem-specific material (for example manifestation+reason, reference+method+reason, temporal resolution). It is workflow identity, not legal identity. |
| `POBS-*` | Provision Observation | Current compiled-provision registrar includes provision + extraction + segment + parser version. |
| `DPOS-*` | DIAN doctrine position | Current doctrine registrar uses document + ordinal. |
| `GQ-*` | Official guidance question | Current RUT guidance registrar uses document + ordinal + question segment identity. |
| `IDMIG-*` | Document identity migration provenance | Deterministic record of an issuer-identity backfill/split/rebinding operation. It records migration history; it is not a schema migration ID. |

Other tables can contain IDs without a project-wide generation guarantee. Issue #9 does not infer guarantees merely from column names.

## Generated / execution-attempt identifiers

### `FETCH-*`

**Identifies:** one HTTP fetch attempt.

**Class:** execution/acquisition attempt identity.

**Generation:** UUIDv4 in `fetch_source.py`.

**Stability:** intentionally **not** stable across repeated fetches. Even if the URL and returned bytes are identical, each attempt is a separate audit event.

**New ID:** every fetch attempt.

**Must not be used as:** Manifestation, Source, or Document identity.

### `extraction_run_id`

The initial schema defines `extraction_runs.extraction_run_id`, but current repository inspection for issue #9 does not establish one single active producer/generation contract for that table. Therefore no determinism or cross-backend stability guarantee is asserted here. Issue #11 is the future work item for complete processing-run manifests/reproducibility.

### `job_id`

The initial schema defines `jobs.job_id` and an idempotency uniqueness key over processor/input/version/configuration. Issue #9 does not infer a universal `job_id` generation algorithm where current inspected pipeline code does not establish one.

## Case IDs and Claim IDs

`CASE-*` names such as `CASE-0001` are repository/case-workflow identifiers, not automatically generated legal-domain identities.

`claims.claim_id` is part of the current case model, but case-bundle registration accepts the claim IDs declared by the bundle. There is no repository-wide deterministic Claim ID formula that can be promised by this document.

## Canonical-key semantics

The canonical key is more important than the `DOC-*` UUID representation.

Current identity logic includes:

```text
issuer-scoped:
CO:<issuer_key>:<document_type>:<number>:<year>

non-issuer-scoped conventional national family:
CO:<document_type>:<number>:<year>

family-specific official guidance:
family-specific canonical form
```

Examples of issuer-scoped types in current source identity logic include Resolución, Circular, Concepto, Oficio, Sentencia C, CONPES and Constitución Política.

Legacy unqualified aliases can be retained as non-primary identifiers when useful, but they must not collapse distinct issuers.

## Stability across persistence-backend migration

A future backend change should preserve IDs where the **domain identity inputs** are unchanged. In particular:

- changing SQLite to PostgreSQL must not itself create a new Document;
- rebuilding FTS must not create a new Manifestation or Document;
- changing storage paths must not create a new Document/Provision;
- a new extractor/detector/promoter version may intentionally create new **derived** IDs because the version is part of the identity contract;
- a legal identity correction (for example splitting an issuer collision) may intentionally create/rebind domain IDs and must carry explicit provenance.

Issue #10 is responsible for persistence decoupling; this document defines the identity semantics that such a refactor must preserve.

## What this document does not guarantee

It does not claim:

- every prefix has one global helper or one derivation formula;
- UUIDv5 alone proves legal correctness;
- all current processing is fully reproducible from a Git commit/config/image manifest;
- IDs produced by a changed algorithm will stay stable unless the change explicitly preserves the previous identity contract.

Those stronger execution-provenance guarantees belong to issue #11.
