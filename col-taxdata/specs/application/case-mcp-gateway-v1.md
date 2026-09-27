# CASE MCP legal-research gateway v1

## Status and authority

Status: **implemented external-adapter contract**

Gateway contract version: **1.0.0**

Semantic dependency: CASE public REST **1.0.0**, transporting CASE application contract **4.0.0**.

Driver: GitHub issue #145 under epic #130.

This contract defines the independent MCP boundary for external LLM/agent consumers. It does not redefine canonical CASE/domain objects. The authoritative legal/research payload remains the LegalResearchBundle transported by the public REST contract.

## 1. Dependency direction

```text
external MCP consumer
        ↓
col-taxdata-mcp
        ↓ HTTP/JSON only
CASE REST v1 (#144)
        ↓
CASE application / canonical research
```

The MCP gateway must not import backend Python, open SQLite, inspect CASE/corpus storage, mount backend source/storage, or call an intake/inference provider. A backend implementation change that preserves REST v1 must not require a gateway semantic change.

## 2. Originating consumer responsibility

The originating LLM/agent owns extraction from files available in its environment. For PDFs, images, spreadsheets, email, or other artifacts it must:

1. inspect/process the artifacts with its own capabilities;
2. extract the facts/questions relevant to the legal matter;
3. submit a self-contained textual `problem_text` and normal scalar metadata.

The gateway accepts no binary file, local filesystem path, arbitrary document URL, OCR job/payload, or attachment persistence request.

External consumer synthesis/inference/final prose is consumer-owned. The gateway exposes no operation that promotes that prose into canonical evidence, rules, evaluations, calculations, identity, provenance, or unresolved state.

## 3. Tool surface

Exactly seven semantic tools are exposed:

| Tool | Semantics |
| --- | --- |
| `research_case` | Submit `problem_text`, optional `as_of_date`, `client_reference`, and scalar `caller_metadata` through REST `POST /v1/cases`; return the exact LegalResearchBundle plus an ephemeral handle. |
| `get_case_research` | Re-read the exact cached REST bundle by ephemeral handle. |
| `get_authority` | Return one existing CanonicalAuthority plus referenced official sources/evidence/relationships/unresolved items already in the bundle. |
| `get_provision` | Return only existing provision refs and matching authority/evidence objects. REST v1 has no standalone Provision transport object, so the gateway must not infer one. |
| `get_evidence` | Return one exact EvidenceSpan plus its existing authority and OfficialSource. |
| `get_normative_relationships` | Filter NormativeRelationship objects already present in the bundle. |
| `get_calculation` | Return one CalculationTrace plus existing linked deterministic evaluations/rules/evidence. |

There is no generic raw-HTTP/URL-fetch tool, provider-selection tool, storage tool, canonical write tool, prompt surface, or MCP resource surface.

## 4. Ephemeral bundle handles

A successful research call is cached in bounded process memory for follow-up semantic projections. The gateway handle is deterministically derived from the REST API version, REST `case_input_sha256`, and canonical bundle ref.

`mcpbundle:<sha256>` is:

- gateway-local;
- ephemeral;
- noncanonical;
- nonpersistent;
- not a legal-document/evidence/provenance identifier.

Eviction or process restart may make a handle unavailable. The consumer can repeat `research_case` when it needs a fresh handle.

## 5. Citation and authority discipline

The gateway passes through REST bundle data; it must never:

- repair or paraphrase `EvidenceSpan.exact_text`;
- manufacture evidence/span/provision/document/authority/source/provenance refs;
- infer a missing article number or legal identity;
- convert search similarity into legal authority;
- hide unresolved/ambiguous/conflict state;
- mutate source/text SHA-256 identities;
- turn consumer-generated inference into canonical CASE material.

Follow-up views are projections only. They must be reconstructible from the cached REST bundle without external lookup or hidden backend access.

## 6. REST validation and error mapping

The REST client is fixed to configured `CASE_REST_BASE_URL + /v1/cases`. A tool cannot change the upstream base URL.

Success validation requires:

- exact REST version `1.0.0`;
- closed success envelope;
- both SHA-256 request fingerprints;
- LegalResearchBundle v4 identity/status and closed required top-level shape;
- exact preservation of caller-owned CaseInput fields.

Public REST errors map to stable MCP codes. Upstream public error codes may be retained as identifiers, but arbitrary exception strings, provider URLs/details, credentials, local paths, stack traces, and storage diagnostics must not cross the MCP boundary.

Request and response bodies are byte-bounded. HTTP timeout is bounded.

## 7. Deployment contract

The independent image is built only from `col-taxdata/mcp_gateway/`.

Runtime requirements:

- CASE REST base URL configured by environment;
- MCP listen host configured by environment (no hardcoded host/IP);
- independent process/container lifecycle;
- Streamable HTTP deployment transport;
- `/healthz` and `/readyz` non-secret-bearing endpoints;
- no backend/corpus/SQLite mounts;
- no provider credentials;
- no direct OpenAI/Google/Anthropic/llama.cpp or other inference traffic.

The pinned MCP SDK is an adapter/runtime dependency only. It is not a legal authority or semantic source.

## 8. Contract-driven tests

Contract-level tests use #144's checked-in complete/partial/unresolved/error fixtures. They must run without a live CASE backend and without importing backend Python into the gateway.

Validation additionally covers the gateway against the real repository CASE REST server implementation, proving the same HTTP-only client works without a privileged path.

The image build executes an installed-SDK MCP smoke that proves:

- server construction succeeds independently;
- tool discovery exposes exactly the seven intended tools;
- a semantic tool call returns structured output;
- no prompts/resources create an alternate surface.

## 9. Deferred scope

For the current Go/No-Go milestone, synchronous request/response and a bounded ephemeral bundle cache are intentional.

Deferred unless separately admitted:

- durable async task/job orchestration;
- large-bundle pagination/resource-on-demand context optimization;
- production authentication/authorization and multi-tenant isolation;
- broader production security hardening.

These deferrals do not weaken the authority/citation boundary above.
