# Post-P1 corpus audit — 2026-09-23

## Status

Read-only audit completed against the current production corpus after DEF-0001 through DEF-0004.

Execution snapshot:

- local date/time: 2026-09-23 20:23:44 -05:00;
- UTC: 2026-09-24T01:23:44+00:00;
- repository: `balamacab/RustIDEAM`;
- branch: `main`;
- repository base observed at audit start and immediately before this report: `71b931c29859324fd87d5e1af18ed9f8871e1a3d`;
- production host: `morichalserver`;
- production SQLite: `/home/user/col-taxdata/data/state/taxdata.sqlite`;
- deployed audit image: `sha256:e98f22055f5ee90d8a516485f5a268fc86c72c847b31a57897778c1d2750b887`.

This document is a new point-in-time measurement. It does **not** rewrite or supersede the historical
`2026-09-22-corpus-audit.md`.

## Scope and method

The audit follows the current architecture/domain contracts rather than the historical implementation assumptions:

- SQLite is the authoritative MVP operational store.
- Source, Manifestation, canonical Document and extracted/derived state are distinct.
- issuer-scoped identity is evaluated with the DEF-0002 model;
- DIAN Oficio pages may legitimately refine to a `CONCEPTO` document when current DEF-0003 family rules accept a matching Concepto heading;
- temporal state is measured as candidate -> role resolution -> promoted event under DEF-0004, with zero/multiple evidence represented as unresolved/ambiguous rather than parser failure;
- raw evidence remains immutable and is verified from registered byte size/SHA-256;
- unresolved references and coverage gaps are reported as unresolved state, not converted into inferred legal truth.

Production database access was read-only:

- SQLite was opened with URI `mode=ro`;
- `PRAGMA query_only=ON` was enabled;
- the final metric pass used an explicit read transaction to keep the database view consistent;
- all SQL was SELECT/PRAGMA validation only;
- raw and normalized artifacts were opened only for byte-size/SHA-256 verification;
- no crawler state, canonical identity, references, relationships, temporal state, case state, raw bytes or normalized bytes were mutated.

The Docker data bind used normal runtime permissions because DEF-0006 still prevents the host `user` from reading all evidence directly. The audit process itself nevertheless opened SQLite read-only and performed file reads only.

## Executive result

The post-P1 corpus is structurally healthy at the database, migration, raw-evidence and provenance layers:

- SQLite quick check: **ok**;
- foreign-key violations: **0**;
- applied migrations: **14/14**, with **0** missing, extra or SHA-256-mismatched migrations;
- raw manifestations physically verified: **1,984/1,984**, with **0** missing, **0** size mismatches and **0** SHA-256 mismatches;
- normalized extraction artifacts physically verified: **1,878/1,878**, with **0** missing, **0** size mismatches and **0** SHA-256 mismatches;
- evidence SHA values inconsistent with their registered Manifestation: **0**;
- relationships lacking required provenance: **0**;
- relationships lacking evidence: **0**;
- temporal candidates lacking evidence: **0**;
- temporal events lacking evidence: **0**.

DEF-0001 through DEF-0004 have materially changed the corpus from the 2026-09-22 baseline without violating the raw-evidence contract. The most visible effects are:

- Manifestations without canonical `document_id`: **404 -> 108**;
- among current `document/done` items with successful extraction, missing canonical identity: **0**;
- active source-family/document-family incompatibilities under current DEF-0003 semantics: **0**;
- duplicate primary canonical keys: **0**;
- historical same-number/year issuer collisions are split into issuer-qualified identities;
- temporal exact-one failure semantics are gone: all three temporal roles now explicitly persist resolved/unresolved/ambiguous state.

The audit also found two new derived-state/materialization anomalies that are not evidence corruption:

