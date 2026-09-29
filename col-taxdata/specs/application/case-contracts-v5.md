# Case application contracts v5 — research aspects and coverage

## Status and authority

Status: **Accepted successor architecture/design contract; not yet active runtime/public transport**

Contract package version: **5.0.0**

Driver: GitHub issue #279 under epic #130.

CASE v5 refines the evidence-first ownership established by ADR-0010 and CASE v4. It does not change the internal LLM role: internal model output remains intake-only. The new contract makes research decomposition and coverage auditable without turning research coverage into an authoritative legal conclusion.

The companion machine-readable schema is schemas/case-contracts-v5.schema.json. The schema is normative for serialized shape. This document is normative for ownership, reference integrity, status semantics, support closure, version compatibility and rollout.

Until #280–#285 implement and publish the successor path, current runtime/public behavior remains CASE v4 + REST v1. Historical v4 serialized bundles remain governed by case-contracts-v4.md and its schema.

Read with:

- architecture/adr/ADR-0010-case-v4-evidence-first-authority.md;
- architecture/adr/ADR-0011-case-v5-research-aspect-coverage.md;
- architecture/identifier-semantics.md;
- application/case-contracts-v4.md;
- application/case-rest-api-v1.md.

## 1. Purpose

v5 adds an explicit finite chain:

~~~
CaseQuestion
  -> ResearchAspect
      -> ResearchTask
          -> ResearchTraceStep
              -> EvidenceSelection
                  -> AspectCoverage
~~~

The chain answers a research-process question: what was planned, executed, found, selected, contextualized and left unresolved for each research aspect?

It does **not** answer the legal merits by itself.

A coverage state must never be interpreted as:

- proof that an authority applies to the caller;
- proof that no other material authority exists;
- a final legal opinion;
- a substitute for missing caller facts;
- a substitute for unresolved temporal/authority conflicts;
- external interpretive synthesis.

## 2. Version boundary

### 2.1 Why this is v5

v4 public/domain objects are closed. v5 adds required graph nodes, typed task targets, new status dimensions and stricter complete semantics. Those are breaking interpretation changes and require a new application major version.

v4 remains frozen. Do not add v5 fields to a serialized object that declares contract_version = 4.0.0.

### 2.2 Historical interpretation

A stored v4 bundle:

- stays v4;
- is validated with v4 rules;
- keeps its existing refs/hashes/status interpretation;
- is never reserialized as v5 merely by changing contract_version.

A new v5 execution may copy caller-owned CaseInput values from an older request. That is a new execution with v5-derived identities where the v5 identity contract says so.

### 2.3 Public transport rollout

REST v1 continues to transport CASE 4.0.0 until #285 publishes an explicitly versioned v5 public boundary. Web/MCP clients must negotiate/dispatch the published public contract; they must not infer v5 support from repository files alone.

## 3. Ownership model

Ownership remains:

| Material | Owner | Authority role |
| --- | --- | --- |
| CaseInput | caller | caller payload |
| IntakeDraft | internal intake model + platform validation | intake only |
| ResearchAspect | platform | research decomposition only |
| ResearchPlan / ResearchTask | platform | research orchestration |
| ResearchTraceStep | platform | execution trace |
| EvidenceSelection | platform | research/support selection, not legal conclusion |
| AspectCoverage | platform | research/support assessment, not legal conclusion |
| CanonicalAuthority / EvidenceSpan | canonical corpus/platform | citable legal evidence |
| RuleFragment | platform deterministic derivation | structured rule/evidence |
| DeterministicEvaluation / CalculationTrace | platform named/versioned evaluator | bounded deterministic result |
| ResearchContinuationRequest | external consumer/caller | non-canonical request metadata |
| external synthesis/prose | external consumer | non-canonical inference |

The internal intake model does not author aspects, coverage, canonical evidence or legal conclusions.

## 4. ResearchAspect

ResearchAspect is a neutral, finite research dimension attached to exactly one CaseQuestion.

Required fields:

| Field | Meaning |
| --- | --- |
| kind | research_aspect |
| contract_version | 5.0.0 |
| aspect_ref | opaque aspect: ref |
| question_ref | owning CaseQuestion |
| origin | explicit_scope, profile or generic_fallback |
| scope_status | explicit_finite, profiled_finite, generic_limited or unknown_unplanned |
| dimension_key | stable machine key for the dimension |
| research_goal | neutral description of what evidence to investigate |
| required | whether support closure is required for the declared plan |
| fact_refs | caller/intake facts relevant to this aspect |
| sequence | deterministic ordering key |
| decomposition_status | certain or uncertain |
| profile_id/profile_version | present when a profile created the aspect |

