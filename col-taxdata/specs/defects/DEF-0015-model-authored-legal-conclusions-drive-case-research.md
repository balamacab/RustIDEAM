# DEF-0015 — model-authored legal conclusions improperly drive CASE research

Status: specified  
Priority: P1  
GitHub: #131  
Area: CASE research authority / retrieval ownership

## Summary

The active CASE v3 path lets an internal LLM author `candidate_claims[].text` before
the platform has researched the law. That same model-authored sentence is then used
as the principal retrieval query, subjected to an exact-support promotion rule, and
retained as CASE claim/candidate text.

The conservative promotion rule prevents unsupported model prose from becoming a
validated claim. That safety property is necessary and must be preserved. It does
not correct the more fundamental dependency inversion:

```text
model legal hypothesis
    -> retrieval query
    -> attempt to prove the hypothesis
```

Canonical legal research must instead originate from accepted facts, legal questions,
the requested as-of date, and platform-owned research planning. An LLM may structure
intake, but it must not supply the legal proposition that the platform then tries to
prove.

This specification records and characterizes the defect. Issue #131 does not
implement CASE v4 and does not by itself resolve DEF-0015.

## Observed behavior

Current `main` at the #131 baseline uses the following active sequence in
`tools/case_application.py`:

```python
for candidate in draft["candidate_claims"]:
    hits = retrieval.search_candidate(candidate)
    supports = retrieval.exact_canonical_support(candidate, hits)
```

`CorpusRetrievalService.search_candidate()` in `tools/case_retrieval.py`
constructs the FTS query from:

1. `candidate["text"]`; and
2. any model-authored `target_hints`.

The exact-support rule then requires the candidate sentence itself to occur
conservatively in a canonical extracted segment before promotion.

When support is absent, the sentence remains unvalidated, which is correct for
safety. However, current CASE state/materialization still carries the same
model-authored text as a candidate legal claim. The model therefore controls both
the research target and part of the legal-result vocabulary even when it has no
canonical support.

## Evidence

### #123 webcam / natural-person reproduction

The disposable #123 POC recorded a synthetic/public natural-person question about
income from webcam activity and whether a return must be filed.

The resulting CASE had:

- 0 canonical sources;
- 0 direct evidence;
- 0 validated/human-verified conclusions;
- empty claim bindings;
- `analysis_status=partial`.

Read-only FTS queries against the same isolated corpus nevertheless returned relevant
general filing material, including the Estatuto Tributario Article 592 family,
natural-person filing provisions, and `ingresos brutos` / UVT threshold material.

The observed miss therefore cannot be explained as "the corpus lacks all relevant
material". The same corpus could retrieve relevant legal text when queried with
neutral legal vocabulary.

The #123 POC code/runtime was disposable and is not an implementation source for this
fix. Its issue history is retained only as defect evidence.

### #17 historical blind validation

The earlier blind CASE validation independently showed the same architectural risk:

- model-generated candidates could be materially wrong;
- one frozen compound candidate incorrectly asserted a 19% self-withholding rate;
- conservative promotion correctly kept that candidate unvalidated;
- synthesized/compound candidate wording commonly obtained zero exact evidence;
- structurally valid CASE bundles could still be semantically poor;
- provenance and unsupported-claim containment remained intact.

This history supports two separate conclusions:

1. conservative promotion is a useful safety boundary and is not the defect to remove;
2. safety after model-authored hypothesis generation does not make the research
   direction evidence-first.

Historical model outputs and legal answers are not correctness baselines for the
new architecture.

### Current source-path evidence

The current source establishes the dependency directly:

- the v3 model contract contains `candidate_claims`;
- `search_candidate()` searches model candidate text plus hints;
- `exact_canonical_support()` attempts to validate that same text;
- CASE persistence/materialization retains the candidate text even when unsupported.

No provider behavior is needed to reproduce this dependency.

## Impact

DEF-0015 can reduce legal research coverage and semantic usefulness even when:

- canonical corpus evidence exists;
- document identity and provenance are correct;
- the LLM response is syntactically valid;
- exact-support promotion is conservative;
- the final bundle is structurally valid.