1. **11 fully unreferenced canonical Document rows** have no Manifestation and no downstream provision, relationship, temporal-event or case linkage. One is the known historical false identity `CO:RESOLUCION:33933:2025`; the other ten are not declared legally invalid by this audit, but they are orphan cleanup/invariant candidates.
2. **CASE-0001 report materialization drift**: the case graph remains structurally supported, but the checked-in `report.md` differs from the current deterministic materializer on six lines.

DEF-0005, DEF-0006, DEF-0007 and GAP-0001 remain separate P2 work. Their manifestations are reported below and are not reclassified as database/raw-evidence integrity failures.

---

## 1. Database and migration integrity

| Check | Result |
| --- | ---: |
| `PRAGMA quick_check` | `ok` |
| Foreign-key violations | 0 |
| Applied migrations | 14 |
| Repository migration files in deployed image | 14 |
| Missing applied migrations | 0 |
| Extra applied migration names | 0 |
| Applied/repository migration SHA-256 mismatches | 0 |

The migration history therefore satisfies the current append-only/hash-checked migration contract.

No schema migration is part of this audit.

---

## 2. Crawl/source/Manifestation state

### Queue

| Item type | Status | 2026-09-22 | Current |
| --- | --- | ---: | ---: |
| document | done | 1,873 | 1,873 |
| document | error | 4 | 3 |
| index | done | 141 | 142 |

The three current `document/error` rows are acquisition HTTP 404s:

- `c-750_2008.htm`;
- `decision_comisioncandina_dec885.htm`;
- `decreto_1273_2020.htm`.

These are source-availability failures, not raw-hash/provenance corruption.

### Core counts

| Metric | 2026-09-22 historical audit | Current |
| --- | ---: | ---: |
| Sources | 1,985 | 1,986 |
| Manifestations | 1,982 | 1,984 |
| Successful text extractions | 1,876 | 1,878 |
| Distinct canonical Documents bound to Manifestations | 1,547 | 1,875 |
| Manifestations without `document_id` | 404 | 108 |
| Sources without a Manifestation | not highlighted | 3 |

The three Sources without a Manifestation align with current acquisition failures.

### Current source-family distribution

Classification uses the current deterministic source URL classifier over all 1,984 Manifestations:

| Source family | Manifestations |
| --- | ---: |
| `NORMATIVE_ACT` | 1,488 |
| `DIAN_OFICIO` | 239 |
| `CORTE_CONSTITUCIONAL_SENTENCIA_C` | 111 |
| `DIAN_CONCEPTO` | 104 |
| `UNKNOWN` | 21 |
| `JURISPRUDENCIA` | 15 |
| `CONPES` | 5 |
| `CONSTITUCION_POLITICA` | 1 |
| **Total** | **1,984** |

### Remaining unbound Manifestations

All 108 Manifestations with `document_id IS NULL` are currently queue `index/done` items with no successful text extraction:

| Family | Unbound |
| --- | ---: |
| `CORTE_CONSTITUCIONAL_SENTENCIA_C` | 71 |
| `UNKNOWN` | 19 |
| `JURISPRUDENCIA` | 15 |
| `CONPES` | 3 |
| **Total** | **108** |

For the acceptance-relevant legal-document population:

- queue `item_type=document`;
- queue `status=done`;
- successful extraction;

the number still lacking `document_id` is **0**.

This distinction is important: the 108 null identities are not evidence that DEF-0003 regressed.

### DEF-0007 observation: C-096/2001

The historical audit recorded C-096/2001 as a document extraction error caused by the short-body boundary defect. Current state is:

- queue item type: `index`;
- status: `done`;
- attempts: 15;
- Manifestation: `MAN-dc1a12a702495f58870479b0430f0ca0`;
- extraction: **none**;
- canonical Document: **none**;
- registered raw size: 68,686 bytes.

Therefore the reduction from four to three queue errors must **not** be interpreted as resolution of DEF-0007. C-096/2001 remains absent from extraction/FTS/canonical identity; it is now hidden from the error count by its queue classification.

