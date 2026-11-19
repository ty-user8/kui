"""trace 追加写：一行一条 JSON，字段固定，跨平台文件锁保护整行写入。

字段按 `specs/09-state.md` §4 定义，只增不改；`excerpt` 取命中 chunk 前 80 个码点（D-009）。
不写完整原文、密钥、用户目录绝对路径——记录由白名单字段构造，不接受任意 dict 透传。

并发安全：每次写入单独 open 一个 fd，写入前对文件首字节加平台锁
（POSIX `fcntl.flock` / Windows `msvcrt.locking`），写完解锁，不新增依赖。
"""

from __future__ import annotations

import json
import os
import pathlib
import time

EXCERPT_CHARS = 80
TRACE_FIELDS = (
    "run_id",
    "case_id",
    "query_raw",
    "query_norm",
    "dense",
    "bm25",
    "fused",
    "reranked",
    "hit_chunk_id",
    "hit_rank",
    "excerpt",
    "latency_ms",
    "flags",
)


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """取前 `limit` 个码点，换行折成空格以保持单行可读。"""
    flat = text.replace("\r", " ").replace("\n", " ")
    return flat[:limit]


def _lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _hits(pairs: list[tuple[str, float]]) -> list[dict]:
    return [{"chunk_id": chunk_id, "score": round(float(score), 6), "rank": rank} for rank, (chunk_id, score) in enumerate(pairs, start=1)]


def build_record(
    run_id: str,
    query_raw: str,
    dense: list[tuple[str, float]] | None = None,
    bm25: list[tuple[str, float]] | None = None,
    fused: list[tuple[str, float]] | None = None,
    hit_chunk_id: str | None = None,
    hit_rank: int | None = None,
    hit_text: str | None = None,
    case_id: str | None = None,
    latency_ms: dict | None = None,
    query_norm: str | None = None,
    reranked: list[tuple[str, float]] | None = None,
    flags: list[str] | None = None,
) -> dict:
    """按固定字段顺序组装一条 trace；未使用的版本字段写 None 而不是省略。"""
    record = {
        "run_id": run_id,
        "case_id": case_id,
        "query_raw": query_raw,
        "query_norm": query_norm,
        "dense": _hits(dense or []),
        "bm25": _hits(bm25 or []),
        "fused": [chunk_id for chunk_id, _ in (fused or [])],
        "reranked": [chunk_id for chunk_id, _ in (reranked or [])] if reranked else None,
        "hit_chunk_id": hit_chunk_id,
        "hit_rank": hit_rank,
        "excerpt": excerpt(hit_text) if hit_text else None,
        "latency_ms": {k: round(float(v), 2) for k, v in (latency_ms or {}).items()},
        "flags": list(flags or []),
    }
    return {field: record[field] for field in TRACE_FIELDS}


class TraceWriter:
    """追加写 trace.jsonl；父目录不存在时创建。"""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        missing = [field for field in TRACE_FIELDS if field not in record]
        if missing:
            raise ValueError("trace 缺少字段：%s" % ", ".join(missing))
        line = json.dumps({field: record[field] for field in TRACE_FIELDS}, ensure_ascii=False)
        # 用独立的 .lock 文件做互斥令牌：直接锁数据文件时，Windows 上并发 open 会因区域锁冲突
        # 报 PermissionError（实测 4 线程写 100 行只落 75 行）。锁文件常驻，不删除以免竞态。
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+b") as guard:
            _lock(guard)
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                _unlock(guard)

    def write_many(self, records: list[dict]) -> int:
        for record in records:
            self.write(record)
        return len(records)


def read_records(path: pathlib.Path | str, run_id: str | None = None) -> list[dict]:
    """读回 trace；可按 `run_id` 过滤。坏行跳过并计数。"""
    records: list[dict] = []
    target = pathlib.Path(path)
    if not target.is_file():
        return records
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is None or record.get("run_id") == run_id:
                records.append(record)
    return records


def main() -> int:
    """自检：真实检索写 3 条 trace，再做 4 线程并发写校验。"""
    import sys
    import threading

    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.config import ConfigError, load
    from src.retrieve.hybrid import HybridRetriever

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    from src.index import bm25_index
    from src.retrieve.dense import DenseRetriever

    retriever = HybridRetriever(
        dense=DenseRetriever(conf),
        bm25=bm25_index.load(conf.paths.index_dir),
        rrf_k=conf.retrieval.rrf_k,
        candidate_k=conf.retrieval.candidate_k,
    )
    # 自检写独立文件，不污染正式 trace.jsonl
    probe_file = pathlib.Path(conf.paths.trace_file).with_name("trace-selftest.jsonl")
    if probe_file.exists():
        probe_file.unlink()
    writer = TraceWriter(probe_file)
    run_id = "selftest-trace"
    for query in ("发明专利权的期限是几年", "发现数据安全漏洞后要马上做什么", "程序化交易要符合什么要求"):
        started = time.perf_counter()
        both = retriever.search_both(query)
        fused = retriever.search(query, conf.retrieval.top_k)
        elapsed = (time.perf_counter() - started) * 1000
        top_id = fused[0][0] if fused else None
        writer.write(
            build_record(
                run_id=run_id,
                query_raw=query,
                dense=both["dense"],
                bm25=both["bm25"],
                fused=fused,
                hit_chunk_id=top_id,
                hit_rank=1 if top_id else None,
                hit_text=_chunk_text(conf, top_id),
                latency_ms={"retrieve": elapsed},
            )
        )
    records = read_records(probe_file, run_id)
    print("写入 trace %d 条，最新一条字段：%s" % (len(records), sorted(records[-1]) if records else "无"))
    print("excerpt 长度：%s（上限 %d）" % ([len(r["excerpt"] or "") for r in records], EXCERPT_CHARS))

    # 并发写：4 线程各 25 行，验证 100 行完整且无交错
    probe = pathlib.Path(conf.paths.trace_file).with_name("trace-concurrency-check.jsonl")
    if probe.exists():
        probe.unlink()
    probe_writer = TraceWriter(probe)

    def worker(tag: str, count: int) -> None:
        for index in range(count):
            probe_writer.write(
                build_record(run_id="concurrency-%s" % tag, query_raw="并发写 %s-%d" % (tag, index), latency_ms={"x": index})
            )

    threads = [threading.Thread(target=worker, args=(str(i), 25)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = probe.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    ok = len(parsed) == 100 and all(isinstance(item, dict) for item in parsed)
    probe.unlink()
    print("并发写：%d 行，可全部解析=%s（临时文件已删）" % (len(parsed), ok))
    return 0 if ok and len(records) == 3 else 1


def _chunk_text(conf, chunk_id: str | None) -> str | None:
    if not chunk_id:
        return None
    from src.store.db import connect

    conn = connect(conf.require_db_path())
    try:
        row = conn.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    finally:
        conn.close()
    return row["text"] if row else None


if __name__ == "__main__":
    raise SystemExit(main())
