CREATE TABLE IF NOT EXISTS provisions (
    provision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    provision_type TEXT NOT NULL,
    designation TEXT NOT NULL,
    normalized_designation TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, normalized_designation)
);

CREATE INDEX IF NOT EXISTS idx_provisions_document
    ON provisions(document_id, normalized_designation);

CREATE TABLE IF NOT EXISTS provision_observations (
    provision_observation_id TEXT PRIMARY KEY,
    provision_id TEXT NOT NULL
        REFERENCES provisions(provision_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    extracted_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE CASCADE,
    observed_text TEXT NOT NULL,
    normative_text TEXT NOT NULL,
    editorial_note TEXT,
    observed_text_sha256 TEXT NOT NULL,
    normative_text_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    UNIQUE(provision_id, extraction_id, extracted_segment_id)
);

CREATE INDEX IF NOT EXISTS idx_provision_observations_provision
    ON provision_observations(provision_id, extraction_id);

CREATE TABLE IF NOT EXISTS reference_resolutions (
    reference_resolution_id TEXT PRIMARY KEY,
    reference_mention_id TEXT NOT NULL
        REFERENCES reference_mentions(reference_mention_id) ON DELETE CASCADE,
    target_document_id TEXT
        REFERENCES documents(document_id) ON DELETE SET NULL,
    target_provision_id TEXT
        REFERENCES provisions(provision_id) ON DELETE SET NULL,
    resolution_method TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL
        CHECK (status IN ('resolved', 'unresolved', 'ambiguous')),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(reference_mention_id, resolution_method)
);

CREATE INDEX IF NOT EXISTS idx_reference_resolutions_target
    ON reference_resolutions(target_document_id, target_provision_id, status);
