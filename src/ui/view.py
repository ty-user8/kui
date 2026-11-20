"""Streamlit 页面的纯函数部分：把检索结果整理成表格行。

刻意不 import streamlit——渲染归 `app.py`，这里的拼接逻辑可以脱网单测，
也避免测试为了断言一个表头去启动 Streamlit 运行时。
"""

from __future__ import annotations

import json
import pathlib

EXCERPT_CHARS = 80


def _row_meta(meta: dict | None) -> dict:
    meta = meta or {}
    text = meta.get("text") or ""
    return {
        "doc": (meta.get("title") or meta.get("doc_id") or "")[:24],
        "article_no": meta.get("article_no") or "—",
        "heading": (meta.get("heading_path") or "—")[:28],
        "span": "%d–%d" % (meta.get("char_start", 0), meta.get("char_end", 0))
        if meta.get("char_start") is not None
        else "—",
        "chars": meta.get("n_chars") or len(text),
        "excerpt": text.replace("\n", " ")[:EXCERPT_CHARS],
    }


def route_rows(
    dense: list[tuple[str, float]],
    bm25: list[tuple[str, float]],
    fused: list[tuple[str, float]],
    meta: dict[str, dict],
    limit: int = 10,
) -> list[dict]:
    """两路召回 + 融合的三列对照表：同一 chunk 只占一行，缺哪一路就留空。

    行序按融合排名；两路分数量纲不同（余弦 vs BM25），只并排展示，不做归一。
    """
    dense_rank = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(dense, start=1)}
    bm25_rank = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(bm25, start=1)}
    fused_rank = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(fused, start=1)}

    ordered: list[str] = [chunk_id for chunk_id, _score in fused]
    for chunk_id, _score in dense:
        if chunk_id not in fused_rank:
            ordered.append(chunk_id)
    for chunk_id, _score in bm25:
        if chunk_id not in fused_rank and chunk_id not in dense_rank:
            ordered.append(chunk_id)

    rows = []
    for chunk_id in ordered[:limit]:
        d = dense_rank.get(chunk_id)
        b = bm25_rank.get(chunk_id)
        f = fused_rank.get(chunk_id)
        rows.append(
            {
                "chunk": chunk_id[-14:],
                **_row_meta(meta.get(chunk_id)),
                "向量排名": d[0] if d else None,
                "向量分": round(d[1], 4) if d else None,
                "BM25 排名": b[0] if b else None,
                "BM25 分": round(b[1], 3) if b else None,
                "融合排名": f[0] if f else None,
                "融合分": round(f[1], 5) if f else None,
            }
        )
    return rows


def rerank_rows(
    before: list[tuple[str, float]],
    after: list[tuple[str, float]],
    meta: dict[str, dict],
    limit: int = 10,
) -> list[dict]:
    """rerank 前后对照：按 rerank 后顺序排列，标出排名变化（正数=上升）。"""
    before_rank = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(before, start=1)}
    rows = []
    for rank, (chunk_id, score) in enumerate(after[:limit], start=1):
        old = before_rank.get(chunk_id)
        rows.append(
            {
                "chunk": chunk_id[-14:],
                **_row_meta(meta.get(chunk_id)),
                "rerank 排名": rank,
                "rerank 分": round(score, 4),
                "原排名": old[0] if old else None,
                "变化": (old[0] - rank) if old else None,
            }
        )
    return rows


def hit_rows(hits: list[tuple[str, float]], meta: dict[str, dict], limit: int = 5) -> list[dict]:
    """最终返回给用户的 top-k 表格。"""
    rows = []
    for rank, (chunk_id, score) in enumerate(hits[:limit], start=1):
        rows.append({"rank": rank, "chunk": chunk_id[-14:], "分数": round(score, 4), **_row_meta(meta.get(chunk_id))})
    return rows


def flags_note(flags: list[str]) -> str:
    """把降级标记翻成一句人话；无标记返回空串。"""
    mapping = {
        "FALLBACK_BM25": "向量路不可用，本次只用 BM25 召回",
        "FALLBACK_RERANK_TIMEOUT": "重排超时，已回退到融合顺序",
        "FALLBACK_RERANK_UNAVAILABLE": "重排模型不可用，已回退到融合顺序",
        "FILTER_RELAXED": "过滤后无结果，已放宽过滤条件重试",
    }
    parts = [mapping.get(flag, flag) for flag in flags]
    return "；".join(parts)


def latest_attempt(runs_dir: pathlib.Path | str, run_id: str) -> dict | None:
    """读指定 run 下编号最大的 attempt 的 metrics；没有就返回 None（页面据此提示未跑过评测）。"""
    root = pathlib.Path(runs_dir) / run_id
    if not root.is_dir():
        return None

    def index_of(path: pathlib.Path) -> int:
        suffix = path.name.split("-")[-1]
        return int(suffix) if suffix.isdigit() else 0

    attempts = sorted([p for p in root.glob("attempt-*") if p.is_dir()], key=index_of)
    if not attempts:
        return None
    latest = attempts[-1]
    payload = json.loads((latest / "metrics.json").read_text(encoding="utf-8"))
    payload["attempt"] = index_of(latest)
    return payload


def baseline_metrics(path: pathlib.Path | str) -> dict | None:
    target = pathlib.Path(path)
    if not target.is_file():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def metric_delta(current: float, base: float) -> float:
    """当前值减基准值；页面用来标绿/标红（不退化为绿）。"""
    return round(current - base, 6)
