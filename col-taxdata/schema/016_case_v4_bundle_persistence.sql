-- Issue #140: additive CASE v4 LegalResearchBundle persistence.
--
-- v3 cases/claims remain historical compatibility state.  The v4 tables keep
-- explicit ownership/trust metadata so intake/model material cannot be
-- confused with canonical legal support.

CREATE TABLE IF NOT EXISTS case_v4_bundles (
    bundle_ref TEXT PRIMARY KEY,
    case_ref TEXT NOT NULL,
    contract_version TEXT NOT NULL
        CHECK (contract_version = '4.0.0'),
    status TEXT NOT NULL
        CHECK (status IN ('complete', 'partial', 'blocked')),
    bundle_sha256 TEXT NOT NULL
        CHECK (length(bundle_sha256) = 64),
    research_context_sha256 TEXT NOT NULL
        CHECK (length(research_context_sha256) = 64),
    generated_at TEXT NOT NULL,
    persisted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_case_v4_bundles_case_ref
    ON case_v4_bundles(case_ref);

CREATE TABLE IF NOT EXISTS case_v4_artifacts (
    bundle_ref TEXT NOT NULL
        REFERENCES case_v4_bundles(bundle_ref) ON DELETE CASCADE,
    artifact_kind TEXT NOT NULL
        CHECK (artifact_kind IN (
            'case_input',
            'intake_draft',
            'research_plan',
            'research_result',
            'official_source',
            'canonical_authority',
            'evidence_span',
            'normative_relationship',
            'rule_fragment',
            'deterministic_evaluation',
            'calculation_trace',
            'unresolved_item'
        )),
    artifact_ref TEXT NOT NULL,
    owner TEXT NOT NULL
        CHECK (owner IN ('caller', 'internal_intake_model', 'platform')),
    authority_role TEXT NOT NULL
        CHECK (authority_role IN (
            'caller_input',
            'intake_only',
            'platform_research',
            'source_metadata',
            'canonical_legal_support',
            'deterministic_platform',
            'unresolved_platform'
        )),
    ordinal INTEGER NOT NULL
        CHECK (ordinal >= 0),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
        CHECK (length(payload_sha256) = 64),
    PRIMARY KEY(bundle_ref, artifact_kind, artifact_ref),
    UNIQUE(bundle_ref, artifact_kind, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_case_v4_artifacts_kind
    ON case_v4_artifacts(artifact_kind, artifact_ref);
