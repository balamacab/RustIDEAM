CREATE TABLE IF NOT EXISTS provision_designation_conflicts (
    conflict_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    normalized_designation TEXT NOT NULL,
    observation_count INTEGER NOT NULL
        CHECK (observation_count >= 2),
    distinct_normative_text_count INTEGER NOT NULL
        CHECK (distinct_normative_text_count >= 1),
    reason_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    UNIQUE(document_id, extraction_id, normalized_designation)
);

CREATE INDEX IF NOT EXISTS idx_provision_designation_conflicts_open
    ON provision_designation_conflicts(
        document_id,
        normalized_designation,
        status
    );
