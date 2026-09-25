# Colombian Tax Data Agent — MVP

`col-taxdata` is a local-first pipeline for building structured, traceable and versioned Colombian tax/accounting legal data from primary official sources.

The project is primarily **legal knowledge/data infrastructure**, not an LLM application. It preserves source evidence first, then derives canonical document/provision identity, references, relationships, temporal evidence, retrieval indexes and case-analysis material.

## Non-negotiable rule

The LLM is never the legal source or canonical authority.

Every validated legal assertion must remain traceable to primary-source evidence. Unknown, conflicting or insufficiently supported identity, relationships and temporal state remain explicitly unresolved/reviewable rather than being guessed.

## Current MVP state

The project has moved beyond its original single-source vertical slice:

- DIAN Normograma acquisition/crawl state is implemented.
- Raw manifestations are SHA-256 registered and stored content-addressed.
- Versioned text extraction and extracted segments are implemented.
- SQLite FTS5 indexes extracted segments for retrieval.
- Canonical document identity is source-family validated and issuer-aware where required.
- Additional DIAN doctrine, Constitutional Court Sentencia C, CONPES and Constitución families are supported by family-specific identity logic.
- Canonical provisions and manifestation-specific provision observations are represented.
- Reference mentions, reference resolutions, explicit relation mentions and provenance-backed relationships are represented.
- DEF-0004's temporal candidate/resolution/event model is implemented; ambiguous/missing temporal evidence remains unresolved rather than causing exact-one failures.
- CASE-0001 demonstrates registered case claims/evidence and reproducible source/report materialization from canonical SQLite state.\n- The v3 Case Application Service now accepts natural-language case input through `tools/analyze_case.py`, uses a provider-neutral structured LLM boundary for candidate state, and keeps retrieval/evidence promotion deterministic.

The 2026-09-22 corpus audit remains a **historical baseline**, not a statement that all of its defect counts are still current. DEF-0001 through DEF-0004 are now verified. Other specified defects/gaps remain separate work.

SQLite is the authoritative operational store for the MVP. Runtime corpus data is intentionally excluded from Git.

## External HTTP CaseInput endpoint

The supported v3 CASE application can also be invoked without a host input file. The HTTP process is a thin transport over the same `case_application.analyze_case` orchestrator used by `tools/analyze_case.py`:

```bash
python3 tools/case_http.py \
  --host 127.0.0.1 \
  --port 8765 \
  --config config/llm/local-platform.yaml
```

Submit only client-owned input fields to `POST /v1/cases`:

```bash
curl --fail-with-body -sS \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8765/v1/cases \
  --data-binary '{"problem_text":"Una sociedad colombiana consulta el tratamiento tributario de un servicio.","as_of_date":"2026-09-24","client_reference":"matter-123"}'
```

`problem_text` and `as_of_date` are required by the HTTP contract; `client_reference` is optional. The caller cannot set model/backend selection, contract metadata, CASE/corpus IDs, source hints, evidence bindings, or expected conclusions. Model/backend choice remains server configuration through the existing LLM profile (and its supported environment overrides). HTTP host/port, database path and case-root are likewise process configuration; `--dry-run` uses the normal non-mutating CASE preview path.

Successful responses include the normal deterministic `CASE-<hash>`, the v3 CaseResult, persistence summary, and two audit fingerprints: SHA-256 of the exact raw request bytes and SHA-256 of the canonical server-constructed CaseInput. The server also emits those fingerprints in a structured audit event without logging `problem_text`. Errors remain JSON and distinguish invalid input, provider timeout/unavailability, malformed structured output, context/output limits, and CASE persistence/materialization/validation failures.

The server defaults to loopback. A deployment that binds it to another interface is responsible for its surrounding network/authentication controls; those controls are not encoded in CaseInput.

## Architecture and specifications

Start with:

- [`specs/architecture/overview.md`](specs/architecture/overview.md) — current architecture and current-vs-deferred boundary.
- [`specs/architecture/domain-model.md`](specs/architecture/domain-model.md) — authoritative domain concepts and invariants.
- [`specs/architecture/data-lifecycle.md`](specs/architecture/data-lifecycle.md) — immutable evidence and reprocessing lifecycle.
- [`specs/architecture/glossary.md`](specs/architecture/glossary.md) — project terminology.
- [`specs/architecture/identifier-semantics.md`](specs/architecture/identifier-semantics.md) — stable/domain/processing identifier semantics.
- [`specs/architecture/adr/`](specs/architecture/adr/) — durable architectural decisions.
- [`specs/README.md`](specs/README.md) — specification-driven development workflow.
- [`specs/manifest.yaml`](specs/manifest.yaml) — tracked defect/gap state.
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — older implementation-oriented data-model notes; architecture specs above are authoritative for cross-cutting semantics.

