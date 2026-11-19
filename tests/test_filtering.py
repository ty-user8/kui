"""元数据过滤与三条降级的单元测试。"""

from __future__ import annotations

import unittest

from src.retrieve.filtering import FILTER_RELAXED, FilteredRetriever, MetadataFilter, apply_filter
from src.retrieve.hybrid import HybridRetriever

META = {
    "c1": {"doc_id": "d1", "category": "法律", "authority": "全国人大", "publish_date": "2020-01-01"},
    "c2": {"doc_id": "d2", "category": "行政法规", "authority": "国务院", "publish_date": "2021-06-01"},
}


class FakeBase:
    def __init__(self, hits, ready=True):
        self._hits = hits
        self.ready = ready
        self.calls = 0

    def search(self, query, top_k=5):
        self.calls += 1
        return self._hits[:top_k]


class TestMetadataFilter(unittest.TestCase):
    def test_category_filter_keeps_matching(self):
        flt = MetadataFilter(categories={"行政法规"})
        kept = apply_filter([("c1", 0.9), ("c2", 0.8)], META, flt, 5)
        self.assertEqual([item[0] for item in kept], ["c2"])

    def test_date_range_filter(self):
        flt = MetadataFilter(publish_from="2021-01-01")
        kept = apply_filter([("c1", 0.9), ("c2", 0.8)], META, flt, 5)
        self.assertEqual([item[0] for item in kept], ["c2"])

    def test_inactive_filter_passes_through(self):
        self.assertFalse(MetadataFilter().active)


class TestFilteredRetriever(unittest.TestCase):
    def test_filter_hit(self):
        retriever = FilteredRetriever(FakeBase([("c1", 0.9), ("c2", 0.8)]), lambda hits: META)
        result = retriever.search("q", 5, MetadataFilter(authorities={"国务院"}))
        self.assertEqual([item[0] for item in result.hits], ["c2"])
        self.assertEqual(result.flags, [])

    def test_empty_after_filter_relaxes_and_flags(self):
        retriever = FilteredRetriever(FakeBase([("c1", 0.9), ("c2", 0.8)]), lambda hits: META)
        result = retriever.search("q", 5, MetadataFilter(publish_from="2099-01-01"))
        self.assertEqual(len(result.hits), 2)  # 放宽后返回未过滤结果
        self.assertIn(FILTER_RELAXED, result.flags)
        self.assertTrue(result.relaxed)

    def test_no_filter_returns_base_hits(self):
        base = FakeBase([("c1", 0.9)])
        retriever = FilteredRetriever(base, lambda hits: META)
        self.assertEqual(len(retriever.search("q", 5).hits), 1)
        self.assertEqual(base.calls, 1)


class TestFallbackBM25(unittest.TestCase):
    def test_dense_error_falls_back_to_bm25(self):
        class Boom:
            ready = True

            def search(self, query, top_k=5):
                raise RuntimeError("faiss broken")

        class Bm:
            ntotal = 2

            def search(self, query, top_k=5):
                return [("c1", 1.0), ("c2", 0.5)]

        retriever = HybridRetriever(dense=Boom(), bm25=Bm(), rrf_k=60, candidate_k=20)
        hits = retriever.search("q", 5)
        self.assertTrue(hits)
        self.assertIn("FALLBACK_BM25", retriever.last_flags)


if __name__ == "__main__":
    unittest.main()
