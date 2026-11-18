-- v0.3 父段落表：small-to-big 的 parent 侧，只被 child 引用
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS parents (
    parent_id    TEXT PRIMARY KEY,
    doc_id       TEXT    NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    text         TEXT    NOT NULL,
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL,
    article_no   TEXT,
    heading_path TEXT,
    n_chars      INTEGER NOT NULL,
    UNIQUE (doc_id, seq),
    CHECK (char_end > char_start)
);

CREATE INDEX IF NOT EXISTS idx_parents_doc ON parents(doc_id, seq);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (2, 'parents');
