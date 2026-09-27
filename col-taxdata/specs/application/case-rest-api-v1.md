# CASE public REST API v1

## Status and authority

Status: **authoritative public transport contract**

REST contract version: **1.0.0**

CASE application contract transported by this API: **4.0.0**

Driver: GitHub issue #144 under epic #130.

The machine-readable contract is `openapi/case-rest-api-v1.openapi.json`. Transport-only JSON Schemas are in `schemas/case-rest-api-v1.schema.json`; CASE domain objects are referenced from the authoritative `case-contracts-v4.schema.json`.

This contract is the only semantic interface required by external web/MCP clients. Backend Python packages, SQLite layout, filesystem layout, provider adapters and runtime model configuration are not public API.

## 1. Version boundary

The public major version is encoded in the path: `/v1`. The response header `X-Col-Taxdata-API-Version: 1.0.0` and response field `api_version = "1.0.0"` identify the exact published wire contract.

REST version and CASE application version are deliberately separate. REST v1 transports `LegalResearchBundle.contract_version = "4.0.0"`. A historical v3 `CaseResult` must never be relabeled as a v4 bundle.

Breaking public request/response/error changes require a new REST major path. Compatible documentation clarifications or additive independent operations may evolve within v1, but the closed shape of `POST /v1/cases` is not silently widened. Unsupported version paths fail rather than being coerced.

## 2. Public operation

`POST /v1/cases` accepts a self-contained textual case and returns one validated v4 LegalResearchBundle.

Request fields:

| Field | Ownership | Required | Meaning |
| --- | --- | --- | --- |
| `problem_text` | caller | yes | Self-contained case facts/questions. Preserved exactly. |
| `as_of_date` | caller | no | ISO date when the caller requests an as-of legal view. |
| `client_reference` | caller | no | External correlation value only. Never canonical identity. |
| `caller_metadata` | caller | no | Up to 32 scalar JSON values for correlation/transport context. |

The adapter creates server-owned `kind="case_input"` and `contract_version="4.0.0"`. Caller-owned values and presence are copied without trimming, Unicode normalization, date substitution or semantic repair.

Not accepted in this milestone: files/binary attachments, local paths, arbitrary document URLs, OCR payloads/jobs, client-supplied canonical document/provision/evidence IDs, expected legal conclusions, source hints that force authority, provider/model/backend selection or credentials.

Reserved server-owned/control names are also forbidden as `caller_metadata` keys so correlation metadata cannot masquerade as an execution control.

## 3. Success envelope and status semantics

HTTP 200 means the request was processed into a structurally and semantically valid LegalResearchBundle. It does **not** mean every legal question is resolved.

```json
{
  "api_version": "1.0.0",
  "request_fingerprints": {
    "raw_request_sha256": "<sha256>",
    "case_input_sha256": "<sha256>"
  },
  "bundle": { "...": "LegalResearchBundle v4" }
}
```

The legal/research state is `bundle.status`:

- `complete`: platform research completed for its bounded scope;
- `partial`: supported material exists but unresolved work remains;
- `blocked`: a missing/ambiguous/integrity condition truthfully prevents completion.

A partial or blocked bundle is still a successful HTTP representation when the bundle itself is valid. Clients must inspect `bundle.unresolved`; they must not infer completeness from HTTP 200.

## 4. Ownership and authority markers

Clients distinguish material by the v4 `kind` field and typed references:

- `official_source`, `canonical_authority`, `evidence_span`, `normative_relationship`: canonical/platform evidence views with traceable references;
- `rule_fragment`: reproducible structured rule/evidence derivation, not model legal prose;
- `deterministic_evaluation` and `calculation_trace`: named/versioned deterministic platform results;
- `unresolved_item`: explicit missing, ambiguous, conflicting, integrity, unsupported-evaluator or `requires_interpretive_synthesis` state;
- `intake_draft.model_metadata`: descriptive intake-generation audit metadata only, never legal authority.

External consumer inference/final-answer prose is not a LegalResearchBundle field and has no canonical write-back path through this API.

## 5. Provenance and public references

