---
id: DEF-0002
type: defect
status: specified
priority: P1
area: canonical-identity
baseline: 2026-09-22-corpus-audit
---

# DEF-0002 — Canonical keys can merge different issuers with the same type/number/year

## Summary

The generic canonical key is currently:

`CO:<document_type>:<number>:<year>`

It omits the issuing authority. Different legal instruments with identical type, number and year can therefore collapse into one `document_id`.

## Observed behavior

The audit found real collisions, including:

- DIAN Resolución 1 de 2018 and Banco de la República Junta Directiva Resolución 1 de 2018;
- DIAN Resolución 7 de 2021 and Banco de la República Junta Directiva Resolución 7 de 2021;
- Circular 1 de 2019 from different issuers.

The manifestations were associated with the same canonical document identity.

## Evidence

`register_document_identity.py` line of behavior:

`canonical_key = f"CO:{doc_type}:{number}:{year}"`

`register_simple_normative_act.py` uses the same shape.

The generic `document_identifiers` insert currently stores `issuer = NULL` for the canonical key.

## Impact

- two legally distinct instruments can be merged;
- provisions from separate issuers can share a canonical namespace;
- references can resolve to the wrong authority;
- provenance remains technically traceable to manifests but the canonical graph becomes legally ambiguous.

## Proposed solution

Make issuer part of canonical identity for document families where type/number/year is not globally unique.

Recommended canonical form:

`CO:<issuer_key>:<document_type>:<number>:<year>`

Examples:

- `CO:DIAN:RESOLUCION:1:2018`
- `CO:BANREP_JD:RESOLUCION:1:2018`

Requirements:

1. define a normalized issuer registry/key vocabulary;
2. extract issuer from trusted URL family and/or heading metadata;
3. persist issuer explicitly on identifiers;
4. generate `document_id` from the issuer-aware canonical key;
5. preserve legacy aliases as non-primary identifiers when useful;
6. detect legacy collisions before migration and split them deterministically.

For nationally unique instrument families where issuer is intrinsic to the type, the normalized issuer may still be stored explicitly for consistency.

## Non-goals

- Do not use free-form issuer display names in deterministic IDs.
- Do not silently retain a merged legacy document after a confirmed collision.

## Reprocessing plan

1. introduce issuer normalization/migration support;
2. identify canonical keys currently representing more than one issuer;
3. create new issuer-aware document identities;
4. rebind manifestations and derived provision/evidence relationships;
5. rerun reference resolution and relationship promotion;
6. retain migration provenance from legacy document IDs.

## Acceptance criteria

- no two distinct normalized issuers share one canonical document for the same type/number/year;
- the two observed Resolución 1/2018 sources resolve to different `document_id` values;
- the two observed Resolución 7/2021 sources resolve to different `document_id` values;
- canonical identity remains deterministic across repeated processing;
- migration does not alter raw or normalized source hashes;
- references with explicit issuer resolve to the correct issuer-specific document;
- references without enough issuer information remain ambiguous instead of guessing.

## Regression tests

Create fixtures for:
- DIAN vs Banco de la República same-number resolutions;
- same-number circulars from different issuers;
- a normal DIAN resolution;
- a document reference lacking issuer where more than one target exists.

## Dependencies / ordering

Coordinate with DEF-0001 source-family classification. Implement before full corpus identity reprocessing.