This audit does not change that state.

---

## 3. Canonical identity after DEF-0001 / DEF-0002 / DEF-0003

### Document inventory

| Document type | Count |
| --- | ---: |
| DECRETO | 885 |
| RESOLUCION | 434 |
| OFICIO | 185 |
| LEY | 174 |
| CONCEPTO | 157 |
| SENTENCIA_C | 40 |
| CIRCULAR | 7 |
| CONPES | 2 |
| CONSTITUCION_POLITICA | 1 |
| TRAMITE_OFICIAL | 1 |
| **Total** | **1,886** |

### Active identity invariants

- duplicate primary canonical-key groups across different Documents: **0**;
- trusted source-family/document-family incompatibilities under current rules: **0**;
- trusted source issuer vs issuer-qualified canonical-key mismatches: **0**;
- Documents simultaneously bound to multiple trusted source issuers: **0**;
- DEF-0002 `document_identity_migrations`: **440** rows:
  - 434 issuer-key backfills;
  - 6 collision splits.

The 54 observed `DIAN_OFICIO -> CONCEPTO` bindings are **not** identity incompatibilities. Current DEF-0003 explicitly permits an `oficio_dian_*` source page to resolve to `CONCEPTO` when compatible Concepto front matter confirms the same number/year and DIAN issuer.

### Issuer collisions

The previously dangerous same-type/number/year cases remain split into distinct issuer-qualified Documents, including:

- Resolución 1/2018 — BANREP_JD vs DIAN;
- Resolución 7/2021 — BANREP_JD vs DIAN;
- Circular 1/2019 — DIAN vs PRESIDENCIA.

No primary canonical key is duplicated across those distinct Documents.

### Orphan canonical rows

There are **11** canonical Documents with no Manifestation. All 11 are also fully unreferenced by provisions, temporal events, relationships and case items:

- `CO:DECRETO:568:2020`
- `CO:DECRETO:767:1957`
- `CO:DECRETO:461:2020`
- `CO:LEY:1082:2006`
- `CO:LEY:643:2001`
- `CO:LEY:1261:2008`
- `CO:LEY:424:1998`
- `CO:LEY:21:1992`
- `CO:LEY:06:1992`
- `CO:LEY:56:1981`
- `CO:RESOLUCION:33933:2025`

The last row is the canonical identity created by the historical Constitución/Resolución false-positive example. It is no longer attached to any Manifestation, but its canonical Document/identifier row remains.

This does not contaminate active Manifestation identity or graph provenance, but it is stale derived-state residue. A future cleanup/invariant issue should define whether and when fully unreferenced canonical rows may be removed; this audit does not guess or mutate that policy.

The same stale Resolución row is the only issuer-scoped primary canonical key still using the old unqualified shape. Because it has zero active bindings/references, no current issuer collision was observed.

---

## 4. Extraction and provisions

| Metric | Current |
| --- | ---: |
| Successful text extractions | 1,878 |
| Extracted segments | 576,766 |
| Canonical provisions | 36,450 |
| Provision observations | 37,393 |

Provision coverage by Document type:

| Document type | Documents | Documents with provisions | Provisions |
| --- | ---: | ---: | ---: |
| DECRETO | 885 | 877 | 17,404 |
| LEY | 174 | 165 | 12,757 |
| RESOLUCION | 434 | 429 | 6,289 |
| CIRCULAR | 7 | 0 | 0 |
| CONCEPTO | 157 | 0 | 0 |
| OFICIO | 185 | 0 | 0 |
| SENTENCIA_C | 40 | 0 | 0 |
| CONPES | 2 | 0 | 0 |
| CONSTITUCION_POLITICA | 1 | 0 | 0 |
| TRAMITE_OFICIAL | 1 | 0 | 0 |

The decline from the historical 36,800 provisions to 36,450 is consistent with post-DEF identity cleanup/replay of derived state. This audit does not infer legal deletion from the count alone.