Documentation roles:

```text
README     = current project orientation / operational entry point
specs      = authoritative behavioral contracts
audits     = measured state at a point in time
ADRs       = durable architectural decisions and trade-offs
```

## High-level data flow

```text
official source
  -> discovery / fetch
  -> immutable raw manifestation + SHA-256
  -> versioned extraction / segments
  -> source-family classification / canonical identity
  -> provisions / references / resolutions / relationships
  -> temporal candidates / events
  -> FTS retrieval
  -> case analysis
  -> future MCP / RAG / LLM consumer
```

Raw evidence is immutable. Derived state may be rebuilt from preserved evidence under deterministic, auditable rules.

## Directory layout

The active project contains, among other paths:

```text
col-taxdata/
├── README.md
├── config/
│   ├── official_domains.json
│   └── pipelines/
├── docs/
│   └── DATA_MODEL.md
├── schema/
│   └── 001_...sql through current append-only migrations
├── specs/
│   ├── architecture/
│   ├── audits/
│   ├── defects/
│   ├── gaps/
│   └── manifest.yaml
├── tools/
├── tests/
└── cases/
    └── CASE-0001/
```

Runtime data is excluded from Git:

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

## Initialize or migrate the database

Run from `col-taxdata/`:

```bash
python3 tools/init_db.py
```

The initializer applies ordered SQL migrations once and records each migration SHA-256 in `schema_metadata`. If an already-applied migration changes on disk, initialization stops rather than silently accepting schema drift.

## Corpus doctor / invariant validator

Run routine read-only validation from `col-taxdata/`:

```bash
python3 tools/doctor.py
```

The default quick mode checks structural/database invariants without hashing every corpus file. Use full mode for complete registered raw and normalized/extracted artifact SHA-256 verification:

```bash
python3 tools/doctor.py --full
```

Machine-readable output and focused invariant families are available without changing validation semantics:

```bash
python3 tools/doctor.py --format json
python3 tools/doctor.py --scope provenance --scope identity
```

The doctor opens SQLite in read-only/query-only mode and has no repair path. Stable check IDs are grouped by invariant family; each result is `PASS`, `WARN`, `INFO`, or `ERROR`. Exit status is `0` when no ERROR exists, `1` when one or more invariant checks report ERROR, and `2` when the validator itself cannot execute safely. Full hashing is intentionally explicit because it can be expensive on a large corpus.

## Evidence preservation

`tools/fetch_source.py`:

- accepts only HTTP/HTTPS sources inside the official-domain allowlist;
- validates redirects against the allowlist;
- streams bytes while calculating SHA-256;
- stores immutable raw bytes below `data/raw/sha256/`;
- registers a source-specific Manifestation;
- records HTTP attempts in `fetches`;
- performs no legal parsing during fetch.

Repeated same-source/same-byte content reuses Manifestation identity. A later parser change creates/rebuilds derived state; it does not rewrite the raw manifestation.

## Specification-driven changes

Changes affecting legal identity, provenance, temporal state, extraction, retrieval, relationships or corpus coverage are issue/spec driven under [`specs/`](specs/README.md).

Key invariants include:

- raw evidence and raw SHA-256 are immutable/traceable;
- a Source/Manifestation is not automatically a canonical Document;
- a cited norm is not the identity of the citing document;
- same type/number/year from different issuers may be distinct Documents;
- ambiguity remains unresolved instead of guessed;
- absence of evidence is not legal truth;
- derived state can be rebuilt from immutable evidence;
- LLM output is not canonical legal authority.

## Deferred architecture

These are **not current implementation**:

- Ports and Adapters / persistence decoupling — GitHub issue #10;
- complete code/config/runtime execution-provenance manifests — issue #11;
- PostgreSQL/Redis persistence adapters;
- a graph database;
- an MCP/RAG layer with authority to overwrite canonical/evidence state.

Future work must preserve the domain and provenance contracts documented in `specs/architecture/`.
