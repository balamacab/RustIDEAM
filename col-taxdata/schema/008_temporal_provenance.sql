CREATE TABLE IF NOT EXISTS temporal_event_evidence (
    temporal_event_id TEXT NOT NULL
        REFERENCES temporal_events(temporal_event_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL
        REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(temporal_event_id, evidence_id, evidence_role)
);

CREATE INDEX IF NOT EXISTS idx_temporal_event_evidence_evidence
    ON temporal_event_evidence(evidence_id);

CREATE TABLE IF NOT EXISTS relationship_temporal_basis (
    relationship_id TEXT NOT NULL
        REFERENCES relationships(relationship_id) ON DELETE CASCADE,
    temporal_event_id TEXT NOT NULL
        REFERENCES temporal_events(temporal_event_id) ON DELETE RESTRICT,
    basis_role TEXT NOT NULL
        CHECK (basis_role IN ('asserted_date', 'effective_date', 'end_date')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(relationship_id, basis_role)
);

CREATE INDEX IF NOT EXISTS idx_relationship_temporal_basis_event
    ON relationship_temporal_basis(temporal_event_id);
