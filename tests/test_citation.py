"""引用校验单测：抽取顺序、去重、越界判定、全角兼容。"""

from __future__ import annotations

import unittest

from src.generate.citation import extract_citations, validate

ALLOWED = {"doc:00001", "doc:00002"}


class TestExtract(unittest.TestCase):
    def test_ordered_and_deduped(self):
        text = "结论一 [doc:00002]，结论二 [doc:00001]，又提到 [doc:00002]。"
        self.assertEqual(extract_citations(text), ["doc:00002", "doc:00001"])

    def test_fullwidth_brackets_tolerated(self):
        self.assertEqual(extract_citations("见【doc:00001】"), ["doc:00001"])

    def test_plain_text_has_no_citations(self):
        self.assertEqual(extract_citations("没有引用"), [])

    def test_empty_answer(self):
        self.assertEqual(extract_citations(""), [])


class TestValidate(unittest.TestCase):
    def test_all_inside(self):
        result = validate("结论 [doc:00001]。", ALLOWED)
        self.assertTrue(result["valid"])
        self.assertEqual(result["invalid"], [])

    def test_out_of_range_flagged_but_citations_kept(self):
        result = validate("结论 [doc:00001]，另见 [doc:99999]。", ALLOWED)
        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid"], ["doc:99999"])
        self.assertEqual(result["citations"], ["doc:00001", "doc:99999"])

    def test_no_citation_is_valid(self):
        self.assertTrue(validate("现有条文不足以回答。", ALLOWED)["valid"])

    def test_similar_prefix_is_not_matched(self):
        # 只差一位的 id 必须判越界，不能被前缀匹配放过
        result = validate("见 [doc:000010]", ALLOWED)
        self.assertEqual(result["invalid"], ["doc:000010"])


if __name__ == "__main__":
    unittest.main()
