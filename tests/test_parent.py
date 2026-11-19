"""父子 chunk 的单元测试：覆盖、包含关系、折叠去重、锚点映射。"""

from __future__ import annotations

import unittest

from src.split.parent import collapse, parent_at


class TestCollapse(unittest.TestCase):
    def test_same_parent_kept_once_at_best_rank(self):
        hits = [("d:c00001", 0.9), ("d:c00002", 0.8), ("d:c00003", 0.7)]
        mapping = {"d:c00001": "d:p0000", "d:c00002": "d:p0000", "d:c00003": "d:p0001"}
        folded = collapse(hits, mapping, 5)
        self.assertEqual([item[0] for item in folded], ["d:p0000", "d:p0001"])
        self.assertAlmostEqual(folded[0][1], 0.9)

    def test_top_k_after_dedup(self):
        hits = [(f"d:c{i:05d}", 1.0 - i * 0.01) for i in range(10)]
        mapping = {f"d:c{i:05d}": "d:p0000" for i in range(10)}
        self.assertEqual(len(collapse(hits, mapping, 5)), 1)

    def test_missing_parent_falls_back_to_chunk(self):
        folded = collapse([("d:c00001", 0.5)], {}, 3)
        self.assertEqual(folded[0][0], "d:c00001")


class TestParentAt(unittest.TestCase):
    def test_position_maps_to_parent(self):
        from src.split.fixed import Chunk

        children = [
            Chunk("d:c0", "d", 0, "abc", 0, 3, None, "", 3, "d:p0"),
            Chunk("d:c1", "d", 1, "def", 3, 6, None, "", 3, "d:p1"),
        ]
        self.assertEqual(parent_at(children, 0), "d:p0")
        self.assertEqual(parent_at(children, 4), "d:p1")
        self.assertIsNone(parent_at(children, 9))


if __name__ == "__main__":
    unittest.main()
