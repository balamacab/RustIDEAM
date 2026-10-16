---
id: DEF-0008
type: defect
status: verified
area: case-materialization
---

# DEF-0008 — Canonical case-materialization freshness

Status: **verified**  
GitHub issue: [#18](https://github.com/balamacab/RustIDEAM/issues/18)  
Priority: **unspecified by the authoritative issue**

## Problem and observed evidence

The 2026-09-23 post-P1 audit found that `CASE-0001` retained its canonical claims and evidence while its checked-in `report.md` no longer matched a fresh deterministic render. Four relationship evidence IDs and two source-kind labels had changed in canonical state. The source manifest's source-ID set still matched, but its source-kind values had drifted. Thus claim existence and source-ID membership alone do **not** prove freshness. This was derived-state drift, not a change to immutable raw evidence.

## Verified invariant

Canonical SQLite case/corpus state and declared case-local materializer inputs (including `unresolved.json`) are authoritative. `cases/<CASE>/report.md` and `cases/<CASE>/sources/manifest.json` are **derived, reproducible materializations**, not independent legal or provenance authorities.

An artifact is current **only** if its complete stored UTF-8 content equals the canonical renderer's output for the same inputs. Any case-visible canonical change may stale it, including relationship/evidence rebinding, evidence replacement, source-kind normalization, identity/reprocessing, or future temporal/reference replay affecting rendered output. A matching claim count, source-ID set, or checksum of unrelated inputs is insufficient.

## Implementation contract

- `tools/materialize_case_report.py` renders the canonical report; `tools/materialize_case_sources.py` renders the canonical source manifest.
- `tools/validate_case_bundle.py` compares the complete report and source-manifest materializations against canonical renders, in addition to preserving its existing membership/provenance checks.
- `tools/rematerialize_case.py` is the supported refresh path. Default execution previews current/stale/missing artifacts and prospective changes **without writing**. `--diff` exposes a unified diff. Explicit `--write` writes the canonical renders and immediately checks convergence.
- Repeating refresh against unchanged canonical inputs must yield zero further writes and byte-identical artifacts. Generated report/source lines must never be patched by hand to match a changed ID or label.
- Rendered-artifact SHA-256 values are comparison aids only; they do not replace the original manifestation/source/evidence provenance chain.

## Regression and acceptance evidence

`tests/test_def0008_case_materialization.py` exercises freshness, drift detection, non-mutating preview, explicit refresh, convergence and idempotency on isolated fixtures. The issue #18 completion log records the `CASE-0001` preview delta (four relationship evidence-ID lines and two source-kind lines in the report; two source-kind lines in the source manifest), canonical regeneration through the tool, zero writes on repeat, and unchanged raw manifestation SHA. The issue was closed after verified implementation.

Preservation: legal claims and canonical evidence are not rewritten to make the report pass. No database migration is required by this defect; no raw file, manifestation hash or provenance record is changed by rematerialization.

## Scope and sources

This specification records **already implemented** behavior, not a new feature or authorization to refresh production artifacts. Sources: closed [issue #18](https://github.com/balamacab/RustIDEAM/issues/18), [post-P1 audit](../audits/2026-09-23-post-p1-corpus-audit.md), [data lifecycle](../architecture/data-lifecycle.md), the canonical materializer/validator implementations, and `tests/test_def0008_case_materialization.py`. Issue #53 registers this historical verified contract without altering it.
