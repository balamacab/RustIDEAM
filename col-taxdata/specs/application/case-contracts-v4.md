# Case application contracts v4

## Status and authority

Status: **Accepted architectural/application contract; intake boundary implemented, platform research/bundle stages pending**

Contract package version: **4.0.0**

Driver: GitHub issue #132 under epic #130, after DEF-0015 / issue #131.

This specification defines the evidence-first CASE application boundary. Issues #134-#136 implement the v4 contract primitives, semantic intake port, and active intake-only generation/validation path. Platform-owned research and LegalResearchBundle production remain staged for #137+; until those stages land, a valid v4 intake ends in the explicit `CASE_RESEARCH_NOT_IMPLEMENTED` transition rather than falling back to v3 candidate-claim synthesis. Historical v3 remains an explicit compatibility contract only.

The companion machine-readable schema is `schemas/case-contracts-v4.schema.json`. The schema is normative for serialized shape. This document is normative for ownership, trust, dependency direction, lifecycle, cross-object semantics, compatibility and canonical-authority rules.

This contract must be read consistently with:

- `../architecture/adr/ADR-0010-case-v4-evidence-first-authority.md`;
- `../architecture/adr/ADR-0004-preserve-ambiguity.md`;
- `../architecture/adr/ADR-0005-llm-not-canonical-authority.md`;
- `../architecture/domain-model.md`;
- `../architecture/data-lifecycle.md`;
- `../architecture/identifier-semantics.md`;
- `../defects/DEF-0015-model-authored-legal-conclusions-drive-case-research.md`;
- issue #76 structured-generation/no-repair guarantees.

## 1. Purpose

v4 reverses the v3 authority dependency.

```text
v3 defective direction

internal model legal hypothesis
        ↓
candidate claim text
        ↓
retrieval
        ↓
attempt to prove model sentence
```

The v4 direction is:

```text
self-contained CaseInput
        ↓
internal intake structurer
        ↓
IntakeDraft
  facts / questions / missing-or-ambiguous facts
  optional advisory search vocabulary
        ↓
platform ResearchPlan
        ↓
canonical corpus research
        ↓
ResearchResult
        ↓
CanonicalAuthority + EvidenceSpan + NormativeRelationship
        ↓
RuleFragment
        ↓
DeterministicEvaluation / CalculationTrace where explicitly implemented
        ↓
LegalResearchBundle
        ↓
REST / web / MCP
        ↓
optional external consumer inference
```

External consumer inference is not part of the canonical bundle.

## 2. v4 object model

The named v4 contract objects are:

- `CaseInput`;
- `IntakeDraft`;
- `ResearchPlan`;
- `ResearchResult`;
- `CanonicalAuthority`;
- `EvidenceSpan`;
- `NormativeRelationship`;
- `RuleFragment`;
- `DeterministicEvaluation`;
- `CalculationTrace`;
- `UnresolvedItem`;
- `LegalResearchBundle`.

Supporting value objects include `IntakeFact`, `CaseQuestion`, `SearchHint`, `ResearchTask`, `ResearchTraceStep`, `ResearchContextFingerprint`, `OfficialSource`, authority publication metadata and intake metadata.

There is deliberately no generic free-text `claim` object in the active v4 authority path.

## 3. Trust and ownership

| Object/material | Owner | Trust meaning |
| --- | --- | --- |
| CaseInput problem text / caller scalar metadata | caller | caller-provided input, not independent legal truth |
| IntakeDraft facts/questions/search hints | internal intake model after application validation | intake structure only; never canonical legal authority |
| ResearchPlan | platform | platform research intent and bounds |
| ResearchResult / trace | platform | record of bounded research execution; relevance is not authority |
| OfficialSource | platform/canonical corpus | transport-safe official acquisition-source identity/URI; not a Document identity |
| CanonicalAuthority | platform/canonical corpus | resolved legal authority identity and supported metadata |
| EvidenceSpan | platform/canonical corpus | exact citable legal source text with provenance |
| NormativeRelationship | platform/canonical corpus | supported relationship with evidence/provenance |
| RuleFragment | platform deterministic derivation | structured rule/evidence data reproducibly derived from canonical support |
| DeterministicEvaluation | explicit platform evaluator | deterministic result under a named/versioned evaluator |
| CalculationTrace | explicit platform calculator/evaluator | reproducible numeric trace |
| UnresolvedItem | platform | explicit missing/ambiguous/conflicting/interpretive state |
| LegalResearchBundle | platform | transport-safe materialization of the above |
| external LLM synthesis/inference | external consumer | consumer-owned analysis; never canonical merely because generated |