A vague, compound, incorrectly worded, or domain-specific model proposition can
steer retrieval away from controlling general rules. If the controlling rule does
not use the user's domain vocabulary (for example, `webcam`), searching a
model-generated answer sentence may miss evidence that a neutral legal question
would retrieve.

The defect also blurs ownership: model prose can become the vocabulary of persisted
legal candidates before the platform has established canonical authority.

## Root cause — confirmed

The root cause is **semantic authority inversion in orchestration**, not model quality.

The current order is:

```text
CaseInput
  -> internal LLM creates facts/questions AND legal candidate conclusions
  -> candidate conclusion text becomes retrieval axis
  -> FTS returns candidate-biased hits
  -> exact-support tries to prove the model sentence
  -> supported or unresolved/candidate state
```

The correct authority order is:

```text
self-contained case description
  -> intake-only structure: facts/questions/missing/ambiguous facts
  -> platform-owned ResearchPlan
  -> neutral/bounded corpus research
  -> canonical document/provision + temporal/normative resolution
  -> exact evidence/source spans
  -> reproducible structured rules/evidence
  -> deterministic evaluations/calculations where explicitly implemented
  -> LegalResearchBundle
  -> optional external LLM synthesis/inference
```

The model/provider can influence intake quality, but it must not own the legal
hypothesis that defines canonical research.

## Five boundaries that must remain distinct

### 1. Corpus coverage

Whether relevant legal material exists in the corpus at all.

A retrieval miss does not prove a coverage gap. #123 demonstrated relevant filing
material existed in the same corpus.

### 2. Retrieval targeting

Which queries/subquestions the platform executes against the corpus.

This is the direct DEF-0015 failure: active v3 targeting originates from a
model-authored legal candidate rather than a platform research plan.

### 3. Claim/evidence promotion

Whether retrieved material is sufficient to support a canonical platform-owned
legal proposition or deterministic result.

The current exact-support rule is conservative and prevented false promotion in
#17/#123. Promotion safety does not cure bad targeting.

### 4. Semantic authority ownership

Who is allowed to create authoritative legal state.

The internal LLM may structure intake. Canonical evidence, structured rules,
deterministic evaluations/calculations, and platform legal authority must be derived
from canonical evidence and auditable platform logic, not from model prose.

An external MCP consumer may infer/synthesize from a LegalResearchBundle, but its
inference is consumer-owned and does not become canonical col-taxdata authority.

### 5. Report/presentation ownership

A report or UI may display platform state and unresolved material, but presentation
must not relabel unsupported internal-model prose as a platform conclusion.

The durable v4 integration object is the citable `LegalResearchBundle`, not a
model-authored legal opinion persisted as platform truth.

## Target invariant

For the active evidence-first path:

> Internal model output may structure intake, but model-authored legal conclusions
> MUST NOT drive canonical research, become platform legal claims, supply
> deterministic calculations/evaluations, or become canonical final-answer text.

Corollaries:

- legal research begins from facts/questions/platform planning;
- optional model search hints are advisory and cannot be the sole research source;
- canonical document/provision/evidence identities are platform-owned;
- absence of support remains unresolved rather than becoming negative legal truth;
- external MCP inference remains non-canonical consumer output;
- every platform-owned legal support item must remain traceable to canonical evidence.

## Required solution direction

Permanent correction is owned by the #130 program, principally #132/#134/#136/#137
and downstream evidence/bundle work.

The implementation must:

1. remove model-authored legal conclusions from the operational research boundary;
2. define intake-only model contracts;
3. create a platform-owned `ResearchPlan` from facts/questions and deterministic
   legal/research vocabulary;
4. make research work without model hints and prevent misleading hints from
   suppressing mandatory platform queries;
5. build legal evidence/rule material from retrieved canonical sources rather than
   searching for a sentence the model already wrote;
6. preserve conservative ambiguity, provenance, canonical identity and temporal
   boundaries;
7. keep deterministic evaluations/calculations explicit and bounded;
8. expose unresolved/requires-synthesis states when deterministic evaluation is not
   implemented;
9. keep external MCP-consumer inference outside canonical state.

A prompt change, a different model, a larger model, more tokens, lower temperature,
or a different provider is not a root fix. Those changes may alter candidate quality
while preserving the defective dependency direction.

