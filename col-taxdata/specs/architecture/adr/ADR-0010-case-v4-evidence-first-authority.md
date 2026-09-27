# ADR-0010 — CASE v4 uses evidence-first research with separate intake and consumer inference roles

## Status

Accepted target architecture. Implementation is staged under GitHub epic #130; the current runtime remains v3 until the dependent implementation issues converge.

## Context

CASE v3 permits an internal structuring model to emit `CandidateClaim` legal hypotheses before the platform researches the law. DEF-0015 / issue #131 proved that these model-authored sentences can become the retrieval axis and miss relevant canonical evidence even while conservative exact-support promotion correctly prevents unsupported prose from becoming validated.

ADR-0005 already establishes that LLM output is not canonical legal authority. That decision remains valid, but the #130 program requires a stronger dependency rule: canonical research itself must not begin from a model-authored proposed legal answer.

At the same time, the product must support external LLM/agent consumers through a future MCP gateway. Those consumers legitimately may synthesize evidence and draft user-facing legal explanations, provided their inference remains outside canonical col-taxdata state.

This ADR therefore distinguishes two LLM roles with different authority.

## Decision

### 1. Internal LLM role: intake structurer only

The internal inference capability is a semantic application port:

```text
structure_intake(CaseInput) -> IntakeDraft
```

The internal model MAY:

- structure facts stated in the self-contained case description;
- faithfully normalize stated facts while preserving origin/provenance state;
- identify missing or ambiguous facts;
- decompose the caller's questions;
- suggest bounded neutral search vocabulary as advisory hints.

The internal model MUST NOT:

- author a legal conclusion used as canonical research authority;
- emit a candidate tax/legal outcome for later "validation";
- select controlling law by unsupported inference;
- create canonical document, provision, evidence, relationship or temporal identities;
- write platform rule fragments;
- choose rates or legal outcomes;
- perform authoritative calculations/evaluations;
- produce the canonical final legal answer.

Provider/model/runtime identity remains an infrastructure concern. Issue #76's constrained-generation and no-post-response-repair rules remain mandatory.

### 2. Platform role: research and canonical legal support

col-taxdata owns the evidence-first research pipeline:

```text
CaseInput
    |
    v
internal intake LLM
    |
    v
IntakeDraft
    |
    v
platform ResearchPlan
    |
    v
canonical corpus retrieval
    |
    v
document/provision + temporal/normative resolution
    |
    v
exact EvidenceSpan + CanonicalAuthority
    |
    v
structured RuleFragment
    |
    +--> DeterministicEvaluation / CalculationTrace when an explicit evaluator exists
    |
    v
LegalResearchBundle
```

The platform owns:

- research planning and bounded retrieval;
- canonical document/provision resolution;
- source and manifestation provenance;
- exact legal-corpus evidence spans;
- temporal/as-of-date resolution;
- normative relationships;
- legal-authority metadata/classification;
- structured rule/evidence fragments whose derivation is deterministic and reproducible;
- deterministic evaluations/calculations where an explicit evaluator exists;
- explicit unresolved/conflict/requires-synthesis state;
- LegalResearchBundle materialization.

Search relevance is not evidentiary authority. A retrieval hit becomes usable legal support only through the canonical identity, evidence, authority, temporal and provenance boundaries defined by the corpus architecture.

### 3. External LLM role: consumer-owned synthesis

A separate LLM/agent may consume LegalResearchBundle through the future MCP gateway and MAY:

- synthesize supplied authorities/evidence;
- make legal inferences;
- explain consequences;
- draft a user-facing answer;
- request further research.

That inference is consumer-owned. It is not a `RuleFragment`, `DeterministicEvaluation`, `EvidenceSpan`, canonical authority or other canonical col-taxdata state merely because an LLM produced it.

The canonical v4 bundle schema contains no field for consumer-authored legal inference. A later integration may transport consumer output in a separate consumer-owned envelope, but no presentation/REST/MCP path may promote it into canonical platform authority without a separately defined deterministic/human authority process.

