"""数据访问：documents / chunks 的写入与计数。

同一 `doc_id` 重复入库时先删旧 chunk 再写新行，保证“要么全旧、要么全新”，
不产生重复 chunk；删除与写入由调用方包在同一个事务里。
"""

from __future__ import annotations

import sqlite3

DOCUMENT_COLUMNS = (
    "doc_id",
    "file_name",
    "title",
    "category",
    "authority",
    "publish_date",
    "effective_date",
    "source_url",
    "text_sha256",
    "index_text_sha256",
    "normalizer_version",
    "chars_total",
    "excluded_chars",
    "tables_count",
    "paragraphs",
)


def replace_document(conn: sqlite3.Connection, document: dict, chunks: list[dict]) -> None:
    """写入一篇文档及其 chunk；已存在则先清空旧 chunk 与旧行。"""
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (document["doc_id"],))
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (document["doc_id"],))
    placeholders = ", ".join("?" for _ in DOCUMENT_COLUMNS)
    conn.execute(
        "INSERT INTO documents (%s) VALUES (%s)" % (", ".join(DOCUMENT_COLUMNS), placeholders),
        tuple(document[column] for column in DOCUMENT_COLUMNS),
    )
    if chunks:
        conn.executemany(
            "INSERT INTO chunks (chunk_id, doc_id, seq, text, char_start, char_end, article_no,"
            " heading_path, parent_id, source_format, n_chars)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            [
                (
                    chunk["chunk_id"],
                    chunk["doc_id"],
                    chunk["seq"],
                    chunk["text"],
                    chunk["char_start"],
                    chunk["char_end"],
                    chunk["article_no"],
                    chunk["heading_path"],
                    chunk["source_format"],
                    chunk["n_chars"],
                )
                for chunk in chunks
            ],
        )


def count_documents(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])


def count_chunks(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])


def format_sources(conn: sqlite3.Connection) -> list[str]:
    """返回索引中出现的 source_format 取值，用于断言只含 docx。"""
    return [row[0] for row in conn.execute("SELECT DISTINCT source_format FROM chunks ORDER BY 1")]


def document_digest(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT doc_id, text_sha256, chars_total, excluded_chars FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()


def upsert_run(conn: sqlite3.Connection, row: dict) -> None:
    """写入或更新一次运行记录；同一 run_id 只保留最后一条指标快照。"""
    columns = (
        "run_id",
        "seed",
        "model_name",
        "model_version",
        "chunk_size",
        "overlap",
        "top_k",
        "cases_sha256",
        "corpus_sha256",
        "doc_count",
        "normalizer_version",
        "config_hash",
        "deps_sha256",
        "metrics_json",
    )
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join("%s = excluded.%s" % (column, column) for column in columns if column != "run_id")
    conn.execute(
        "INSERT INTO runs (%s) VALUES (%s) ON CONFLICT(run_id) DO UPDATE SET %s, created_at = datetime('now')"
        % (", ".join(columns), placeholders, updates),
        tuple(row[column] for column in columns),
    )