---

## 5. References and relationships

### Reference mentions

| Status | Count |
| --- | ---: |
| candidate | 148,411 |
| resolved | 12,408 |
| unresolved | 9,664 |
| ambiguous | 248 |
| **Total** | **170,731** |

Historical total: 170,098.

### Resolution rows

| Status | Count |
| --- | ---: |
| resolved | 23,013 |
| unresolved | 17,685 |
| ambiguous | 407 |
| **Total** | **41,105** |

Resolution rows are method/version results and therefore are not expected to have one-to-one cardinality with the current status field on `reference_mentions`.

### Explicit relation mentions

- candidate: **14,651**;
- validated: **4,419**;
- total: **19,070**.

### Promoted relationships

- total: **4,456**;
- status `validated`: **4,456**;
- without `relationship_provenance`: **0**;
- without `evidence_id`: **0**;
- sampled/full relational provenance chain break checks: **0**.

Historical relationship count: 4,410.

### GAP-0001 coverage state

Open `TARGET_DOCUMENT_NOT_FOUND` review items: **17,269**.

They represent **1,278 distinct target canonical keys**:

| Target type | Distinct absent keys |
| --- | ---: |
| DECRETO | 681 |
| LEY | 333 |
| RESOLUCION | 262 |
| CONCEPTO | 1 |
| OFICIO | 1 |

Historical GAP-0001 baseline was 1,268 keys. The current 1,278 is a corpus-coverage result, not proof of reference corruption: the target legal instrument is absent from the currently acquired corpus.

---

## 6. Temporality after DEF-0004

The current model is measured as temporal candidates, per-role resolutions and promoted/superseded events. The old exact-one-match warning model is not used as a correctness metric.

### Candidate count

Total temporal candidates: **3,313**.

Trusted structural candidates are retained alongside non-trusted editorial/quoted/unknown candidates; candidate presence alone does not imply promotion.

### Per-role resolutions

There are **5,625** role-resolution rows, exactly three role decisions for each of the 1,875 currently bound canonical Documents.

| Role | Resolved | Unresolved | Ambiguous |
| --- | ---: | ---: | ---: |
| publication_date | 1,113 | 757 | 5 |
| issued_date | 1,095 | 780 | 0 |
| commencement_rule | 656 | 1,211 | 8 |

This directly demonstrates that zero/multiple candidate cardinality is now represented as explicit state rather than a document-level processing exception.

Observed cardinality behavior includes:

- unresolved commencement: 1,130 zero-candidate and 81 one-candidate/no-trusted cases;
- ambiguous commencement: 8 multi-candidate/multi-trusted cases;
- resolved commencement: 655 single-candidate cases plus 1 multi-candidate case with exactly one trusted candidate;
- unresolved issued date: 640 zero-candidate and 140 one-candidate/no-trusted cases;
- resolved issued date: 1,093 single-candidate cases plus 2 multi-candidate cases with exactly one trusted candidate;
- unresolved publication: 749 zero-candidate and 8 one-candidate/no-trusted cases;
- ambiguous publication: 5 multi-candidate cases;
- resolved publication: 1,087 single-candidate cases plus 26 multi-candidate cases with exactly one trusted candidate.

No first/earliest/latest guessing is inferred from those counts.

### Temporal events

| Status | Event type | Count |
| --- | --- | ---: |
| validated | published | 1,215 |
| validated | issued | 1,197 |
| validated | enters_into_force | 487 |
| superseded | published | 475 |
| superseded | issued | 475 |
| superseded | enters_into_force | 475 |
| **Total** |  | **4,324** |

Current provenance checks:

- temporal candidates missing their evidence row: **0**;
- temporal events with neither direct nor linked evidence: **0**;
- temporal event evidence-chain breaks: **0**.

The 1,425 superseded events are preserved historical derived state rather than deleted evidence.

---

## 7. Review queue

Open review items: **27,378**.