Rules:

1. A profile dimension describes what to research, not the expected legal outcome.
2. Profiles must not embed case-specific canonical document/provision IDs as an answer shortcut.
3. generic_fallback is mandatory when no accepted profile can safely enumerate a finite material scope.
4. generic_limited and unknown_unplanned are explicit limitations and cannot yield a complete bundle.
5. Decomposition uncertainty is preserved, not silently normalized into certainty.

## 5. ResearchTask v5

Every task resolves to exactly one question_ref and aspect_ref.

Required task fields include required, origin, purpose, strategy, target, depth and sequence.

### 5.1 origin

Allowed origin values:

- platform_required;
- intake_hint_expansion;
- reference_expansion;
- context_expansion;
- consumer_request_expansion.

A platform_required task exists for every required aspect. Optional hints never suppress required work.

### 5.2 purpose

Allowed purpose values:

- primary_research;
- reference_expansion;
- temporal_resolution;
- conflict_resolution;
- context_completion.

### 5.3 strategy

Allowed strategy values:

- thematic_search;
- exact_target_lookup;
- reference_expansion;
- temporal_resolution;
- conflict_resolution;
- context_expansion;
- generic_fallback.

### 5.4 target

Target is a closed tagged object:

- query — query_text;
- document — document_ref;
- provision — document_ref + provision_ref;
- relationship — relationship_ref;
- evidence_context — evidence_ref.

Known canonical targets stay typed. They are not converted back into loose query text merely for convenience.

The planner must not manufacture canonical refs from model/user prose. Unresolved targets remain unresolved.

## 6. Research budgets and fairness

ResearchPlan v5 contains ResearchBudgets with two canonical classes.

### 6.1 research budget

Fields:

- max_rounds;
- max_tasks;
- max_queries_per_aspect;
- max_hits_per_query;
- max_reference_depth;
- max_total_authorities.

Research-budget exhaustion is execution incompleteness when required work remains.

### 6.2 support budget

Fields:

- max_selected_evidence_per_aspect;
- max_context_expansions_per_aspect;
- max_relationships_per_aspect;
- max_total_evidence_spans.

Support-budget exhaustion is support incompleteness when required context/evidence/dependencies remain.

### 6.3 display budget is separate

Display/context-window limits are not canonical ResearchPlan budget fields. They are representation/access behavior owned by #159.

A display projection may omit inline material only when:

- omission is explicit;
- canonical coverage is unchanged;
- exact omitted material remains recoverable by stable refs/continuation;
- no lossy summary replaces the canonical source.

Until #159 is separately admitted and implemented, the authoritative v5 bundle representation is the complete canonical materialization produced by #285.

### 6.4 fairness policy

ResearchPlan.fairness_policy is required. v5 initially defines required_aspects_round_robin: every required question/aspect receives bounded progress before optional hint expansion or high-fanout reference work can consume the remaining budget.

Task sequence is deterministic for unchanged input/configuration.

## 7. ResearchTraceStep v5

Each trace step records the actual task/aspect and executed target.

Required distinction:

- retrieved_authority_refs — candidates admitted from retrieval;
- selected_authority_refs — authorities selected for aspect support;
- selected_evidence_refs — exact evidence selected for support;
- unresolved_refs — unresolved conditions discovered by this step.

Search/retrieval rank remains a relevance signal. A retrieved authority is not automatically selected evidence, and a selected authority is not automatically legally applicable.

Outcomes are hits, no_hits, blocked, budget_exhausted or integrity_failure.

## 8. EvidenceSelection

EvidenceSelection is the auditable bridge between retrieval and coverage.

Required fields:

| Field | Meaning |
| --- | --- |
| selection_ref | opaque selection: ref |
| aspect_ref / task_ref | owning research chain |
| authority_ref | selected canonical authority |
| evidence_refs | one or more exact EvidenceSpan refs |
| basis | why the material was selected |
| context_status | exact/context adequacy |
| authority_status | classification uncertainty |
| temporal_status | temporal assessment of the selected support |