The internal model may structure intake. It cannot author a platform legal proposition for later validation.

## 4. Contract versioning and compatibility

### 4.1 Breaking change

v4.0.0 is a new major contract because ownership, required objects and trust semantics change.

v3 `CaseDraft.candidate_claims`, `SupportedClaim`, `remaining_candidate_claims` and claim-promotion semantics are not v4 concepts.

A change in ownership from "model candidate legal conclusion" to "platform evidence-first research" cannot be represented as a minor v3 extension.

### 4.2 Historical contracts remain frozen

v1.0.0, v2.0.0 and v3.0.0 remain valid historical compatibility contracts for consumers that explicitly support them.

A v3 object MUST NOT be:

- relabeled as v4 by changing `contract_version`;
- treated as a v4 RuleFragment;
- treated as a v4 EvidenceSpan;
- treated as a DeterministicEvaluation;
- promoted into CanonicalAuthority because its text was once supported;
- silently rewritten in stored/frozen history.

Explicit version dispatch is mandatory.

A v3 CaseInput may be copied into a **new v4 execution** using only caller-owned input fields. That is a new execution, not an in-place conversion, and carries no v3 candidate-claim authority forward.

### 4.3 Schema strictness

Serialized v4 objects use `additionalProperties: false` at contract boundaries unless a field is explicitly defined as an extensible structured payload.

Consumers that do not support major version 4 reject it explicitly.

## 5. CaseInput

CaseInput is the sole normal starting object supplied to col-taxdata.

Required:

- `kind = "case_input"`;
- `contract_version = "4.0.0"`;
- non-empty `problem_text`.

Optional caller-owned scalar context:

- `as_of_date`;
- `client_reference`;
- bounded `caller_metadata` whose values are scalar JSON values only.

`caller_metadata` is correlation/transport context. It MUST NOT be treated as a hidden source of legal facts. Legally relevant facts must appear in the self-contained `problem_text`.

### 5.1 Current milestone input boundary

CaseInput has no attachment/file ingestion contract.

The following are not v4 CaseInput fields:

- binary uploads;
- local filesystem paths;
- arbitrary document URLs for col-taxdata to fetch;
- OCR payloads/jobs;
- attachment identifiers;
- client-document storage handles.

An originating MCP-capable LLM may read user artifacts in its own environment and construct the self-contained `problem_text`, but col-taxdata does not own that file-processing step for this milestone.

### 5.2 Immutable caller payload

Across `CaseInput -> IntakeDraft`:

- `problem_text` is identical;
- presence and value of `as_of_date` are identical;
- presence and value of `client_reference` are identical;
- presence, keys and scalar values of `caller_metadata` are identical.

The application may deterministically materialize omitted caller-owned fields into the model result only by exact copy from the already validated CaseInput and only when the adapter's structured-generation projection intentionally omits those fields. It MUST NOT overwrite a backend-supplied value.

No trimming, translation, Unicode repair, normalization, date substitution or semantic rewrite of caller-owned fields is allowed.

## 6. IntakeDraft

IntakeDraft is the only model-owned v4 application object.

It contains:

- `intake_ref`;
- exact caller-owned CaseInput fields;
- `facts`;
- `questions`;
- optional/advisory `search_hints`;
- `model_metadata`.

It contains no candidate legal conclusion, canonical identifier, evidence object, rule fragment, evaluator result, calculation, or final-answer prose field.

### 6.1 IntakeFact

Allowed states are:

- `user_provided`;
- `llm_normalized`;
- `missing`;
- `ambiguous`.

