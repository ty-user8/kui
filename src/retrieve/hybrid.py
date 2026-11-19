"""两路检索的 RRF 融合。

`score(d) = Σ_i 1 / (k + rank_i(d))`，`rank_i` 从 1 开始、`k` 取 `retrieval.rrf_k`（默认 60）。
两路分数不可比（余弦有界、BM25 无界且可负），所以只用**排名**，不归一化原始分数（REQ-020）。

某一路没命中不影响另一路计分；两路都没命中时返回空列表，由调用方标记 `NO_MATCH`。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.index import bm25_index
from src.retrieve.dense import DenseRetriever

DEFAULT_RRF_K = 60


def fuse(rankings: list[list[str]], rrf_k: int = DEFAULT_RRF_K, top_k: int = 5) -> list[tuple[str, float]]:
    """按 RRF 融合多路排名，返回 [(chunk_id, score)] 降序。

    `rankings` 每项是一路的 chunk_id 有序列表（越靠前排名越高），可含重复 id（同一路内不应有，但容错跳过）。
    """
    if rrf_k <= 0:
        raise ValueError("rrf_k 必须为正数")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for position, chunk_id in enumerate(ranking, start=1):
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + position)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:top_k]


@dataclass
class HybridRetriever:
    """向量路 + BM25 路，按 RRF 融合；某一路缺失时退化为单路（REQ-024 的降级之一）。"""

    dense: DenseRetriever
    bm25: bm25_index.BM25Bundle | None
    rrf_k: int = DEFAULT_RRF_K
    candidate_k: int = 20

    @property
    def ready(self) -> bool:
        return self.dense.ready or (self.bm25 is not None and self.bm25.ntotal > 0)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        rankings: list[list[str]] = []
        if self.dense.ready:
            rankings.append([chunk_id for chunk_id, _ in self.dense.search(query, self.candidate_k)])
        if self.bm25 is not None and self.bm25.ntotal > 0:
            rankings.append([chunk_id for chunk_id, _ in self.bm25.search(query, self.candidate_k)])
        if not rankings:
            return []
        return fuse(rankings, self.rrf_k, top_k)

    def search_both(self, query: str) -> dict[str, list[tuple[str, float]]]:
        """分别返回两路原始结果，供 trace 与 A/B 对比使用。"""
        result = {"dense": [], "bm25": []}
        if self.dense.ready:
            result["dense"] = self.dense.search(query, self.candidate_k)
        if self.bm25 is not None and self.bm25.ntotal > 0:
            result["bm25"] = self.bm25.search(query, self.candidate_k)
        return result


def build(conf) -> HybridRetriever:
    """按配置装配；`retrieval.use_bm25=False` 时不加载 BM25（省内存）。"""
    dense = DenseRetriever(conf)
    bundle = None
    if conf.retrieval.use_bm25:
        try:
            bundle = bm25_index.load(conf.paths.index_dir)
        except FileNotFoundError:
            bundle = None
    return HybridRetriever(
        dense=dense,
        bm25=bundle,
        rrf_k=conf.retrieval.rrf_k,
        candidate_k=conf.retrieval.candidate_k,
    )


def main() -> int:
    """自检：对三条查询打印两路 top3 与融合 top5。"""
    import pathlib
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

    dense = DenseRetriever(conf)
    bundle = bm25_index.load(conf.paths.index_dir)
    retriever = HybridRetriever(dense=dense, bm25=bundle, rrf_k=conf.retrieval.rrf_k, candidate_k=conf.retrieval.candidate_k)
    for query in ("发明专利权的期限是几年", "专利代理师执业前要实习多久", "发现数据安全漏洞后要马上做什么"):
        both = retriever.search_both(query)
        fused = retriever.search(query, 5)
        print("查询 %s" % query)
        print("  向量 %s" % [c[-5:] for c, _ in both["dense"][:3]])
        print("  BM25 %s" % [c[-5:] for c, _ in both["bm25"][:3]])
        print("  融合 %s" % ["%s:%.5f" % (c[-5:], s) for c, s in fused[:5]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
