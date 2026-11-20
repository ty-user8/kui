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
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.parse.anchor import build_structure  # noqa: E402
from src.parse.docx_reader import EntryError, check_entry, read_docx  # noqa: E402
from src.split.fixed import split_fixed  # noqa: E402
from src.split.parent import build_children, build_parents  # noqa: E402
from src.split.recursive import split_recursive  # noqa: E402
from src.split.sliding import split_sliding  # noqa: E402
from src.store import dao  # noqa: E402
from src.store.db import apply_migrations, connect, transaction  # noqa: E402

SOURCE_FORMAT = "docx"
INGEST_RUN_ID = "ingest-" + time.strftime("%Y%m%dT%H%M%S")
SPLITTERS = {"fixed": split_fixed, "recursive": split_recursive, "sliding": split_sliding}


def load_manifest(path: pathlib.Path) -> dict[str, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {record["file_name"]: record for record in records}


def pick_files(conf, source: str) -> list[pathlib.Path]:
    if source == "v01_subset":
        return [conf.corpus.docs_dir / name for name in conf.corpus.v01_subset]
    return sorted(conf.corpus.full_dir.glob("*.docx"))


def decide_action(
    doc_id: str,
    digest: str,
    existing: dict[str, str],
    seen: dict[str, str],
    force: bool = False,
) -> tuple[str, str | None]:
    """决定单个文件的入库动作：insert / skip 及原因。`seen` 是本批已见的内容哈希 → doc_id。"""
    if force:
        return "insert", "content_changed" if doc_id in existing else "new"
    duplicate_of = seen.get(digest)
    if duplicate_of and duplicate_of != doc_id:
        return "skip", "duplicate_content:%s" % duplicate_of
    if existing.get(doc_id) == digest:
        return "skip", "unchanged"
    return "insert", "content_changed" if doc_id in existing else "new"


def build_document(conf, path: pathlib.Path, record: dict, parent_child: bool = False) -> tuple[dict, list[dict], list[dict]]:
    """解析并切分单篇文档，返回（documents 行, chunks 行）。"""
    parsed = read_docx(path)
    structure = build_structure(parsed)
    parent_rows: list[dict] = []
    if parent_child:
        parents = build_parents(parsed, structure, record["doc_id"])
        chunks = build_children(parents, record["doc_id"], conf.split.chunk_size, conf.split.overlap)
        parent_rows = [
            {
                "parent_id": item.parent_id,
                "doc_id": item.doc_id,
                "seq": item.seq,
                "text": item.text,
                "char_start": item.char_start,
                "char_end": item.char_end,
                "article_no": item.article_no,
                "heading_path": item.heading_path,
                "n_chars": item.n_chars,
            }
            for item in parents
        ]
    else:
        splitter = SPLITTERS[conf.split.strategy]
        chunks = splitter(
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
            "parent_id": chunk.parent_id,
        }
        for chunk in chunks
    ]
    return document, chunk_rows, parent_rows