| Reason code | Open |
| --- | ---: |
| TARGET_DOCUMENT_NOT_FOUND | 17,269 |
| EDITORIAL_RELATION_SOURCE_PROVISION_UNRESOLVED | 6,460 |
| TEMPORAL_ROLE_UNRESOLVED | 2,748 |
| TARGET_PROVISION_NOT_FOUND | 437 |
| AMBIGUOUS_DOCUMENT_ID | 401 |
| OPERATIONAL_RELATION_SOURCE_PROVISION_UNRESOLVED | 35 |
| TEMPORAL_ROLE_AMBIGUOUS | 13 |
| DUPLICATE_DESIGNATION_IN_SOURCE | 8 |
| AMBIGUOUS_PROVISION_DESIGNATION | 6 |
| UNNUMBERED_PROVISION_IN_SOURCE | 1 |

The increase from the historical 15,893 open review items is not interpreted as a general integrity regression. DEF-0004 intentionally materializes unresolved/ambiguous temporal roles as first-class reviewable state, and later reference/relationship replay exposes additional unresolved coverage rather than guessing.

Current temporal review state is explicit:

- `TEMPORAL_ROLE_UNRESOLVED`: 2,748;
- `TEMPORAL_ROLE_AMBIGUOUS`: 13;
- total: **2,761**.

`AMBIGUOUS_DOCUMENT_ID` review rows are reference-mention ambiguity, not source-Manifestation identity conflicts.

---

## 8. Retrieval / FTS

| Metric | Current |
| --- | ---: |
| `extracted_segments` rows | 576,766 |
| `extracted_segments_fts` rows | 576,766 |
| Duplicate text-SHA groups within one extraction, text >=100 chars | 3,498 |
| Duplicate extra rows in those groups | 6,862 |
| Maximum repetition | 129 |

Historical duplicate baseline:

- groups: 3,496;
- extra rows: 6,860;
- maximum repetition: 129.

Representative current FTS sanity queries returned matches:

- `cancelacion RUT`: 772;
- `liquidacion RUT`: 67;
- `fraccion de ano`: 452;
- `articulo 595`: 241;
- `Registro Unico Tributario`: 4,088.

For these five samples, no exact duplicate text hash repeated inside the first 100 ranked rows. This does **not** mean DEF-0005 is fixed: the global duplicate population remains present and retrieval still lacks the specified deterministic deduplication/diversification contract.

Raw/extracted duplicate rows are preserved as evidence, as required.

---

## 9. Raw, normalized and provenance integrity

### Raw Manifestations — full physical verification

- registered: **1,984**;
- physically present: **1,984**;
- missing: **0**;
- byte-size mismatches: **0**;
- SHA-256 mismatches: **0**;
- bytes checked: **242,153,350**;
- ordered registry digest:
  `18375bda6003ec62ed7f456037b2d07534b15d209dfb13a9dbd5f85ce1d252ee`;
- ordered physical digest:
  `18375bda6003ec62ed7f456037b2d07534b15d209dfb13a9dbd5f85ce1d252ee`.

Integrity level: **full physical verification of every registered raw Manifestation file in this snapshot**, not sampling.

### Normalized extraction artifacts — full physical verification

- registered: **1,878**;
- physically present: **1,878**;
- missing: **0**;
- byte-size mismatches: **0**;
- SHA-256 mismatches: **0**;
- bytes checked: **99,737,556**;
- ordered registry digest:
  `ca9d13e269291b79c3e8051764e44b733f4b0c043e3c86210914a05d6c5e2ff6`;
- ordered physical digest:
  `ca9d13e269291b79c3e8051764e44b733f4b0c043e3c86210914a05d6c5e2ff6`.

### Derived provenance invariants

- Evidence `source_sha256` differing from linked Manifestation SHA-256: **0**;
- promoted Relationships without provenance row: **0**;
- promoted Relationships without evidence: **0**;
- Temporal Candidates without evidence: **0**;
- Temporal Events without direct/linked evidence: **0**;
- foreign-key violations: **0**.

