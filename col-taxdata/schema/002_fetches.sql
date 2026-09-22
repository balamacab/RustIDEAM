CREATE TABLE IF NOT EXISTS fetches (
    fetch_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    byte_size INTEGER,
    sha256 TEXT,
    etag TEXT,
    last_modified TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_fetches_source_time
    ON fetches(source_id, started_at);

CREATE INDEX IF NOT EXISTS idx_fetches_sha256
    ON fetches(sha256);
