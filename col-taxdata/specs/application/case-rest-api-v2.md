# CASE public REST API v2

## Status and authority

Status: **authoritative public transport contract**

REST contract version: **2.0.0**

CASE application contract transported by this API: **5.0.0**

Driver: GitHub issue #285 under epic #130.

The machine-readable contract is `openapi/case-rest-api-v2.openapi.json`. Transport-only schemas are in `schemas/case-rest-api-v2.schema.json`; CASE domain objects are referenced from `case-contracts-v5.schema.json`.

REST v1 remains frozen and continues to transport CASE 4.0.0. A v4 bundle is never relabeled as v5.

## Version boundary

The public major version is encoded in `/v2`. `POST /v2/cases` returns only a semantically valid CASE 5.0.0 `LegalResearchBundle`. Unsupported REST paths or application contract versions fail explicitly; there is no version coercion or fallback.

The caller-owned request surface is intentionally unchanged from REST v1: `problem_text`, optional `as_of_date`, optional `client_reference`, and optional scalar `caller_metadata`. The adapter owns `kind="case_input"` and `contract_version="5.0.0"`. No files, provider controls, canonical identifiers, evidence bindings, source forcing or expected legal conclusions are accepted.

## Coverage-preserving success response

A success response has the same transport envelope shape as v1 but carries a complete v5 bundle:

```json
{
  "api_version": "2.0.0",
  "request_fingerprints": {
    "raw_request_sha256": "<sha256>",
    "case_input_sha256": "<sha256>"
  },
  "bundle": { "...": "LegalResearchBundle v5" }
}
```

The response preserves the canonical v5 research graph exactly, including:
- ResearchPlan aspects and tasks;
- ResearchResult trace, EvidenceSelection, AspectCoverage and OmittedWork;
- authority/evidence/unresolved typed references;
- research-context policy fingerprints;
- bundle status and per-aspect support/synthesis states.

HTTP 200 means the returned bundle is structurally and semantically valid. It does not mean an external legal interpretation has been performed. `requires_interpretive_synthesis` is a normal explicit handoff state and does not authorize write-back of consumer prose.

## Persistence/materialization boundary

Issue #285 persists v5 as immutable canonical JSON artifacts in a version-specific store and materializes the whole canonical bundle. v4 storage remains readable and unchanged. Persistence-engine layout does not redefine any application reference.

Internal model prose remains `intake_only`. Canonical authority/evidence and deterministic platform artifacts retain their existing ownership roles. External consumer inference is not a LegalResearchBundle field and is rejected by the closed v5 schema.

## Errors, fingerprints and diagnostics

REST v2 uses the same stable public error codes and retryability semantics as v1, with `api_version="2.0.0"`. Public errors never expose provider text, credentials, local paths, database details or stack traces.

`raw_request_sha256` hashes the exact request bytes. `case_input_sha256` hashes deterministic compact/sorted JSON of the validated v5 CaseInput. These are audit fingerprints, not legal-domain identity.

## Deferred scope

REST v2 does not add pagination/resource windows (#159), Web rendering, MCP transport, consumer synthesis, production authorization or a new graph-selection policy.
