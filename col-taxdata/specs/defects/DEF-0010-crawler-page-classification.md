---
id: DEF-0010
type: defect
status: verified
area: crawl-page-classification
---

# DEF-0010 — Do not conceal legal extraction failures as crawler indexes

Status: **verified**  
GitHub issue: [#20](https://github.com/balamacab/RustIDEAM/issues/20)  
Priority: **unspecified by the authoritative issue**

## Problem and historical evidence

The post-P1 audit found Sentencia C-096/2001 in the crawler queue as `index/done`, with 15 attempts, a registered raw manifestation and **no extraction or canonical document ID**. The earlier document-heading failure had become invisible to document-error monitoring. The former `process_document()` fallback treated `legal document heading was not detected` as sufficient reason to reclassify a candidate as a successful navigation index; later index processing could overwrite the trace. This is separate from DEF-0007's legal-body parser boundary.

## Verified classification invariant

A missing legal heading is **not** positive navigation evidence. Classification must be deterministic, explicit, durable and reviewable. The persisted `dian_crawl_queue.classification_state` distinguishes:

- `unclassified`: existing/unevaluated state, **not** confirmation of a navigation page;
- `confirmed_index`: positive structural navigation evidence;
- `legal_document`: successfully extracted legal document;
- `legal_extraction_failure`: known legal source whose legal extraction failed;
- `ambiguous`: insufficient evidence for either classification.

A known legal source family must not be silently promoted to navigation merely because heading extraction failed. Unknown sources can be confirmed as navigation only with the implementation's positive internal-link structure and absence-of-legal-cue criteria. Legal-looking but inconclusive pages remain ambiguous/reviewable. URL/source-family routing constrains classification; it never creates canonical legal identity.

## Implementation and observability

- `tools/crawl_page_classification.py` supplies deterministic heading-failure classification and structured reason/evidence fields.
- `tools/crawl_dian_normograma.py` records durable classification and distinguishes meaningful legal/classification failures from confirmed indexes. Its status view also exposes suspicious legacy document-route `index/done` rows lacking extraction as review candidates; queue success alone cannot erase that obligation.
- Append-only migration `schema/015_crawl_page_classification.sql` adds `classification_state`, `classification_json` and an index. Existing rows default to `unclassified`; migration does **not** bulk-reclassify them.
- `tools/reclassify_crawl_queue.py` previews deterministic before/after queue changes by default. Only explicit `--apply` mutates derived queue classification. It preserves immutable raw evidence, retains confirmed indexes, and supports idempotent reevaluation. Missing/unreadable raw evidence is a conflict, not permission to guess.
- Unresolved legal/ambiguous candidates remain observable as errors/reviewable rather than being counted as successful document processing.

## Regression and acceptance evidence

`tests/test_def0010_crawl_classification.py` covers the C-096-derived known legal candidate, genuine navigation, truncated legal pages, ambiguous legal-looking pages, legacy status visibility, preview/apply/idempotency, migration upgrade and raw preservation. Issue #20's completion log records eight passing targeted regressions, the full 118-test suite passing, and successful post-merge convergence of PR #35. Isolated fixture preview performed zero mutations; the first explicit apply changed one legacy candidate, and repeat apply changed zero rows.

DEF-0007 extraction/body-boundary logic remains independent. The historical C-096 queue state is evidence of the defect, **not** a claim that production reclassification was applied during issue #20. No raw manifestation, registered SHA-256 or original audit is rewritten.

## Scope and sources

This specification reconciles the **already verified** issue #20 contract, not a crawler redesign or a request to operate on the production queue. Sources: closed [issue #20](https://github.com/balamacab/RustIDEAM/issues/20), [post-P1 audit](../audits/2026-09-23-post-p1-corpus-audit.md), [data lifecycle](../architecture/data-lifecycle.md), `tools/crawl_page_classification.py`, `tools/crawl_dian_normograma.py`, `tools/reclassify_crawl_queue.py`, `schema/015_crawl_page_classification.sql`, and `tests/test_def0010_crawl_classification.py`.
