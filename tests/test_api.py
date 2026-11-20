"""接口层的单元测试：参数校验、错误码映射、reason 优先级、trace 摘要。

不起 HTTP 服务（`starlette` 的 TestClient 需要额外装 `httpx`），
这里直接测 `service` 与 `errors`；真实请求链路由 `src.api.main` 起服务后用 urllib 冒烟。
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import tempfile
import unittest

from src.api import service
from src.api.errors import CODE_TO_STATUS, ApiError, error_body


class TestErrorMapping(unittest.TestCase):
    def test_every_code_has_status(self):
        expected = {
            "INVALID_REQUEST": 400,
            "ENTRY_UNSAFE_PATH": 400,
            "ENTRY_TOO_LARGE": 413,
            "ENTRY_UNSUPPORTED_FORMAT": 415,
            "PARSE_FAILED": 422,
            "PARSE_FAILURE_RATE_EXCEEDED": 422,
            "INDEX_EMPTY": 409,
            "RUN_NOT_FOUND": 404,
            "CONFIG_MISSING_KEY": 500,
            "INTERNAL_ERROR": 500,
        }
        for code, status in expected.items():
            self.assertEqual(ApiError(code, "x").status, status, code)

    def test_unknown_code_falls_back_to_500(self):
        self.assertEqual(ApiError("WHATEVER", "x").status, 500)

    def test_body_omits_empty_detail(self):
        self.assertEqual(error_body("INDEX_EMPTY", "先入库"), {"code": "INDEX_EMPTY", "message": "先入库"})

    def test_body_keeps_detail(self):
        self.assertEqual(error_body("RUN_NOT_FOUND", "无", {"run_id": "r1"})["detail"], {"run_id": "r1"})


class TestValidation(unittest.TestCase):
    def test_query_required(self):
        for bad in (None, "", "   "):
            with self.assertRaises(ApiError) as ctx:
                service.validate_query(bad)
            self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

    def test_top_k_bounds(self):
        self.assertEqual(service.validate_top_k(None, 5), 5)
        self.assertEqual(service.validate_top_k(50, 5), 50)
        for bad in (0, 51, -1):
            with self.assertRaises(ApiError):
                service.validate_top_k(bad, 5)

    def test_filters_unknown_key_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            service.parse_filters({"categoy": "法律"})  # 故意拼错
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        self.assertEqual(ctx.exception.detail["unknown"], ["categoy"])

    def test_filters_map_to_metadata_filter(self):
        flt = service.parse_filters(
            {"category": "法律", "publish_date_from": "2020-01-01", "doc_ids": ["d1"]}
        )
        self.assertEqual(flt.categories, {"法律"})
        self.assertEqual(flt.doc_ids, {"d1"})
        self.assertEqual(flt.publish_from, "2020-01-01")
        self.assertTrue(flt.active)

    def test_filters_bad_date_rejected(self):
        with self.assertRaises(ApiError):
            service.parse_filters({"publish_date_from": "2020/01/01"})

    def test_filters_date_order_rejected(self):
        with self.assertRaises(ApiError):
            service.parse_filters({"publish_date_from": "2021-01-01", "publish_date_to": "2020-01-01"})


class TestReason(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(service.reason_of([("c", 1.0)], ["FILTER_RELAXED"]), "FILTER_RELAXED")
        self.assertEqual(service.reason_of([], []), "NO_MATCH")
        self.assertEqual(service.reason_of([("c", 1.0)], ["FALLBACK_BM25"]), "FALLBACK_BM25")
        self.assertIsNone(service.reason_of([("c", 1.0)], []))

    def test_relaxed_wins_over_no_match(self):
        self.assertEqual(service.reason_of([], ["FILTER_RELAXED"]), "FILTER_RELAXED")


class FakeHybrid:
    pass


class FakeReranker:
    pass


class TestPath(unittest.TestCase):
    def test_path_by_retriever_type(self):
        class HybridRetriever:
            pass

        class RerankedRetriever:
            pass

        self.assertEqual(service.path_of(HybridRetriever(), []), "fused")
        self.assertEqual(service.path_of(RerankedRetriever(), []), "rerank")
        self.assertEqual(service.path_of(object(), []), "dense")
        # 向量路降级时命中来自 BM25，路径必须如实标 bm25
        self.assertEqual(service.path_of(HybridRetriever(), ["FALLBACK_BM25"]), "bm25")


class TestIndexEmpty(unittest.TestCase):
    def test_missing_index_raises_index_empty(self):
        from src.config import load

        os.environ.setdefault("RAG_DB_PATH", str(pathlib.Path("data") / "rag.db"))
        conf = load()
        broken = dataclasses.replace(
            conf, paths=dataclasses.replace(conf.paths, index_dir=pathlib.Path("data/index-absent"))
        )
        with self.assertRaises(ApiError) as ctx:
            service.search(broken, "发明专利权的期限", 5, write_trace=False)
        self.assertEqual(ctx.exception.code, "INDEX_EMPTY")


class TestEvalSplit(unittest.TestCase):
    def test_bad_split_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            service.eval_metrics(object(), "bogus")
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")


class TestTraceItems(unittest.TestCase):
    def _conf(self, trace_file: pathlib.Path):
        return type("Conf", (), {"paths": type("Paths", (), {"trace_file": trace_file})()})()

    def test_filters_by_run_id_and_shapes_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            rows = [
                {"run_id": "r1", "case_id": "C001", "query_raw": "q1", "query_norm": None,
                 "hit_chunk_id": "c1", "hit_rank": 1, "excerpt": "摘要", "latency_ms": {"total_ms": 1.5}, "flags": []},
                {"run_id": "r2", "case_id": "C002", "query_raw": "q2", "query_norm": None,
                 "hit_chunk_id": None, "hit_rank": None, "excerpt": None, "latency_ms": {}, "flags": []},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            items = service.trace_items(self._conf(path), "r1")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["case_id"], "C001")
            self.assertEqual(json.loads(items[0]["latency_json"]), {"total_ms": 1.5})

    def test_case_id_filter_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            rows = [
                {"run_id": "r1", "case_id": "C001", "query_raw": "q1", "query_norm": None,
                 "hit_chunk_id": None, "hit_rank": None, "excerpt": None, "latency_ms": {}, "flags": []},
                {"run_id": "r1", "case_id": "C002", "query_raw": "q2", "query_norm": None,
                 "hit_chunk_id": None, "hit_rank": None, "excerpt": None, "latency_ms": {}, "flags": []},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            self.assertEqual(len(service.trace_items(self._conf(path), "r1", "C002")), 1)
            self.assertEqual(len(service.trace_items(self._conf(path), "r1", limit=1)), 1)

    def test_unknown_run_id_raises_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ApiError) as ctx:
                service.trace_items(self._conf(path), "nope")
            self.assertEqual(ctx.exception.code, "RUN_NOT_FOUND")

    def test_limit_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            path.write_text("", encoding="utf-8")
            for bad in (0, 501):
                with self.assertRaises(ApiError):
                    service.trace_items(self._conf(path), "r1", limit=bad)


class TestContractCoverage(unittest.TestCase):
    """代码里用到的枚举值必须都在契约里声明，防止实现与 `openapi.yaml` 悄悄分叉。"""

    @classmethod
    def setUpClass(cls):
        import yaml

        cls.spec = yaml.safe_load(pathlib.Path("specs/07-api/openapi.yaml").read_text(encoding="utf-8"))

    def test_search_response_declares_flags_and_reason_enum(self):
        schema = self.spec["components"]["schemas"]["SearchResponse"]
        self.assertIn("flags", schema["properties"])
        self.assertEqual(
            set(schema["properties"]["reason"]["enum"]),
            {None, "NO_MATCH", "FALLBACK_BM25", "FILTER_RELAXED"},
        )

    def test_path_enum_matches_service_outputs(self):
        enum = set(self.spec["components"]["schemas"]["SearchResult"]["properties"]["path"]["enum"])
        self.assertEqual(enum, {"dense", "bm25", "fused", "rerank"})

    def test_trace_item_fields_are_covered(self):
        props = set(self.spec["components"]["schemas"]["TraceItem"]["properties"])
        rendered = {"case_id", "query_raw", "query_norm", "hit_chunk_id", "hit_rank", "excerpt", "latency_json"}
        self.assertTrue(rendered.issubset(props), rendered - props)


class TestAppWiring(unittest.TestCase):
    def test_routes_and_no_auth(self):
        from src.api.main import app

        paths = set(app.openapi()["paths"])
        self.assertEqual(paths, {"/search", "/eval", "/ingest", "/trace"})
        schema = json.dumps(app.openapi(), ensure_ascii=False)
        for forbidden in ("securitySchemes", "bearerAuth", "apiKey"):
            self.assertNotIn(forbidden, schema)


if __name__ == "__main__":
    unittest.main()