v4 deliberately removes v3's general `llm_inferred` fact state from the intake authority boundary. The internal model may faithfully normalize stated facts but does not manufacture unstated factual premises for legal evaluation.

Rules:

- `user_provided` requires exact `source_quote` from `CaseInput.problem_text` and `requires_confirmation=false`;
- `llm_normalized` requires an exact source quote and `requires_confirmation=true`;
- `missing` / `ambiguous` require `needed_information` and `requires_confirmation=true`;
- normalization must not change legal/factual substance;
- a missing/ambiguous fact is not guessed.

`source_quote` is an intake-fidelity bridge inherited from #91. It is not an EvidenceSpan and not canonical legal evidence. Future client-input span identity remains #122.

### 6.2 CaseQuestion

A CaseQuestion records what needs to be researched/resolved.

It carries:

- `question_ref`;
- question text;
- category;
- `open` or `blocked` status;
- optional dependencies on intake facts.

A blocked question remains visible.

### 6.3 SearchHint

SearchHint contains bounded vocabulary terms only.

It is:

- optional;
- model-owned;
- explicitly `origin="internal_intake_model"`;
- linked to one or more questions;
- advisory and non-authoritative.

Search hints cannot carry typed canonical IDs or a field representing an answer/outcome.

Even a syntactically valid hint cannot force a canonical target. The platform must work when all search hints are absent or poor.

### 6.4 Structured generation and no repair

The #76 two-gate rule remains:

1. generation compatibility: constrained/structured generation returns one directly parseable object;
2. application validity: authoritative schema + semantic validation.

CASE MUST NOT repair arbitrary model text by:

- stripping Markdown fences;
- extracting embedded JSON;
- fixing malformed JSON;
- renaming fields;
- inventing required semantics;
- coercing values/enums;
- dropping unknown fields;
- repairing source quotes.

A backend that cannot produce compatible structured IntakeDraft output is unavailable for intake under v4.

## 7. Intake semantic validation

Before research, the application validates at least:

- exact caller payload preservation;
- fact-state/source-quote requirements;
- exact source-quote substring fidelity;
- no extra fields;
- no canonical/document/provision/evidence/relationship/calculation fields;
- no candidate-claim/legal-outcome field;
- typed ref uniqueness and resolution;
- model metadata completeness;
- missing/ambiguous state preserved.

Malformed intake is `INVALID_INTAKE_DRAFT`, not legal uncertainty.

No canonical research/case mutation is driven from an invalid draft.

## 8. ResearchPlan

ResearchPlan is platform-owned. It is not model output.

Inputs may include:

- accepted intake facts;
- accepted questions;
- explicit as-of date;
- deterministic platform research vocabulary/taxonomy;
- optional SearchHint terms as secondary expansion signals.

A plan contains:

- `plan_ref`;
- `intake_ref`;
- traceable `ResearchTask` objects;
- explicit `ResearchBounds`;
- explicit stop conditions;
- planner version;
- generation timestamp.

### 8.1 Mandatory platform-origin research

For every open legal research question, semantic validation requires at least one `ResearchTask.origin = "platform_required"`.

Hint-originated tasks can supplement but never replace these tasks.

A misleading hint cannot suppress a required platform task.

### 8.2 Bounded expansion

Research may expand through explicit resolved references/relationships, but the plan must bound at least:

- number of research rounds;
- queries per question;
- hits per query;
- reference-expansion depth;
- total canonical authorities.

Expansion stops when:

- planned questions are sufficiently researched for the platform scope;
- no new canonical authorities are produced;
- a required fact blocks further research;
- explicit plan bounds are exhausted;
- an integrity failure occurs.

Exhausting bounds is not permission to guess.

## 9. ResearchResult

ResearchResult records execution of one ResearchPlan.

It contains:

- `result_ref`;
- `plan_ref`;
- `complete`, `partial` or `blocked` status;
- `ResearchTraceStep` entries;
- refs to resolved CanonicalAuthority objects;
- refs to platform UnresolvedItem objects;
- `ResearchContextFingerprint`;
- timestamp.

### 9.1 Relevance versus authority

A search result/hit is a relevance signal only.

