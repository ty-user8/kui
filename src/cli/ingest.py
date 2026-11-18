"""入库入口：解析 → 标题与条号识别 → 固定长度切分 → 写库。

失败按篇记录；失败率超过 `ingest.max_failure_rate` 时整批中止，不写任何数据。
写入完成后断言 documents 行数等于计划入库的文档数、chunks 行数大于 0。

用法（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    .venv\\Scripts\\python.exe -m src.cli.ingest --source v01_subset
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.parse.anchor import build_structure  # noqa: E402
from src.parse.docx_reader import EntryError, check_entry, read_docx  # noqa: E402
from src.split.fixed import split_fixed  # noqa: E402
from src.store import dao  # noqa: E402
from src.store.db import apply_migrations, connect, transaction  # noqa: E402

SOURCE_FORMAT = "docx"


def load_manifest(path: pathlib.Path) -> dict[str, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {record["file_name"]: record for record in records}


def pick_files(conf, source: str) -> list[pathlib.Path]:
    if source == "v01_subset":
        return [conf.corpus.docs_dir / name for name in conf.corpus.v01_subset]
    return sorted(conf.corpus.full_dir.glob("*.docx"))


def build_document(conf, path: pathlib.Path, record: dict) -> tuple[dict, list[dict]]:
    """解析并切分单篇文档，返回（documents 行, chunks 行）。"""
    parsed = read_docx(path)
    structure = build_structure(parsed)
    chunks = split_fixed(
        parsed,
        structure,
        record["doc_id"],
        conf.split.chunk_size,
        conf.split.overlap,
    )
    document = {
        "doc_id": record["doc_id"],
        "file_name": path.name,
        "title": record.get("title"),
        "category": record.get("category"),
        "authority": record.get("authority"),
        "publish_date": record.get("publish_date"),
        "effective_date": record.get("effective_date"),
        "source_url": record.get("source_url"),
        "text_sha256": parsed.text_sha256,
        "index_text_sha256": None,
        "normalizer_version": conf.run.normalizer_version,
        "chars_total": parsed.chars_total,
        "excluded_chars": parsed.excluded_chars,
        "tables_count": parsed.tables_count,
        "paragraphs": len(parsed.paragraphs),
    }
    chunk_rows = [
        {
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "seq": chunk.seq,
            "text": chunk.text,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "article_no": chunk.article_no,
            "heading_path": chunk.heading_path,
            "source_format": SOURCE_FORMAT,
            "n_chars": chunk.n_chars,
        }
        for chunk in chunks
    ]
    return document, chunk_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="按固定长度切分并写入 SQLite")
    parser.add_argument("--source", choices=("v01_subset", "full"), default="v01_subset")
    args = parser.parse_args()

    try:
        conf = load()
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    manifest = load_manifest(conf.corpus.manifest)
    files = pick_files(conf, args.source)
    if not files:
        print("没有可入库的文件：source=%s" % args.source)
        return 2

    planned: list[tuple[dict, list[dict]]] = []
    failures: list[tuple[str, str]] = []
    for path in files:
        record = manifest.get(path.name)
        if record is None:
            failures.append((path.name, "manifest 中无此文件"))
            continue
        try:
            check_entry(path, conf.ingest.max_file_mb, conf.ingest.max_unpacked_mb)
            planned.append(build_document(conf, path, record))
        except EntryError as exc:
            failures.append((path.name, exc.code))

    failure_rate = len(failures) / len(files)
    print("文件 %d 篇，成功解析 %d 篇，失败 %d 篇（失败率 %.1f%%）" % (len(files), len(planned), len(failures), failure_rate * 100))
    for name, code in failures:
        print("  失败 %s: %s" % (name, code))
    if failure_rate > conf.ingest.max_failure_rate:
        print("失败率超过 %.0f%%，整批中止，未写入任何数据" % (conf.ingest.max_failure_rate * 100))
        return 3

    conn = connect(db_path)
    try:
        apply_migrations(conn, conf.paths.migrations_dir)
        with transaction(conn):
            for document, chunk_rows in planned:
                dao.replace_document(conn, document, chunk_rows)
        documents = dao.count_documents(conn)
        chunks = dao.count_chunks(conn)
        formats = dao.format_sources(conn)
    finally:
        conn.close()

    if documents != len(planned) or chunks <= 0:
        print("入库后校验失败：documents=%d（应为 %d）、chunks=%d" % (documents, len(planned), chunks))
        return 4
    if formats != [SOURCE_FORMAT]:
        print("索引中存在非 docx 记录：%s" % formats)
        return 5

    print("入库完成：documents=%d、chunks=%d、source_format=%s、数据库=%s" % (documents, chunks, formats[0], db_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
