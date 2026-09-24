---
id: DEF-0007
type: defect
status: verified
priority: P2
area: html-extraction
baseline: 2026-09-22-corpus-audit
---

# DEF-0007 — Valid Sentencia C-096/2001 is rejected as an unexpectedly short legal body

## Summary

`extract_normograma_html.py` rejects the DIAN Normograma page for Sentencia C-096/2001 with:

`RuntimeError: detected legal body is unexpectedly short`

The archived page actually contains a substantial, complete-looking Constitutional Court decision.

## Observed behavior

Source:

`https://normograma.dian.gov.co/dian/compilacion/docs/c-096_2001.htm`

Archived manifestation:

- byte size: 66,247;
- visible text measured during audit: approximately 35,593 characters;
- content includes `SENTENCIA C-096/01`, antecedentes, normas demandadas and substantive legal text.

The crawler retries the document but extraction fails in `find_legal_body()`.

## Evidence

`extract_normograma_html.py`:

- detects a legal heading;
- slices candidate body blocks;
- applies a minimum/body-shape guard;
- raises `detected legal body is unexpectedly short`.

The raw SHA-256 is intact, so the failure is parser logic rather than a broken download.

## Impact

- one valid jurisprudence source remains in crawler error state;
- its text is unavailable to canonical extraction/FTS/identity;
- repeated retries waste crawl work without changing outcome.

## Proposed solution

Make legal-body boundary detection structural rather than dependent on a brittle block-count/length assumption.

Recommended approach:

1. create a regression fixture from C-096/2001 raw HTML;
2. inspect the exact heading/end-boundary block sequence;
3. allow jurisprudence-specific body structure;
4. validate body using multiple signals:
   - recognized primary heading;
   - minimum normalized character count;
   - presence of expected legal sections/body blocks;
   - absence of navigation-only classification;
5. retain the short-body guard for genuinely malformed/navigation pages, but make thresholds family-aware.

If confidence remains insufficient, extraction should return a structured unresolved/parser-review result rather than retrying indefinitely as a network-like failure.

## Non-goals

- Do not disable short-body validation globally.
- Do not treat any large HTML page as a valid legal document.
- Do not rewrite the archived raw page.

## Reprocessing plan

After parser fix, re-run extraction for C-096/2001 and downstream identity/reference stages.

## Acceptance criteria

- C-096/2001 extracts successfully from the archived raw fixture;
- resulting text contains the primary sentence heading and substantive decision sections;
- navigation pages previously reclassified as indexes are not regressed into legal documents;
- malformed short legal pages still fail safely;
- crawler no longer keeps C-096/2001 in retry error for this parser reason.

## Regression tests

At minimum:
- C-096/2001 positive fixture;
- a normal Sentencia C fixture;
- a Normograma navigation/index page negative fixture;
- a deliberately truncated legal page negative fixture.

## Dependencies / ordering

Independent parser fix. Canonical jurisprudence identity still requires DEF-0003 after extraction succeeds.
