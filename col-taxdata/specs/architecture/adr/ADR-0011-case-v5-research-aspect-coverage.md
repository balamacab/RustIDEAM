# ADR-0011 — CASE v5 makes research coverage explicit without claiming legal conclusions

## Status

Accepted architectural decision for issue #279. Runtime implementation remains deferred to the issue-owned children described below.

## Context

CASE v4 correctly separates intake, platform research, canonical evidence, deterministic evaluation and external consumer synthesis. Its research graph, however, is principally question -> task -> authority. A non-empty authority list can therefore be mistaken for question coverage even when a question contains several independent research dimensions, the selected passage is only a heading, required work was skipped by a bound, personal facts are missing, temporal applicability is unassessed, or an external consumer must still perform interpretation.

The public v4 objects and REST v1 envelopes are closed contracts. Adding aspect/coverage fields in place would either fail existing schemas or silently change the meaning of historical 4.0.0 objects and status values. ADR-0010 also requires external interpretive synthesis to remain non-canonical.

Issue #279 therefore requires a successor design that is finite, auditable and useful without pretending that col-taxdata is a universal legal expert system.

## Decision

### 1. Use a new CASE major version

The successor application contract is CASE **5.0.0**.

Historical CASE v4 remains frozen and interpretable under its existing schema and semantics. A v4 bundle is never relabeled as v5. A v5 execution may copy only caller-owned input fields into a new v5 CaseInput; this creates new versioned execution/derived identities where their documented identity material includes the contract or policy version.

REST v1 remains the v4 transport until #285 publishes an explicitly versioned v5 transport. MCP and Web clients do not infer v5 support from the existence of this ADR.

### 2. The research chain is explicit

For each legal question, the platform records a finite chain:

~~~
question
  -> research aspect
      -> platform-owned task
          -> retrieved candidates
          -> selected authorities/evidence
              -> aspect coverage assessment
~~~

A ResearchAspect is a neutral research dimension, not a proposed answer. An aspect may originate from an explicit finite user scope, a versioned neutral profile, or a generic fallback. Profiles name dimensions to investigate; they do not name outcomes, rates, winners or hard-coded controlling document IDs.

Every task belongs to exactly one aspect. Tasks use typed strategies and targets so exact document/provision/reference/context work is not degraded into free-text thematic search.

### 3. Coverage is multidimensional

AspectCoverage records independent states for:

- task execution;
- evidence availability and contextual adequacy;
- authority classification/uncertainty;
- temporal assessment;
- required factual inputs;
- deterministic-evaluator availability/completion;
- external interpretive synthesis;
- declared scope/support closure.

No single supported flag exists.

Evidence located, a task completed, or a high search score never means that the evidence is legally applicable, that all material law has been found, or that col-taxdata has reached an authoritative conclusion.

### 4. Minimum complete support closure is finite and conservative

A v5 ResearchResult or LegalResearchBundle may be complete only when every required aspect inside a declared finite scope has complete support closure.

Complete support closure requires all of the following:

1. every required task for the aspect reached a terminal completed state;
2. no required research or support work for the aspect is omitted by an exhausted bound;
3. selected support resolves to valid typed authority/evidence references;
4. required evidence context is exact-sufficient or verified-expanded, never context-incomplete;
5. authority ambiguity/conflict that prevents using the support is not hidden;
6. any caller-requested temporal assessment is either resolved or explicitly prevents closure;
7. missing facts that are necessary only for personalization are recorded without preventing unrelated general research;
8. unresolved interpretive synthesis may remain when no deterministic evaluator owns the conclusion.

Complete means the declared bounded research/support work is complete. It never means exhaustive knowledge of all Colombian law, legal applicability in the absence of required temporal/factual inputs, or a final legal opinion.

A generic-limited or unknown/unplanned scope cannot produce bundle status complete. It remains partial with the unplanned/unsupported scope visible.

### 5. Missing personal facts are local blockers

A missing or ambiguous client fact is linked to the affected aspect(s). It does not block general legal research for unrelated aspects.

An aspect may therefore have useful exact legal evidence while fact_status is missing or ambiguous and synthesis_status is requires_facts. Other aspects may complete normally.

### 6. Temporal input stays caller-owned

CaseInput.as_of_date remains optional and caller-owned.

If it is absent:

- no current date, server date or model date is inserted into CaseInput or ResearchPlan;
- ResearchContextFingerprint.as_of_date is null and explicitly unavailable for caller temporal scope;
- affected coverage records temporal_status = unassessed;
- no consumer may interpret absence as current-law validation.

If a historical date is supplied, it is preserved exactly and research evaluates that date. A future client may choose a visible default before submission, but the resulting request must carry the date explicitly.

### 7. Typed task strategy and target representation

ResearchTask v5 contains:

- aspect_ref;
- required flag;
- origin;
- purpose;
- strategy;
- typed target;
- fact/hint provenance;
- depth and deterministic scheduling order.

Strategies include thematic_search, exact_target_lookup, reference_expansion, temporal_resolution, conflict_resolution, context_expansion and generic_fallback.

Targets are typed query, document, provision, relationship or evidence-context targets. Canonical target refs are accepted only when already resolved by platform/corpus semantics; the planner never manufactures them from text.

### 8. Separate research, support and display budgets

Three budget classes have different authority:

**Research budget** limits execution work such as tasks, rounds, queries, hits, reference depth and admitted authorities. Exhausting required research work makes the affected coverage incomplete.

**Support budget** limits evidence/context/relationship material selected to substantiate an aspect. Exhausting required support work also prevents complete support closure.

**Display budget** is representation/access only. It may limit what a client receives inline, but it must not change the canonical ResearchResult, coverage state, authority identity or exact evidence. Any bounded projection must reveal omitted material and provide recoverable access. Display budgeting remains owned by #159 and is not implemented by #279 or the v5 canonical bundle.

