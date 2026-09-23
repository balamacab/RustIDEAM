# ADR-0006 — Canonical document identity is issuer-aware where required

## Status

Accepted and implemented by DEF-0002.

## Context

Type + number + year is not globally unique. The corpus observed real collisions such as resolutions with the same number/year from DIAN and Banco de la República.

A canonical identity that omits issuer can merge legally distinct instruments and contaminate provisions, references and provenance.

## Decision

Canonical identity includes a normalized issuer key for document types where type/number/year is not sufficient.

The current generic shape is:

```text
CO:<issuer_key>:<document_type>:<number>:<year>
```

for issuer-scoped types. Families where issuer is intrinsic to the supported national instrument type can retain the established non-qualified key; family-specific official documents can define their own deterministic canonical form.

Issuer evidence must come from trusted source-family/content constraints. If issuer cannot be resolved sufficiently, identity/reference resolution remains unresolved rather than guessing.

## Alternatives considered

A globally issuer-blind `CO:<type>:<number>:<year>` key was the previous behavior and was rejected by DEF-0002 because it produced real collisions.

## Consequences / trade-offs

- Legacy collisions required deterministic identity migration/rebinding with provenance.
- References that omit issuer can remain ambiguous when multiple targets exist.
- Issuer vocabulary is normalized rather than using arbitrary display strings in IDs.
- Backend migrations must preserve the same canonical identity semantics.

## Related specs/issues

- DEF-0002.
- DEF-0001 source-family validation.
- `schema/013_issuer_aware_identity.sql`.