A ResearchTraceStep may record query/hit counts and resulting authority refs, but similarity/rank does not create legal authority.

CanonicalAuthority requires the normal canonical identity/provenance/temporal/authority-classification boundaries.

### 9.2 Minimal ResearchContextFingerprint

The fingerprint records:

- corpus/snapshot SHA-256 when available;
- schema/migration-state fingerprint when available;
- retrieval/index configuration identity/hash when available;
- planner version;
- retrieval version;
- as-of date if supplied;
- explicit list of unavailable fingerprint fields.

A nullable fingerprint field is unavailable only when listed in `unavailable_fields`. Values are never guessed.

This is the bounded milestone fingerprint from #137/#140, not the full #11 execution-provenance model.

## 10. CanonicalAuthority

CanonicalAuthority is a transport-safe view of one resolved canonical legal authority relevant to the research.

It carries:

- `authority_ref`;
- public canonical `document_ref`;
- zero or more public `provision_refs`;
- display name;
- document/instrument type where known;
- issuer where known;
- jurisdiction/scope where known;
- source family where known;
- legal-function classification;
- classification state;
- official source refs;
- publication/promulgation metadata with explicit resolution state;
- temporal state;
- evidence refs;
- normative relationship refs.

### 10.1 Legal-function classification

The base v4 vocabulary is:

- `normative`;
- `jurisprudential`;
- `administrative_interpretation`;
- `guidance`;
- `other`;
- `unknown`.

Classification may be `resolved`, `partial`, `ambiguous`, or `unknown`.

Issue #146 implements mapping from existing canonical corpus semantics. Unknown/ambiguous values remain explicit.

### 10.2 OfficialSource

`OfficialSource` is a transport-safe view of the acquisition/source identity used by canonical evidence.

It carries:

- `source_ref`;
- source authority/owner label;
- official `source_uri`;
- optional source kind;
- optional display title.

`source_ref` is an application-level opaque ref and is not a Document identity. A source page may contain or cite several legal documents, and the source/canonical-document distinction from the corpus domain model remains mandatory.

### 10.3 Publication/promulgation metadata

CanonicalAuthority contains a publication metadata object with:

- `state = resolved | partial | ambiguous | unknown`;
- zero or more supported publication dates;
- zero or more supported promulgation dates;
- optional publication reference/identifier text;
- supporting evidence refs.

Multiple candidate dates remain visible when the state is ambiguous. This metadata does not imply effectiveness; effectiveness remains a separate temporal resolution.

### 10.4 No universal authority rank

CanonicalAuthority has no numeric rank, weight, precedence score or universal ordering field.

Where deterministic legal effect/precedence is explicitly implemented later, it must be represented as a separately supported rule/evaluation with evidence, not as a magic authority score.

### 10.5 Temporal state

The transport representation records:

- requested `as_of_date` when available;
- `resolution_state = resolved | unresolved | ambiguous | not_applicable`;
- `effective = true | false | null`;
- basis evidence refs.

`effective=null` is mandatory when the platform cannot support a binary effective/not-effective determination or when it is not applicable.

Modification/repeal/regulation/supersession semantics remain explicit relationships rather than being compressed into this boolean.

## 11. EvidenceSpan

EvidenceSpan is exact citable text from the canonical legal corpus.

It carries:

- `evidence_ref`;
- opaque stable `span_ref`;
- owning `authority_ref`;
- `document_ref` and optional `provision_ref`;
- `source_ref` resolving to one OfficialSource in the bundle;
- `exact_text`;
- raw/source SHA-256;
- exact-text SHA-256;
- opaque provenance ref;
- anchor semantics version;
- optional retrieval timestamp.

The exact text is platform-materialized from canonical evidence. It is not model-written.

The public `span_ref` is an application-level stable reference. #138 owns its implementation and exact anchor mechanics. v4 does not duplicate #122's client-input source-span identity.

A quote mismatch is an integrity failure; the platform does not repair it semantically.

## 12. NormativeRelationship

NormativeRelationship represents a supported canonical relation between two CanonicalAuthority objects.

It contains:

