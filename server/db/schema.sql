-- Fin Assistant PostgreSQL + pgvector Schema
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 1. Persistent Chat Sessions & Messages
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    model TEXT NOT NULL DEFAULT 'Fin:latest',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, created_at ASC);

-- 2. Phone SMS/MMS Messages (Relational + Full-Text + Vector Embedding)
CREATE TABLE IF NOT EXISTS sms_messages (
    id VARCHAR(32) PRIMARY KEY,
    address TEXT NOT NULL,
    contact_name TEXT,
    body TEXT NOT NULL,
    msg_date BIGINT NOT NULL DEFAULT 0,
    msg_type VARCHAR(16) DEFAULT '',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(address, '') || ' ' || coalesce(contact_name, '') || ' ' || coalesce(body, ''))
    ) STORED,
    embedding vector(768)
);
CREATE INDEX IF NOT EXISTS idx_sms_date ON sms_messages (msg_date DESC);
CREATE INDEX IF NOT EXISTS idx_sms_address ON sms_messages (address);
CREATE INDEX IF NOT EXISTS idx_sms_tsv ON sms_messages USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_sms_embedding ON sms_messages USING hnsw (embedding vector_cosine_ops);

-- 3. Long-Term Semantic & Episodic Memory (pgvector)
CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    category VARCHAR(64) NOT NULL DEFAULT 'general',
    subject TEXT DEFAULT '',
    content TEXT NOT NULL UNIQUE,
    source_type VARCHAR(32) NOT NULL DEFAULT 'chat',
    source_ref TEXT DEFAULT '',
    importance SMALLINT NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(subject, '') || ' ' || coalesce(content, ''))
    ) STORED,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memories_tsv ON memories USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories (category);

-- 4. Human-in-the-Loop Pending Approvals Queue
CREATE TABLE IF NOT EXISTS pending_approvals (
    id VARCHAR(12) PRIMARY KEY,
    action_type VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    result_text TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals (status, created_at DESC);

-- 5. Tasks, Reminders & Job Application Tracker
CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT DEFAULT '',
    category VARCHAR(32) NOT NULL DEFAULT 'general',
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, created_at DESC);

-- 6. Tool & MCP Execution Audit Log
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments JSONB,
    result_preview TEXT,
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs (created_at DESC);