### 4. v4 is a breaking ownership contract

The new application contract is v4.0.0.

v1/v2/v3 remain historical compatibility contracts and retain their original semantics. In particular:

- historical v3 `CandidateClaim` and supported-claim text remain interpretable as v3 objects;
- they MUST NOT be silently relabeled as v4 evidence, rule fragments or deterministic evaluations;
- no compatibility reader may promote v3 candidate/model text into v4 canonical authority;
- a v3 `CaseInput` may be explicitly re-submitted as a new v4 request by copying caller-owned input fields, but this is a new v4 execution, not an in-place version conversion;
- frozen historical artifacts are not rewritten.

### 5. Research starts from facts/questions, never a proposed answer

`ResearchPlan` is platform-owned and is derived from:

- accepted intake facts;
- accepted questions;
- explicit as-of date when supplied;
- deterministic platform research vocabulary/taxonomy;
- optional model search hints as secondary inputs only.

For every open legal research question, the plan must contain at least one platform-originated required research task independent of model hints.

Model hints:

- are optional;
- are non-authoritative;
- cannot be the sole research source;
- cannot suppress platform-required tasks;
- cannot force a canonical identity;
- cannot turn a proposed answer into a research target with authority.

Bounded expansion may follow explicit resolved references/relationships, subject to plan limits and explicit stopping conditions. Missing, ambiguous, conflicting or exhausted research remains visible instead of being guessed.

### 6. Legal evidence, structured rules, evaluations and inference remain distinct

The v4 contract separates:

1. **EvidenceSpan** — exact text from canonical legal evidence plus stable source/provenance references.
2. **CanonicalAuthority** — canonical document/provision identity plus official-source, legal-function, temporal and authority metadata.
3. **RuleFragment** — platform-owned structured legal/rule data reproducibly derived from one or more EvidenceSpan objects.
4. **DeterministicEvaluation** — output of an explicitly implemented evaluator consuming supported rules and accepted facts.
5. **CalculationTrace** — exact numeric/formula/input/version trace for a deterministic calculation.
6. **UnresolvedItem** — missing, ambiguous, conflicting, unsupported or interpretive material that the platform cannot deterministically resolve.
7. **External consumer inference** — outside canonical col-taxdata state.

A generic free-text `claim` object that conflates these categories is forbidden in the active v4 authority path.

### 7. Rule fragments do not create a universal expert system

A RuleFragment is not a universal free-form legal conclusion language.

Each fragment carries:

- a stable application ref;
- a registered `rule_type`;
- a `rule_schema_version`;
- structured data validated for that type/version;
- explicit derivation method/version;
- canonical authority/evidence references.

Issue #138 owns the initial registered fragment types and their deterministic derivation. Unknown or unsupported fragment types are rejected rather than interpreted heuristically.

Where no explicit deterministic evaluator exists, the platform returns supported evidence/rule material plus an `UnresolvedItem` such as `requires_interpretive_synthesis`. It does not invoke an internal LLM fallback to manufacture the result.

### 8. Deterministic evaluation/calculation is explicitly bounded

A deterministic evaluation is permitted only when:

- the evaluator is explicitly implemented and versioned;
- every required fact is accepted and sufficiently resolved;
- required rule/evidence inputs are canonical and supported;
- temporal/as-of state required by the evaluator is resolved;
- calculation semantics, when numeric, are reproducible.

Missing inputs or unresolved legal/temporal state block the evaluation and produce unresolved state.

Numeric calculations use explicit inputs, units, formula/calculator identity, version, rounding policy and exact result trace. They never source a rate or legal premise from model prose.

### 9. LegalResearchBundle is the durable integration object

The transport-safe v4 integration object is `LegalResearchBundle`, not a platform-written universal legal opinion.

It exposes, where available:

