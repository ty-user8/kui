"""gold 锚点 → chunk 映射。

规则（`01-requirements.md` 5.3.5，v0.1）：gold 起点落在 chunk 的 `[char_start, char_end)`
内即视为命中该 chunk。**只按字符区间判断，不使用 `chunks.article_no`**——chunk 的
`article_no` 取自区间起点所在段落，与 gold 条号在实测中几乎不重合，用它过滤会误杀正确 chunk。

固定长度切分带 64 字符 overlap，同一 gold 起点可能落在两个 chunk 里；此时返回两条，
命中判定按「任一命中即 hit、一条 query 只计一次」处理（见 `metrics.py`）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkSpan:
    chunk_id: str
    doc_id: str
    start: int
    end: int


def load_chunk_spans(conn: sqlite3.Connection) -> dict[str, list[ChunkSpan]]:
    """按 doc_id 分组的 chunk 区间，按起点升序。"""
    grouped: dict[str, list[ChunkSpan]] = {}
    rows = conn.execute("SELECT chunk_id, doc_id, char_start, char_end FROM chunks ORDER BY doc_id, char_start")
    for row in rows:
        grouped.setdefault(row["doc_id"], []).append(
            ChunkSpan(row["chunk_id"], row["doc_id"], row["char_start"], row["char_end"])
        )
    return grouped


def map_gold_start(doc_id: str, gold_start: int, grouped: dict[str, list[ChunkSpan]]) -> list[str]:
    """返回覆盖 gold 起点的全部 chunk_id（可能有 0 条、1 条或 2 条）。"""
    return [span.chunk_id for span in grouped.get(doc_id, []) if span.start <= gold_start < span.end]


def load_parent_map(conn: sqlite3.Connection) -> dict[str, str | None]:
    """返回 chunk_id → parent_id 的映射（无 parent 的 chunk 值为 None）。"""
    return {row["chunk_id"]: row["parent_id"] for row in conn.execute("SELECT chunk_id, parent_id FROM chunks")}


def map_cases_to_parent(
    cases: list[dict],
    grouped: dict[str, list[ChunkSpan]],
    chunk_to_parent: dict[str, str | None],
) -> tuple[dict[str, list[str]], list[dict]]:
    """把 gold 起点映射到 parent：起点 → 覆盖它的 child → 该 child 的 parent。"""
    mapped: dict[str, list[str]] = {}
    unmapped: list[dict] = []
    for case in cases:
        try:
            gold_start = int(case["char_start"])
        except (TypeError, ValueError):
            unmapped.append({"case_id": case["case_id"], "reason": "区间为空"})
            continue
        parents = []
        for chunk_id in map_gold_start(case["doc_id"], gold_start, grouped):
            parent_id = chunk_to_parent.get(chunk_id)
            if parent_id and parent_id not in parents:
                parents.append(parent_id)
        if not parents:
            unmapped.append({"case_id": case["case_id"], "reason": "child 无 parent 或未覆盖起点"})
            continue
        mapped[case["case_id"]] = parents
    return mapped, unmapped


def map_cases(cases: list[dict], grouped: dict[str, list[ChunkSpan]]) -> tuple[dict[str, list[str]], list[dict]]:
    """批量映射。返回（case_id → chunk_id 列表, 映射失败清单）。"""
    mapped: dict[str, list[str]] = {}
    unmapped: list[dict] = []
    for case in cases:
        try:
            gold_start = int(case["char_start"])
        except (TypeError, ValueError):
            unmapped.append({"case_id": case["case_id"], "reason": "区间为空"})
            continue
        hits = map_gold_start(case["doc_id"], gold_start, grouped)
        if not hits:
            unmapped.append({"case_id": case["case_id"], "reason": "起点不落在任何 chunk 内"})
            continue
        mapped[case["case_id"]] = hits
    return mapped, unmapped