Fair scheduling reserves bounded work for required aspects and multiple questions before optional hints or high-fanout expansion.

### 9. Exact-context requirement

A selected exact span is not automatically context-ready.

Each evidence selection records context_status:

- exact_sufficient;
- expanded_verified;
- incomplete;
- not_applicable.

Headings, amendment introductions, definitions that require referenced text, exceptions and explicit cross-references cannot close support unless their necessary context is present through separate provenance-preserving spans. Unrelated passages are never concatenated into one purported exact quote.

### 10. Graph selection happens before support closure

Normative graph expansion is not evidence of topical coverage by itself.

Coverage is computed from selected research/evidence and necessary legal dependencies. Graph materialization may add evidence owners and selected modification/repeal/exception/definition/conflict endpoints required for integrity, but high-degree relationship endpoints do not create new aspect coverage merely because they are reachable.

Every materialized support edge must retain a selection basis. Omitted potentially relevant graph work remains visible.

### 11. Consumer continuation requests are non-canonical input

A later REST/MCP consumer may request additional research by referencing an existing bundle/question/aspect and a neutral requested focus.

Consumer request text is request metadata only. It cannot become:

- CanonicalAuthority;
- EvidenceSpan;
- RuleFragment;
- DeterministicEvaluation;
- a canonical legal conclusion.

The platform validates the request and, if admitted, creates new platform-owned aspects/tasks under the active planner/policy. Consumer inference is never promoted merely because it motivated the request.

### 12. Identifier and fingerprint policy

New refs are opaque typed identifiers. Prefixes aid validation but do not define persistence identity.

The v5 contract introduces aspect:, selection:, coverage:, omission: and continuation: namespaces.

Identity classes:

- ResearchAspect, EvidenceSelection, AspectCoverage and OmittedWork are derived/versioned identities.
- Their stability material includes the owning execution/result identity plus the structural key and the relevant planner/selection/coverage policy version.
- A policy/version change may intentionally create a new derived identity; a persistence-engine change alone must not.
- continuation: is non-canonical request/execution identity and carries no legal-domain stability guarantee.

ResearchContextFingerprint v5 adds explicit profile, coverage, support-selection and graph-selection version/fingerprint fields so materially different research policies cannot masquerade as the same context.

Historical v4 identifiers and hashes are not recomputed or reinterpreted.

### 13. Versioned rollout

The implementation order is:

| Issue | Ownership | Dependency |
| --- | --- | --- |
| #280 | v5 typed aspect/coverage schema + semantic validation/version dispatch | #279 |
| #281 | aspect planning, generic fallback, fairness/profile fingerprinting | #280; integrate after #276–#278 |
| #282 | bounded exact evidence-context retrieval | #280; integrate after #276 |
| #283 | per-aspect evidence/coverage ledger and v5 status calculation | #281 + #282 |
| #284 | research-relevant relationship selection/support closure | #283 |
| #285 | v5 persistence/materialization and versioned public REST | #283; revalidate #284 before integration |
| #286 | Web coverage presentation | #285 |
| #287 | MCP v5 coverage projection/continuation compatibility | #285 |
| #288 | fresh independent coverage/consumer validation | #276 + #277 + #278 + #284 + #285 + #286 + #287 |

#159 remains representation/access ownership, not coverage/authority ownership.

### 14. Future admission for #159

#159's historical admission text requires #142 PASS. #142 is closed as not_planned, so that condition is not satisfied and must not be treated as satisfied by closure.

The proposed replacement, subject to explicit Controller approval, is a **representation-pressure gate** after #285–#287 converge. #159 may be admitted when:

1. the then-current full canonical bundle is reproducibly shown to exceed a published REST/MCP/client representation constraint, or there is an explicit product requirement for resource-on-demand access; and
2. the required solution can preserve exact evidence, stable refs and canonical coverage independently of page/window layout; and
3. the work does not redefine research coverage, legal authority or canonical identity.

#288 may provide measurements supporting that decision but is neither a dependency nor an automatic admission trigger. This avoids a #159 <-> validation dependency cycle.

## Consequences

- v4 remains stable and existing consumers keep deterministic historical interpretation.
- v5 can express research completeness without conflating evidence with legal conclusions.
- More states and refs exist, so validators must enforce typed cross-reference and closure invariants.
- A bundle may be complete while still requiring external interpretive synthesis, but it cannot be complete with generic/unknown-unplanned scope or required omitted research/support work.
- Temporal applicability is intentionally weaker when the caller supplies no as-of date; the bundle says unassessed rather than silently assuming today.
- Paging/context-window optimization remains separate and can be added later without rewriting canonical research meaning.

## Rejected alternatives

### Add optional aspect/coverage fields to v4

Rejected because v4 schemas are closed and the change would silently alter status/coverage interpretation for historical serialized objects.

### Treat any authority hit as question support

Rejected because relevance, exact evidence, context, authority character, temporality and factual prerequisites are independent.

### Require a deterministic evaluator before an aspect can close

Rejected because many legitimate legal questions require external interpretation after rigorous evidence research. Lack of an evaluator is not itself a research failure.

### Make fixed domain profiles authoritative coverage inventories

Rejected because a finite profile cannot guarantee all material dimensions for arbitrary questions. Unknown/generic scope remains visible and non-complete.

### Let display/token limits drive canonical research

Rejected because provider/client context windows are representation concerns. They must not change legal evidence identity or coverage semantics.

## Related contracts/issues

ADR-0010 remains authoritative for evidence-first ownership and external consumer inference. This ADR refines research decomposition/coverage and introduces the v5 compatibility boundary required by #279.