- caller-owned CaseInput;
- accepted IntakeDraft facts/questions/missing/ambiguous state;
- platform ResearchPlan;
- ResearchResult and research trace;
- minimal research-context fingerprint;
- OfficialSource refs/URIs;
- CanonicalAuthority objects, including publication/promulgation and temporal metadata;
- EvidenceSpan objects;
- NormativeRelationship objects;
- RuleFragment objects;
- DeterministicEvaluation objects;
- CalculationTrace objects;
- UnresolvedItem objects;
- provenance/hash identities;
- explicit ownership/type markers.

It must be possible for a consumer to distinguish exact source text, platform-structured rule data, deterministic platform output and unresolved material without inspecting persistence internals.

### 10. Legal-authority metadata has no universal numeric rank

CanonicalAuthority exposes structured context needed for downstream reasoning, including supported document/provision identity, instrument/source type, issuer, jurisdiction/scope, legal-function classification, publication/promulgation metadata, temporal state and normative relationships. Official acquisition/source identity and URI are exposed through transport-safe OfficialSource refs rather than conflating Source with Document.

Issue #146 owns implementation and detailed classification mapping against existing corpus semantics.

A single universal numeric authority rank/weight/precedence score is prohibited. Legal effect may depend on competence, subject matter, time and explicit relationships. Deterministic precedence/effect may be represented only when an explicit supported rule exists.

### 11. Evidence-span ownership is split deliberately

For this Go/No-Go milestone, col-taxdata receives a self-contained textual case description. It does not ingest client attachments/files.

Accordingly:

- #122 remains the owner of future authoritative span/reference semantics for **client-input evidence** and is deferred from the current milestone;
- v4 intake continues the #91 bridge: literal `source_quote` for user-provided/normalized facts is exact client-text fidelity metadata, not canonical legal evidence;
- #138 owns exact, citable `EvidenceSpan` semantics for **canonical legal-corpus authorities** used by LegalResearchBundle.

No parallel client-document/source identity system is introduced by #132.

### 12. Input boundary excludes attachments for the current milestone

v4 `CaseInput` accepts:

- one self-contained `problem_text`;
- optional `as_of_date`;
- optional caller correlation/reference metadata;
- optional bounded caller-owned scalar metadata that is transport/correlation context only.

It does not accept:

- binary uploads;
- filesystem paths;
- arbitrary document URLs for col-taxdata to fetch;
- OCR jobs;
- attachment persistence;
- client-document storage.

For MCP use, the originating consumer LLM is responsible for reading any user artifacts in its own environment and converting relevant facts/questions into the self-contained textual case description.

### 13. Minimal research-context identity is required; full execution provenance remains deferred

ResearchResult / LegalResearchBundle carries the minimum research-context identity required by #137/#140 to distinguish materially different research environments, including where available:

- corpus/snapshot SHA-256;
- schema/migration-state fingerprint;
- retrieval/index configuration identity or hash;
- planner version;
- retrieval version;
- as-of date.

Unavailable fields are explicit. This does not implement the broader #11 execution/replay provenance program.

### 14. Integration dependency direction

The allowed direction is:

```text
internal provider adapter
        |
        v
IntakeInferencePort
        |
        v
CASE application
        |
        v
ResearchPlan -> ResearchResult -> evidence/rules/evaluations
        |
        v
LegalResearchBundle
        |
        v
#144 REST contract
      /        \
     v          v
#143 web     #145 MCP gateway
                 |
                 v
          external consumer LLM
```

Forbidden dependency directions include:

- CASE application/domain importing a concrete LLM provider transport;
- research/evidence/evaluator code consuming provider response envelopes;
- web console or MCP gateway importing backend/domain/persistence implementation;
- REST/MCP/UI bypassing canonical evidence to manufacture authority;
- MCP consumer inference flowing back into canonical bundle state merely because it exists.

#143 and #145 consume only #144 at runtime. Neither adapter reads SQLite or backend filesystem state directly.

