CREATE TABLE IF NOT EXISTS text_extractions (
    extraction_id TEXT PRIMARY KEY,
    manifestation_id TEXT NOT NULL
        REFERENCES manifestations(manifestation_id) ON DELETE CASCADE,
    extractor_name TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    normalized_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(manifestation_id, extractor_name, extractor_version)
);

CREATE INDEX IF NOT EXISTS idx_text_extractions_manifestation
    ON text_extractions(manifestation_id);

CREATE INDEX IF NOT EXISTS idx_text_extractions_sha256
    ON text_extractions(normalized_sha256);

CREATE TABLE IF NOT EXISTS extracted_segments (
    extracted_segment_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    segment_type TEXT NOT NULL,
    section_path TEXT,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    UNIQUE(extraction_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS idx_extracted_segments_extraction
    ON extracted_segments(extraction_id, sequence_no);

CREATE VIRTUAL TABLE IF NOT EXISTS extracted_segments_fts USING fts5(
    extracted_segment_id UNINDEXED,
    text,
    section_path,
    content=''
);

ALTER TABLE evidence ADD COLUMN extracted_segment_id TEXT
    REFERENCES extracted_segments(extracted_segment_id) ON DELETE SET NULL;
