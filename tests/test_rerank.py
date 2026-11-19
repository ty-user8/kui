"""rerank 的单元测试：排序、超时降级、模型缺失降级。"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from src.retrieve.rerank import TIMEOUT_FLAG, UNAVAILABLE_FLAG, Reranker


def make_conf(top_n=20, timeout_ms=3000):
    return SimpleNamespace(
        model=SimpleNamespace(rerank_name="BAAI/bge-reranker-base", device="cpu"),
        retrieval=SimpleNamespace(rerank_top_n=top_n, rerank_timeout_ms=timeout_ms),
        model_cache_dir=lambda: None,
    )


class TestRerank(unittest.TestCase):
    def test_orders_by_cross_encoder_score(self):
        # 分数与候选原序相反，重排后应完全翻转
        reranker = Reranker(make_conf(), predict=lambda pairs: [float(i) for i in range(len(pairs))])
        candidates = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        texts = {"a": "A", "b": "B", "c": "C"}
        result = reranker.rerank("q", candidates, texts, top_k=3)
        self.assertEqual([chunk for chunk, _ in result.hits], ["c", "b", "a"])
        self.assertTrue(result.scored)
        self.assertEqual(result.flags, [])

    def test_timeout_falls_back_to_fused_order(self):
        def slow(pairs):
            time.sleep(0.3)
            return [1.0] * len(pairs)

        reranker = Reranker(make_conf(timeout_ms=50), predict=slow)
        candidates = [("a", 0.9), ("b", 0.8)]
        result = reranker.rerank("q", candidates, {"a": "A", "b": "B"}, top_k=2)
        self.assertEqual([chunk for chunk, _ in result.hits], ["a", "b"])
        self.assertIn(TIMEOUT_FLAG, result.flags)
        self.assertFalse(result.scored)

    def test_model_unavailable_keeps_order(self):
        reranker = Reranker(make_conf(), predict=None)
        reranker._model = None
        result = reranker.rerank("q", [("a", 0.9), ("b", 0.8)], {"a": "A", "b": "B"}, top_k=2)
        self.assertEqual([chunk for chunk, _ in result.hits], ["a", "b"])
        self.assertIn(UNAVAILABLE_FLAG, result.flags)

    def test_truncates_candidates_to_top_n(self):
        reranker = Reranker(make_conf(top_n=3), predict=lambda pairs: [float(i) for i in range(len(pairs))])
        candidates = [(f"c{i}", 1.0 - i * 0.01) for i in range(10)]
        texts = {chunk: chunk for chunk, _ in candidates}
        result = reranker.rerank("q", candidates, texts, top_k=2)
        self.assertEqual(result.candidates, 3)
        self.assertEqual(len(result.hits), 2)


if __name__ == "__main__":
    unittest.main()
