"""评测编排：读用例 → 映射 gold → 单路检索 → 算指标。

本模块只负责算数与返回结构，不写文件、不生成 `run_id`（那是 T-008 的 eval 入口）。
`unmapped` 与 `unconfirmed` 分开计数：前者是锚点映射失败，后者是标注尚未人工确认，
两者都不得计入指标（REQ-030、REQ-033）。
"""

from __future__ import annotations

import csv
import pathlib
import sqlite3
import time

from src.eval import mapping, metrics
from src.index import bm25_index
from src.retrieve.dense import DenseRetriever
from src.retrieve.hybrid import HybridRetriever
from src.store.db import connect

K_VALUES = (1, 3, 5)


def build_retriever(conf):
    """按 `retrieval.use_bm25` 选单路或融合；BM25 索引缺失时退回单路（REQ-024 降级）。"""
    dense = DenseRetriever(conf)
    if not conf.retrieval.use_bm25:
        return dense
    try:
        bundle = bm25_index.load(conf.paths.index_dir)
    except FileNotFoundError:
        return dense
    return HybridRetriever(
        dense=dense,
        bm25=bundle,
        rrf_k=conf.retrieval.rrf_k,
        candidate_k=conf.retrieval.candidate_k,
    )


def load_cases(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def select_cases(rows: list[dict], split: str) -> tuple[list[dict], int]:
    """返回（参与评测的已确认用例, 未确认数）；`split` 取 all/dev/holdout。"""
    confirmed = [row for row in rows if (row.get("anchor_status") or "").strip() == "confirmed"]
    unconfirmed = len(rows) - len(confirmed)
    if split != "all":
        confirmed = [row for row in confirmed if (row.get("split") or "").strip() == split]
    return confirmed, unconfirmed


def run_eval(conf, split: str = "all", top_k: int | None = None) -> dict:
    started = time.time()
    rows = load_cases(conf.eval.cases_file)
    cases, unconfirmed = select_cases(rows, split)

    conn: sqlite3.Connection = connect(conf.require_db_path())
    try:
        grouped = mapping.load_chunk_spans(conn)
    finally:
        conn.close()

    gold_map, unmapped = mapping.map_cases(cases, grouped)
    retriever = build_retriever(conf)
    k = top_k or conf.retrieval.top_k

    per_case: list[dict] = []
    overlap_cases = 0
    for case in cases:
        case_id = case["case_id"]
        gold = gold_map.get(case_id)
        if not gold:
            continue
        if len(gold) > 1:
            overlap_cases += 1
        hits = retriever.search(case["query"], k)
        ranked = [chunk_id for chunk_id, _score in hits]
        rank = metrics.first_hit_rank(ranked, gold)
        per_case.append(
            {
                "case_id": case_id,
                "split": case.get("split"),
                "query": case["query"],
                "gold": gold,
                "ranked": ranked,
                "hit_rank": rank,
                "top1_score": hits[0][1] if hits else None,
            }
        )

    result = {
        "split": split,
        "case_count": len(per_case),
        "unmapped": len(unmapped),
        "unmapped_detail": unmapped,
        "unconfirmed": unconfirmed,
        "overlap_cases": overlap_cases,
        "top_k": k,
        "metrics": metrics.aggregate(per_case, K_VALUES),
        "per_case": per_case,
        "elapsed_seconds": round(time.time() - started, 2),
        "flags": [] if retriever.ready else ["NO_MATCH"],
    }
    return result


def format_report(result: dict) -> str:
    lines = [
        "split=%s 用例 %d 条（unmapped %d、unconfirmed %d、多 chunk 映射 %d 条）top_k=%d，耗时 %.2fs"
        % (
            result["split"],
            result["case_count"],
            result["unmapped"],
            result["unconfirmed"],
            result["overlap_cases"],
            result["top_k"],
            result["elapsed_seconds"],
        )
    ]
    for name in ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "hitrate@5"):
        value = result["metrics"].get(name)
        if value is not None:
            lines.append("  %-10s %.4f" % (name, value))
    for item in result["per_case"]:
        lines.append(
            "  %s %-6s %s | gold %s | 命中排名 %s"
            % (item["case_id"], item["split"], item["query"][:26], ",".join(x[-5:] for x in item["gold"]), item["hit_rank"])
        )
    return "\n".join(lines)


def main() -> int:
    import sys

    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.config import ConfigError, load

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2
    print(format_report(run_eval(conf)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
