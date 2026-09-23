# DEF-0004 post-reprocessing audit — 2026-09-23

Issue: #4 — DEF-0004 temporality cardinality assumptions  
Implementation commit: `2828eb085ee09e82a99d221af0a92b56a1dfd691`  
Authoritative spec: `specs/defects/DEF-0004-temporality-cardinality-assumptions.md`

## Scope

This audit verifies the DEF-0004 implementation against the accumulated
`col-taxdata` corpus after migration 014 and deterministic reprocessing from
existing immutable raw/text-extraction evidence.

No evidence was redownloaded. The crawler was not stopped or restarted, and no
production container was replaced.

## Historical baseline

The 2026-09-22 corpus audit recorded 1,101 completed documents with temporal
cardinality warnings:

- publication count = 0: 495
- commencement count = 0: 426
- issued count = 0: 143
- multiple publication matches existed across the corpus
- Decreto 1625 de 2016 contained 70 commencement matches

The crawl queue continues to retain those historical warning records. DEF-0004
does not rewrite crawler history; it replaces the derived temporal model and
reprocesses canonical documents.

## Immediate pre-reprocessing runtime baseline

Read-only inspection immediately before DEF-0004 reprocessing found:

- manifestations: 1,983
- distinct canonical manifestation documents: 1,875
- canonical documents with a successful extraction: 1,875
- validated temporal events: 1,630
- documents with active processor-v2 temporal events: 475
- active processor-v2 temporal events: 1,425

Raw-evidence verification before reprocessing:

- registered manifestations: 1,983
- missing raw files: 0
- SHA-256 mismatches: 0
- aggregate registered digest:
  `84706e1681ac841e37dab37b4ec5167500c68f927e5ba09c130f73772f169ff4`
- aggregate actual-file digest:
  `84706e1681ac841e37dab37b4ec5167500c68f927e5ba09c130f73772f169ff4`

## Production-snapshot dry-run

A SQLite-consistent copy of the production database was created. Migration
`014_temporal_candidates.sql` was applied only to that copy before the first
full preview.

Command semantics:

```text
python3 tools/reprocess_temporality.py --db <snapshot>
```

Dry-run is the default; no `--apply` flag was supplied.

Result:

- canonical documents in scope: 1,875
- selected documents: 1,875
- processed documents: 1,875
- skipped: 0
- errors: 0
- persistent mutation: false

### Role coverage and ambiguity

| Role | Resolved | Unresolved | Ambiguous | Total |
| --- | ---: | ---: | ---: | ---: |
| publication_date | 1,113 | 757 | 5 | 1,875 |
| issued_date | 1,095 | 780 | 0 | 1,875 |
| commencement_rule | 656 | 1,211 | 8 | 1,875 |

This separates successful extraction coverage from unresolved and ambiguous
legal state instead of converting absence or multiplicity into failure.

### Expected dry-run delta

- temporal candidates inserted: 3,313
- exact candidate evidence rows inserted: 3,313
- temporal role resolutions inserted: 5,625
- review-queue items inserted: 2,761
- v3 temporal events inserted: 2,694
- event-evidence links inserted: 3,180
- v2 temporal events superseded: 1,425
- relationship temporal-basis rows deleted: 120
- relationship temporal-basis rows inserted/rebound: 4,395
- relationship dates cleared: 120
- relationship dates updated: 4,395
- document date rows updated: 961

Summary:

- inserts: 25,281
- updates: 6,901
- deletes: 120
- rebindings: 4,395

The registered raw-hash digest was unchanged by the dry-run.

## Isolated apply prediction check

The dry-run snapshot was then applied using the same decision path. The
resulting delta and per-role status counts matched the dry-run exactly.

A subsequent dry-run against the applied snapshot produced total delta 0.

This verifies:

- dry-run and apply execute the same decision logic;
- the operation is idempotent on the full real-corpus snapshot;
- no raw evidence hash changes are required.

## Decreto 1625 de 2016 regression

Real corpus identifiers:

- document:
  `DOC-953dfb6ed74256259a337297d3a03634`