No immutable raw bytes were rewritten by this audit.

---

## 10. CASE-0001 structural/materialization validation

The existing `tools/validate_case_bundle.py` validator was executed against the current read-only SQLite snapshot and the repository case bundle.

Structural result:

- case: `CASE-0001`;
- status: `open`;
- as-of date: `2026-09-22`;
- claims: **8**;
- validated/human-verified claims: **8/8**;
- evidence rows: **15**;
- case relationships: **4**;
- SQLite sources: **7**;
- source manifest matches SQLite: **yes**;
- orphan case items: **0**;
- validated claims lacking canonical support: **0**;
- duplicate claim evidence: **0**.

Materialization result:

- `report_matches_materializer`: **false**;
- validator `valid`: **false**;
- validator error: `report_not_materialized_from_canonical_state`.

The difference was isolated without rewriting the report. Stored and newly rendered reports both contain 425 lines; exactly six lines differ:

- four relationship rows retain older `evidence_id` values while current canonical relationships point to replacement evidence IDs;
- source `SRC-0004` stored type is `normograma_html`, current source type is `decreto`;
- source `SRC-0005` stored type is `resolucion_compilada`, current source type is `resolucion`.

The claims, quotes, source SHA-256 values, source set and relationship identities remain structurally supported. This is therefore classified as **case materialization drift**, not raw-evidence/provenance corruption.

Because issue #14 is a read-only audit, `CASE-0001/report.md` was intentionally not rematerialized here. A separate follow-up should define the case materialization refresh/lifecycle rule and update the bundle through its canonical materializer rather than by manual patching.

---

## 11. Historical baseline vs current post-P1 state

Selected measurements:

| Metric | 2026-09-22 | 2026-09-23 post-P1 | Interpretation |
| --- | ---: | ---: | --- |
| Sources | 1,985 | 1,986 | normal corpus growth |
| Manifestations | 1,982 | 1,984 | normal corpus growth |
| Successful extractions | 1,876 | 1,878 | normal corpus growth |
| Bound canonical Documents | 1,547 | 1,875 | DEF-0001/2/3 identity stabilization/coverage |
| Manifestations without Document | 404 | 108 | all current 108 are index/no-successful-extraction |
| Provisions | 36,800 | 36,450 | derived cleanup/replay effect |
| Reference mentions | 170,098 | 170,731 | replay/growth |
| Relationships | 4,410 | 4,456 | replay/growth |
| Temporal events | 1,528 | 4,324 total | new v3 state + preserved superseded history |
| Open review items | 15,893 | 27,378 | explicit unresolved/ambiguity + replay; not a raw integrity score |
| Duplicate >=100-char segment groups | 3,496 | 3,498 | DEF-0005 remains |
| Distinct missing target keys | 1,268 | 1,278 | GAP-0001 remains |

The comparison is descriptive. Historical counts are not retroactively rewritten to fit current semantics.

---

## 12. Remaining specified work vs newly observed anomalies

### Existing specified P2 work

**DEF-0005 — retrieval duplicate segments**

Still present. FTS cardinality is correct, but 3,498 same-extraction duplicate text-hash groups remain independently searchable. Raw/extracted duplicates should remain preserved; the missing feature is retrieval-time deterministic deduplication/diversification.

**DEF-0006 — container file ownership**

Still operationally visible. Host-side raw inspection requires container/root-compatible access; this audit therefore used the deployed container for full physical verification. No evidence loss was observed.

**DEF-0007 — legal body false-short**

Still unresolved in effect. C-096/2001 has a raw Manifestation but no text extraction/canonical identity. Its queue state is currently `index/done`, so it is no longer counted among `document/error` rows even though the legal source remains absent from the searchable/canonical corpus.

**GAP-0001 — referenced documents outside current corpus**

