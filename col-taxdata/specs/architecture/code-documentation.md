# Code documentation and rationale standard

## Purpose

Production code in `col-taxdata` must preserve enough local explanation that a competent maintainer can understand its intent, safety boundaries, and domain assumptions without reconstructing the implementation from historical GitHub issues.

This standard complements issue-specific specifications and architecture documents. It does not make comments or docstrings canonical legal authority, and it does not replace tests, ADRs, or behavioral contracts.

The goal is useful rationale, not comment density.

## Required documentation

Meaningful implementation-point documentation is required for non-trivial production code when the behavior is not obvious from names and structure alone. In particular, document the reason for logic that controls:

- legal-data assumptions or source-family constraints;
- ambiguity-preserving behavior, including deliberate unresolved states;
- provenance/evidence creation, preservation, or rejection;
- canonical identity or reference/relationship promotion;
- temporal-state decisions;
- deterministic hashes or identifiers whose exact input material is contract-sensitive;
- persistence, replay, reprocessing, or migration entry points;
- read-only versus mutating boundaries;
- transaction boundaries when correctness depends on atomicity;
- intentionally conservative rejection/preservation behavior;
- compatibility behavior that appears redundant but is deliberate.

Public production classes/functions and materially modified public methods must have concise docstrings that explain their contract when it is not already obvious from the signature. Complex internal functions require the same level of rationale even when they are not part of the mechanical CI check.

Comments should explain **why** a decision or boundary exists, not translate syntax into English.

Bad:

```python
# increment counter
count += 1
```

Good:

```python
# Do not choose the first candidate date. Multiple supported dates are an
# ambiguity state under DEF-0004 and must remain unresolved.
```

## Documentation that is not required

Do not add prose merely to satisfy a quota. Documentation is normally unnecessary for:

- trivial getters or wrappers whose contract is fully obvious;
- obvious one-line private helpers;
- test methods whose names/assertions already explain the scenario;
- syntax-restating comments;
- comments that simply translate Python, SQL, or shell syntax into English.

Private does not mean unimportant. A private function that implements a non-obvious legal, provenance, ambiguity, mutation, or compatibility rule still requires useful rationale under static review.

## References to authoritative contracts

Code may reference the authoritative reason for a rule using a lightweight identifier or path, for example:

- `DEF-0004`;
- `ADR-0006`;
- `case-contracts-v3`;
- `architecture/data-lifecycle.md`.

A reference complements the explanation; it does not replace it. A maintainer should be able to understand what the code is protecting without opening the referenced document merely to decode the comment.

## Repository-side enforcement

The CI policy enforces the objective subset of this standard for changed production Python.

### Production Python scope

Production Python is any `col-taxdata/**/*.py` file except `col-taxdata/tests/**`.

Tests and fixtures are intentionally excluded from docstring enforcement. They must remain readable, but they are not forced to carry boilerplate documentation.

### Incremental transition rule

Legacy undocumented code is not scanned repository-wide on every PR.

Instead:

```text
accepted legacy debt
    -> remains tracked separately while untouched

new or materially modified production definitions
    -> must satisfy the current documentation contract
```

A public definition is considered materially modified when its parsed Python AST differs from the accepted base revision. Whitespace-only and comment-only edits do not manufacture documentation debt. A pure file rename preserves the old path as the comparison source.

The mechanical check requires a non-empty docstring for:

- every new public top-level function or class;
- every new public method in a public class;
- every materially modified public top-level function or class;
- every materially modified public method in a public class.

Private/internal definitions are not mechanically scored. Their required rationale is enforced through the completion/static-review contract because a simplistic complexity score would encourage boilerplate and false confidence.

### New module documentation

A newly introduced production module also requires a module docstring when it is structurally substantial: it introduces either a public class or at least two public top-level callables.

This rule is intentionally structural rather than a line-count or comment-percentage threshold.

### No density or prose scoring

The repository must not:

- require a percentage of commented lines;
- score comment volume;
- generate comments mechanically to satisfy CI;
- infer documentation quality from a complexity threshold;
- force tests to contain meaningless docstrings.

The CI check detects objective omissions only. Human/agent static review remains responsible for whether rationale is actually useful and located at the decision point.

## Completion review

Before an autonomous task can be considered ready for merge, review all changed production code for:

1. missing public/module docstrings covered by the mechanical policy;
2. non-obvious legal-data assumptions lacking local explanation;
3. ambiguity/provenance/identity/temporal decisions whose conservative behavior is not documented;
4. deterministic identifier/hash logic whose exact inputs are not explained;
5. read-only/mutating or transaction boundaries whose safety reason is unclear;
6. compatibility behavior that would look removable to a future maintainer without explanation;
7. reliance on GitHub issue comments as the sole record of why code behaves as it does.

Issue comments remain an engineering audit trail, but they are not a substitute for implementation-point rationale.

## Legacy remediation

Issue #58 prevents new documentation debt; it does not retroactively document every existing module.

Existing high-risk undocumented modules should be remediated through separate scoped issues so that rationale can be added deliberately, reviewed against the relevant domain contracts, and tested without mixing broad cleanup into unrelated work.
