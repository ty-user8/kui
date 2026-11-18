"""检索指标：Recall@k、MRR、nDCG@k、HitRate@k。

口径（v0.1，单条 query 只有一个 gold 条款）：
- gold 对应的 chunk 可能因 overlap 有 1~2 个，命中集视为**同一个相关目标**；
- 一条 query 只计一次：top-k 中只要出现任一 gold chunk 即算命中，排名取其中最靠前的位置；
- 因此 Recall@k 与 HitRate@k 数值相同，保留两个名字是因为报告里两者含义不同
  （前者衡量「找到没有」，后者衡量「命中率」），实现共用同一判定。
- nDCG 按单相关文档计算：rel=1 时 DCG = 1/log2(rank+1)，IDCG = 1。
"""

from __future__ import annotations

import math


def first_hit_rank(ranked_ids: list[str], gold_ids: list[str]) -> int | None:
    """返回 1-based 的首个命中排名；未命中返回 None。"""
    gold = set(gold_ids)
    for position, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in gold:
            return position
    return None


def hit_at_k(ranked_ids: list[str], gold_ids: list[str], k: int) -> float:
    rank = first_hit_rank(ranked_ids[:k], gold_ids)
    return 1.0 if rank is not None else 0.0


def recall_at_k(ranked_ids: list[str], gold_ids: list[str], k: int) -> float:
    return hit_at_k(ranked_ids, gold_ids, k)


def reciprocal_rank(ranked_ids: list[str], gold_ids: list[str]) -> float:
    rank = first_hit_rank(ranked_ids, gold_ids)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at_k(ranked_ids: list[str], gold_ids: list[str], k: int) -> float:
    rank = first_hit_rank(ranked_ids[:k], gold_ids)
    if rank is None:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def aggregate(per_case: list[dict], k_values: tuple[int, ...] = (1, 3, 5)) -> dict:
    """对逐条结果求平均；`per_case` 每项含 `ranked` 与 `gold`。"""
    total = len(per_case)
    if total == 0:
        return {name: 0.0 for name in _metric_names(k_values)}
    result = {}
    for k in k_values:
        result["recall@%d" % k] = sum(hit_at_k(c["ranked"], c["gold"], k) for c in per_case) / total
        result["hitrate@%d" % k] = sum(hit_at_k(c["ranked"], c["gold"], k) for c in per_case) / total
        result["ndcg@%d" % k] = sum(ndcg_at_k(c["ranked"], c["gold"], k) for c in per_case) / total
    result["mrr"] = sum(reciprocal_rank(c["ranked"], c["gold"]) for c in per_case) / total
    return result


def _metric_names(k_values: tuple[int, ...]) -> list[str]:
    names = []
    for k in k_values:
        names += ["recall@%d" % k, "hitrate@%d" % k, "ndcg@%d" % k]
    names.append("mrr")
    return names