- extraction:
  `EXT-cc8b66acb85f5ade902d6a390d8cbc1e`

Preview and applied snapshot result:

- publication: resolved, 1 candidate / 1 trusted candidate
- issued: resolved, 1 candidate / 1 trusted candidate
- commencement: ambiguous, 70 candidates / 55 trusted candidates
- promoted commencement candidate: none
- effective date: unresolved / null

All 70 commencement candidates were retained with 70 matching exact evidence
rows. Validated events are limited to:

- issued — 2016-10-11
- published — 2016-10-11

No `enters_into_force` event was guessed from the publication date.

## Actual production reprocessing

Migration `014_temporal_candidates.sql` was applied to production. Existing
migrations 001–013 were detected as already applied and were not modified.

Actual reprocessing result:

- canonical documents in scope: 1,875
- selected documents: 1,875
- processed documents: 1,875
- skipped: 0
- errors: 0

The actual delta matched the production-snapshot dry-run exactly, including all
insert/update/delete/rebinding counts above.

The post-apply role state exactly matched the dry-run:

| Role | Resolved | Unresolved | Ambiguous | Total |
| --- | ---: | ---: | ---: | ---: |
| publication_date | 1,113 | 757 | 5 | 1,875 |
| issued_date | 1,095 | 780 | 0 | 1,875 |
| commencement_rule | 656 | 1,211 | 8 | 1,875 |

Post-apply derived-state totals include:

- v3 temporal candidates: 3,313
- v3 temporal role resolutions: 5,625
- open temporal-resolution review items: 2,761
- v3 validated temporal events: 2,694
- superseded legacy temporal events: 1,425
- all validated temporal events after reprocessing: 2,899

An immediate production dry-run after apply processed all 1,875 documents with
0 errors, 0 skips, and total delta 0.

## Provenance and immutable raw evidence

Post-reprocessing physical verification:

- manifestations: 1,983
- missing raw files: 0
- SHA-256 mismatches: 0
- aggregate registered digest:
  `84706e1681ac841e37dab37b4ec5167500c68f927e5ba09c130f73772f169ff4`
- aggregate actual-file digest:
  `84706e1681ac841e37dab37b4ec5167500c68f927e5ba09c130f73772f169ff4`

The digest is identical to the immediate pre-reprocessing baseline.

Processor-v2 evidence was retained. Its 1,425 derived events were marked
`superseded`; evidence rows were not deleted. Relationship temporal bases
traceable to superseded v2 events were deterministically cleared/rebound only
where v3 validated events provide the replacement basis.

## Acceptance criteria

1. **PASS — zero document-level cardinality failures.** Full dry-run and actual
   reprocessing completed 1,875/1,875 documents with 0 processing errors.
2. **PASS — Decreto 1625 completes without guessing.** Seventy commencement
   candidates were retained; the role is ambiguous and no candidate/effective
   date was promoted.
3. **PASS — ambiguity is explicit and reviewable.** Per-role
   resolved/unresolved/ambiguous rows and 2,761 open temporal review items are
   persisted.
4. **PASS — uniquely structured evidence is deterministic.** Regression tests,
   snapshot dry-run/apply equality, and production idempotency verify the same
   structural decision path.
5. **PASS — temporal events retain segment evidence.** Candidate/event
   regression tests verify exact quote/span/segment linkage; the real Decreto
   1625 validation retained exact evidence for all 70 commencement candidates.
6. **PASS — post-reprocessing audit reports coverage and ambiguity separately.**
   This audit reports resolved, unresolved, and ambiguous counts independently
   for every temporal role.

## Remaining limitations

- An unresolved or ambiguous role remains unresolved; DEF-0004 intentionally
  does not add heuristic date guessing.
- A uniquely identified publication date does not establish effectiveness
  without a uniquely resolved explicit commencement rule.
- Historical crawler warning JSON is retained as operational history and is not
  rewritten by this defect fix.
- The running crawler was not restarted/replaced during this task. Future
  deployments should use the updated `main` image so newly crawled documents
  execute processor v3 directly.