- `relationship_ref`;
- controlled canonical `relationship_type`;
- source and target authority refs;
- one or more supporting evidence refs;
- provenance ref;
- resolved status.

Unresolved/ambiguous relationship candidates are represented as UnresolvedItem rather than guessed into a canonical relationship.

The contract intentionally does not freeze one universal relationship vocabulary; the value must come from the canonical relationship model implemented by the corpus, not arbitrary model text.

## 13. RuleFragment

RuleFragment is platform-owned structured rule/evidence data.

It is not:

- a model candidate claim;
- a free-form final legal conclusion;
- search-result text;
- an external LLM answer.

Every fragment contains:

- `rule_ref`;
- registered `rule_type`;
- `rule_schema_version`;
- `structured_data`;
- derivation method/version;
- canonical authority refs;
- evidence refs;
- optional relationship refs;
- optional as-of date.

The base schema permits a structured payload because fragment families differ. Application semantic validation MUST dispatch by `rule_type + rule_schema_version` to a registered deterministic schema. Unknown fragment types/versions are invalid.

Allowed base derivation methods are:

- `extractive_normalization`;
- `deterministic_composition`.

Issue #138 defines the first registered fragment schemas and derivation rules.

## 14. DeterministicEvaluation

DeterministicEvaluation exists only when an explicit evaluator has been implemented.

It carries:

- `evaluation_ref`;
- evaluator ID/version;
- status;
- question/fact/rule/evidence refs;
- optional as-of date;
- typed deterministic result when determined;
- calculation-trace refs where applicable;
- unresolved refs when blocked;
- timestamp.

Evaluators consume accepted facts plus supported rules/evidence. They never consume model legal prose as authority.

If the required legal conclusion needs interpretation beyond an implemented evaluator, the platform does not create a fake evaluation. It emits `UnresolvedItem.category = "requires_interpretive_synthesis"`.

## 15. CalculationTrace

CalculationTrace records a reproducible numeric operation.

Numeric values are serialized as decimal strings to avoid transport-dependent binary floating-point interpretation.

A trace contains:

- calculator/evaluator ID and version;
- named input decimal values and units;
- fact/rule provenance refs for inputs where applicable;
- explicit formula and formula language/version;
- intermediate steps;
- exact result;
- explicit rounding mode/scale;
- supporting rule/evidence refs;
- timestamp.

A rate, threshold or legal premise must originate from accepted facts or supported rule/evidence, never internal-model prose.

## 16. UnresolvedItem

UnresolvedItem is platform-owned explicit uncertainty or incompleteness.

Categories include:

- `missing_fact`;
- `ambiguous_fact`;
- `no_relevant_corpus_evidence`;
- `corpus_gap`;
- `unresolved_identity`;
- `temporal_uncertainty`;
- `conflicting_authority`;
- `integrity_failure`;
- `unsupported_evaluator`;
- `requires_interpretive_synthesis`;
- `other`.

It may reference related facts, questions, authorities, evidence, rules, evaluations and calculations.

No absence of evidence is converted into affirmative legal truth.

`requires_interpretive_synthesis` is a normal boundary when the platform has completed its evidence/rule work but no deterministic evaluator owns the interpretive conclusion.

## 17. LegalResearchBundle

LegalResearchBundle is the durable v4 integration object.

It embeds or contains:

- CaseInput;
- accepted IntakeDraft;
- ResearchPlan;
- ResearchResult;
- OfficialSource collection;
- CanonicalAuthority collection;
- EvidenceSpan collection;
- NormativeRelationship collection;
- RuleFragment collection;
- DeterministicEvaluation collection;
- CalculationTrace collection;
- UnresolvedItem collection;
- bundle status/timestamp.

It contains no external-consumer inference field.

### 17.1 Bundle status

`complete` means the platform completed the research/evidence work required by its plan under current bounds and integrity rules. It does **not** mean col-taxdata authored a universal final legal opinion.

A complete bundle may therefore include `requires_interpretive_synthesis` items for questions intentionally handed to an external consumer.

`partial` means research/evidence work remains incomplete because of corpus gaps, bounds, conflicts, missing facts or other nonfatal unresolved conditions.

