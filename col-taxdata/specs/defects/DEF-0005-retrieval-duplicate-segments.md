---
id: DEF-0005
type: defect
status: specified
priority: P2
area: retrieval
baseline: 2026-09-22-corpus-audit
---

# DEF-0005 — Repeated equivalent segments bias FTS/RAG retrieval

## Summary

The corpus preserves repeated text exactly as it appears in DIAN source documents, which is correct for evidence preservation. However, retrieval currently exposes repeated equivalent segments independently, allowing one repeated phrase or block to dominate FTS/RAG results.

## Observed behavior

For segments of at least 100 characters, the audit found:

- 3,496 duplicate `text_sha256` groups within the same extraction;
- 6,860 duplicate extra rows;
- maximum observed repetition: 129 copies of the same text.

Examples include XML/reporting specification text repeated many times in older DIAN resolutions. Decreto 2229/2023 also contains exact duplicate regulatory/text blocks that appear multiple times in retrieval results.

## Evidence

Raw and normalized source hashes are valid. The duplicated text is therefore not evidence corruption.

FTS cardinality matches `extracted_segments`, so every preserved duplicate is independently searchable and can occupy multiple top-N result slots.

## Impact

- top-N retrieval diversity decreases;
- RAG context can waste tokens on equivalent evidence;
- repeated text can create an artificial relevance bias;
- legal research may miss a distinct relevant source because duplicate hits consume the result window.

## Proposed solution

Preserve all extracted segments, but add retrieval-time deduplication/diversification.

Recommended behavior:

1. search normally;
2. group exact equivalents by `text_sha256` within an extraction/document;
3. retain the highest-ranked representative;
4. expose duplicate count and alternate segment IDs as provenance metadata;
5. optionally apply diversity by canonical document/source after exact-text deduplication.

Do not physically delete duplicated segments from evidence storage.

Future semantic deduplication may be added separately, but exact SHA-based collapse is deterministic and should be implemented first.

## Non-goals

- Do not remove repeated raw/source content.
- Do not merge text across legally distinct documents solely because wording is identical.
- Do not hide alternate provenance when the same text appears in multiple documents.

## Reprocessing plan

No raw or extraction reprocessing is required for query-time deduplication.

If a materialized search table is introduced, build it as a derived index and keep source segment IDs.

## Acceptance criteria

- exact duplicate segment hashes from one extraction consume at most one normal top-N slot;
- retrieval response includes duplicate count/alternate provenance when applicable;
- FTS for `fraccion ano` returns distinct useful evidence before repeated copies;
- raw/extracted row counts and hashes are unchanged;
- deduplication is deterministic.

## Regression tests

Use a fixture with:
- one phrase repeated >10 times in one document;
- same phrase appearing once in a different document;
- distinct but similar text that must not be exact-deduplicated.

## Dependencies / ordering

Can be implemented independently, but validate after identity reprocessing because document-level diversity depends on correct identities.
