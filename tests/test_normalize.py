"""查询归一化的单元测试：全角半角、空白折叠、幂等、原文本保留。"""

from __future__ import annotations

import unittest

from src.retrieve.normalize import normalize_query


class TestNormalize(unittest.TestCase):
    def test_fullwidth_to_halfwidth(self):
        text, info = normalize_query("ＡＢＣ　１２３")
        self.assertEqual(text, "ABC 123")
        self.assertTrue(info["nfkc"])

    def test_collapse_whitespace(self):
        text, info = normalize_query("发明专利权的   期限\t是几年")
        self.assertEqual(text, "发明专利权的期限是几年")
        self.assertTrue(info["collapsed"])

    def test_idempotent(self):
        once, _ = normalize_query("发明专利权的期限是几年")
        twice, _ = normalize_query(once)
        self.assertEqual(once, twice)

    def test_different_spellings_converge(self):
        variants = ["发明专利权的期限是几年", "发明专利权 的 期限是几年", "发明专利权　的　期限是几年"]
        self.assertEqual(len({normalize_query(item)[0] for item in variants}), 1)

    def test_keeps_original_untouched(self):
        raw = "发明专利权的期限是几年？"
        normalize_query(raw)
        self.assertEqual(raw, "发明专利权的期限是几年？")


if __name__ == "__main__":
    unittest.main()
