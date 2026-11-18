-- v0.4 运行期结构：trace 派生物与入库日志
PRAGMA foreign_keys = ON;

-- 由 data/trace.jsonl 导入生成，非直接写入；明细权威在 JSONL，表只存摘要字段
CREATE TABLE IF NOT EXISTS traces (
    trace_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_run_id TEXT    NOT NULL,
    case_id       TEXT,
    query_raw     TEXT    NOT NULL,
    query_norm    TEXT,
    hit_chunk_id  TEXT,
    hit_rank      INTEGER,
    excerpt       TEXT,
    latency_json  TEXT,
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(source_run_id, case_id);

CREATE TABLE IF NOT EXISTS ingest_log (
    pk          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    doc_id      TEXT,
    file_name   TEXT    NOT NULL,
    action      TEXT    NOT NULL CHECK (action IN ('insert', 'skip', 'fail')),
    reason      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ingest_log_run ON ingest_log(run_id, action);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (3, 'runtime');