basis:

- exact_target;
- thematic_relevance;
- normative_dependency;
- temporal_dependency;
- conflict_dependency;
- context_completion.

context_status:

- exact_sufficient;
- expanded_verified;
- incomplete;
- not_applicable.

authority_status:

- resolved;
- ambiguous;
- conflicting;
- unassessed.

temporal_status:

- effective_as_of;
- historical_as_of;
- not_effective_as_of;
- ambiguous;
- unassessed.

No status above is a case-level legal conclusion.

### 8.1 Context rules

An exact substring is not enough when its meaning depends on adjacent/linked material.

Examples requiring contextual treatment include:

- a heading with no operative text;
- an amendment introduction followed by replacement text;
- a definition used by the selected provision;
- an exception/condition in a verified contiguous provision part;
- an explicit cross-reference needed to understand the selected text.

Expanded context must remain separate exact spans with their own source/hash/anchor provenance. Do not fabricate a synthetic exact quotation by concatenating unrelated passages.

### 8.2 Bounded context retrieval implementation boundary

Issue #282 implements the context rule above as a read-only retrieval/materialization primitive. This implementation boundary does not activate the full v5 orchestration path and does not alter historical v4 bundle semantics.

The bounded implementation obeys these additional rules:

1. Context expansion is explicit. A valid concise provision remains concise merely because it was selected; adjacent text is not appended automatically.
2. Contiguous context may be admitted only from the same extraction and canonical document when every crossed segment is independently verified as one uniquely citable observation of the same canonical provision. A different provision or an unverified/ambiguous segment is a hard boundary.
3. Explicit cross-reference context may be admitted only for a review-free, uniquely resolved canonical **provision** target whose exact citable observation is present in the corpus. A document-only, missing, ambiguous or review-required target produces a context gap; it does not trigger thematic broadening or redownload.
4. Every admitted context part remains its own exact EvidenceSpan with its own source/hash/anchor provenance. Context retrieval never creates one synthetic quote by concatenating parts.
5. Context work is bounded independently from quote length. When verified candidate context exceeds the declared context-hit budget, the result remains incomplete and exposes budget exhaustion rather than silently truncating canonical support.
6. Missing or structurally unverifiable context remains an explicit gap. The primitive does not infer omitted statutory text, definitions, exceptions or article membership from wording alone.

## 9. OmittedWork

OmittedWork makes unfinished canonical research/support work explicit.

Fields include omission_ref, aspect_ref, optional task_ref, class, reason, required and description.

class:

- research;
- support.

reason:

- budget_exhausted;
- not_planned;
- unsupported_scope;
- blocked_by_facts;
- context_unavailable;
- integrity_failure.

If required = true, the affected aspect cannot have support_closure = complete and the bundle cannot be complete.

Display omissions are deliberately excluded; #159 owns representation/access omission semantics.

## 10. AspectCoverage

AspectCoverage is a platform research/support assessment.

Required status dimensions:

### execution_status

- not_started;
- partial;
- complete;
- budget_exhausted;
- blocked.

### evidence_status

- not_assessed;
- none_found;
- candidate_only;
- context_incomplete;
- context_ready.

### authority_status

- unassessed;
- resolved;
- ambiguous;
- conflicting.

### temporal_status

- unassessed;
- assessed;
- mixed;
- ambiguous.

### fact_status

- not_required;
- sufficient;
- missing;
- ambiguous.

### synthesis_status

- not_required;
- deterministic_available;
- deterministic_completed;
- requires_interpretive_synthesis;
- requires_facts;
- unsupported.

### support_closure

- complete;
- incomplete;
- unsupported_scope.

limitation_codes may contain:

- generic_scope;
- unplanned_scope;
- missing_facts;
- temporal_unassessed;
- context_gap;
- authority_conflict;
- budget_exhausted;
- no_evidence;
- unsupported_topic.

### 10.1 No supported shortcut

There is no supported boolean.

A consumer must inspect the independent dimensions. In particular:

- execution_status = complete does not imply evidence_status = context_ready;
- evidence_status = context_ready does not imply authority_status = resolved;
- authority_status = resolved does not imply temporal applicability;
- support_closure = complete does not imply deterministic evaluation;
- requires_interpretive_synthesis is compatible with complete support closure;
- missing facts may coexist with context-ready general evidence.

