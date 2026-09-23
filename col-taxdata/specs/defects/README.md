# Defect index

Baseline: [2026-09-22 corpus audit](../audits/2026-09-22-corpus-audit.md).

| ID | Priority | Title | Status |
|---|---|---|---|
| [DEF-0001](DEF-0001-document-identity-false-positive.md) | P1 | Document identity can be taken from a cited norm instead of the source document | specified |
| [DEF-0002](DEF-0002-canonical-identity-missing-issuer.md) | P1 | Canonical keys can merge different issuers with the same type/number/year | specified |
| [DEF-0003](DEF-0003-incomplete-document-type-registration.md) | P1 | 297 legal documents are extracted but have no canonical document identity | specified |
| [DEF-0004](DEF-0004-temporality-cardinality-assumptions.md) | P1 | Temporal extractor aborts when evidence cardinality is not exactly one | specified |
| [DEF-0005](DEF-0005-retrieval-duplicate-segments.md) | P2 | Repeated equivalent segments bias FTS/RAG retrieval | specified |
| [DEF-0006](DEF-0006-container-file-ownership.md) | P2 | Docker writes runtime evidence as root with raw files mode 0600 | specified |
| [DEF-0007](DEF-0007-legal-body-false-short.md) | P2 | Valid Sentencia C-096/2001 is rejected as an unexpectedly short legal body | specified |

Coverage limitations that are not parser defects are tracked separately under `specs/gaps/`.
