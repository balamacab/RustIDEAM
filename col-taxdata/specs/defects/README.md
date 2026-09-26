# Defect index

Baseline: [2026-09-22 corpus audit](../audits/2026-09-22-corpus-audit.md).

The machine-readable ordering/dependency graph is maintained in [`specs/manifest.yaml`](../manifest.yaml).

| ID | Priority | Title | GitHub | Status |
|---|---|---|---|---|
| [DEF-0001](DEF-0001-document-identity-false-positive.md) | P1 | Document identity can be taken from a cited norm instead of the source document | [#1](https://github.com/balamacab/RustIDEAM/issues/1) | verified |
| [DEF-0002](DEF-0002-canonical-identity-missing-issuer.md) | P1 | Canonical keys can merge different issuers with the same type/number/year | [#2](https://github.com/balamacab/RustIDEAM/issues/2) | verified |
| [DEF-0003](DEF-0003-incomplete-document-type-registration.md) | P1 | 297 legal documents are extracted but have no canonical document identity | [#3](https://github.com/balamacab/RustIDEAM/issues/3) | verified |
| [DEF-0004](DEF-0004-temporality-cardinality-assumptions.md) | P1 | Temporal extractor aborts when evidence cardinality is not exactly one | [#4](https://github.com/balamacab/RustIDEAM/issues/4) | verified |
| [DEF-0005](DEF-0005-retrieval-duplicate-segments.md) | P2 | Repeated equivalent segments bias FTS/RAG retrieval | [#5](https://github.com/balamacab/RustIDEAM/issues/5) | specified |
| [DEF-0006](DEF-0006-container-file-ownership.md) | P2 | Docker writes runtime evidence as root with raw files mode 0600 | [#6](https://github.com/balamacab/RustIDEAM/issues/6) | specified |
| [DEF-0007](DEF-0007-legal-body-false-short.md) | P2 | Valid Sentencia C-096/2001 is rejected as an unexpectedly short legal body | [#7](https://github.com/balamacab/RustIDEAM/issues/7) | verified |
| [DEF-0009](DEF-0009-unreferenced-document-lifecycle.md) | — | Source-less canonical Documents lack an explicit retention/cleanup lifecycle | [#19](https://github.com/balamacab/RustIDEAM/issues/19) | verified |
| [DEF-0011](DEF-0011-rejected-llm-output-evidence.md) | P1 | Rejected CASE LLM output is lost before forensic audit | [#90](https://github.com/balamacab/RustIDEAM/issues/90) | implementing |

Coverage limitations that are not parser defects are tracked separately under `specs/gaps/`; GAP-0001 is tracked by [issue #8](https://github.com/balamacab/RustIDEAM/issues/8).