## 11. Minimum complete support closure

For a required aspect, support_closure = complete is valid only when:

1. execution_status = complete;
2. evidence_status = context_ready;
3. authority_status = resolved;
4. every selection_ref/evidence_ref resolves in typed registries;
5. no required OmittedWork belongs to the aspect;
6. no unresolved integrity/context/authority conflict prevents use of the selected support;
7. if CaseInput.as_of_date was supplied, temporal_status is assessed and no unresolved temporal conflict prevents closure;
8. if CaseInput.as_of_date was absent, temporal_status remains unassessed and limitation_codes includes temporal_unassessed; this does not assert current applicability;
9. synthesis_status may be requires_interpretive_synthesis;
10. fact_status may be missing/ambiguous only when the missing fact is required for personalization/evaluation rather than for locating the general legal support. In that case synthesis_status must be requires_facts and the missing fact is linked explicitly.

The final condition is intentionally conservative: general support may close while personalized outcome remains unavailable.

## 12. ResearchResult and bundle status

ResearchResult v5 includes:

- trace;
- authority_refs;
- evidence_selections;
- aspect_coverage;
- omitted_work;
- unresolved_refs;
- research_context;
- status.

LegalResearchBundle v5 contains the v5 CaseInput/IntakeDraft/ResearchPlan/ResearchResult plus the canonical source/authority/evidence/rule/evaluation/calculation collections.

### 12.1 complete

complete requires:

- every required aspect has support_closure = complete;
- no required research/support OmittedWork exists;
- no required aspect has generic_limited or unknown_unplanned scope;
- no integrity failure blocks trustworthy materialization.

complete means bounded declared support closure, not exhaustive legal completeness or a final opinion.

### 12.2 partial

partial is used when useful research/support exists or safe research can continue, but at least one required aspect is incomplete, generic/unknown scope remains, required facts prevent personalization, required support is omitted, or material authority/temporal/context uncertainty remains.

### 12.3 blocked

blocked means the platform cannot safely continue or materialize the required research contract, for example due to integrity/contract failure.

A missing personal fact alone does not make the whole bundle blocked while unaffected general research remains possible.


### 12.4 Per-aspect coverage implementation boundary

Issue #283 implements the read-only producer for EvidenceSelection, OmittedWork,
AspectCoverage and ResearchResult status. This boundary does not activate CASE v5
public transport, persistence or relationship-selection policy.

The producer follows these additional rules:

1. A retrieval hit is only a candidate. It does not create EvidenceSelection or
   support closure unless a platform-owned execution trace explicitly selects
   the authority and exact evidence with one declared selection basis.
2. Selected evidence is resolved against the final supplied materialized
   EvidenceSpan registry. Deduplication or later graph materialization may not
   leave dangling selection/coverage refs, and graph-only endpoint authorities
   do not acquire aspect coverage merely by being reachable.
3. Required tasks that were not executed, were budget-exhausted, were blocked
   by required facts, or failed integrity are represented as required
   OmittedWork. Context-incomplete selected evidence creates required support
   omitted work rather than being treated as a usable quotation.
4. Coverage remains multidimensional. Candidate-only evidence, context gaps,
   authority conflict, missing/ambiguous facts, temporal uncertainty and
   unsupported scope remain separate states; no one-dimensional supported flag
   is reintroduced.
5. generic_limited and unknown_unplanned aspects remain unsupported_scope and
   prevent a complete ResearchResult even if useful exact evidence was found.
6. With no caller as_of_date, temporal coverage remains unassessed and carries
   temporal_unassessed. With a supplied date, ambiguous, historical-only or
   not-effective selected support cannot silently close current support.
7. requires_interpretive_synthesis is a valid handoff state and does not by
   itself prevent complete bounded support closure. Research coverage is not a
   legal opinion or deterministic evaluator.
8. Coverage and support-selection identities are deterministic for unchanged
   plan/context/materialized refs and bind the active coverage/support policy
   versions. generated_at is not identity material.
9. Relationship relevance/selection remains owned by #284. The #283 producer
   consumes only the refs explicitly selected by its caller and does not infer
   legal dependency from graph reachability.

The initial implementation policy identifiers are
`v5-coverage-1` and `v5-support-selection-1`. They are recorded through the
ResearchContextFingerprint fields already defined by this contract.

## 13. Temporal semantics

