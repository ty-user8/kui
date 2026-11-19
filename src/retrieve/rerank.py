"""交叉编码器重排：只对融合后的 top-N 候选重排，超时降级回融合序。

候选数 N 由覆盖率曲线确定（`evals/experiments-v0.3.md`），不取固定默认值。
rerank 分数与融合分数**只做组内比较**，不混排、不归一（两者量纲不可比）。
超时返回融合排序并标记 `FALLBACK_RERANK_TIMEOUT`（REQ-024）；模型缺失标记
`FALLBACK_RERANK_UNAVAILABLE` 并保持融合序，不静默改变行为。
"""

from __future__ import annotations

import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

TIMEOUT_FLAG = "FALLBACK_RERANK_TIMEOUT"
UNAVAILABLE_FLAG = "FALLBACK_RERANK_UNAVAILABLE"


@dataclass
class RerankResult:
    hits: list[tuple[str, float]]
    flags: list[str] = field(default_factory=list)
    candidates: int = 0
    elapsed_ms: float = 0.0
    scored: bool = False


class Reranker:
    """一次加载、按批打分；`predict` 可注入以便测试。"""

    def __init__(self, conf, model_dir: pathlib.Path | None = None, predict=None) -> None:
        self.model_name = conf.model.rerank_name
        self.top_n = conf.retrieval.rerank_top_n
        self.timeout_ms = conf.retrieval.rerank_timeout_ms
        self._predict = predict
        self._model = None
        if predict is None:
            self._model = self._load(conf, model_dir)

    @staticmethod
    def _load(conf, model_dir: pathlib.Path | None):
        base = model_dir or (conf.model_cache_dir() or pathlib.Path(".cache/models")) / conf.model.rerank_name.split("/")[-1]
        target = base if pathlib.Path(base).is_dir() else conf.model.rerank_name
        try:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(str(target), device=conf.model.device)
        except Exception:
            return None

    @property
    def ready(self) -> bool:
        return self._predict is not None or self._model is not None

    def _score(self, query: str, pairs: list[tuple[str, str]]) -> list[float]:
        if self._predict is not None:
            return list(self._predict([(query, text) for _, text in pairs]))
        scores = self._model.predict([(query, text) for _, text in pairs])
        return [float(item) for item in scores]

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str, float]],
        texts: dict[str, str],
        top_k: int | None = None,
        top_n: int | None = None,
        timeout_ms: int | None = None,
    ) -> RerankResult:
        """对候选重排；候选按融合序截到 `top_n`，输出前 `top_k`。"""
        limit_n = top_n or self.top_n
        limit_k = top_k or limit_n
        started = time.perf_counter()
        head = candidates[:limit_n]
        if not self.ready:
            return RerankResult(head[:limit_k], [UNAVAILABLE_FLAG], len(head), 0.0, False)
        if not head:
            return RerankResult([], [], 0, 0.0, False)

        pairs = [(chunk_id, texts.get(chunk_id, "")) for chunk_id, _ in head]
        timeout = (timeout_ms if timeout_ms is not None else self.timeout_ms) / 1000
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._score, query, pairs)
            scores = future.result(timeout=timeout)
        except Exception as exc:  # 超时或模型报错都降级，不抛给调用方
            flag = TIMEOUT_FLAG if exc.__class__.__name__ in ("TimeoutError", "CancelledError") else UNAVAILABLE_FLAG
            executor.shutdown(wait=False)
            return RerankResult(head[:limit_k], [flag], len(head), (time.perf_counter() - started) * 1000, False)
        finally:
            executor.shutdown(wait=False)

        scored = [(chunk_id, float(score)) for (chunk_id, _), score in zip(pairs, scores)]
        scored.sort(key=lambda item: item[1], reverse=True)
        return RerankResult(
            scored[:limit_k],
            [],
            len(head),
            (time.perf_counter() - started) * 1000,
            True,
        )


class RerankedRetriever:
    """把重排接在融合检索之后：先取融合 top-N 候选，再按交叉编码器分数重排取 top-k。

    查询先归一化（REQ-026），命中分数替换为 rerank 分，只做组内比较；
    降级时保留融合序并把 flag 透传，调用方可据此在 trace 里标记。
    """

    def __init__(self, base, reranker: "Reranker", texts_of, top_n: int | None = None) -> None:
        self.base = base
        self.reranker = reranker
        self.texts_of = texts_of
        self.top_n = top_n or reranker.top_n
        self.last_flags: list[str] = []
        self.last_candidates = 0

    @property
    def ready(self) -> bool:
        return self.base.ready

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        from src.retrieve.normalize import normalize_query

        normalized, _info = normalize_query(query)
        candidates = self.base.search(normalized, self.top_n)
        texts = self.texts_of([chunk_id for chunk_id, _ in candidates])
        result = self.reranker.rerank(normalized, candidates, texts, top_k=top_k, top_n=self.top_n)
        self.last_flags = list(result.flags)
        self.last_candidates = result.candidates
        return result.hits
