# CASE MCP legal-research gateway v2

## Status and authority

Status: **issue #287 implementation contract; active after converged merge**

Gateway contract version: **2.0.0**

Supported semantic transports:

| CASE application contract | Public REST contract | Route |
| --- | --- | --- |
| 4.0.0 | 1.0.0 | `POST /v1/cases` |
| 5.0.0 | 2.0.0 | `POST /v2/cases` |

Driver: GitHub issue #287 under epic #130. This contract extends the independent
MCP adapter from #145 without changing canonical CASE/domain ownership. CASE v4
and REST v1 remain frozen historical contracts; CASE v5 coverage semantics come
only from the published REST v2 bundle created by #285.

## 1. Version negotiation

`research_case` accepts an explicit `case_contract_version`.

- omitted value means CASE `4.0.0`, preserving the historical #145 behavior;
- `4.0.0` selects REST `1.0.0` at `/v1/cases`;
- `5.0.0` selects REST `2.0.0` at `/v2/cases`;
- any other value fails before HTTP with
  `MCP_CASE_UNSUPPORTED_VERSION`, is non-retryable, and identifies the
  supported versions.

There is no version coercion, fallback, relabeling, or content-based guessing.
A v4 response is validated as v4 and a v5 response as v5. The caller-owned POST
body remains the same public fields: `problem_text`, optional `as_of_date`,
optional `client_reference`, and optional scalar `caller_metadata`. The
selected REST adapter owns the application contract version.

## 2. Dependency and trust boundary

~~~text
external MCP consumer
        |
        | seven semantic tools
        v
col-taxdata-mcp
        |
        | HTTP/JSON only
        +----> CASE REST v1 -> CASE 4.0.0
        |
        +----> CASE REST v2 -> CASE 5.0.0
~~~

The gateway must not import backend CASE modules, access SQLite/corpus storage,
mount backend data, call an inference provider, or construct canonical legal
objects from local heuristics.

Consumer synthesis, interpretation and final prose remain consumer-owned. No
tool writes consumer inference into canonical evidence, identity, relationships,
coverage, evaluation, calculation, provenance, or unresolved state.

## 3. Tool surface

The surface remains exactly the seven tools introduced by #145:

1. `research_case`;
2. `get_case_research`;
3. `get_authority`;
4. `get_provision`;
5. `get_evidence`;
6. `get_normative_relationships`;
7. `get_calculation`.

Issue #287 adds no pagination/window tool and no canonical write tool. Resource
pagination/context-window work remains owned by #159.

## 4. Full-bundle compatibility

The gateway always retains and returns the complete validated REST
`LegalResearchBundle` selected by the caller. The bundle is not rewritten,
summarized, paged, truncated by semantic projection, or relabeled.

The bounded in-memory `mcpbundle:<sha256>` handle remains ephemeral,
gateway-local, noncanonical and nonpersistent. Its derivation continues to bind
the REST API version, accepted CaseInput fingerprint and canonical bundle ref,
so v1/v2 responses cannot collide merely because they share display content.

## 5. CASE v5 research-coverage projection

For a validated CASE 5.0.0 bundle, `research_case` and
`get_case_research` additionally expose a sibling
`mcp_research_coverage_view`. It is a read-only projection of existing bundle
objects and includes:

- intake questions;
- exact missing or ambiguous IntakeFact objects, including
  `needed_information`;
- ResearchPlan aspects and tasks;
- EvidenceSelection objects;
- AspectCoverage objects;
- OmittedWork objects;
- unresolved items;
- ResearchContextFingerprint.

Every object is copied from the validated bundle. The projection does not
create canonical references and does not remove fields from those objects.

The projection must not add a `supported` boolean or otherwise collapse the
independent v5 coverage dimensions. In particular:

- complete execution is not equivalent to context-ready evidence;
- context-ready evidence is not a legal applicability conclusion;
- `support_closure=complete` may coexist with
  `requires_interpretive_synthesis`;
- missing personalization facts may leave one aspect incomplete while general
  research/support for another aspect remains usable;
- absent caller `as_of_date` remains temporally unassessed.

The projection notice explicitly states that coverage is platform
research/support state, not a final legal conclusion.

## 6. Navigable semantic links

For CASE v5, the existing authority, provision and evidence getters add a
`research_links` projection. It follows only explicit references already
present in the cached bundle:

`question_ref -> aspect_ref -> task_ref -> selection_ref -> evidence/authority`

and the corresponding:

`coverage_ref -> omission_ref / unresolved_ref`.

Joins may also follow the explicit `related_*_refs` carried by an unresolved
item. The gateway does not create a link because text looks similar, because an
authority is graph-adjacent, or because a consumer claims that a source controls
an issue. Absence of an explicit link remains absence, not a negative legal
conclusion.

The existing getters still return exact evidence/source/hash/provenance objects.
The link projection is supplemental navigation, not a second canonical model.

## 7. Missing facts and external handoff

A v5 bundle may be `partial` while unaffected general research is complete.
The MCP projection preserves that distinction.

When intake facts are `missing` or `ambiguous`, the projection returns the
exact IntakeFact entries and their `needed_information`. Related unresolved
items retain their exact `next_action` and explicit question/aspect/coverage
links. The MCP layer does not invent the missing value, block unrelated general
research, or transform a consumer answer into a canonical fact.

`requires_interpretive_synthesis` is an explicit handoff to the external
consumer. It is not an instruction to write the consumer's interpretation back
into CASE.

## 8. Validation and stable errors

For each selected version the gateway validates:

- the exact expected REST API version;
- the closed success envelope;
- request SHA-256 fingerprints;
- the exact selected CASE application version and bundle status;
- the closed LegalResearchBundle top-level shape;
- exact caller-owned CaseInput preservation;
- expected list-valued canonical collections.

REST v1 and REST v2 public errors use the existing stable MCP error mapping.
Timeout behavior and retryability from #256 are unchanged. Request and response
byte limits remain enforced before projection.

A REST response for a different version than the one requested is an upstream
contract error. It is never silently accepted as another supported version.

## 9. Deployment and security

The gateway continues to build only from `col-taxdata/mcp_gateway/` and uses
only HTTP/JSON to reach CASE REST. It has no backend source/storage mount and no
provider credentials.

`/readyz` reports the gateway version plus supported CASE/REST contract
versions without exposing the upstream URL or runtime secrets. The historical
single `case_rest_api_version` field remains as the v1 compatibility value.

## 10. Deferred scope

This contract does not implement:

- #159 pagination/resource windows/context budgeting;
- canonical continuation execution;
- a new persistence system;
- prompt-injection/security program #161;
- production authentication #160;
- external-model legal synthesis;
- consumer-inference write-back.

A future continuation request may be admitted only under the accepted #279
non-canonical request semantics. Issue #287 does not create such a write path.