## Compatibility and migration plan

Implementation order is deliberately staged so v3 remains interpretable while v4 becomes active:

1. **#134** — implement v4 contract primitives, schemas, typed semantic validators and explicit v3/v4 version dispatch. Keep v3 validators unchanged.
2. **#133** — may proceed in parallel to admit the migration-test runtime.
3. **#135** — introduce the semantic intake inference port and provider adapters.
4. **#136** — switch model semantics to IntakeDraft only; remove model candidate legal conclusions from the active new path.
5. **#137** — implement platform ResearchPlan / ResearchResult, bounded evidence-first retrieval and minimal research-context fingerprint.
6. **#146** — after #134, implement legal-authority metadata/classification; may proceed in parallel with the backend path where dependencies permit.
7. **#138** — implement canonical EvidenceSpan and reproducible RuleFragment graph from #137 + #146.
8. **#139** — add bounded deterministic evaluators/calculations.
9. **#140** — persist/materialize LegalResearchBundle and quarantine v3/model-authored authority.
10. **#141** — add machine-enforced dependency/authority guardrails.
11. **#144** — publish stable REST/OpenAPI transport for the v4 bundle after #134/#146.
12. **#143 / #145** — independent web and MCP adapters consuming only #144.
13. **#142** — fresh evidence-first E2E Go/No-Go validation on converged main.
14. **#61** — final trust-boundary documentation reconciliation.

No #132 database migration or corpus replay is authorized. Any later schema migration must be append-only, issue-owned and independently previewed/tested.

## Alternatives considered

### Keep v3 CandidateClaim but strengthen prompts/model quality

Rejected. DEF-0015 is a dependency/authority inversion. A stronger model can produce better hypotheses while leaving the platform dependent on model-authored legal answers.

### Let the internal LLM perform research/legal synthesis but mark output non-canonical

Rejected for the active platform research path. It would preserve the same sequencing risk and blur the distinction between research relevance and evidentiary authority.

### Build a universal deterministic legal expert system

Rejected. The platform should deterministically evaluate only explicitly formalized domains. Open-ended interpretation remains evidence + unresolved/requires-synthesis material for the external consumer.

### Put external LLM inference inside LegalResearchBundle

Rejected. This would blur ownership and create an accidental write-back/promotion path. Consumer inference remains outside canonical bundle state.

### Require client file ingestion/source-span migration now

Rejected for the current milestone. The caller supplies self-contained text. #122 remains valid technical debt but is not on the critical path.

### Expose one numeric legal-authority score

Rejected. Authority/effect is multidimensional and context-dependent; #146 must expose supported structured metadata without pretending a universal ordering exists.

## Consequences

- v4 is intentionally breaking and requires explicit version dispatch.
- Internal model usefulness is narrowed; legal usefulness temporarily depends on subsequent #137–#140 implementation.
- Legal research and evidence become auditable independently of model prose.
- External LLMs remain useful for synthesis without contaminating canonical platform state.
- REST/web/MCP adapters can evolve independently behind the bundle/REST contract.
- Unsupported interpretation is visibly unresolved instead of being filled by an internal LLM.
- v3 history remains readable but cannot masquerade as v4 authority.

## Related contracts/issues

- ADR-0004 — preserve ambiguity.
- ADR-0005 — LLM output is not canonical legal authority.
- ADR-0009 — persistence Ports-and-Adapters remains separate/deferred.
- DEF-0015 / issue #131 — model-authored legal conclusions drive CASE research.
- issue #130 — evidence-first CASE migration epic.
- issue #132 — this architecture decision and v4 contract.
- issue #76 — provider-neutral constrained structured output / no semantic repair.
- issue #122 — deferred client-input source-span technical debt.
- issue #146 — legal-authority metadata/classification.
- issue #138 — canonical legal EvidenceSpan / structured-rule implementation.
- issue #11 — broader execution provenance, deferred from this milestone.
