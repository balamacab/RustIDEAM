# Colombian Tax Data Agent — MVP

Local-first pipeline for building structured, traceable, versioned Colombian accounting and tax datasets from primary sources.

## Non-negotiable rule

The LLM is never the legal source.

Every extracted legal assertion must be traceable to primary-source evidence. Unknown or insufficiently supported facts remain explicitly unresolved and may enter human review.

## MVP scope

The first iteration implements only the persistence and provenance foundation required before any large-scale crawling:

1. canonical legal documents;
2. downloaded manifestations;
3. immutable SHA-256 source tracking;
4. text segments;
5. extracted claims;
6. exact evidence spans;
7. typed document/provision relationships;
8. temporal events;
9. human-review queue;
10. resumable processing jobs.

SQLite is the canonical operational store for the MVP. Parquet/JSONL exports will be derived artifacts.

## Directory layout

```text
col-taxdata/
├── README.md
├── docs/
│   └── DATA_MODEL.md
├── schema/
│   └── 001_initial.sql
└── tools/
    └── init_db.py
```

Runtime data is intentionally not committed to Git.

Planned runtime layout:

```text
data/
├── raw/sha256/
├── extracted/
├── normalized/
├── datasets/
├── cases/
└── state/taxdata.sqlite
```

## Current milestone

Milestone 0: freeze the initial data/provenance model and prove that SQLite can represent one real Colombian tax research case without losing source-level traceability.

No mass ingestion should begin before the first pilot case passes manual professional review.
