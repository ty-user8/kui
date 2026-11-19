"""trace 写入的单元测试：字段完整性、excerpt 截断、字段顺序。"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from src.trace import EXCERPT_CHARS, TRACE_FIELDS, TraceWriter, build_record, excerpt


class TestExcerpt(unittest.TestCase):
    def test_truncates_to_80_code_points(self):
        self.assertEqual(len(excerpt("字" * 200)), EXCERPT_CHARS)

    def test_keeps_short_text_intact(self):
        self.assertEqual(excerpt("短句"), "短句")

    def test_newlines_become_spaces(self):
        self.assertEqual(excerpt("第一行\n第二行"), "第一行 第二行")


class TestRecord(unittest.TestCase):
    def test_field_order_and_completeness(self):
        record = build_record(run_id="r1", query_raw="查询", dense=[("c1", 0.5)])
        self.assertEqual(tuple(record.keys()), TRACE_FIELDS)
        self.assertEqual(record["dense"][0]["rank"], 1)
        self.assertIsNone(record["reranked"])
        self.assertEqual(record["flags"], [])

    def test_missing_field_rejected(self):
        writer = TraceWriter(pathlib.Path(tempfile.gettempdir()) / "trace-test-missing.jsonl")
        with self.assertRaises(ValueError):
            writer.write({"run_id": "r1"})

    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            writer = TraceWriter(path)
            writer.write(build_record(run_id="r1", query_raw="查询一", hit_text="原文" * 50, hit_chunk_id="c1", hit_rank=1))
            writer.write(build_record(run_id="r2", query_raw="查询二"))
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            self.assertEqual(len(first["excerpt"]), EXCERPT_CHARS)
            self.assertNotIn(str(pathlib.Path.home()), lines[0])


if __name__ == "__main__":
    unittest.main()
