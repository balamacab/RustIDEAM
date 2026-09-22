CREATE TABLE IF NOT EXISTS dian_doctrine_metadata (
    document_id TEXT PRIMARY KEY
        REFERENCES documents(document_id) ON DELETE CASCADE,
    external_number TEXT NOT NULL,
    normalized_external_number TEXT NOT NULL,
    internal_number TEXT,
    document_year INTEGER NOT NULL,
    doctrine_date TEXT,
    web_publication_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(normalized_external_number, document_year)
);

CREATE TABLE IF NOT EXISTS doctrine_positions (
    doctrine_position_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    problem_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE RESTRICT,
    thesis_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE RESTRICT,
    problem_text TEXT NOT NULL,
    thesis_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'validated'
        CHECK (status IN ('candidate', 'validated', 'rejected', 'unresolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_doctrine_positions_document
    ON doctrine_positions(document_id, ordinal);

CREATE TABLE IF NOT EXISTS doctrine_position_evidence (
    doctrine_position_id TEXT NOT NULL
        REFERENCES doctrine_positions(doctrine_position_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL
        REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL
        CHECK (evidence_role IN ('problem', 'thesis')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(doctrine_position_id, evidence_role)
);

CREATE TABLE IF NOT EXISTS document_identifier_evidence (
    identifier_id TEXT NOT NULL
        REFERENCES document_identifiers(identifier_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL
        REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(identifier_id, evidence_id, evidence_role)
);
