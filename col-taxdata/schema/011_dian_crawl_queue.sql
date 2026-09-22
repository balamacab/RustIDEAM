CREATE TABLE IF NOT EXISTS dian_crawl_queue (
    url TEXT PRIMARY KEY,
    item_type TEXT NOT NULL
        CHECK (item_type IN ('index', 'document')),
    scope TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'error')),
    attempts INTEGER NOT NULL DEFAULT 0,
    source_id TEXT,
    manifestation_id TEXT,
    extraction_id TEXT,
    content_sha256 TEXT,
    processing_json TEXT,
    last_error TEXT,
    first_seen_at TEXT NOT NULL,
    last_attempt_at TEXT,
    completed_at TEXT,
    next_attempt_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dian_crawl_queue_due
ON dian_crawl_queue(status, next_attempt_at, item_type, depth);

CREATE TABLE IF NOT EXISTS dian_discovery_edges (
    parent_url TEXT NOT NULL,
    child_url TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY(parent_url, child_url)
);

CREATE INDEX IF NOT EXISTS idx_dian_discovery_edges_child
ON dian_discovery_edges(child_url);