CaseInput.as_of_date is optional and caller-owned.

### 13.1 absent date

When absent:

- it stays absent from CaseInput;
- it stays absent from ResearchPlan;
- ResearchContextFingerprint.as_of_date = null;
- unavailable_fields includes as_of_date;
- AspectCoverage.temporal_status = unassessed where temporal applicability would otherwise matter;
- limitation_codes includes temporal_unassessed;
- no server/model clock date is injected.

### 13.2 supplied historical/current date

When supplied, the exact caller value is copied to the plan/fingerprint. Temporal evaluation uses that date.

A client UI may visibly prefill a date in the future, but submission must carry it explicitly. The server never silently defaults it.

## 14. Missing and ambiguous facts

Missing/ambiguous facts are linked to affected aspect_ref values through fact_refs, AspectCoverage and UnresolvedItem.

The planner must distinguish:

- facts required to perform general legal research;
- facts required only for case-specific characterization/evaluation.

The second class does not suppress general legal research.

Example: a taxpayer may omit a precise income amount. The platform can still research filing thresholds and evidence. The personalized threshold evaluation remains unavailable until the amount exists.

## 15. Evaluator and synthesis semantics

A deterministic evaluator is optional.

Evidence research is valid when no evaluator exists. A question that needs legal interpretation beyond registered deterministic logic may reach:

- support_closure = complete;
- synthesis_status = requires_interpretive_synthesis;
- UnresolvedItem.category = requires_interpretive_synthesis.

That is a successful platform research handoff, not an error.

Unsupported deterministic evaluation is not converted into an invented platform outcome.

## 16. Generic fallback and unknown scope

Profiles are finite aids, not complete legal ontologies.

If no accepted profile applies:

1. create one or more generic_fallback aspects;
2. mark scope_status = generic_limited or unknown_unplanned;
3. run bounded neutral research;
4. expose the limitation;
5. keep bundle status partial even when those generic tasks finish.

An explicit narrow question with a finite target may use explicit_finite scope and may complete without a domain profile.

### 16.1 Initial deterministic planner profile set (#281)

The first executable v5 planner uses a versioned neutral profile catalog at
`config/case-research-profiles-v5.json`. The catalog is planning configuration,
not legal authority. Its canonical JSON SHA-256 and declared profile-set version
are copied into every ResearchPlan and later ResearchContextFingerprint.

The initial catalog covers three reusable research families:

- `tax.simple` — neutral dimensions for scope/entry, compliance mechanics and
  exclusions/changes in the SIMPLE regime;
- `tax.treaty` — neutral treaty dimensions including treaty scope, business
  profits, royalties/services terminology and permanent-establishment context;
- `tax.filing-obligation` — neutral filing-duty dimensions including subject
  scope, threshold/measurement rules and filing mechanics.

Profile matching is deterministic and conservative:

1. matching uses only the legal question text plus confirmed caller facts;
2. intake search hints never select a profile and never suppress required work;
3. missing/ambiguous fact values are never injected into research queries;
4. profile dimensions may link only the fact refs whose declared semantic keys
   are relevant to that dimension, so a missing personalization fact cannot
   block unrelated general research;
5. unusual wording is handled only through versioned neutral aliases in the
   profile catalog; no model inference is used;
6. if no profile matches safely, the planner emits a `generic_fallback`
   aspect with `generic_limited` scope and `uncertain` decomposition.

The `required_aspects_round_robin` scheduler orders required platform tasks
across questions/aspects before optional hint work or reference/context
expansion. High-fanout expansion therefore cannot consume the plan ahead of a
different required question/aspect. Task ordering is deterministic for the same
accepted intake and planner/profile configuration.

Planner-derived `plan_ref`, `aspect_ref` and `task_ref` identity material
includes the planner/profile versioned structural inputs required by section 20.
Formatting-only changes to the profile file do not change its canonical JSON
hash. Material profile/configuration changes do.

## 17. ResearchContinuationRequest

A later consumer may request more research without writing inference into canonical state.

Fields:

- kind = research_continuation_request;
- contract_version = 5.0.0;
- continuation_ref;
- bundle_ref;
- question_ref;
- optional aspect_ref;
- request_kind;
- requested_focus;
- known_authority_refs;
- known_evidence_refs;
- optional client_reference.

request_kind:

