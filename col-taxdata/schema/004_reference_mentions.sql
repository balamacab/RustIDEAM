CREATE TABLE IF NOT EXISTS reference_detection_runs (
    detection_run_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    detector_name TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    relation_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(extraction_id, detector_name, detector_version)
);

CREATE INDEX IF NOT EXISTS idx_reference_detection_runs_extraction
    ON reference_detection_runs(extraction_id);

CREATE TABLE IF NOT EXISTS reference_mentions (
    reference_mention_id TEXT PRIMARY KEY,
    detection_run_id TEXT NOT NULL
        REFERENCES reference_detection_runs(detection_run_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    extracted_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE CASCADE,
    mention_type TEXT NOT NULL
        CHECK (mention_type IN ('document', 'article')),
    raw_text TEXT NOT NULL,
    context_text TEXT NOT NULL,
    normalized_reference TEXT NOT NULL,
    target_document_key TEXT NOT NULL,
    target_document_type TEXT NOT NULL,
    target_document_number TEXT,
    target_document_year INTEGER,
    article_designation TEXT,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    detection_method TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1)),
    status TEXT NOT NULL DEFAULT 'candidate',
    UNIQUE(
        detection_run_id,
        extracted_segment_id,
        mention_type,
        char_start,
        char_end,
        normalized_reference
    )
);

CREATE INDEX IF NOT EXISTS idx_reference_mentions_target
    ON reference_mentions(target_document_key, article_designation);

CREATE INDEX IF NOT EXISTS idx_reference_mentions_segment
    ON reference_mentions(extracted_segment_id, char_start);

CREATE TABLE IF NOT EXISTS explicit_relation_mentions (
    relation_mention_id TEXT PRIMARY KEY,
    detection_run_id TEXT NOT NULL
        REFERENCES reference_detection_runs(detection_run_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    extracted_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE CASCADE,
    target_reference_mention_id TEXT NOT NULL
        REFERENCES reference_mentions(reference_mention_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'current_document_to_target'
        CHECK (direction = 'current_document_to_target'),
    trigger_text TEXT NOT NULL,
    context_text TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    requires_human_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_human_review IN (0,1)),
    status TEXT NOT NULL DEFAULT 'candidate',
    UNIQUE(
        detection_run_id,
        extracted_segment_id,
        target_reference_mention_id,
        relation_type
    )
);

CREATE INDEX IF NOT EXISTS idx_explicit_relation_mentions_target
    ON explicit_relation_mentions(target_reference_mention_id, relation_type);
