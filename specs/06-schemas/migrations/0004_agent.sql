-- 0004：Agent 会话与轮次（`CHG-013` §8.2；D2 读时按 session_ttl_hours 判定过期，无后台清理）。
-- 只新增两张表，不动 0001~0003 的任何既有表/索引；这两张表不被 /search、/eval、ci_check 读取。

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id      TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at  TEXT NOT NULL DEFAULT (datetime('now')),
    stateless_mode  INTEGER NOT NULL DEFAULT 0 CHECK (stateless_mode IN (0, 1)),
    turn_count      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_turns (
    pk               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    turn_no          INTEGER NOT NULL,
    query_raw        TEXT NOT NULL,
    query_rewritten  TEXT,
    rewrite_rule     TEXT,
    tool_calls_json  TEXT,
    answer           TEXT,
    citations_json   TEXT,
    citation_valid   INTEGER,
    flags            TEXT,
    elapsed_ms       REAL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, turn_no)
);

CREATE INDEX IF NOT EXISTS idx_agent_turns_session ON agent_turns(session_id, turn_no);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (4, 'agent');
