-- v0.1 初始结构：文档、chunk、评测用例、运行记录
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    pk                 INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT    NOT NULL UNIQUE,
    file_name          TEXT    NOT NULL,
    title              TEXT,
    category           TEXT,
    authority          TEXT,
    publish_date       TEXT,
    effective_date     TEXT,
    source_url         TEXT,
    text_sha256        TEXT    NOT NULL,
    index_text_sha256  TEXT,
    normalizer_version INTEGER NOT NULL DEFAULT 0,
    -- chars_total / excluded_chars：以 CHG-002 项五批准为生效前提，未批准前实现不得写入非 0 值
    chars_total        INTEGER NOT NULL DEFAULT 0,
    excluded_chars     INTEGER NOT NULL DEFAULT 0,
    tables_count       INTEGER NOT NULL DEFAULT 0,
    paragraphs         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);

CREATE TABLE IF NOT EXISTS chunks (
    pk            INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id      TEXT    NOT NULL UNIQUE,
    doc_id        TEXT    NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    article_no    TEXT,
    heading_path  TEXT,
    parent_id     TEXT,
    source_format TEXT    NOT NULL DEFAULT 'docx' CHECK (source_format IN ('docx', 'pdf')),
    n_chars       INTEGER NOT NULL,
    UNIQUE (doc_id, seq),
    CHECK (char_end > char_start)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, seq);
CREATE INDEX IF NOT EXISTS idx_chunks_span ON chunks(doc_id, char_start, char_end);

CREATE TABLE IF NOT EXISTS eval_cases (
    case_id            TEXT PRIMARY KEY,
    version_introduced TEXT NOT NULL,
    split              TEXT NOT NULL CHECK (split IN ('dev', 'holdout')),
    query              TEXT NOT NULL,
    doc_id             TEXT NOT NULL,
    article_no         TEXT,
    heading_path       TEXT,
    anchor_text        TEXT,
    char_start         INTEGER,
    char_end           INTEGER,
    difficulty         TEXT,
    anchor_status      TEXT NOT NULL DEFAULT 'candidate' CHECK (anchor_status IN ('candidate', 'confirmed')),
    note               TEXT,
    imported_at        TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (char_start IS NULL OR char_end > char_start)
);

CREATE INDEX IF NOT EXISTS idx_cases_split ON eval_cases(split, anchor_status);

CREATE TABLE IF NOT EXISTS runs (
    run_id             TEXT PRIMARY KEY,
    seed               INTEGER NOT NULL,
    model_name         TEXT    NOT NULL,
    model_version      TEXT    NOT NULL,
    chunk_size         INTEGER NOT NULL,
    overlap            INTEGER NOT NULL,
    top_k              INTEGER NOT NULL,
    cases_sha256       TEXT    NOT NULL,
    corpus_sha256      TEXT    NOT NULL,
    doc_count          INTEGER NOT NULL,
    normalizer_version INTEGER NOT NULL,
    config_hash        TEXT    NOT NULL,
    deps_sha256        TEXT    NOT NULL,
    metrics_json       TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (1, 'init');