`blocked` means the application cannot safely produce the required research bundle, for example because of contract/integrity failure.

## 18. Typed reference namespaces

Refs are opaque application identifiers. Prefixes aid transport validation but do not define persistence identity.

At minimum the v4 namespaces are:

- `intake:`;
- `fact:`;
- `question:`;
- `hint:`;
- `plan:`;
- `task:`;
- `research:`;
- `trace:`;
- `authority:`;
- `source:`;
- `document:`;
- `provision:`;
- `evidence:`;
- `span:`;
- `relationship:`;
- `rule:`;
- `evaluation:`;
- `calculation:`;
- `unresolved:`;
- `provenance:`;
- `bundle:`.

Semantic validation uses typed registries, never an untyped "find any matching string" fallback.

### 18.1 Intake graph

Inside IntakeDraft:

- question fact dependencies resolve to exactly one intake fact;
- SearchHint question refs resolve to exactly one intake question;
- fact/question/hint refs are unique in their owning collections.

### 18.2 Research graph

Inside a bundle:

- ResearchPlan.intake_ref resolves to the embedded IntakeDraft;
- each ResearchTask.question_ref resolves to an intake question;
- task hint refs resolve only to IntakeDraft.search_hints;
- ResearchResult.plan_ref resolves to the embedded ResearchPlan;
- ResearchTraceStep.task_ref resolves to one plan task;
- ResearchResult authority/unresolved refs resolve to the corresponding bundle collections.

### 18.3 Evidence/authority graph

- every CanonicalAuthority source ref resolves to exactly one OfficialSource in the bundle;
- CanonicalAuthority evidence/relationship refs resolve to bundle EvidenceSpan / NormativeRelationship collections;
- EvidenceSpan.source_ref resolves to exactly one OfficialSource;
- EvidenceSpan.authority_ref resolves to exactly one authority;
- EvidenceSpan.document_ref must match that authority's document ref;
- EvidenceSpan.provision_ref, when present, must occur in the authority's provision refs;
- NormativeRelationship source/target refs resolve to authorities;
- relationship evidence refs resolve to EvidenceSpan objects.

### 18.4 Rule/evaluation graph

- RuleFragment authority/evidence/relationship refs resolve to the typed collections;
- DeterministicEvaluation fact/question/rule/evidence/calculation/unresolved refs resolve to the corresponding typed collections;
- CalculationTrace source fact/rule and support refs resolve to the typed collections;
- UnresolvedItem related refs resolve only in their declared typed namespaces.

Duplicate, dangling, stale or wrong-type refs invalidate the containing v4 object/bundle.

## 19. Error semantics

Transport-neutral symbolic meanings include:

| Condition | Meaning |
| --- | --- |
| invalid/missing CaseInput | `INVALID_CASE_INPUT` |
| intake backend unavailable/incompatible | `CASE_STRUCTURING_UNAVAILABLE` |
| IntakeDraft schema/semantic failure | `INVALID_INTAKE_DRAFT` |
| ResearchPlan graph/bounds failure | `INVALID_RESEARCH_PLAN` |
| ResearchResult graph/fingerprint failure | `INVALID_RESEARCH_RESULT` |
| bundle graph/ownership failure | `INVALID_LEGAL_RESEARCH_BUNDLE` |
| canonical provenance/hash mismatch | `RESEARCH_INTEGRITY_FAILURE` |

These are system/contract conditions, not legal uncertainty. They MUST NOT be converted to ordinary UnresolvedItem merely to keep processing.

Legal/factual uncertainty inside an otherwise valid graph is represented by UnresolvedItem.

## 20. External integration boundary

The runtime dependency direction is:

```text
CASE application
     ↓
LegalResearchBundle
     ↓
#144 REST
   /     \
  v       v
#143     #145 MCP
web       |
          v
     external LLM
```

#143 and #145 consume only the published REST contract at runtime.

They MUST NOT:

- import backend/domain Python packages;
- read SQLite directly;
- mount/use backend writable CASE state;
- call the internal intake model/provider directly;
- fabricate authority/evidence;
- promote external consumer inference into canonical state.

