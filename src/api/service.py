"""业务服务层：四个接口背后的真实逻辑，不含 HTTP 细节。

放在 `src/api/` 但刻意不 import FastAPI——`07-api/README.md` §4 要求「接口层不实现业务逻辑」，
这样业务逻辑可以脱离服务端单测，接口层只负责校验、调用与错误码映射。

检索链路按 `09-state.md` §2 的固定顺序编排：VALIDATE → RETRIEVE_DENSE → FUSE → RERANK → RESPOND，
每步失败按 `11-errors.md` 处理（能降级就降级并标记 `flags`，不能降级就抛 `ApiError`）。
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import time

from src.api.errors import (
    REASON_FALLBACK_BM25,
    REASON_FILTER_RELAXED,
    REASON_NO_MATCH,
    ApiError,
)
from src.cli.eval import METRIC_ORDER, build_run_id, sha256_file
from src.cli.ingest import IngestAborted, run_ingest
from src.config import ConfigError
from src.eval import runner
from src.retrieve import filtering
from src.store.db import connect
from src.trace import TraceWriter, build_record, read_records

MAX_TOP_K = 50
TRACE_LIMIT_MAX = 500
SPLITS = ("all", "dev", "holdout")
SOURCES = ("v01_subset", "full")

# filters 只接受这几个键；拼错的键必须报错，否则过滤条件会被静默忽略
FILTER_KEYS = ("doc_ids", "category", "authority", "publish_date_from", "publish_date_to")


def require_config(loader) -> object:
    """加载配置；缺环境变量等配置问题统一转成 `CONFIG_MISSING_KEY`（只给变量名）。"""
    try:
        return loader()
    except ConfigError as exc:
        raise ApiError("CONFIG_MISSING_KEY", str(exc)) from exc


def validate_top_k(top_k: int | None, default: int) -> int:
    value = default if top_k is None else top_k
    if not 1 <= value <= MAX_TOP_K:
        raise ApiError(
            "INVALID_REQUEST",
            "top_k 超出范围",
            {"field": "top_k", "value": value, "allowed": "1~%d" % MAX_TOP_K},
        )
    return value


def validate_query(query: str | None) -> str:
    text = (query or "").strip()
    if not text:
        raise ApiError("INVALID_REQUEST", "query 不能为空", {"field": "query", "value": query})
    return text


def parse_filters(payload: dict | None) -> filtering.MetadataFilter:
    """把请求里的 filters（单数键）转成 `MetadataFilter`；未知键直接报错。"""
    if not payload:
        return filtering.MetadataFilter()
    unknown = [key for key in payload if key not in FILTER_KEYS]
    if unknown:
        raise ApiError(
            "INVALID_REQUEST",
            "filters 含未知字段",
            {"field": "filters", "unknown": unknown, "allowed": list(FILTER_KEYS)},
        )

    def as_set(key: str) -> set[str] | None:
        raw = payload.get(key)
        if raw in (None, "", []):
            return None
        if isinstance(raw, str):
            return {raw}
        return {str(item) for item in raw}

    flt = filtering.MetadataFilter(
        doc_ids=as_set("doc_ids"),
        categories=as_set("category"),
        authorities=as_set("authority"),
        publish_from=(payload.get("publish_date_from") or None),
        publish_to=(payload.get("publish_date_to") or None),
    )
    for name, value in (("publish_date_from", flt.publish_from), ("publish_date_to", flt.publish_to)):
        if value and (len(value) != 10 or value[4] != "-" or value[7] != "-"):
            raise ApiError(
                "INVALID_REQUEST",
                "%s 需为 YYYY-MM-DD" % name,
                {"field": "filters.%s" % name, "value": value},
            )
    if flt.publish_from and flt.publish_to and flt.publish_from > flt.publish_to:
        raise ApiError(
            "INVALID_REQUEST",
            "起始日期晚于结束日期",
            {"field": "filters", "from": flt.publish_from, "to": flt.publish_to},
        )
    return flt


def current_run_id(conf) -> str:
    """与 `eval` 入口同一套规范串，保证同一配置下 `/search`、`/eval` 的 `run_id` 一致（REQ-031）。"""
    db_path = conf.require_db_path()
    conn = connect(db_path)
    try:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()
    run_id, _config_hash, _cfg = build_run_id(
        conf,
        sha256_file(conf.eval.cases_file),
        sha256_file(conf.corpus.manifest),
        int(doc_count),
    )
    return run_id


def load_chunk_index(conf) -> dict[str, dict]:
    """一次性取回 chunk 及其文档元数据（v0.4 单用户、2704 行，代价可接受）。

    过滤必须在候选层做（FAISS `IndexFlatIP` 不支持带条件检索），而判定过滤需要文档元数据，
    所以先把元数据装进内存，再交给 `FilteredRetriever`。
    """
    conn: sqlite3.Connection = connect(conf.require_db_path())
    try:
        rows = conn.execute(
            "SELECT c.chunk_id, c.doc_id, c.article_no, c.heading_path, c.char_start, c.char_end,"
            " c.n_chars, d.title, d.category, d.authority, d.publish_date"
            " FROM chunks c JOIN documents d ON d.doc_id = c.doc_id"
        ).fetchall()
    finally:
        conn.close()
    return {row["chunk_id"]: dict(row) for row in rows}


def reason_of(hits: list, flags: list[str]) -> str | None:
    """把降级标记翻成响应里的单个 `reason`。

    优先级：过滤放宽 > 无结果 > 向量路降级。前者改变的是「返回了什么」，
    后两者只改变「怎么算出来的」，用户最先需要知道的是前者。
    """
    if REASON_FILTER_RELAXED in flags:
        return REASON_FILTER_RELAXED
    if not hits:
        return REASON_NO_MATCH
    if REASON_FALLBACK_BM25 in flags:
        return REASON_FALLBACK_BM25
    return None


def path_of(retriever, flags: list[str]) -> str:
    """标明分数来自哪一段，便于调用方判断 score 能不能跨响应比较。"""
    if REASON_FALLBACK_BM25 in flags:
        return "bm25"
    name = type(retriever).__name__
    if name == "RerankedRetriever":
        return "rerank"
    if name == "HybridRetriever":
        return "fused"
    return "dense"


def search(conf, query: str, top_k: int | None = None, filters: dict | None = None, write_trace: bool = True) -> dict:
    """VALIDATE → RETRIEVE → FUSE → RERANK → RESPOND。"""
    started = time.perf_counter()
    text = validate_query(query)
    k = validate_top_k(top_k, conf.retrieval.top_k)
    flt = parse_filters(filters)

    retriever = runner.build_retriever(conf)
    if not retriever.ready:
        raise ApiError("INDEX_EMPTY", "索引未建立或为空，请先跑 ingest 与 build_index")

    chunk_index = load_chunk_index(conf)

    def meta_of(hits: list[tuple[str, float]]) -> dict[str, dict]:
        return {
            chunk_id: chunk_index.get(chunk_id)
            for chunk_id, _score in hits
            if chunk_index.get(chunk_id) is not None
        }

    wrapped = filtering.FilteredRetriever(retriever, meta_of)
    result = wrapped.search(text, k, flt)
    hits = result.hits
    flags = list(result.flags) + list(getattr(retriever, "last_flags", []))

    path = path_of(retriever, flags)
    results = []
    for chunk_id, score in hits:
        meta = chunk_index.get(chunk_id) or {}
        results.append(
            {
                "chunk_id": chunk_id,
                "doc_id": meta.get("doc_id"),
                "article_no": meta.get("article_no"),
                "heading_path": meta.get("heading_path"),
                "char_start": meta.get("char_start"),
                "char_end": meta.get("char_end"),
                "score": round(float(score), 6),
                "path": path,
            }
        )

    run_id = current_run_id(conf)
    latency = {"total_ms": round((time.perf_counter() - started) * 1000, 2)}

    if write_trace:
        base = getattr(retriever, "base", retriever)
        routes = getattr(base, "last_routes", {}) or {}
        record = build_record(
            run_id=run_id,
            query_raw=text,
            query_norm=None,
            dense=routes.get("dense") or [],
            bm25=routes.get("bm25") or [],
            fused=hits if path != "rerank" else [],
            reranked=hits if path == "rerank" else None,
            latency_ms=latency,
            flags=flags,
        )
        TraceWriter(conf.paths.trace_file).write(record)

    return {
        "run_id": run_id,
        "reason": reason_of(hits, flags),
        "flags": flags,
        "results": results,
        "latency_ms": latency["total_ms"],
    }


def eval_metrics(conf, split: str = "all") -> dict:
    """跑评测集并返回指标；不落 attempt 目录（那是命令行 `eval` 的职责），因此天然幂等。"""
    if split not in SPLITS:
        raise ApiError("INVALID_REQUEST", "split 取值非法", {"field": "split", "value": split, "allowed": list(SPLITS)})
    result = runner.run_eval(conf, split=split)
    metrics = {name: round(float(result["metrics"].get(name, 0.0)), 6) for name in METRIC_ORDER}
    return {
        "run_id": current_run_id(conf),
        "split": split,
        "metrics": metrics,
        "unmapped": result["unmapped"],
        "unconfirmed": result["unconfirmed"],
        "case_count": result["case_count"],
    }


def ingest(conf, source: str = "v01_subset", doc_ids: list[str] | None = None) -> dict:
    """调用与命令行同一份 `run_ingest`（默认增量），重复调用不产生重复行（REQ-048）。"""
    if source not in SOURCES:
        raise ApiError("INVALID_REQUEST", "source 取值非法", {"field": "source", "value": source, "allowed": list(SOURCES)})
    try:
        result = run_ingest(conf, source=source, doc_ids=doc_ids)
    except IngestAborted as exc:
        detail = {"failed": exc.failed} if exc.failed else None
        raise ApiError(exc.code, exc.message, detail) from exc
    return {
        "run_id": result["run_id"],
        "documents": result["documents"],
        "chunks": result["chunks"],
        "skipped": result["skipped"],
        "failed": result["failed"],
    }


def trace_items(conf, run_id: str, case_id: str | None = None, limit: int = 50) -> list[dict]:
    """读 JSONL（明细权威，不经 SQLite），按 `run_id`／`case_id` 过滤后截断。"""
    if not (run_id or "").strip():
        raise ApiError("INVALID_REQUEST", "run_id 不能为空", {"field": "run_id"})
    if not 1 <= limit <= TRACE_LIMIT_MAX:
        raise ApiError(
            "INVALID_REQUEST",
            "limit 超出范围",
            {"field": "limit", "value": limit, "allowed": "1~%d" % TRACE_LIMIT_MAX},
        )
    records = read_records(conf.paths.trace_file, run_id)
    if not records:
        raise ApiError("RUN_NOT_FOUND", "trace 中没有这个 run_id 的记录", {"run_id": run_id})
    if case_id:
        records = [record for record in records if record.get("case_id") == case_id]
    items = []
    for record in records[:limit]:
        items.append(
            {
                "case_id": record.get("case_id"),
                "query_raw": record.get("query_raw"),
                "query_norm": record.get("query_norm"),
                "hit_chunk_id": record.get("hit_chunk_id"),
                "hit_rank": record.get("hit_rank"),
                "excerpt": record.get("excerpt"),
                "latency_json": json.dumps(record.get("latency_ms") or {}, ensure_ascii=False),
            }
        )
    return items


def trace_file_of(conf) -> pathlib.Path:
    return pathlib.Path(conf.paths.trace_file)