## Characterization fixture

`tests/fixtures/def0015_webcam_authority_inversion.json` is deliberately synthetic
and non-authoritative. It does not encode a legal answer or reproduce copyrighted
source material.

It preserves only the structural regression:

- the user/domain scenario contains `webcam`;
- a vague model candidate and its hints use domain-specific vocabulary;
- a synthetic canonical segment encodes the general natural-person filing topic
  without the word `webcam`;
- neutral legal terms retrieve that segment;
- the current candidate-driven query misses it;
- even when the neutral hit is supplied, exact support does not promote the unrelated
  model sentence;
- source/document/manifestation/segment provenance remains intact.

This makes the defect deterministic without requiring a real LLM, production corpus,
or historical runtime artifact.

## Reprocessing plan

N/A for #131.

This issue changes no runtime semantics, database schema, canonical identity, raw
evidence, or production corpus state.

No migration, corpus reprocessing, CASE rerun, or production mutation is authorized.

Downstream implementation issues must define their own migration/reprocessing plans
if the v4 authority model requires persisted-state changes.

## Regression characterization required by #131

The characterization suite must prove on current v3 behavior that:

1. the domain term `webcam` is absent from the synthetic controlling-rule segment;
2. neutral legal vocabulary directly retrieves that canonical segment;
3. `search_candidate()` constructs its query from model candidate text + model
   target hints;
4. that candidate-driven query can return zero hits while the neutral query returns
   the relevant segment;
5. a relevant neutral hit does not validate unrelated/non-literal model prose;
6. canonical document/source/manifestation/segment identities and SHA-256 provenance
   survive retrieval unchanged.

These tests intentionally pass on the defective v3 implementation. They are
characterization tests, not a false claim that the defect is fixed. Later
implementation issues may invert or retire them only when the active v4 path has
equivalent evidence-first regression coverage.

## Acceptance criteria for issue #131

- [ ] DEF-0015 is registered in the defect manifest and defect index.
- [ ] The #123 webcam/natural-person observation is preserved without depending on
      disposable POC code/runtime.
- [ ] #17 is characterized as historical supporting evidence without rewriting it.
- [ ] Corpus coverage, retrieval targeting, promotion, semantic authority ownership,
      and report/presentation ownership are explicitly distinguished.
- [ ] Current candidate-driven dependency is reproduced deterministically.
- [ ] Relevant canonical fixture evidence is retrievable through neutral legal terms.
- [ ] Candidate-driven targeting can miss the same evidence.
- [ ] Unsupported model prose is not promoted as canonical support.
- [ ] Provenance/canonical identity preservation remains tested.
- [ ] Prompt/model/provider substitution is explicitly rejected as a root fix.
- [ ] No production semantics, schema, corpus state, raw evidence, or migration is
      changed.
- [ ] DEF-0015 remains `specified`; #131 closure does not claim defect resolution.

## Resolution gate for DEF-0015

DEF-0015 MUST NOT be marked `verified` merely because #131 characterization passes.

Verification requires the evidence-first #130 architecture to converge and the
fresh #142 Go/No-Go validation to prove at minimum that:

- active research does not require model-authored legal candidate text;
- general controlling rules are discoverable from facts/questions/platform planning;
- internal LLM output cannot become canonical legal authority;
- canonical evidence and authority metadata remain citable/provenance-complete;
- deterministic evaluators use only explicit facts + supported canonical rules;
- unsupported interpretive questions remain unresolved/requires-synthesis;
- REST/web/MCP boundaries preserve authority ownership;
- external consumer inference cannot be promoted back into canonical state.

Until that gate passes, the manifest status remains `specified` or an applicable
in-progress state, never `verified`.

## Dependencies / ordering

Characterization issue #131 has no implementation dependency beyond converged main.

Program ordering is governed by #130. In particular:

- #132 depends on #131;
- #134 depends on #131/#132;
- #137 owns the platform ResearchPlan/evidence-first retrieval implementation;
- #142 is the fresh E2E resolution gate;
- #11 full execution provenance and #122 client-input source-span debt remain
  deferred from the current Go/No-Go critical path unless new evidence makes them
  necessary for correctness.
