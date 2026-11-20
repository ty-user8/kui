"""把 `data/trace.jsonl`（明细权威）导入 `traces` 表（派生摘要，供 SQL 聚合）。

明细仍以 JSONL 为准，本命令只做「可重复、不重复」的搬运：
- 每行记 `source_run_id` 与 `imported_at`，能追到来源文件里的哪一次运行、何时导入；
- 同一个 `run_id` 重复导入不产生重复行（REQ-045）——按
  `(source_run_id, case_id, query_raw, hit_chunk_id, hit_rank)` 计次对账：文件里出现 N 次、
  表里已有 M 行，就补 N−M 行。既幂等，也不把「同一条 query 真被问了两次」压成一条；
- `--rebuild` 先清空该 `run_id` 的旧行再导入，用于 JSONL 被人工修正后的重建。

JSONL 与表允许短暂不一致（导入失败不影响查询链路），重跑本命令即可对齐（`09-state.md` §4.1）。

用法（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    .venv\\Scripts\\python.exe -m src.cli.import_traces
    .venv\\Scripts\\python.exe -m src.cli.import_traces --run-id r6c23283f2577
    .venv\\Scripts\\python.exe -m src.cli.import_traces --run-id r6c23283f2577 --rebuild
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.store.db import apply_migrations, connect, transaction  # noqa: E402
from src.trace import read_records  # noqa: E402


def trace_key(record: dict) -> tuple:
    """判重键：同一 run 内「问题 + 命中位置」相同即视为同一条。

    不把 `latency_ms`、`flags` 纳入键——它们随环境波动，纳入会让重导入永远判不重。
    """
    return (
        record.get("run_id") or "",
        record.get("case_id") or "",
        record.get("query_raw") or "",
        record.get("hit_chunk_id") or "",
        -1 if record.get("hit_rank") is None else int(record["hit_rank"]),
    )


def load_existing_counts(conn, run_ids: list[str] | None) -> collections.Counter:
    """按判重键统计表里已有多少行。用计数而不是集合：同一条 query 被问过两次，
    JSONL 里就该有两行，导入后表里也该有两行——判重不能把真实重复记录压掉。"""
    sql = "SELECT source_run_id, case_id, query_raw, hit_chunk_id, hit_rank FROM traces"
    params: tuple = ()
    if run_ids:
        sql += " WHERE source_run_id IN (%s)" % ", ".join("?" for _ in run_ids)
        params = tuple(run_ids)
    counts: collections.Counter = collections.Counter()
    for row in conn.execute(sql, params):
        counts[
            (
                row["source_run_id"],
                row["case_id"] or "",
                row["query_raw"] or "",
                row["hit_chunk_id"] or "",
                -1 if row["hit_rank"] is None else int(row["hit_rank"]),
            )
        ] += 1
    return counts


def import_traces(
    conf,
    db_path: pathlib.Path | str | None = None,
    run_ids: list[str] | None = None,
    rebuild: bool = False,
) -> dict:
    """导入 trace；返回条目级统计（读入、写入、跳过、清空、按 run 分组）。"""
    target_db = pathlib.Path(db_path) if db_path else conf.require_db_path()
    records = read_records(conf.paths.trace_file)
    if not records:
        return {"file": str(conf.paths.trace_file), "read": 0, "inserted": 0, "skipped": 0, "purged": 0, "runs": {}}
    if run_ids:
        wanted = set(run_ids)
        records = [record for record in records if (record.get("run_id") or "") in wanted]

    rows: list[tuple] = []
    skipped = 0
    purged = 0
    conn = connect(target_db)
    try:
        apply_migrations(conn, conf.paths.migrations_dir)
        with transaction(conn):
            if rebuild:
                if run_ids:
                    placeholders = ", ".join("?" for _ in run_ids)
                    purged = conn.execute(
                        "DELETE FROM traces WHERE source_run_id IN (%s)" % placeholders, tuple(run_ids)
                    ).rowcount
                else:
                    purged = conn.execute("DELETE FROM traces").rowcount
            existing = collections.Counter() if rebuild else load_existing_counts(conn, run_ids)
            # 每个键「文件里出现几次」减去「表里已有几行」= 本次还差几行；
            # 差 0 就不写，差 2 就补两行，重复导入自然幂等，也不丢真实重复。
            wanted = collections.Counter(trace_key(record) for record in records)
            missing = {key: max(0, count - existing.get(key, 0)) for key, count in wanted.items()}
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            for record in records:
                key = trace_key(record)
                if missing.get(key, 0) <= 0:
                    skipped += 1
                    continue
                missing[key] -= 1
                rows.append(
                    (
                        key[0],
                        record.get("case_id"),
                        record.get("query_raw") or "",
                        record.get("query_norm"),
                        record.get("hit_chunk_id"),
                        record.get("hit_rank"),
                        record.get("excerpt"),
                        json.dumps(record.get("latency_ms") or {}, ensure_ascii=False),
                        stamp,
                    )
                )
            if rows:
                conn.executemany(
                    "INSERT INTO traces (source_run_id, case_id, query_raw, query_norm, hit_chunk_id,"
                    " hit_rank, excerpt, latency_json, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
        summary = {
            record["source_run_id"]: record["n"]
            for record in conn.execute(
                "SELECT source_run_id, COUNT(*) AS n FROM traces GROUP BY source_run_id ORDER BY source_run_id"
            )
        }
    finally:
        conn.close()

    return {
        "file": str(conf.paths.trace_file),
        "read": len(records),
        "inserted": len(rows),
        "skipped": skipped,
        "purged": purged,
        "runs": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="把 trace.jsonl 导入 traces 表（重复导入幂等）")
    parser.add_argument("--run-id", action="append", default=None, help="只导入指定 run_id，可重复")
    parser.add_argument("--rebuild", action="store_true", help="先清空目标 run 的旧行再导入")
    args = parser.parse_args()

    try:
        conf = load()
        conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    result = import_traces(conf, run_ids=args.run_id, rebuild=args.rebuild)
    print(
        "导入完成：读入 %d 条、写入 %d 条、跳过（已存在）%d 条、清空 %d 条"
        % (result["read"], result["inserted"], result["skipped"], result["purged"])
    )
    if result["runs"]:
        print("表内按 run 汇总：")
        for run_id, count in result["runs"].items():
            print("  %-16s %d 条" % (run_id, count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
