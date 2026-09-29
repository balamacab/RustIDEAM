# CASE web console coverage presentation v2

## Status and authority

Status: **implemented presentation contract**

Driver: GitHub issue #286 under epic #130.

Public transport dependency: CASE REST API 2.0.0 / CASE 5.0.0 from #285.
Historical compatibility dependency: REST 1.0.0 / CASE 4.0.0.

This document defines only the independent web presentation boundary. It does
not redefine CASE v5 research semantics, evidence identity, temporal semantics,
or legal authority. Those remain owned by the authoritative application and REST
contracts.

## 1. Active and historical contract handling

The console actively submits caller input to `POST /api/v2/cases`, the
same-origin projection of REST `/v2/cases`.

The browser supports these response pairs:

- REST 2.0.0 -> CASE 5.0.0: render structured question/aspect coverage;
- REST 1.0.0 -> CASE 4.0.0: preserve historical JSON views and display an
  explicit message that structured aspect coverage does not exist in v4.

Any other API version or API/bundle version mismatch is displayed as unsupported.
The browser preserves Raw JSON and does not coerce or reinterpret the response.

## 2. Caller-owned temporal input

`as_of_date` remains optional and caller-owned.

When the field is blank, the browser omits it from the submitted request. It does
not insert the current date. The UI explains this before submission, and CASE v5
`temporal_status=unassessed` / `temporal_unassessed` limitations remain visible in
the Coverage view.

When a date is supplied, the UI describes it as caller supplied. Selection-level
`effective_as_of`, `historical_as_of`, `not_effective_as_of`, `ambiguous` and
`unassessed` states are displayed literally through descriptive labels; the
browser does not independently decide legal effectiveness.

## 3. Coverage projection

For each public CaseQuestion the console groups public ResearchAspect objects by
`question_ref`. For each aspect it displays, when present:

- scope/origin and research goal;
- execution status;
- evidence status;
- authority status;
- temporal status;
- fact status;
- support closure;
- OmittedWork limitations;
- linked UnresolvedItem limitations;
- selected exact EvidenceSpan text;
- supplied CanonicalAuthority metadata;
- supplied OfficialSource URI.

The display distinguishes at minimum:

- complete, partial and blocked bundle/research states;
- not researched (`execution_status=not_started` and/or `not_planned`);
- generic/unknown/unplanned scope;
- required missing facts;
- no evidence/corpus gaps;
- context gaps;
- authority ambiguity/conflict;
- budget exhaustion;
- integrity failure;
- temporal unassessed/mixed/ambiguous states;
- external interpretive synthesis.

Display labels are presentation mappings only. They do not collapse the
underlying multidimensional CASE v5 objects into a new canonical status.

## 4. Evidence/source navigation

The navigation chain is:

`question -> aspect -> EvidenceSelection -> exact EvidenceSpan -> CanonicalAuthority -> OfficialSource`

Only source URIs with `http` or `https` schemes become clickable links. Missing
or ambiguous authority metadata is displayed as unavailable/ambiguous; it is
never guessed from text or source URLs.

Selected evidence text is rendered with DOM `textContent`, not HTML parsing.

## 5. Synthesis boundary

When `synthesis_status=requires_interpretive_synthesis`, the console explicitly
states that interpretive synthesis remains external to col-taxdata and that
research coverage is not a legal conclusion.

The browser has no model/provider controls and no direct model invocation. It
cannot write consumer synthesis, outcomes, canonical IDs, evidence, temporal
state or other domain state back into CASE.

## 6. Raw inspection/export

The existing Raw JSON view is preserved. After any received JSON response, the
operator may export the exact response object as formatted JSON. Local transport
failures have no fake CASE payload to export.

## 7. Security and deployment boundary

The web image remains static code only. It contains no backend Python imports,
SQLite/corpus mount, writable CASE state, credentials or provider integration.
nginx exposes only exact POST proxy routes for `/api/v2/cases` and historical
`/api/v1/cases`; there is no generic `/api/` forwarding surface.

Existing #274 ES-module MIME guarantees apply to every `.mjs` browser module,
including the coverage renderer.

## 8. Validation matrix

Synthetic presentation fixtures cover:

1. complete finite coverage with selected evidence and external synthesis;
2. partial coverage with context gap, authority conflict, budget exhaustion,
   ambiguous/missing authority metadata and historical evidence;
3. blocked/integrity failure;
4. not-researched work;
5. unknown-profile / unplanned scope;
6. requires-facts while retaining explicit limitation state.

Browser-side regression checks execute the actual coverage view-model and DOM
renderer against these fixtures, verify safe official-source links, verify
unsupported/historical version messages, preserve raw export, and retain the
container/module MIME checks from #143/#274.

## 9. Non-goals

No legal answering chatbot, pagination/resource windows, legal outcome editing,
new backend dependency, schema migration, persistence mutation, corpus replay or
production mutation is introduced by this contract.
