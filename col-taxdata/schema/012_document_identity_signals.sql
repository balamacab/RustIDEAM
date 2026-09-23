CREATE TABLE IF NOT EXISTS document_identity_signals (
    identity_signal_id TEXT PRIMARY KEY,
    manifestation_id TEXT NOT NULL
        REFERENCES manifestations(manifestation_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    signal_origin TEXT NOT NULL
        CHECK (signal_origin IN ('source_url', 'document_heading')),
    source_family TEXT NOT NULL,
    document_type TEXT,
    document_number TEXT,
    document_year INTEGER,
    raw_value TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_identity_signals_manifestation
    ON document_identity_signals(manifestation_id, extraction_id, signal_origin);