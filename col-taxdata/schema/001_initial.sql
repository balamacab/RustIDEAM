PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    jurisdiction TEXT NOT NULL DEFAULT 'CO',
    entity TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT,
    issued_date TEXT,
    publication_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_identifiers (
    identifier_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    issuer TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    UNIQUE(document_id, identifier_type, identifier_value)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    authority TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    discovered_from TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source_url)
);

CREATE TABLE IF NOT EXISTS manifestations (
    manifestation_id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(document_id) ON DELETE SET NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    content_type TEXT,
    sha256 TEXT NOT NULL,
    byte_size INTEGER,
    retrieved_at TEXT NOT NULL,
    http_etag TEXT,
    http_last_modified TEXT,
    local_path TEXT NOT NULL,
    parser_version TEXT,
    UNIQUE(sha256, source_id)
);

CREATE INDEX IF NOT EXISTS idx_manifestations_sha256
    ON manifestations(sha256);

CREATE TABLE IF NOT EXISTS segments (
    segment_id TEXT PRIMARY KEY,
    manifestation_id TEXT NOT NULL REFERENCES manifestations(manifestation_id) ON DELETE CASCADE,
    segment_type TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    page_number INTEGER,
    section_path TEXT,
    char_start INTEGER,
    char_end INTEGER,
    text TEXT NOT NULL,
    text_sha256 TEXT,
    UNIQUE(manifestation_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    object_literal TEXT,
    claim_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN (
            'candidate',
            'validated',
            'rejected',
            'conflicting',
            'unresolved',
            'human_verified'
        )),
    extraction_method TEXT NOT NULL,
    confidence_extraction REAL
        CHECK (confidence_extraction IS NULL OR
               (confidence_extraction >= 0.0 AND confidence_extraction <= 1.0)),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES claims(claim_id) ON DELETE CASCADE,
    manifestation_id TEXT NOT NULL REFERENCES manifestations(manifestation_id) ON DELETE CASCADE,
    segment_id TEXT REFERENCES segments(segment_id) ON DELETE SET NULL,
    page_number INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    exact_quote TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    extraction_method TEXT,
    extractor_version TEXT,
    confidence REAL
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    scope TEXT,
    asserted_date TEXT,
    effective_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    evidence_id TEXT REFERENCES evidence(evidence_id) ON DELETE SET NULL,
    confidence REAL
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_relationships_source
    ON relationships(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_relationships_target
    ON relationships(target_type, target_id);

CREATE TABLE IF NOT EXISTS temporal_events (
    temporal_event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT,
    effective_from TEXT,
    effective_to TEXT,
    caused_by_type TEXT,
    caused_by_id TEXT,
    scope TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    evidence_id TEXT REFERENCES evidence(evidence_id) ON DELETE SET NULL,
    confidence REAL
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_temporal_entity
    ON temporal_events(entity_type, entity_id, effective_from);

CREATE TABLE IF NOT EXISTS extraction_runs (
    extraction_run_id TEXT PRIMARY KEY,
    processor_name TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    model_name TEXT,
    model_sha256 TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    configuration_hash TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    raw_output TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
    review_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    reviewer TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_open
    ON review_queue(resolved_at, severity, reason_code);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    processor_name TEXT NOT NULL,
    input_identity TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(processor_name, input_identity, processor_version, configuration_hash)
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    query_text TEXT NOT NULL,
    as_of_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_items (
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    relevance TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY(case_id, item_type, item_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS segment_fts USING fts5(
    segment_id UNINDEXED,
    text,
    section_path,
    content=''
);
