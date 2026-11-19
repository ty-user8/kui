"""配对 bootstrap 置信区间与延迟基线。

用途：判断两组配置的指标差异是否值得声明（REQ-035）——只有区间整体在 0 之上才算提升，
区间跨 0（即与基线重叠）一律表述为「无显著差异」，不得写成提升。

抽样方式：对同一批 query 做配对重采样（同一 query 的 A/B 结果一起进样本），
避免把配对数据当独立样本而低估方差。
"""

from __future__ import annotations

import random
import statistics

DEFAULT_ROUNDS = 1000
DEFAULT_ALPHA = 0.05
DEFAULT_SEED = 20261116


def paired_bootstrap(
    baseline: list[float],
    candidate: list[float],
    rounds: int = DEFAULT_ROUNDS,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
) -> dict:
    """返回 {mean, lower, upper, rounds}；差值定义为 candidate - baseline。"""
    if len(baseline) != len(candidate):
        raise ValueError("两组样本数不一致：%d vs %d" % (len(baseline), len(candidate)))
    if not baseline:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "rounds": 0}

    deltas = [c - b for b, c in zip(baseline, candidate)]
    n = len(deltas)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(rounds):
        total = 0.0
        for _ in range(n):
            total += deltas[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    low_index = max(0, int(alpha / 2 * rounds))
    high_index = min(rounds - 1, int((1 - alpha / 2) * rounds) - 1)
    return {"mean": statistics.fmean(deltas), "lower": means[low_index], "upper": means[high_index], "rounds": rounds}


def verdict(interval: dict) -> str:
    """把区间翻译成结论：overlap / improved / degraded。"""
    if interval["lower"] > 0:
        return "improved"
    if interval["upper"] < 0:
        return "degraded"
    return "overlap"


def percentiles(values: list[float], points: tuple[float, ...] = (50, 95)) -> dict:
    """返回 {p50: x, p95: y}；样本为空时返回 None。"""
    if not values:
        return {("p%d" % point): None for point in points}
    ordered = sorted(values)
    result = {}
    for point in points:
        index = min(len(ordered) - 1, max(0, int(round(point / 100 * (len(ordered) - 1)))))
        result["p%d" % point] = ordered[index]
    return result


def main() -> int:
    """自检：对 rerank 开关做配对 bootstrap，并输出检索延迟 p50/p95。"""
    import dataclasses
    import pathlib
    import sys
    import time

    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.config import ConfigError, load
    from src.eval import runner

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    base_conf = dataclasses.replace(conf, retrieval=dataclasses.replace(conf.retrieval, use_rerank=False))
    cand_conf = dataclasses.replace(conf, retrieval=dataclasses.replace(conf.retrieval, use_rerank=True))

    started = time.perf_counter()
    base = runner.run_eval(base_conf, split="dev")
    baseline_seconds = time.perf_counter() - started
    started = time.perf_counter()
    cand = runner.run_eval(cand_conf, split="dev")
    candidate_seconds = time.perf_counter() - started

    def per_case(result: dict, metric: str) -> dict[str, float]:
        values = {}
        for item in result["per_case"]:
            rank = item["hit_rank"]
            if metric == "hit@1":
                values[item["case_id"]] = 1.0 if rank == 1 else 0.0
            elif metric == "hit@5":
                values[item["case_id"]] = 1.0 if rank is not None and rank <= 5 else 0.0
            else:
                values[item["case_id"]] = 1.0 / rank if rank else 0.0
        return values

    print("dev 用例 %d 条；基线耗时 %.1fs，候选耗时 %.1fs" % (base["case_count"], baseline_seconds, candidate_seconds))
    for metric, label in (("hit@1", "Recall@1"), ("hit@5", "Recall@5"), ("rr", "MRR")):
        left = per_case(base, metric)
        right = per_case(cand, metric)
        shared = sorted(set(left) & set(right))
        interval = paired_bootstrap([left[key] for key in shared], [right[key] for key in shared])
        print(
            "%s：基线 %.4f → 候选 %.4f，差值 %+.4f，95%% 区间 [%+.4f, %+.4f] → %s"
            % (
                label,
                statistics.fmean(left[key] for key in shared),
                statistics.fmean(right[key] for key in shared),
                interval["mean"],
                interval["lower"],
                interval["upper"],
                verdict(interval),
            )
        )

    # 延迟基线：同一批 query 各跑一次检索，记录单条耗时
    retriever = runner.build_retriever(cand_conf)
    queries = [item["query"] for item in cand["per_case"][:20]]
    timings = []
    for query in queries:
        mark = time.perf_counter()
        retriever.search(query, conf.retrieval.top_k)
        timings.append((time.perf_counter() - mark) * 1000)
    stats = percentiles(timings)
    print("检索延迟（%d 条，含重排）：p50 %.1f ms、p95 %.1f ms" % (len(timings), stats["p50"], stats["p95"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
