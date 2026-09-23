-- DEF-0002: persist normalized issuer identity and migration provenance.
-- Existing raw evidence and applied migrations remain untouched.

ALTER TABLE document_identity_signals ADD COLUMN issuer_key TEXT;
ALTER TABLE reference_mentions ADD COLUMN target_issuer TEXT;

CREATE INDEX IF NOT EXISTS idx_document_identifiers_lookup_issuer
    ON document_identifiers(identifier_type, identifier_value, issuer, is_primary);

CREATE INDEX IF NOT EXISTS idx_reference_mentions_target_issuer
    ON reference_mentions(target_document_key, target_issuer, article_designation);

CREATE TABLE IF NOT EXISTS document_identity_migrations (
    migration_id TEXT PRIMARY KEY,
    manifestation_id TEXT NOT NULL
        REFERENCES manifestations(manifestation_id) ON DELETE RESTRICT,
    legacy_document_id TEXT NOT NULL,
    new_document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE RESTRICT,
    legacy_canonical_key TEXT NOT NULL,
    new_canonical_key TEXT NOT NULL,
    issuer_key TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    migrated_at TEXT NOT NULL,
    UNIQUE(manifestation_id, new_document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_identity_migrations_legacy
    ON document_identity_migrations(legacy_document_id, issuer_key);
