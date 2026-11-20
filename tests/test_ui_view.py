"""页面纯函数的单测：三列对照、rerank 名次变化、降级文案、指标读取。"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from src.ui import view

META = {
    "d:00001": {"title": "中华人民共和国专利法", "article_no": "第二十二条", "heading_path": "第二章",
                "char_start": 100, "char_end": 200, "n_chars": 100, "text": "第一行\n第二行"},
    "d:00002": {"title": "专利代理条例", "article_no": None, "heading_path": "第一章",
                "char_start": 0, "char_end": 50, "n_chars": 50, "text": "代理师执业"},
}


class TestRouteRows(unittest.TestCase):
    def test_merges_three_columns_by_chunk(self):
        dense = [("d:00001", 0.8), ("d:00002", 0.5)]
        bm25 = [("d:00002", 12.5), ("d:00001", 3.0)]
        fused = [("d:00002", 0.032), ("d:00001", 0.031)]
        rows = view.route_rows(dense, bm25, fused, META, limit=5)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["chunk"], "d:00002"[-14:])
        self.assertEqual(rows[0]["融合排名"], 1)
        self.assertEqual(rows[0]["BM25 排名"], 1)
        self.assertEqual(rows[0]["向量排名"], 2)

    def test_chunk_only_in_one_route_keeps_blanks(self):
        rows = view.route_rows([("d:00001", 0.8)], [], [("d:00001", 0.02)], META, limit=5)
        self.assertIsNone(rows[0]["BM25 排名"])
        self.assertIsNone(rows[0]["BM25 分"])

    def test_limit_applies(self):
        rows = view.route_rows([("d:00001", 0.8), ("d:00002", 0.5)], [], [], META, limit=1)
        self.assertEqual(len(rows), 1)

    def test_excerpt_flattens_newlines(self):
        rows = view.route_rows([("d:00001", 0.8)], [], [], META, limit=1)
        self.assertEqual(rows[0]["excerpt"], "第一行 第二行")

    def test_missing_meta_does_not_crash(self):
        rows = view.route_rows([("unknown:1", 0.1)], [], [], META, limit=1)
        self.assertEqual(rows[0]["article_no"], "—")


class TestRerankRows(unittest.TestCase):
    def test_reports_rank_moves(self):
        before = [("d:00001", 0.03), ("d:00002", 0.02)]
        after = [("d:00002", 0.91), ("d:00001", 0.11)]
        rows = view.rerank_rows(before, after, META, limit=5)
        self.assertEqual(rows[0]["chunk"], "d:00002"[-14:])
        self.assertEqual(rows[0]["原排名"], 2)
        self.assertEqual(rows[0]["变化"], 1)   # 2 → 1，上升一位
        self.assertEqual(rows[1]["变化"], -1)  # 1 → 2，下降一位


class TestFlags(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(view.flags_note([]), "")

    def test_known_and_unknown(self):
        text = view.flags_note(["FILTER_RELAXED", "SOMETHING_NEW"])
        self.assertIn("放宽过滤", text)
        self.assertIn("SOMETHING_NEW", text)


class TestMetrics(unittest.TestCase):
    def test_latest_attempt_picks_highest_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "r1"
            for name, recall in (("attempt-2", 0.5), ("attempt-10", 0.9), ("attempt-1", 0.1)):
                (root / name).mkdir(parents=True)
                (root / name / "metrics.json").write_text(
                    json.dumps({"run_id": "r1", "metrics": {"recall@5": recall}}, ensure_ascii=False),
                    encoding="utf-8",
                )
            payload = view.latest_attempt(tmp, "r1")
            self.assertEqual(payload["attempt"], 10)
            self.assertEqual(payload["metrics"]["recall@5"], 0.9)

    def test_missing_run_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(view.latest_attempt(tmp, "nope"))

    def test_baseline_and_delta(self):
        payload = view.baseline_metrics(pathlib.Path("evals/baseline.json"))
        self.assertEqual(payload["run_id"], "r31a95a0e1de6")
        self.assertAlmostEqual(view.metric_delta(0.9, 0.9), 0.0)
        self.assertLess(view.metric_delta(0.88, 0.9), 0)
        self.assertIsNone(view.baseline_metrics("nope.json"))


if __name__ == "__main__":
    unittest.main()
