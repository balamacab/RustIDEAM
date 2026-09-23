-- DEF-0004: persist every temporal evidence candidate and the per-role
-- resolution decision. Raw evidence is not modified; these tables are derived
-- state and can be rebuilt by a later extractor version.
CREATE TABLE IF NOT EXISTS temporal_candidates (
    temporal_candidate_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    manifestation_id TEXT NOT NULL
        REFERENCES manifestations(manifestation_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    extracted_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE CASCADE,
    role TEXT NOT NULL
        CHECK (role IN ('publication_date', 'issued_date', 'commencement_rule')),
    candidate_date TEXT,
    context_type TEXT NOT NULL
        CHECK (context_type IN (
            'primary_document_date',
            'publication_metadata',
            'commencement_clause',
            'editorial_history',
            'quoted_cited_norm',
            'unknown'
        )),
    is_trusted_structure INTEGER NOT NULL
        CHECK (is_trusted_structure IN (0,1)),
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    exact_quote TEXT NOT NULL,
    evidence_id TEXT NOT NULL
        REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
    processor_name TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(
        extraction_id,
        role,
        extracted_segment_id,
        char_start,
        char_end,
        processor_name,
        processor_version
    )
);

CREATE INDEX IF NOT EXISTS idx_temporal_candidates_document_role
    ON temporal_candidates(document_id, role, processor_version);

CREATE INDEX IF NOT EXISTS idx_temporal_candidates_extraction
    ON temporal_candidates(extraction_id, processor_version);

CREATE TABLE IF NOT EXISTS temporal_role_resolutions (
    temporal_resolution_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    role TEXT NOT NULL
        CHECK (role IN ('publication_date', 'issued_date', 'commencement_rule')),
    status TEXT NOT NULL
        CHECK (status IN ('resolved', 'unresolved', 'ambiguous')),
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    trusted_candidate_count INTEGER NOT NULL CHECK (trusted_candidate_count >= 0),
    promoted_candidate_id TEXT
        REFERENCES temporal_candidates(temporal_candidate_id) ON DELETE RESTRICT,
    processor_name TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(extraction_id, role, processor_name, processor_version),
    CHECK (
        (status = 'resolved' AND promoted_candidate_id IS NOT NULL)
        OR
        (status != 'resolved' AND promoted_candidate_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_temporal_role_resolutions_document
    ON temporal_role_resolutions(document_id, status, processor_version);
