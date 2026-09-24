# DEF-0009 — Lifecycle and cleanup for unreferenced canonical Documents

Status: **verified**

GitHub issue: [#19](https://github.com/balamacab/RustIDEAM/issues/19)

Priority: **unspecified by current issue/planning metadata**

## 1. Problem

The canonical `documents` table is derived state. Reprocessing can correct a
Manifestation binding and remove dependent derived rows while leaving the old
Document and its identifiers behind. Conversely, a Document can legitimately
have zero directly linked Manifestations while it is still an active target of
reference resolution or while its canonical identifier has explicit evidence.

Therefore this rule is invalid:

```text
zero Manifestations => delete Document
```

The missing contract is a lifecycle rule that distinguishes supported
source-less canonical state from unsupported derived residue without making any
claim about whether the underlying legal instrument exists in the world.

## 2. Authoritative invariant

A canonical Document with zero linked Manifestations is **not stale merely
because the count is zero**.

A zero-Manifestation Document is retained when any of these conditions holds:

1. **Active dependency protection.** A current derived/canonical row still
   binds to the Document. This includes every direct foreign key to
   `documents.document_id` other than the Document's intrinsic identifier rows
   and the already-zero Manifestation relation, plus current polymorphic
   document endpoints such as relationships, temporal events, case items,
   claims and document review state.
2. **Explicit identifier provenance.** The Document has exactly one primary
   canonical key and evidence attached through `document_identifier_evidence`
   whose `evidence.source_sha256` still equals the registered SHA-256 of the
   supporting Manifestation.
3. **Conservative conflict retention.** Identity/provenance exists but is
   malformed or inconsistent. Missing/multiple primary keys, broken evidence
   chains, or other conflicts are retained for validation/review rather than
   converted into permission to delete.

An active resolved reference is a protected dependency. Its
`reference_resolutions -> reference_mentions -> extracted_segments ->
text_extractions -> manifestations` chain is the provenance of that active
reference-only use.

A zero-Manifestation Document is **stale derived residue eligible for cleanup**
only when all of the following are true:

- it has exactly one primary canonical identifier;
- it has no linked Manifestation;
- it has no active direct Document binding;
- it has no active supported polymorphic Document binding;
- it has no identifier-evidence row of any kind.

This classification describes the support state of the database row. It MUST
NOT be interpreted as a legal conclusion that the named law, decree,
resolution, circular or other instrument does not exist.

## 3. Active bindings

The cleanup implementation MUST discover direct foreign keys to `documents`
from the current SQLite schema rather than keeping a closed hard-coded list.
This ensures a new direct dependency defaults to retention.

The current polymorphic Document endpoints that are not protected by SQLite
foreign keys are checked explicitly:

- `relationships` source/target Document endpoints;
- `temporal_events` entity/caused-by Document endpoints;
- `case_items` with `item_type='document'`;
- `claims` subject/object Document endpoints;
- `review_queue` with `entity_type='document'`.

A row protected by an active binding is retained even when separate identity
evidence is absent. The owning subsystem must remove/rebind that dependency
first if later work proves it obsolete.

## 4. Explicit source-less provenance

`document_identifier_evidence` is the current repository mechanism that can
prove a canonical identifier from evidence even when no Manifestation is
directly bound to the Document.

For automatic retention as an explicitly supported source-less canonical
Document:

- at least one valid evidence row must support the primary canonical key;
- every identifier-evidence row currently attached to that Document must lead
  to a registered Manifestation whose SHA-256 matches
  `evidence.source_sha256`.

If evidence exists but these conditions do not hold, classification is
`retained_conflict`; cleanup does not delete it.

No new placeholder table or migration is required by DEF-0009.

## 5. Cleanup contract

Canonical implementation:

```text
tools/cleanup_unreferenced_documents.py
```

The tool:

- scans all zero-Manifestation Documents; it does not use a corpus-specific ID
  allow/deny list;
- defaults to **dry-run** and opens SQLite read-only;
- reports deletion candidates, retained rows and reasons, conflicts, and the
  number of identifier rows that would disappear with candidate Documents;
- never uses document type, number, year, title wording, age, or odd-looking
  canonical keys as deletion evidence;
- on `--apply`, starts `BEGIN IMMEDIATE`, rebuilds the plan inside that
  transaction, and reclassifies every candidate immediately before deletion;
- deletes only the unsupported Document row. Its intrinsic
  `document_identifiers` cascade with the Document; candidates are required to
  have no provenance or active dependent state;
- keeps SQLite foreign-key enforcement enabled as a second safety boundary;
- computes the registered Manifestation SHA registry digest before and after
  apply and rolls back if it changes;
- is idempotent: after a successful cleanup, an immediate repeat has no
  additional deletion candidates created by the cleanup itself.

The tool exits non-zero if the operation cannot be classified or executed
safely. A provenance conflict is a retained classification, not permission to
delete.

## 6. Current 11-row investigation

The 2026-09-23 post-P1 audit identified 11 canonical Documents with zero linked
Manifestations. A batched read-only inspection for issue #19 on 2026-09-24
confirmed all 11 still have zero Manifestations, provisions, direct document
relationships, temporal rows, case items, claim bindings,
`document_identifier_evidence`, and `document_identity_migrations`.

Current reference bindings refine that historical observation:

| Canonical key | Current classification | Evidence / reason |
|---|---|---|
| `CO:DECRETO:568:2020` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:DECRETO:767:1957` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:DECRETO:461:2020` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:1082:2006` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:643:2001` | retain — active reference target | 28 current `reference_resolutions.target_document_id` bindings |
| `CO:LEY:1261:2008` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:424:1998` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:21:1992` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:06:1992` | stale derived residue | no Manifestation, active binding, identifier evidence, or migration provenance |
| `CO:LEY:56:1981` | retain — active reference target | 2 current `reference_resolutions.target_document_id` bindings |
| `CO:RESOLUCION:33933:2025` | stale derived residue | known historical DEF-0001 false-identity residue; now has no support/binding |

For `CO:RESOLUCION:33933:2025`, the historical creation path is known from
DEF-0001: content from a different source family was previously promoted as the
source Document identity and later detached by corrected reprocessing.

For the other eight current stale candidates, the exact historical creator
cannot be reconstructed from surviving canonical provenance: there is no
Manifestation binding, identifier evidence, identity migration row or active
consumer binding. DEF-0009 deliberately does not guess which old source page or
processor created them. Their **row support state** is nevertheless
deterministically stale under the invariant above.

The two retained laws are not inferred valid because they are laws. They are
retained because current reference-resolution state actively targets them.

## 7. Reprocessing and production safety

The required sequence for current corpus cleanup is:

```text
current source-less set
  -> read-only dry-run classification
  -> regression/full tests
  -> review exact candidate/retained delta
  -> apply deterministic cleanup
  -> immediate second dry-run
  -> verify Manifestation registry/hash integrity
```

Expected current delta from the issue baseline is nine stale candidates and two
retained active reference targets. If the production dry-run differs, the
current state wins and the difference must be investigated rather than forcing
the historical expectation.

No raw file, Manifestation row, registered SHA-256, source, extraction, segment,
reference mention, or other active binding may be modified by this cleanup.

## 7.1 Verified corpus result — 2026-09-24

The guarded production run completed after the full 115-test suite passed.

- dry-run: 11 source-less Documents -> 9 stale candidates, 2 retained active reference targets, 0 conflicts;
- apply: 9 Documents deleted with 9 intrinsic identifier rows cascading;
- raw Manifestation registry digest before/after: `a9e10e4a7bedc01e2552e6d8a93177ec13c3e1d397f618cfd1838088b7d1b3f2`;
- post-apply dry-run: 2 source-less Documents, 0 candidates, 2 retained, 0 conflicts;
- the retained rows remain `CO:LEY:643:2001` (28 reference resolutions) and `CO:LEY:56:1981` (2 reference resolutions).

The direct host account could not write the SQLite database. That attempt failed without mutation; the exact tested cleanup implementation was then mounted read-only into a transient taxdata container using the existing production data volume. No production service was stopped or replaced.

## 8. Schema / migration

**N/A.** Existing schema already carries the required provenance and active
binding information. No applied migration is changed and no new migration is
introduced.

## 9. Regression requirements

Tests must cover at least:

1. known `CO:RESOLUCION:33933:2025` stale residue is reported by dry-run;
2. dry-run performs no mutation;
3. stale fixture apply removes only the Document/intrinsic identifiers and
   leaves unrelated Manifestation SHA state unchanged;
4. immediate second apply/dry-run is idempotent;
5. a source-less Document with valid primary identifier evidence is retained;
6. a reference-only target Document is retained;
7. Documents with active provision/relationship/temporal/case bindings are
   retained;
8. broken identifier provenance is retained as conflict rather than deleted.

The full existing project suite must remain green.

## 10. Relationship to corpus doctor (#12)

Issue #12 may later expose this invariant as a stable read-only corpus-doctor
check. The doctor should call/reuse equivalent classification semantics, report
unsupported source-less Documents and provenance conflicts, and must not perform
cleanup. DEF-0009's cleanup tool remains the repair path.

## 11. Acceptance criteria

DEF-0009 is verified only when:

- the zero-Manifestation lifecycle invariant is explicit in architecture and
  this specification;
- all 11 observed rows are classified without guessing;
- legitimate source-less/reference-only rows are retained from explicit
  provenance or active dependency evidence;
- stale residue is removable only through deterministic systemic cleanup;
- dry-run reports candidates, retained rows/reasons and conflicts without
  mutation;
- no active document/provision/reference/relationship/temporal/case binding is
  accidentally deleted;
- raw Manifestation/SHA state is unchanged;
- the `CO:RESOLUCION:33933:2025` regression passes;
- stale cleanup apply is idempotent;
- healthy source-less provenance and reference-only fixtures are not false
  positives;
- the current affected corpus is reprocessed through the dry-run/apply gate and
  a second preview converges;
- the future read-only doctor can validate the invariant without becoming a
  mutator;
- every repository content change remains under `col-taxdata/`.

## 12. Non-goals

This defect does not:

- decide legal validity/existence from missing local evidence;
- fetch missing legal sources;
- implement GAP-0001 corpus expansion;
- turn issue #12's doctor into a repair mechanism;
- manually delete the nine current candidates by ID/key;
- change canonical identity rules for supported documents;
- alter immutable raw evidence.
