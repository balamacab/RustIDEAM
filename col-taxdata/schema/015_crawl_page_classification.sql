-- DEF-0010: make crawler page classification explicit and durable.
-- Existing queue rows remain unclassified until deterministic processing or
-- an explicit preview/apply reclassification evaluates them.
ALTER TABLE dian_crawl_queue
ADD COLUMN classification_state TEXT NOT NULL DEFAULT 'unclassified'
    CHECK (classification_state IN (
        'unclassified',
        'confirmed_index',
        'legal_document',
        'legal_extraction_failure',
        'ambiguous'
    ));

ALTER TABLE dian_crawl_queue
ADD COLUMN classification_json TEXT;

CREATE INDEX IF NOT EXISTS idx_dian_crawl_queue_classification
ON dian_crawl_queue(classification_state, status, item_type);