- expand_aspect;
- research_unplanned_scope;
- resolve_context_gap;
- resolve_temporal_uncertainty;
- resolve_conflict.

requested_focus is non-authoritative request metadata. It may influence new platform planning as a secondary signal only. The platform creates any new ResearchAspect/ResearchTask and validates all canonical targets/evidence normally.

There is no expected_answer or proposed_legal_conclusion field.

## 18. ResearchContextFingerprint v5

v5 preserves the v4 context identity and adds policy identity.

Required fields include:

- corpus_snapshot_sha256;
- schema_migration_fingerprint;
- retrieval_config_sha256;
- planner_version;
- retrieval_version;
- profile_set_version;
- profile_set_sha256;
- coverage_policy_version;
- support_selection_version;
- graph_selection_version;
- as_of_date;
- unavailable_fields.

Profile/configuration/policy changes that can alter plan/coverage selection must produce distinguishable fingerprints.

Unavailable values remain null plus explicit unavailable_fields; values are never guessed.

## 19. Typed references and semantic invariants

New namespaces:

- aspect:;
- selection:;
- coverage:;
- omission:;
- continuation:.

Existing v4 namespaces remain for their corresponding v5 object families.

Semantic validation is required in addition to JSON shape validation.

Mandatory invariant codes declared by the schema:

- V5-REF-ASPECT-001 — task.aspect_ref resolves to one plan aspect and the question refs agree.
- V5-REF-SELECTION-002 — selection aspect/task/authority/evidence refs resolve with correct types.
- V5-REF-COVERAGE-003 — coverage task/selection/omission/unresolved refs resolve inside the owning bundle/result.
- V5-COMPLETE-001 — complete status satisfies minimum complete support closure for every required finite-scope aspect.
- V5-OMISSION-001 — required research/support omission prevents complete closure/status.
- V5-CONTEXT-001 — context-incomplete selected evidence cannot close required support.
- V5-TEMPORAL-001 — caller date ownership and absent-date unassessed semantics are preserved.
- V5-FACT-001 — missing facts block only linked work; unrelated general research may continue.
- V5-EVALUATOR-001 — no evaluator is required for evidence support closure; interpretive handoff remains valid.
- V5-SCOPE-001 — generic_limited/unknown_unplanned scope cannot produce complete.
- V5-CONSUMER-001 — consumer continuation input cannot become canonical evidence/conclusion by promotion.
- V5-ID-001 — new derived refs obey declared versioned identity/stability material.

## 20. Identifier stability

Prefixes are validation aids, not identity semantics.

New derived identities:

### aspect_ref

Derived/versioned identity over the owning v5 execution/intake/question plus stable aspect structural key (origin/profile dimension) and planner/profile version. Formatting-only storage changes do not create a new aspect; a materially changed planning/profile contract may.

### selection_ref

Derived/versioned identity over result/task/aspect, selected canonical authority/evidence set, selection basis and support-selection version.

### coverage_ref

Derived/versioned identity over result/aspect and coverage-policy version.

### omission_ref

Derived/versioned identity over result/aspect/task where present, omission class/reason and relevant policy version.

### continuation_ref

Non-canonical request/execution identity. It has no legal-domain stability guarantee and must not be used as evidence/document/provision identity.

Persistence backend changes alone must not redefine domain/evidence identity.

## 21. Graph-selection boundary

Coverage is determined from selected evidence and necessary dependencies, not all reachable graph nodes.

Relationship selection may retain:

- modification/repeal/supersession dependencies affecting selected provisions;
- exceptions/definitions/cross-references required for context;
- conflict/temporal dependencies needed to explain uncertainty;
- evidence owners/endpoints required for referential integrity.

A graph endpoint materialized solely for closure does not gain aspect coverage merely by existence.

#284 owns implementation of this selection boundary.

### 21.1 Relationship-selection implementation boundary

Issue #284 implements this boundary as a read-only v5 selector plus a selected-subgraph
support-closure seam. It does not activate v5 public transport or change historical
v4 bundle materialization.

The implementation follows these additional rules:

1. Complete canonical relationship classification remains upstream and unchanged.
   Case-specific selection consumes that classified candidate set; it never deletes
   or rewrites canonical relationship rows.
2. Selected exact EvidenceSpan provision refs define the strongest structural
   relevance boundary. A relationship that directly touches a selected provision is
   eligible without query-text similarity or a legal-validity score.
