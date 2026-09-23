---
id: DEF-0004
type: defect
status: specified
priority: P1
area: temporality
baseline: 2026-09-22-corpus-audit
---

# DEF-0004 — Temporal extractor aborts when evidence cardinality is not exactly one

## Summary

`extract_document_temporality.py` requires exactly one publication date, exactly one issued date, and exactly one effective-on-publication rule. Real compiled legal documents frequently contain zero or multiple matching historical/editorial references, causing the entire temporal stage to abort.

## Observed behavior

1,101 completed documents produced temporal-extraction warnings.

Dominant failures:

- 495 publication date matches = 0;
- 426 effective-on-publication matches = 0;
- 143 issued date matches = 0;
- 22 publication date matches = 2;
- other pages contain 3, 4, 8, 13, 34 or 40 publication-date matches;
- Decreto 1625 de 2016 contains 70 effective-on-publication matches.

Temporal coverage is therefore materially incomplete.

## Evidence

Current code explicitly performs:

- `if len(publication_matches) != 1: raise RuntimeError(...)`
- `if len(issued_matches) != 1: raise RuntimeError(...)`
- `if len(effective_matches) != 1: raise RuntimeError(...)`

Only after those checks does it create evidence and validated temporal events.

## Impact

- documents with otherwise usable temporal evidence get no structured dates;
- compiled documents are disproportionately affected;
- legal-state queries "as of date" cannot safely rely on current temporal coverage;
- downstream relationship dates can remain incomplete.

## Proposed solution

Replace exact-one extraction with an evidence-candidate model.

For each temporal role:

1. collect all candidate spans with provenance;
2. classify candidate context:
   - primary document heading/date;
   - publication metadata;
   - commencement clause;
   - editorial note/history;
   - quoted/cited norm;
3. score only deterministic structural evidence;
4. automatically validate only when one candidate is uniquely supported by trusted structure;
5. persist zero/multiple candidates as unresolved/ambiguous review state rather than raising;
6. keep every candidate and evidence span for auditability.

A document may legitimately have:
- issued date but no known publication date;
- publication date but a commencement rule other than publication;
- multiple historical publication references in editorial notes.

Do not derive repeal/effectiveness from chronology alone.

## Data-model direction

Prefer explicit candidate/evidence storage rather than overloading one date column.

If a schema change is required, add append-only tables/columns through a migration. Existing validated events must remain traceable to the extraction version that created them.

## Non-goals

- Do not select the earliest/latest date merely because multiple dates exist.
- Do not assume publication date equals effective date without an explicit rule.
- Do not treat absence of a match as an extraction exception.

## Reprocessing plan

Re-run temporal extraction across all canonical documents using a new extractor version.

Preserve prior events/provenance or explicitly supersede them according to the temporal-event versioning strategy.

## Acceptance criteria

- zero document-level failures solely because a temporal candidate count is 0 or >1;
- Decreto 1625/2016 completes temporal extraction without selecting one of 70 commencement references as the document-level rule by guess;
- ambiguous candidates remain explicitly unresolved/reviewable;
- uniquely structured publication/issued/commencement evidence is still promoted deterministically;
- all generated events retain exact segment evidence;
- post-reprocessing audit reports coverage and ambiguity separately.

## Regression tests

Fixtures:
- zero publication date;
- exactly one publication date;
- two publication dates;
- one issued date + multiple quoted dates;
- no commencement clause;
- multiple commencement clauses;
- Decreto 1625-like compiled document.

## Dependencies / ordering

Independent of crawler download. Reprocess after document identity fixes so events attach to correct canonical documents.