Still a coverage limitation. Current unresolved demand is 1,278 distinct missing target keys. No missing target text was inferred or synthesized.

### Newly observed audit anomalies

**A. CASE-0001 materialization drift**

The canonical case graph/support remains consistent, but `report.md` is stale on six deterministic materialization lines. This should be handled by a dedicated case-materialization refresh/lifecycle change, not by manual audit-time patching.

**B. Fully unreferenced canonical Document residue**

Eleven canonical Document rows have no Manifestation and no downstream graph/case use. At least `CO:RESOLUCION:33933:2025` is known residue from the historical DEF-0001 false-identity case. The audit does not infer whether every unreferenced Document is legally invalid; cleanup requires an explicit invariant and provenance-preserving policy.

**C. Queue classification obscures DEF-0007 state**

C-096/2001 moved from the historical error population to `index/done` while still having no extraction. Operational dashboards that count only queue errors would incorrectly suggest this defect disappeared. DEF-0007 acceptance must continue to test extraction/canonical availability, not only queue status.

No anomaly above was silently repaired during this audit.

---

## 13. Applicability of implementation gates

- code/schema implementation: **N/A** — issue #14 is audit/validation only;
- migration: **N/A** — no schema change;
- dry-run/preview: **N/A** — no mutation path was introduced or executed;
- reprocessing: **N/A** — current state was measured only;
- unit/regression test modification: **N/A** — no production logic changed;
- runtime access: **applicable** — required to measure the real corpus and physical hashes; all database access was read-only;
- raw/provenance verification: **applicable and PASS** — full registered raw + normalized file verification plus derived provenance checks;
- manifest/spec status synchronization: **N/A** — this audit is not a DEF/GAP lifecycle item in `specs/manifest.yaml`.

---

## 14. Acceptance verification for GitHub issue #14

1. **PASS** — a new dated audit file is created under `col-taxdata/specs/audits/`.
2. **PASS** — the historical `2026-09-22-corpus-audit.md` is treated as immutable; its repository blob was not edited.
3. **PASS** — production corpus inspection was read-only; no corpus/reprocessing mutation occurred.
4. **PASS** — measurements use the current architecture/domain contracts, not pre-P1 exact-one/issuer-blind assumptions.
5. **PASS** — DEF-0004 temporality is measured through candidates, per-role resolutions and events; unresolved/ambiguous state is explicit.
6. **PASS** — canonical identity was checked for source-family compatibility, issuer-aware collision separation and duplicate primary keys.
7. **PASS** — raw/provenance verification states its level explicitly: full physical SHA-256/size verification for all registered raw and normalized artifacts plus relational provenance checks.
8. **PASS** — CASE-0001 validator was executed and its `valid=false` materialization-drift result is documented without concealing it.
9. **PASS** — remaining DEF-0005/6/7 and GAP-0001 are kept separate from integrity failures; new anomalies are separately identified.
10. **PASS** — repository content change for this task is limited to this new audit file under `col-taxdata/`.
11. **PASS** — no immutable raw evidence, production SQLite state or derived production corpus state was changed.

No mandatory acceptance criterion is FAIL or UNRESOLVED.

## Conclusion

The post-P1 corpus has a substantially stronger canonical identity and temporal-state model than the 2026-09-22 baseline, while preserving immutable evidence. The current production snapshot passes database, migration, raw-byte and core provenance integrity checks.

The remaining work is not one undifferentiated integrity problem. It separates into:

- unresolved corpus coverage/reference demand (GAP-0001);
- retrieval diversity/deduplication (DEF-0005);
- runtime ownership (DEF-0006);
- a still-unextracted C-096/2001 despite its current queue classification (DEF-0007);
- CASE-0001 materialization drift;
- fully unreferenced canonical-row cleanup/invariant policy.

Those items should be handled by their own issue/spec contracts rather than by mutating evidence or broadening this audit task.