3. Amendment/modification, repeal/supersession, exception, definition, temporal and
   explicit conflict dependency classes remain eligible when they affect selected
   support even if endpoint text has low query similarity.
4. A mandatory dependency expressed only at document scope is retained
   conservatively and its document-scope uncertainty is recorded in the deterministic
   selection reason. A provision-scoped relationship for a different known provision
   of the same high-degree document is not admitted merely because that document was
   researched.
5. Relationship work uses the support budget
   `max_relationships_per_aspect`, not research-query or display budgets. Stable
   canonical-ref ordering is only deterministic work ordering; it is not legal
   precedence. If required relevant relationships exceed the support budget, the
   overflow becomes required support OmittedWork and the aspect cannot claim complete
   closure.
6. Endpoint and evidence-owner closure runs only after selection and reuses the
   existing first-order evidence-owner integrity rules. Closure-only authorities
   remain distinguishable from researched/selected authorities and do not acquire
   aspect coverage.
7. Every selected relationship, endpoint and required evidence ref must resolve in
   the selected support graph. Missing canonical ownership/provenance is an integrity
   failure rather than a dangling selected ref.
8. Selection/closure is deterministic and read-only. Display/pagination policy is
   not consulted and cannot change canonical selected content.

The initial deterministic selector version is `v5-graph-selection-1`.

## 22. Persistence and REST/Web/MCP rollout

### Phase A — contract primitives

#280 implements v5 schema/version dispatch and semantic cross-reference/status validation. It does not activate research behavior.

### Phase B — research semantics

#281 implements aspects/fair planning.
#282 implements bounded context retrieval.
#283 implements the coverage ledger.
#284 implements relevant graph selection.

### Phase C — durable/public transport

#285 implements v5 persistence/materialization and publishes a versioned REST boundary. Historical v4 persistence remains readable; no stored v4 bundle is silently rewritten.

### Phase D — consumers

#286 renders coverage faithfully in Web.
#287 supports the v5 public REST contract in MCP and may expose continuation requests without inference write-back.

Web/MCP may run in parallel only after the shared REST v5 contract converges.

### Phase E — validation

#288 performs fresh frozen semantic/consumer validation after its declared dependencies converge.

## 23. #159 representation/access ownership and admission

#159 owns pagination/resource-on-demand/context-window representation. It does not own:

- aspect planning;
- research coverage;
- evidence sufficiency/context;
- authority status;
- temporal assessment;
- canonical graph selection;
- canonical bundle status.

Its existing post-#142-PASS gate is unsatisfied because #142 closed not_planned.

Proposed replacement gate, requiring explicit Controller approval:

**REPRESENTATION_PRESSURE_GATE**

Prerequisites:

1. #285, #286 and #287 converged so the actual v5 public/consumer contract is known.
2. Reproducible measurement shows that full exact material exceeds a published transport/client constraint, or a product requirement explicitly requires resource-on-demand access.
3. The proposed solution preserves canonical coverage/IDs/exact evidence independent of representation windows.
4. No dependency on #159 is added to core coverage acceptance that would create a cycle.

#288 may contribute measurements, but it is not a prerequisite and does not automatically satisfy/admit #159.

Until the Controller accepts this replacement, #159 remains deferred.

## 24. Machine-checkable examples

specs/application/examples/case-v5/research-coverage-examples.json contains machine-readable scenarios for:

- broad generic-limited research;
- narrow finite complete-support research;
- mixed research with missing personalization facts;
- ambiguous/mixed temporal evidence;
- unsupported topic/unplanned scope;
- valid complete support with no deterministic evaluator and external synthesis handoff;
- dangling aspect ref;
- dangling evidence ref;
- invalid complete status with unsupported/generic scope.

Negative examples declare the invariant code they must violate. Positive examples declare expected status dimensions.

The issue #279 contract test checks those examples against the schema vocabulary and semantic invariant table. #280 will own the runtime semantic validator.

## 25. Non-goals

This architecture issue does not:

- implement planner/retrieval/coverage runtime code;
- modify persistence or database schema;
- publish REST v5 runtime endpoints;
- implement Web/MCP support;
- implement #159 pagination/resource windows;
- mutate/reprocess production state;
- create a universal legal-rule inventory;
- let the internal LLM author legal conclusions;
- treat #142 closure as PASS.
