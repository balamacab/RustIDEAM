---
id: DEF-0003
type: defect
status: implementing
priority: P1
area: document-identity
baseline: 2026-09-22-corpus-audit
---

# DEF-0003 — 297 legal documents are extracted but have no canonical document identity

## Summary

The crawler successfully downloads and extracts many legal-document families that the current registrars do not canonicalize. They remain searchable as raw/extracted text but cannot participate reliably in the canonical graph.

## Observed behavior

After excluding navigation/index pages, 297 completed legal documents had successful extraction but no `document_id`:

- 189 DIAN Oficios;
- 3 `concepto_dian_*` pages;
- 83 `concepto_tributario_dian_*` pages;
- 11 other concept pages, including aduanero/cambiario forms;
- 9 Constitutional Court `c-*` decisions;
- 2 CONPES documents.

The existing DIAN doctrine registrar canonicalized only 50 doctrine documents.

## Evidence

`register_dian_doctrine.py` requires a narrow full-title pattern and raises when exactly one expected DIAN concept title is not found.

Audit warning distribution included:

- 190 doctrine failures: `expected exactly one full DIAN concept title; found 0`;
- family-specific generic identity failures on concepts and jurisprudence;
- relationship promoters subsequently fail for these manifests because `source manifestation has no canonical document_id`.

## Impact

- doctrine/jurisprudence evidence cannot be represented as first-class canonical documents;
- outgoing relationships cannot be promoted from those sources;
- references to these documents cannot resolve consistently;
- MCP clients would see incomplete source metadata despite having the text.

## Proposed solution

Introduce a document-family registry and family-specific canonicalizers.

Initial supported families:

- `DIAN_CONCEPTO`
- `DIAN_OFICIO`
- `CORTE_CONSTITUCIONAL_SENTENCIA_C`
- `CONPES`
- `CONSTITUCION_POLITICA`

Each family defines:

- trusted URL patterns;
- allowed heading patterns;
- issuer;
- document type;
- number normalization;
- year/date extraction;
- canonical-key construction;
- optional family metadata.

Refactor `register_dian_doctrine.py` so an Oficio or older Concepto does not have to imitate the exact modern "full DIAN concept title" shape.

Family parsers must return candidate identity + evidence or explicit unresolved reason; they must not fall through to a generic normative-act identity.

## Non-goals

- Do not force every source into Ley/Decreto/Resolución.
- Do not require provision/article registration for doctrine documents.
- Do not infer missing numbers/dates without evidence.

## Reprocessing plan

Re-run identity registration for the 297 known manifests first, then all supported document-family manifests.

After identity assignment:

- rerun doctrine metadata extraction;
- rerun reference resolution;
- rerun relationship promotion;
- recompute audit counts.

## Acceptance criteria

- all 189 known Oficio pages receive an issuer-aware doctrine identity or an explicit unresolved reason;
- all 9 known `c-*` pages receive Constitutional Court decision identities or explicit unresolved reasons;
- both CONPES pages receive their own canonical identities;
- no newly supported family is misregistered as a quoted Ley/Decreto/Resolución;
- the number of completed legal-document manifests without identity is reduced to only documented unsupported/ambiguous cases;
- relationship promoters no longer fail solely because a supported source family lacks `document_id`.

## Regression tests

Include representative historic and modern:
- Oficio;
- Concepto tributario;
- Concepto aduanero;
- Concepto cambiario;
- Sentencia C;
- CONPES;
- Constitución page.

## Dependencies / ordering

Requires DEF-0001 family-safe identity behavior and should share issuer normalization from DEF-0002.
