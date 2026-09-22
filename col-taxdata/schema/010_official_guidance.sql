CREATE TABLE IF NOT EXISTS official_guidance_metadata (
    document_id TEXT PRIMARY KEY
        REFERENCES documents(document_id) ON DELETE CASCADE,
    guidance_kind TEXT NOT NULL,
    canonical_slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guidance_questions (
    guidance_question_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL
        REFERENCES text_extractions(extraction_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    question_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE RESTRICT,
    question_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'validated'
        CHECK (status IN ('candidate', 'validated', 'rejected', 'unresolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, ordinal),
    UNIQUE(document_id, question_segment_id)
);

CREATE INDEX IF NOT EXISTS idx_guidance_questions_document
    ON guidance_questions(document_id, ordinal);

CREATE TABLE IF NOT EXISTS guidance_answer_segments (
    guidance_question_id TEXT NOT NULL
        REFERENCES guidance_questions(guidance_question_id) ON DELETE CASCADE,
    answer_order INTEGER NOT NULL CHECK (answer_order >= 1),
    extracted_segment_id TEXT NOT NULL
        REFERENCES extracted_segments(extracted_segment_id) ON DELETE RESTRICT,
    answer_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(guidance_question_id, answer_order),
    UNIQUE(guidance_question_id, extracted_segment_id)
);

CREATE TABLE IF NOT EXISTS guidance_question_evidence (
    guidance_question_id TEXT NOT NULL
        REFERENCES guidance_questions(guidance_question_id) ON DELETE CASCADE,
    evidence_role TEXT NOT NULL
        CHECK (evidence_role IN ('question', 'answer')),
    evidence_order INTEGER NOT NULL CHECK (evidence_order >= 0),
    evidence_id TEXT NOT NULL
        REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(guidance_question_id, evidence_role, evidence_order)
);

CREATE INDEX IF NOT EXISTS idx_guidance_question_evidence
    ON guidance_question_evidence(guidance_question_id, evidence_role);
