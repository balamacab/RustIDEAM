CREATE TABLE IF NOT EXISTS relationship_provenance (
    relationship_id TEXT PRIMARY KEY
        REFERENCES relationships(relationship_id) ON DELETE CASCADE,
    relation_mention_id TEXT NOT NULL
        REFERENCES explicit_relation_mentions(relation_mention_id) ON DELETE RESTRICT,
    reference_resolution_id TEXT NOT NULL
        REFERENCES reference_resolutions(reference_resolution_id) ON DELETE RESTRICT,
    promoter_name TEXT NOT NULL,
    promoter_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(relation_mention_id, reference_resolution_id)
);

CREATE INDEX IF NOT EXISTS idx_relationship_provenance_relation_mention
    ON relationship_provenance(relation_mention_id);

CREATE INDEX IF NOT EXISTS idx_relationship_provenance_resolution
    ON relationship_provenance(reference_resolution_id);