The MCP gateway may expose semantic research tools, but it is not a raw privileged side channel.

## 21. v3 -> v4 schema delta

| v3 | v4 |
| --- | --- |
| `CaseDraft` | `IntakeDraft` with intake-only semantics |
| `CandidateClaim` | removed from model contract |
| model `target_hints` attached to claims | optional standalone advisory SearchHint vocabulary |
| `SupportedClaim` | no direct equivalent; split into EvidenceSpan / RuleFragment / DeterministicEvaluation |
| `remaining_candidate_claims` | removed; unresolved legal work uses UnresolvedItem |
| `PublicSourceRef` | replaced by OfficialSource as the transport-safe source identity/URI object |
| `CaseEvidence` | replaced by canonical legal EvidenceSpan with explicit source/authority/span/hash semantics |
| `CaseResult` | replaced by LegalResearchBundle |
| no ResearchPlan | platform-owned ResearchPlan |
| no ResearchResult trace/fingerprint | platform-owned ResearchResult + ResearchContextFingerprint |
| model metadata in result | intake metadata remains attached to IntakeDraft and is audit-only |
| source_quote exact client text | retained only as intake fidelity bridge; never canonical legal evidence |
| claim promotion | replaced by evidence/rule construction and explicit deterministic evaluators |

No v3 field is silently reinterpreted under a v4 name.

## 22. Implementation ordering

The contract fixes ownership so later issues do not re-decide it:

1. #134 — v4 primitives/schema/validators + v3 compatibility dispatch.
2. #133 — migration-test runtime may proceed in parallel.
3. #135 — IntakeInferencePort/adapters.
4. #136 — active intake-only model semantics.
5. #137 — ResearchPlan/ResearchResult evidence-first retrieval + research fingerprint.
6. #146 — legal-authority metadata/classification after #134; no numeric rank.
7. #138 — EvidenceSpan + RuleFragment graph from canonical research.
8. #139 — deterministic evaluators/calculations.
9. #140 — canonical bundle persistence/materialization and legacy authority quarantine.
10. #141 — architecture/authority guardrails.
11. #144 — stable REST/OpenAPI contract.
12. #143 and #145 — independent web/MCP adapters through #144 only.
13. #142 — fresh evidence-first Go/No-Go.
14. #61 — final documentation reconciliation.

## 23. Migration and persistence plan

Issue #132 itself changes no runtime persistence and requires no migration.

Later implementation must prefer additive/versioned state.

If new storage is required:

- add a new append-only migration;
- never edit applied migrations;
- do not rewrite v3 historical rows/artifacts;
- retain raw SHA-256/provenance;
- expose explicit object/version ownership;
- dry-run/preview isolated state before any authorized production mutation.

No production corpus replay is required merely to define or validate this contract.

## 24. Non-goals

v4 design in #132 does not:

- implement the runtime migration;
- implement a DB migration;
- implement ResearchPlan execution;
- implement authority classification (#146);
- implement canonical legal citation spans/rules (#138);
- implement deterministic evaluators (#139);
- implement persistence/materialization (#140);
- implement REST (#144);
- implement web console (#143);
- implement MCP (#145);
- implement client attachment ingestion;
- implement #122 client-input spans;
- implement persistence-wide Ports-and-Adapters (#10);
- implement full execution provenance (#11);
- create an embedded universal legal-answer LLM.

## 25. Acceptance implications for downstream work

A downstream implementation conforms only if it preserves all of these invariants:

- model output is intake-only;
- research starts from facts/questions/platform planning;
- optional hints cannot be the sole research source;
- canonical identity/evidence remains platform-owned and provenance-backed;
- retrieval relevance cannot become authority by itself;
- exact EvidenceSpan, structured RuleFragment, deterministic evaluation and consumer inference remain separate;
- no universal numeric authority rank exists;
- no deterministic evaluator means unresolved/requires-synthesis, not an internal-LLM fallback;
- v3 history remains interpretable but cannot masquerade as v4;
- external MCP inference has no canonical write-back path;
- current milestone input is self-contained text plus caller-owned scalar metadata, not files/attachments.
