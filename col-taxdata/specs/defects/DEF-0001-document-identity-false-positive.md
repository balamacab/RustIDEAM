---
id: DEF-0001
type: defect
status: verified
priority: P1
area: document-identity
baseline: 2026-09-22-corpus-audit
---

# DEF-0001 — Document identity can be taken from a cited norm instead of the source document

## Summary

For document families not safely recognized by the current identity registrar, the first extracted `document_heading` can belong to a norm quoted inside the page rather than to the page itself. The manifestation is then assigned the identity of that cited norm.

This creates false provenance: evidence from one legal document is attached to a different canonical document.

## Observed behavior

The 2026-09-22 audit found 39 Normograma manifestations whose source filename independently signals a document family incompatible with the canonical `document_type` assigned by the pipeline.

Examples:

- `c-621_2013.htm` -> `LEY 1450 DE 2011`;
- `c-833_2013.htm` -> `LEY 1607 DE 2012`;
- `concepto_aduanero_dian_0001465_2019.htm` -> `DECRETO 2685 DE 1999...`;
- `constitucion_politica_1991.htm` -> `RESOLUCIÓN 33933 DE 2025...`.

Several false assignments caused multiple unrelated Normograma URLs to converge on the same canonical `document_id`.

## Evidence

`register_document_identity.py`:

- selects a segment classified as `document_heading`;
- applies `DOCUMENT_HEADING_RE`;
- builds `canonical_key = CO:<type>:<number>:<year>`;
- has no independent validation that the heading agrees with the source URL/document family.

`register_simple_normative_act.py` follows the same identity pattern.

For 1,462 conventional Ley/Decreto/Resolución/Circular URLs where type/number/year can be parsed deterministically from the URL, the audit found zero number/year mismatches. False assignments are concentrated in source families for which the source-page identity is not currently represented by the generic heading parser.

## Impact

- incorrect canonical provenance;
- relationships may be promoted from the wrong source document;
- FTS hits can be attributed to the wrong legal instrument;
- MCP/LLM clients may cite a valid excerpt under an invalid document identity;
- reprocessing later may be difficult if false convergence is not explicitly detected.

## Root-cause hypothesis

Identity is currently inferred from content before establishing a trusted source-family identity constraint.

On pages such as jurisprudence, doctrine, constitutional texts, and concept pages, quoted legal instruments can appear in prominent heading-like blocks and match the generic normative heading regex.

## Proposed solution

Introduce a two-stage identity contract:

1. **Source-family classifier**
   - deterministically classify the Normograma URL/path first;
   - extract expected family and, when encoded in the URL, expected number/year;
   - supported families include normative act, DIAN doctrine, Constitutional Court decision, CONPES, Constitución, etc.

2. **Family-specific identity parser**
   - parse identity only with the parser registered for that family;
   - reject incompatible headings rather than falling back to a cited Ley/Decreto/Resolución;
   - validate content-derived identity against URL-derived constraints when available.

Store independent identity evidence from both:
- source URL/path;
- primary document heading/content.

If the two disagree, create a review item such as `SOURCE_IDENTITY_CONFLICT`; do not attach a canonical `document_id`.

## Non-goals

- Do not infer legal validity from filenames.
- Do not rewrite raw manifestations.
- Do not automatically choose between contradictory source/content identity signals.

## Reprocessing plan

After implementation:

1. clear/recompute derived identity for Normograma document manifestations;
2. rerun family-specific identity registration;
3. rerun provision registration, reference resolution and relationship promotion for affected documents;
4. close obsolete review items only after successful new identity assignment.

Raw files and raw SHA-256 values must remain unchanged.

## Acceptance criteria

- zero known filename-family/type incompatibilities among supported Normograma families;
- `constitucion_politica_1991.htm` cannot resolve to a Resolución;
- `c-621_2013.htm` cannot resolve to Ley 1450/2011;
- `c-833_2013.htm` cannot resolve to Ley 1607/2012;
- concept/oficio pages cannot resolve to a quoted Ley/Decreto unless the source itself is that norm;
- incompatible source/content identity creates an unresolved review item rather than a false canonical assignment;
- all previously correct conventional normative URLs remain stable.

## Regression tests

Fixture tests should include:

- `c-621_2013.htm`;
- `c-833_2013.htm`;
- `concepto_aduanero_dian_0001465_2019.htm`;
- `constitucion_politica_1991.htm`;
- one valid Ley;
- one valid Decreto;
- one valid Resolución.

## Dependencies / ordering

Implement before DEF-0003 and before mass reprocessing of relationships.
