"""RRF 融合的单元测试：用构造排名验证 score = Σ 1/(k + rank)。"""

from __future__ import annotations

import unittest

from src.retrieve.hybrid import fuse


class TestRRF(unittest.TestCase):
    def test_single_ranking(self):
        fused = fuse([["a", "b", "c"]], rrf_k=60, top_k=5)
        self.assertEqual([item[0] for item in fused], ["a", "b", "c"])
        self.assertAlmostEqual(fused[0][1], 1 / 61, places=12)
        self.assertAlmostEqual(fused[1][1], 1 / 62, places=12)
        self.assertAlmostEqual(fused[2][1], 1 / 63, places=12)

    def test_two_rankings_sum(self):
        dense = ["a", "b", "c"]
        bm25 = ["b", "c", "d"]
        fused = dict(fuse([dense, bm25], rrf_k=60, top_k=10))
        self.assertAlmostEqual(fused["a"], 1 / 61, places=12)
        self.assertAlmostEqual(fused["b"], 1 / 62 + 1 / 61, places=12)
        self.assertAlmostEqual(fused["c"], 1 / 63 + 1 / 62, places=12)
        # d 只在 BM25 路排第 3 → 1/(60+3)
        self.assertAlmostEqual(fused["d"], 1 / 63, places=12)

    def test_order_follows_sum(self):
        fused = fuse([["a", "b", "c"], ["b", "c", "d"]], rrf_k=60, top_k=4)
        self.assertEqual([item[0] for item in fused], ["b", "c", "a", "d"])

    def test_top_k_truncation(self):
        fused = fuse([["a", "b", "c", "d"]], rrf_k=60, top_k=2)
        self.assertEqual(len(fused), 2)
        self.assertEqual([item[0] for item in fused], ["a", "b"])

    def test_missing_route_is_ignored(self):
        """某一路为空时退化为单路，不报错（REQ-024 降级）。"""
        fused = fuse([["a", "b"], []], rrf_k=60, top_k=5)
        self.assertEqual([item[0] for item in fused], ["a", "b"])
        self.assertAlmostEqual(fused[0][1], 1 / 61, places=12)

    def test_both_empty(self):
        self.assertEqual(fuse([[], []], rrf_k=60, top_k=5), [])

    def test_duplicate_in_one_route_counted_once(self):
        fused = dict(fuse([["a", "a", "b"]], rrf_k=60, top_k=5))
        self.assertAlmostEqual(fused["a"], 1 / 61, places=12)
        self.assertAlmostEqual(fused["b"], 1 / 63, places=12)

    def test_k_must_be_positive(self):
        with self.assertRaises(ValueError):
            fuse([["a"]], rrf_k=0, top_k=1)


if __name__ == "__main__":
    unittest.main()