class IngestAborted(RuntimeError):
    """入库被中止（无文件可入、失败率超限、写后校验不通过）。

    携带结构化 `code` 与条目级 `failed`，供命令行打印、接口映射成 4xx——
    中止原因不靠解析 stdout 文本，避免接口层猜。
    """

    def __init__(self, code: str, message: str, failed: list[dict] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.failed = failed or []


def run_ingest(
    conf,
    source: str = "v01_subset",
    parent_child: bool = False,
    force: bool = False,
    doc_ids: list[str] | None = None,
) -> dict:
    """执行一次入库（默认增量），返回条目级结果。

    不解析命令行、不 `sys.exit`：命令行与接口都调这里，异常统一走 `IngestAborted`。
    """
    db_path = conf.require_db_path()
    manifest = load_manifest(conf.corpus.manifest)
    files = pick_files(conf, source)
    if doc_ids:
        wanted = set(doc_ids)
        files = [path for path in files if manifest.get(path.name, {}).get("doc_id") in wanted]
    if not files:
        raise IngestAborted("INVALID_REQUEST", "没有可入库的文件：source=%s、doc_ids=%s" % (source, doc_ids or "全部"))

    conn = connect(db_path)
    apply_migrations(conn, conf.paths.migrations_dir)
    existing = {row["doc_id"]: row["text_sha256"] for row in conn.execute("SELECT doc_id, text_sha256 FROM documents")}
    conn.close()

    planned: list[tuple[dict, list[dict], list[dict]]] = []
    failures: list[tuple[str, str]] = []
    log_rows: list[tuple[str, str | None, str, str, str | None]] = []
    seen_hash: dict[str, str] = {}
    skipped_unchanged = skipped_duplicate = 0
    for path in files:
        record = manifest.get(path.name)
        if record is None:
            failures.append((path.name, "manifest 中无此文件"))
            log_rows.append((INGEST_RUN_ID, None, path.name, "fail", "no_manifest"))
            continue
        try:
            check_entry(path, conf.ingest.max_file_mb, conf.ingest.max_unpacked_mb)
            document, chunk_rows, parent_rows = build_document(conf, path, record, parent_child=parent_child)
        except EntryError as exc:
            failures.append((path.name, exc.code))
            log_rows.append((INGEST_RUN_ID, record["doc_id"], path.name, "fail", exc.code))
            continue

        digest = document["text_sha256"]
        action, reason = decide_action(document["doc_id"], digest, existing, seen_hash, force)
        if action == "skip":
            if reason and reason.startswith("duplicate_content"):
                skipped_duplicate += 1
            else:
                skipped_unchanged += 1
            log_rows.append((INGEST_RUN_ID, document["doc_id"], path.name, "skip", reason))
            continue
        seen_hash[digest] = document["doc_id"]
        planned.append((document, chunk_rows, parent_rows))
        log_rows.append((INGEST_RUN_ID, document["doc_id"], path.name, "insert", reason))

    failure_rate = len(failures) / len(files)
    failed_items = [{"file_name": name, "reason": code} for name, code in failures]
    if failure_rate > conf.ingest.max_failure_rate:
        # 失败率超限：整批不写，避免半批数据（11-errors.md「事务写入失败」不可降级）
        raise IngestAborted(
            "PARSE_FAILURE_RATE_EXCEEDED",
            "失败率 %.1f%% 超过上限 %.0f%%，整批中止，未写入任何数据"
            % (failure_rate * 100, conf.ingest.max_failure_rate * 100),
            failed_items,
        )

    conn = connect(db_path)
    try:
        with transaction(conn):
            for document, chunk_rows, parent_rows in planned:
                dao.replace_document(conn, document, chunk_rows, parent_rows)
            if log_rows:
                conn.executemany(
                    "INSERT INTO ingest_log (run_id, doc_id, file_name, action, reason) VALUES (?, ?, ?, ?, ?)",
                    log_rows,
                )
        documents = dao.count_documents(conn)
        chunks = dao.count_chunks(conn)
        parents = dao.count_parents(conn)
        formats = dao.format_sources(conn)
    finally:
        conn.close()

    # 只校验本批清单内的文档是否落库，兼容「增量跳过」与「库里原有更多文档」两种情况
    listed = sorted({manifest[path.name]["doc_id"] for path in files if path.name in manifest})
    conn = connect(db_path)
    try:
        placeholders = ", ".join("?" for _ in listed)
        present = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE doc_id IN (%s)" % placeholders, tuple(listed)
        ).fetchone()[0]
    finally:
        conn.close()
    if present != len(listed) or chunks <= 0:
        raise IngestAborted(
            "INTERNAL_ERROR",
            "入库后校验失败：清单 %d 篇、库内命中 %d 篇、chunks=%d" % (len(listed), present, chunks),
            failed_items,
        )
    if formats != [SOURCE_FORMAT]:
        raise IngestAborted("INTERNAL_ERROR", "索引中存在非 docx 记录：%s" % formats, failed_items)

    report, report_path = write_quality_report(conf, db_path, documents, chunks, parents)
    return {
        "run_id": INGEST_RUN_ID,
        "source": source,
        "documents": documents,
        "chunks": chunks,
        "parents": parents,
        "inserted": len(planned),
        "skipped": skipped_unchanged + skipped_duplicate,
        "skipped_unchanged": skipped_unchanged,
        "skipped_duplicate": skipped_duplicate,
        "failed": failed_items,
        "failure_rate": round(failure_rate, 6),
        "quality": report,
        "report_path": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按固定长度切分并写入 SQLite")
    parser.add_argument("--source", choices=("v01_subset", "full"), default="v01_subset")
    parser.add_argument("--parent-child", action="store_true", help="按父子结构入库：parent 聚合、child 建索引")
    parser.add_argument("--force", action="store_true", help="忽略内容哈希，全量重写（默认增量：内容未变则跳过）")
    parser.add_argument(
        "--strategy",
        choices=tuple(SPLITTERS),
        default=None,
        help="覆盖 config 的 split.strategy：fixed / recursive / sliding",
    )
    args = parser.parse_args()

    try:
        conf = load()
        conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    if args.strategy is not None:
        import dataclasses

        conf = dataclasses.replace(conf, split=dataclasses.replace(conf.split, strategy=args.strategy))

    try:
        result = run_ingest(conf, source=args.source, parent_child=args.parent_child, force=args.force)
    except IngestAborted as exc:
        print(exc.message)
        for item in exc.failed:
            print("  失败 %s: %s" % (item["file_name"], item["reason"]))
        return 3 if exc.code == "PARSE_FAILURE_RATE_EXCEEDED" else 4

    print(
        "文件 %d 篇：待写入 %d、内容未变 %d、重复内容 %d、失败 %d（失败率 %.1f%%）"
        % (
            result["inserted"] + result["skipped"] + len(result["failed"]),
            result["inserted"],
            result["skipped_unchanged"],
            result["skipped_duplicate"],
            len(result["failed"]),
            result["failure_rate"] * 100,
        )
    )
    for item in result["failed"]:
        print("  失败 %s: %s" % (item["file_name"], item["reason"]))
    print(
        "入库完成：documents=%d、chunks=%d、parents=%d、source_format=%s"
        % (result["documents"], result["chunks"], result["parents"], SOURCE_FORMAT)
    )
    quality = result["quality"]
    print(
        "质量报告：字符 %d（表格排除 %d，占 %.2f%%）、含表格文档 %d 篇、条号覆盖 %.1f%% → %s"
        % (
            quality["chars_total"],
            quality["excluded_chars"],
            quality["excluded_ratio"] * 100,
            quality["tables_count"],
            quality["article_coverage"] * 100,
            result["report_path"],
        )
    )
    return 0


def write_quality_report(conf, db_path, documents: int, chunks: int, parents: int) -> tuple[dict, pathlib.Path]:
    """质量报告：字符守恒、表格排除量、条号覆盖（CHG-002 项五要求含 `excluded_chars`）。"""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT SUM(chars_total), SUM(excluded_chars), SUM(tables_count), COUNT(*) FROM documents"
        ).fetchone()
        with_article = conn.execute("SELECT COUNT(*) FROM chunks WHERE article_no IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    total_chars, excluded, tables, _ = row[0] or 0, row[1] or 0, row[2] or 0, row[3]
    report = {
        "run_id": INGEST_RUN_ID,
        "documents": documents,
        "chunks": chunks,
        "parents": parents,
        "chars_total": int(total_chars),
        "excluded_chars": int(excluded),
        "excluded_ratio": round(excluded / total_chars, 6) if total_chars else 0.0,
        "tables_count": int(tables),
        "chunks_with_article": int(with_article),
        "article_coverage": round(with_article / chunks, 6) if chunks else 0.0,
    }
    target = pathlib.Path(conf.resolve(conf.paths.data_dir)) / "ingest-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report, target


if __name__ == "__main__":
    raise SystemExit(main())