Public refs such as `document:...`, `evidence:...`, `span:...`, `source:...` and `provenance:...` are opaque application references. Consumers must not derive filesystem paths, table keys or storage locations from them.

`EvidenceSpan` exposes exact text, source/text SHA-256, an opaque provenance ref and source ref. `CanonicalAuthority` exposes the legal-authority metadata fixed by #146. `ResearchContextFingerprint` exposes the bounded corpus/schema/retrieval context defined by v4, including explicit unavailable fields rather than guessed values.

No database filename, row ID, local path or internal persistence counter is part of the success envelope.

## 6. Request fingerprints

Two audit fingerprints are public:

- `raw_request_sha256`: SHA-256 over the exact HTTP request-body bytes, before decoding/parsing;
- `case_input_sha256`: SHA-256 over deterministic UTF-8 JSON of the validated v4 CaseInput using sorted keys and compact separators.

Equivalent JSON bodies may share `case_input_sha256` while retaining different `raw_request_sha256`. These fingerprints are audit identities, not canonical legal-document identities.

## 7. Error contract

Errors use a closed envelope:

```json
{
  "api_version": "1.0.0",
  "error": {
    "code": "CASE_API_INVALID_REQUEST",
    "message": "The request does not conform to the public CASE API contract.",
    "retryable": false
  },
  "request_fingerprints": {
    "raw_request_sha256": "<sha256>"
  }
}
```

Stable mappings:

| HTTP | Code | Retryable |
| ---: | --- | --- |
| 400 | `CASE_API_INVALID_REQUEST` | no |
| 404 | `CASE_API_NOT_FOUND` | no |
| 405 | `CASE_API_METHOD_NOT_ALLOWED` | no |
| 411 | `CASE_API_LENGTH_REQUIRED` | no |
| 413 | `CASE_API_REQUEST_TOO_LARGE` | no |
| 415 | `CASE_API_UNSUPPORTED_MEDIA_TYPE` | no |
| 500 | `CASE_API_INTEGRITY_FAILURE` | no |
| 500 | `CASE_API_INTERNAL_ERROR` | no |
| 503 | `CASE_API_SERVICE_UNAVAILABLE` | yes |
| 504 | `CASE_API_TIMEOUT` | yes |

Provider exception text, provider URLs, credentials, filesystem/database paths, stack traces and persistence diagnostics are internal and must not be copied into error responses. Fingerprints are included only when they have been safely established.

## 8. Safe diagnostics

Public diagnostic material is intentionally limited to:

- request fingerprints;
- v4 `IntakeModelMetadata` already defined by the application contract as descriptive/audit-only;
- v4 `ResearchContextFingerprint`;
- explicit bundle status/unresolved state;
- type/version/provenance markers already defined by v4.

Not public: provider health payloads, endpoint URLs, retry internals, API keys/tokens, local paths, DB IDs, persistence counts, worker/process state or debug stack traces.

## 9. Browser/CORS behavior

The base API does not emit permissive CORS headers. The preferred browser deployment for #143 is the accepted same-origin thin reverse proxy that forwards only published REST operations.

A deployment that intentionally enables direct cross-origin browser calls must apply an explicit origin allowlist at infrastructure/API deployment level. CORS policy must not introduce privileged/internal endpoints or browser-only semantic fields.

## 10. Contract-driven consumers

The checked-in OpenAPI/schema/examples are sufficient for #143 and #145 contract-level development. Their build/unit tests must not import backend Python or require a live CASE server.

The HTTP adapter in `tools/case_rest_api.py` is a transport implementation of this contract. It accepts an injected research service and validates its returned LegalResearchBundle. It deliberately does not synthesize a v4 bundle from the still-historical v3 #66 runtime.

## 11. Compatibility and deferred scope

Historical `tools/case_http.py` remains evidence for #66/v3 behavior and is not this public v4 contract.

Deferred beyond the current Go/No-Go milestone unless separately admitted: async jobs/tasks, pagination/resource-on-demand, production auth/authorization and broader multi-tenant security hardening.

Persistence refactors, legal reasoning, source acquisition and model/provider changes are outside #144.
