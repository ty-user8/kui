"""trace 导入的单测：计次对账、重复导入幂等、rebuild、按 run 过滤。"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import tempfile
import unittest

from src.cli.import_traces import import_traces, trace_key
from src.config import load
from src.store.db import connect


def record(run_id: str, query: str, chunk: str | None = None, rank: int | None = None, case_id=None) -> dict:
    return {
        "run_id": run_id,
        "case_id": case_id,
        "query_raw": query,
        "query_norm": None,
        "dense": [],
        "bm25": [],
        "fused": [],
        "reranked": None,
        "hit_chunk_id": chunk,
        "hit_rank": rank,
        "excerpt": None,
        "latency_ms": {"total_ms": 12.5},
        "flags": [],
    }


class TestTraceKey(unittest.TestCase):
    def test_none_hit_rank_normalised(self):
        self.assertEqual(trace_key(record("r1", "q")), trace_key(record("r1", "q", None, None)))

    def test_different_query_is_different_key(self):
        self.assertNotEqual(trace_key(record("r1", "q1")), trace_key(record("r1", "q2")))


class TestImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.trace_file = self.root / "trace.jsonl"
        self.db_path = self.root / "rag.db"
        conf = load()
        self.conf = dataclasses.replace(conf, paths=dataclasses.replace(conf.paths, trace_file=self.trace_file))

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows: list[dict]) -> None:
        self.trace_file.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )

    def _count(self) -> int:
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        finally:
            conn.close()

    def test_first_import_writes_all_then_idempotent(self):
        # 3 条里有 1 条是同一 query 的重复，导入后应是 3 行（不压缩）
        self._write([record("r1", "q1", "c1", 1), record("r1", "q2", "c2", 2), record("r1", "q1", "c1", 1)])
        first = import_traces(self.conf, db_path=self.db_path)
        self.assertEqual((first["read"], first["inserted"], first["skipped"]), (3, 3, 0))
        self.assertEqual(self._count(), 3)

        second = import_traces(self.conf, db_path=self.db_path)
        self.assertEqual((second["inserted"], second["skipped"]), (0, 3))
        self.assertEqual(self._count(), 3)

    def test_incremental_append_only_adds_new_rows(self):
        self._write([record("r1", "q1", "c1", 1)])
        import_traces(self.conf, db_path=self.db_path)
        self._write([record("r1", "q1", "c1", 1), record("r1", "q2", "c2", 2)])
        result = import_traces(self.conf, db_path=self.db_path)
        self.assertEqual((result["inserted"], result["skipped"]), (1, 1))
        self.assertEqual(self._count(), 2)

    def test_same_query_twice_in_file_needs_two_rows(self):
        self._write([record("r1", "q1", "c1", 1), record("r1", "q1", "c1", 1)])
        import_traces(self.conf, db_path=self.db_path)
        self._write([record("r1", "q1", "c1", 1), record("r1", "q1", "c1", 1), record("r1", "q1", "c1", 1)])
        result = import_traces(self.conf, db_path=self.db_path)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self._count(), 3)

    def test_rebuild_purges_then_reinserts(self):
        self._write([record("r1", "q1", "c1", 1), record("r2", "q2", "c2", 2)])
        import_traces(self.conf, db_path=self.db_path)
        result = import_traces(self.conf, db_path=self.db_path, run_ids=["r1"], rebuild=True)
        self.assertEqual(result["purged"], 1)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self._count(), 2)  # r2 未被清

    def test_run_id_filter(self):
        self._write([record("r1", "q1"), record("r2", "q2")])
        result = import_traces(self.conf, db_path=self.db_path, run_ids=["r2"])
        self.assertEqual((result["read"], result["inserted"]), (1, 1))
        self.assertEqual(list(result["runs"]), ["r2"])

    def test_missing_trace_file_is_noop(self):
        result = import_traces(self.conf, db_path=self.db_path)
        self.assertEqual((result["read"], result["inserted"]), (0, 0))

    def test_imported_at_and_latency_are_recorded(self):
        self._write([record("r1", "q1", "c1", 1)])
        import_traces(self.conf, db_path=self.db_path)
        conn = connect(self.db_path)
        try:
            row = conn.execute("SELECT source_run_id, imported_at, latency_json FROM traces").fetchone()
        finally:
            conn.close()
        self.assertEqual(row["source_run_id"], "r1")
        self.assertTrue(row["imported_at"])
        self.assertEqual(json.loads(row["latency_json"]), {"total_ms": 12.5})


if __name__ == "__main__":
    unittest.main()
