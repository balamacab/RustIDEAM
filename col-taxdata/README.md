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
10. resumable processing jobs;
11. auditable HTTP fetch history.

SQLite is the canonical operational store for the MVP. Parquet/JSONL exports will be derived artifacts.

## Directory layout

```text
col-taxdata/
├── README.md
├── config/
│   └── official_domains.json
├── docs/
│   └── DATA_MODEL.md
├── schema/
│   ├── 001_initial.sql
│   └── 002_fetches.sql
├── tools/
│   ├── init_db.py
│   └── fetch_source.py
└── cases/
    └── CASE-0001/
```

Runtime data is intentionally excluded from Git.

```text
data/
├── raw/
│   └── sha256/
├── extracted/
├── normalized/
├── datasets/
├── cases/
├── tmp/
└── state/
    └── taxdata.sqlite
```

## Initialize the database

Run from the `col-taxdata/` directory:

```bash
python3 tools/init_db.py
```

The initializer applies ordered SQL migrations once and records their SHA-256 in `schema_metadata`. If an already-applied migration changes on disk, initialization stops instead of silently accepting schema drift.

## First vertical slice: one official source

The first real source selected for CASE-0001 is DIAN's compiled Decreto 2229 de 2023 page.

After the database is initialized:

```bash
python3 tools/fetch_source.py \
  --source-id SRC-0004 \
  --url 'https://normograma.dian.gov.co/dian/compilacion/docs/decreto_2229_2023.htm' \
  --authority DIAN \
  --source-kind norma_compilada
```

Expected behavior:

- only HTTP/HTTPS is accepted;
- the source and every redirect must remain inside the official-domain allowlist;
- bytes are streamed to a temporary file;
- SHA-256 is calculated during download;
- the immutable original is stored as `data/raw/sha256/<prefix>/<sha256>.<ext>`;
- repeated identical content reuses the same manifestation identity;
- every HTTP attempt is recorded in `fetches`;
- no parsing, summarization or LLM processing occurs at this stage.

## Current milestone

Milestone 1: prove end-to-end preservation of one official primary source for CASE-0001, including URL, retrieval time, HTTP metadata, SHA-256, immutable raw bytes and SQLite provenance.

No mass ingestion should begin before this vertical slice is executed and inspected on the target server.
