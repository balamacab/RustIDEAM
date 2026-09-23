# Corpus audit — 2026-09-22

## Scope

Read-only audit of the continuously crawled DIAN Normograma corpus in `data/state/taxdata.sqlite` and its immutable raw/extracted files.

The audit was executed as the runtime account `user` (UID 1000), except file-integrity checks that had to run inside the existing crawler container because the raw bind-mounted files are owned by root and mode 0600. That ownership condition is recorded as DEF-0006.

## Baseline metrics

- DIAN queue: 1,873 document done, 4 document error, 141 index done.
- Normograma sources: 1,985.
- Normograma manifestations: 1,982.
- Successful text extractions: 1,876.
- Distinct canonical documents referenced by Normograma manifestations: 1,547.
- Extracted segments at audit time: approximately 576k.
- Canonical provisions for Normograma documents: 36,800.
- Reference mentions: 170,098.
- Canonical relationships: 4,410, all currently marked validated.
- Temporal events: 1,528, all currently marked validated.
- Open review queue: 15,893.

## Integrity results

SQLite `PRAGMA quick_check` returned `ok`.

No orphan rows were found for:

- manifestation -> source;
- manifestation -> document;
- extraction -> manifestation;
- segment -> extraction;
- reference mention -> extraction/segment;
- reference resolution -> reference mention;
- provision -> document.

Raw evidence verification:

- 1,982 / 1,982 raw manifestation files present;
- 0 byte-size mismatches;
- 0 SHA-256 mismatches;
- approximately 0.225 GiB checked.

Normalized extraction verification:

- 1,876 / 1,876 extracted files present;
- 0 byte-size mismatches;
- 0 normalized SHA-256 mismatches;
- approximately 0.093 GiB checked.

**Conclusion:** primary evidence preservation and normalized-file integrity are healthy. Observed defects are in derived interpretation/identity/retrieval layers rather than evidence corruption.

## Document identity findings

404 manifestations had no `document_id`.

106 are index/navigation pages and are expected to have no legal document identity.

297 are completed legal-document queue items with successful extraction but no canonical identity:

- 189 DIAN `oficio_dian_*` pages;
- 3 `concepto_dian_*` pages;
- 83 `concepto_tributario_dian_*` pages;
- 11 other concepts (including aduanero/cambiario patterns);
- 9 Constitutional Court `c-*` decisions;
- 2 CONPES documents.

Additionally, 39 manifestations were linked to a clearly incompatible document type when the source filename is used as an independent identity signal. Examples:

- `c-621_2013.htm` -> `LEY 1450 DE 2011`;
- `c-833_2013.htm` -> `LEY 1607 DE 2012`;
- `concepto_aduanero_dian_0001465_2019.htm` -> `DECRETO 2685 DE 1999...`;
- `constitucion_politica_1991.htm` -> `RESOLUCIÓN 33933 DE 2025...`.

For 1,462 conventional Ley/Decreto/Resolución/Circular URLs whose number/year can be parsed deterministically from the URL, no number/year mismatch was found. The false-positive problem is concentrated in document families not yet safely handled by the identity registrar.

## Issuer collision finding

Canonical identity currently permits collisions between different issuers sharing type, number, and year.

Observed examples include:

- DIAN Resolución 1 de 2018 and Banco de la República Junta Directiva Resolución 1 de 2018;
- DIAN Resolución 7 de 2021 and Banco de la República Junta Directiva Resolución 7 de 2021;
- Circular 1 de 2019 from different issuers.

These manifestations can converge on one `document_id`.

## Provision coverage

Among identified normative documents:

- Decreto: 880 / 885 have at least one provision.
- Resolución: 428 / 432.
- Ley: 168 / 174.
- Circular: 0 / 6.

Notable structured documents:

- Decreto 1625 de 2016: 2,141 provisions.
- Decreto 624 de 1989 / Estatuto Tributario: 1,294 provisions.
- Decreto 1165 de 2019: 775 provisions.
- Resolución 227 de 2025: 774 provisions.

There are 15 identified Ley/Decreto/Resolución documents with zero registered provisions.

## Reference-resolution findings

Reference mention states:

- candidate: 148,411;
- resolved: 12,228;
- unresolved: 9,456;
- ambiguous: 3.

The large candidate count is **intentional under the current crawler design**: the crawler invokes `resolve_references.py --relations-only`, so non-relational mentions remain candidates until explicitly resolved.

Open `TARGET_DOCUMENT_NOT_FOUND` reviews correspond to 1,268 distinct canonical document keys:

- 675 Decretos;
- 332 Leyes;
- 259 Resoluciones;
- 1 Oficio;
- 1 Concepto.

This is primarily corpus-coverage debt, not evidence loss; see GAP-0001.

## Temporality findings

1,101 completed documents recorded a temporal-extraction warning.

Dominant failure modes:

- 495: expected exactly one publication date, found 0;
- 426: expected exactly one effective-on-publication rule, found 0;
- 143: expected exactly one issued date, found 0;
- 22: expected exactly one publication date, found 2;
- additional documents contain 3, 4, 8, 13, 34 or 40 publication-date matches;
- Decreto 1625 de 2016 contains 70 effective-on-publication matches and therefore fails the exact-one assumption.

Temporal-event coverage for canonical Normograma documents is incomplete; this is DEF-0004.

## Retrieval findings

FTS index cardinality matched the extracted-segment table and returned relevant evidence for audit queries including:

- cancelación RUT;
- liquidación RUT;
- fracción de año;
- artículo 595;
- Registro Único Tributario.

Within individual extractions, substantial repeated text exists:

- 3,496 duplicate text-hash groups for segments >= 100 characters;
- 6,860 extra duplicate rows;
- maximum observed repetition: 129 copies of the same text.

Some repetition is genuinely present in DIAN documents (for example repeated XML specification instructions). Raw/extracted evidence must remain intact; retrieval ranking should collapse or diversify equivalent text hashes. See DEF-0005.

## Crawler errors

Four document queue items were in error.

Three are source HTTP 404 responses.

`c-096_2001.htm` is not empty or corrupt. Its archived page contains approximately 35,593 visible legal-text characters and a complete Constitutional Court decision, but `extract_normograma_html.py` raises `detected legal body is unexpectedly short`. See DEF-0007.

## Overall assessment

The corpus is strong as an immutable evidence repository and usable for FTS retrieval, but derived legal identity and temporal state require correction before an LLM/MCP client should treat the canonical graph as authoritative.

Fix ordering:

1. DEF-0001 false document identity;
2. DEF-0002 issuer-aware canonical identity;
3. DEF-0003 additional document-family registration;
4. DEF-0004 temporal candidate model;
5. DEF-0007 legal-body boundary regression;
6. DEF-0005 retrieval deduplication;
7. DEF-0006 runtime ownership hardening.

After DEF-0001 through DEF-0004 are reprocessed, run a second corpus audit before evaluating new legal cases.
