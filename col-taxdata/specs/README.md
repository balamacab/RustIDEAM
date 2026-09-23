# col-taxdata specification-driven development

This directory is the authoritative planning layer for changes to `col-taxdata`.

The runtime database and crawler output describe what the system currently does. Specs describe what the system must do, why a change is required, how correctness will be measured, and which evidence justified the change.

## Principles

1. **Evidence before implementation.** A defect spec must include reproducible evidence from the corpus, database, source document, or code path.
2. **Primary evidence is immutable.** Fixes must never rewrite archived raw manifestations. Reprocessing creates or updates derived state only.
3. **No inferred legal truth.** Ambiguous identity, temporal state, or relationships remain unresolved rather than being guessed.
4. **Deterministic acceptance criteria.** Every spec defines machine-checkable acceptance criteria where possible.
5. **Reprocessing is explicit.** A fix must state which existing derived artifacts require replay and which tables/files are expected to change.
6. **Compatibility matters.** Database migrations are append-only and existing provenance must remain traceable.
7. **LLMs are not authorities.** LLMs may classify or propose candidates, but canonical legal identity and evidence remain deterministic/auditable.

## Layout

```text
specs/
├── README.md
├── audits/
│   └── YYYY-MM-DD-<audit>.md
├── defects/
│   ├── README.md
│   └── DEF-NNNN-<slug>.md
└── gaps/
    └── GAP-NNNN-<slug>.md
```

## Defect lifecycle

`observed -> specified -> implementing -> verified -> closed`

A defect is **verified** only after:

- the regression test passes;
- affected existing corpus data has been reprocessed;
- post-reprocessing audit metrics satisfy the acceptance criteria;
- raw SHA-256 evidence remains unchanged.

## Required defect sections

Each `DEF-NNNN` spec contains:

- Summary
- Observed behavior
- Evidence
- Impact
- Root-cause hypothesis
- Proposed solution
- Non-goals
- Reprocessing plan
- Acceptance criteria
- Regression tests
- Dependencies / ordering

## Prioritization

- **P0** — corrupts primary evidence or makes provenance unreliable.
- **P1** — can produce materially wrong legal identity, state, or retrieval.
- **P2** — materially reduces coverage or quality but evidence remains recoverable.
- **P3** — operational/efficiency issue without loss of legal correctness.

The corpus audit dated 2026-09-22 is the baseline for the first defect set.
