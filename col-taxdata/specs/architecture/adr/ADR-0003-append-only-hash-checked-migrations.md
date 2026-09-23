# ADR-0003 — Database migrations are append-only and hash checked

## Status

Accepted and implemented.

## Context

The schema encodes provenance and legal-data semantics. Editing an already-applied migration would make two databases with the same nominal migration name represent different history.

## Decision

Schema changes are introduced as new ordered SQL migrations. `tools/init_db.py` records each migration filename and SHA-256 in `schema_metadata`.

If an already-applied migration file has a different SHA-256 on disk, initialization stops instead of silently accepting drift.

Applied migrations are never rewritten to retrofit later decisions.

## Alternatives considered

In-place editing of historical migrations is explicitly prohibited by the project workflow and is not an accepted option.

## Consequences / trade-offs

- Schema history is inspectable and stable.
- Fixes sometimes require an additional migration even when editing an earlier migration would look simpler.
- Fresh-database creation and upgrades use the same ordered migration set.
- Migration-file hash integrity is not the same as complete execution provenance; issue #11 remains separate.

## Related specs/issues

- `tools/init_db.py`
- `schema/001_initial.sql` … `schema/014_temporal_candidates.sql`
- GitHub issue #11 — future execution provenance/reproducibility.
