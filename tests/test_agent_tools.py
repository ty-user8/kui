"""Agent 工具层单测（`CHG-013` S1）：schema 结构、参数校验、4 个工具的正常/边界/错误路径，
以及「同一 query 下工具结果与 `/search` 逐条一致」这条硬验收。

需要真实的 `data/rag.db` 与索引（CI 里在第 10~12 步之后才跑单测，顺序天然满足）；缺失时 skip。
"""

from __future__ import annotations

import pathlib
import unittest

from src.agent import schema, tools
from src.api import service
from src.config import ConfigError, load

QUERY = "发明专利权的期限是几年"


def load_conf_or_skip(tc: unittest.TestCase):
    """缺 `RAG_DB_PATH`／库不存在时真正 Skip 掉依赖库与索引的用例（不是 ERROR）。

    注意：`TestCase.skipTest` 是实例方法，在 `setUpClass` 里对类调用会变成
    `TypeError: missing 1 required positional argument`；这里统一 `raise unittest.SkipTest`。
    结构断言类不调用本函数，因此缺环境变量时仍会照常跑。
    """
    try:
        conf = load()
        db = pathlib.Path(conf.require_db_path())
    except ConfigError as exc:
        raise unittest.SkipTest("配置缺失（%s），跳过依赖库与索引的用例" % exc)
    if not db.is_file():
        raise unittest.SkipTest("库不存在：%s" % db)
    return conf


def find_keys(node, forbidden: set[str], path: str = "root") -> list[str]:
    """递归找出 schema 里的禁用关键字（含 `$ref`／`$defs`，strict 模式同样不建议）。"""
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in forbidden:
                hits.append("%s/%s" % (path, key))
            hits.extend(find_keys(value, forbidden, "%s/%s" % (path, key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits.extend(find_keys(value, forbidden, "%s[%d]" % (path, index)))
    return hits


class TestSchemaShape(unittest.TestCase):
    """模型可见 schema 的结构约束（`CHG-013` §5 通用规则）。"""

    def test_four_tools_in_whitelist(self):
        names = [item["name"] for item in schema.TOOL_SCHEMAS]
        self.assertEqual(names, list(schema.TOOL_NAMES))
        self.assertEqual(len(names), 4)

    def test_no_conditional_keywords(self):
        forbidden = {"oneOf", "anyOf", "allOf", "if", "then", "not", "else"}
        for item in schema.TOOL_SCHEMAS:
            hits = find_keys(item["parameters"], forbidden)
            self.assertEqual(hits, [], "工具 %s 的 schema 含条件构造：%s" % (item["name"], hits))

    def test_no_ref_or_defs(self):
        for item in schema.TOOL_SCHEMAS:
            hits = find_keys(item["parameters"], {"$ref", "$defs", "definitions"})
            self.assertEqual(hits, [], "工具 %s 的 schema 含引用构造：%s" % (item["name"], hits))

    def test_every_parameter_object_forbids_extra(self):
        def walk(node, name):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False, "工具 %s 有对象未禁额外字段" % name)
                for value in node.values():
                    walk(value, name)

        for item in schema.TOOL_SCHEMAS:
            walk(item["parameters"], item["name"])

    def test_filter_metadata_value_is_plain_array(self):
        params = next(item for item in schema.TOOL_SCHEMAS if item["name"] == "filter_metadata")["parameters"]
        value = params["properties"]["value"]
        self.assertEqual(value["type"], "array")
        self.assertEqual(value["minItems"], 1)
        self.assertEqual(value["maxItems"], 10)
        self.assertEqual(value["items"]["type"], "string")

    def test_filter_metadata_description_carries_combination_rules(self):
        item = next(item for item in schema.TOOL_SCHEMAS if item["name"] == "filter_metadata")
        for token in ("between", "publish_date", "contains", "title", "TOOL_ARGS_INVALID"):
            self.assertIn(token, item["description"])

    def test_get_anchor_text_only_exposes_chunk_id(self):
        params = next(item for item in schema.TOOL_SCHEMAS if item["name"] == "get_anchor_text")["parameters"]
        self.assertEqual(params["required"], ["chunk_id"])
        self.assertEqual(sorted(params["properties"]), ["chunk_id", "max_chars"])


class TestArgValidation(unittest.TestCase):
    """参数校验在代码侧兜底：非法结构一律 `TOOL_ARGS_INVALID`。"""

    def test_extra_field_rejected(self):
        with self.assertRaises(schema.ToolArgError) as ctx:
            schema.validate_args("search_laws", {"query": "水法", "foo": 1})
        self.assertEqual(ctx.exception.code, "TOOL_ARGS_INVALID")

    def test_unknown_tool_raises_key_error(self):
        with self.assertRaises(KeyError):
            schema.validate_args("delete_everything", {})

    def test_between_requires_publish_date(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args(
                "filter_metadata",
                {"field": "category", "op": "between", "value": ["2020-01-01", "2021-01-01"]},
            )

    def test_between_requires_two_dates(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args(
                "filter_metadata", {"field": "publish_date", "op": "between", "value": ["2020-01-01"]}
            )

    def test_between_rejects_bad_date_format(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args(
                "filter_metadata", {"field": "publish_date", "op": "between", "value": ["2020/01/01", "2021-01-01"]}
            )

    def test_contains_only_for_title(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args("filter_metadata", {"field": "category", "op": "contains", "value": ["法"]})

    def test_eq_requires_single_value(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args("filter_metadata", {"field": "category", "op": "eq", "value": ["法律", "行政法规"]})

    def test_valid_combination_passes(self):
        args = schema.validate_args(
            "filter_metadata", {"field": "publish_date", "op": "between", "value": ["2020-01-01", "2026-12-31"]}
        )
        self.assertEqual(args.field, "publish_date")

    def test_max_chars_capped(self):
        with self.assertRaises(schema.ToolArgError):
            schema.validate_args("get_anchor_text", {"chunk_id": "x", "max_chars": schema.MAX_TOOL_CHARS + 1})


class TestSearchTool(unittest.TestCase):
    """`search_laws` 与 `/search` 必须逐条一致（同一条链路，不另建索引）。"""

    @classmethod
    def setUpClass(cls):
        cls.conf = load_conf_or_skip(cls)

    def test_matches_search_service_exactly(self):
        direct = service.search(self.conf, QUERY, 5, None, write_trace=False)
        tool = tools.dispatch(self.conf, "search_laws", {"query": QUERY, "top_k": 5})
        self.assertEqual([item["chunk_id"] for item in tool["hits"]], [item["chunk_id"] for item in direct["results"]])
        self.assertEqual([item["score"] for item in tool["hits"]], [item["score"] for item in direct["results"]])
        self.assertEqual(tool["flags"], direct["flags"])
        self.assertEqual(tool["count"], len(direct["results"]))

    def test_matches_search_service_with_filters(self):
        payload = {"category": ["法律"]}
        direct = service.search(self.conf, "专利", 5, dict(payload), write_trace=False)
        tool = tools.dispatch(
            self.conf, "search_laws", {"query": "专利", "top_k": 5, "filters": {"category": ["法律"]}}
        )
        self.assertEqual([item["chunk_id"] for item in tool["hits"]], [item["chunk_id"] for item in direct["results"]])
        self.assertEqual(tool["flags"], direct["flags"])

    def test_hits_carry_title_and_anchor(self):
        tool = tools.dispatch(self.conf, "search_laws", {"query": QUERY, "top_k": 3})
        self.assertTrue(tool["hits"])
        first = tool["hits"][0]
        self.assertIn("title", first)
        self.assertTrue(first["chunk_id"])
        self.assertIn(first["path"], ("dense", "fused", "rerank"))

    def test_does_not_write_trace_or_runs(self):
        """工具调用不得产出评测/追踪产物（`CHG-013` §8.1 D1）。"""
        trace_file = pathlib.Path(self.conf.paths.trace_file)
        runs_dir = pathlib.Path(self.conf.paths.runs_dir)
        trace_before = trace_file.stat().st_size if trace_file.is_file() else None
        runs_before = sorted(p.name for p in runs_dir.iterdir()) if runs_dir.is_dir() else []

        tools.dispatch(self.conf, "search_laws", {"query": QUERY, "top_k": 3})

        trace_after = trace_file.stat().st_size if trace_file.is_file() else None
        runs_after = sorted(p.name for p in runs_dir.iterdir()) if runs_dir.is_dir() else []
        self.assertEqual(trace_before, trace_after, "工具调用写入了 trace")
        self.assertEqual(runs_before, runs_after, "工具调用新增了 runs 目录")


class TestFilterMetadataTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = load_conf_or_skip(cls)

    def test_eq_category(self):
        result = tools.dispatch(self.conf, "filter_metadata", {"field": "category", "op": "eq", "value": ["法律"]})
        self.assertGreater(result["count"], 0)
        self.assertTrue(all(doc["category"] == "法律" for doc in result["documents"]))

    def test_in_authority(self):
        result = tools.dispatch(
            self.conf,
            "filter_metadata",
            {"field": "authority", "op": "in", "value": ["全国人民代表大会常务委员会"]},
        )
        self.assertGreater(result["count"], 0)
        self.assertTrue(all(doc["authority"] == "全国人民代表大会常务委员会" for doc in result["documents"]))

    def test_between_publish_date(self):
        result = tools.dispatch(
            self.conf,
            "filter_metadata",
            {"field": "publish_date", "op": "between", "value": ["2026-01-01", "2026-12-31"]},
        )
        self.assertGreater(result["count"], 0)
        self.assertTrue(all("2026-01-01" <= (doc["publish_date"] or "")[:10] <= "2026-12-31" for doc in result["documents"]))

    def test_contains_title(self):
        result = tools.dispatch(self.conf, "filter_metadata", {"field": "title", "op": "contains", "value": ["专利"]})
        self.assertGreater(result["count"], 0)
        self.assertTrue(all("专利" in (doc["title"] or "") for doc in result["documents"]))

    def test_limit_truncates_and_flags(self):
        result = tools.dispatch(self.conf, "filter_metadata", {"field": "category", "op": "eq", "value": ["法律"], "limit": 1})
        self.assertEqual(len(result["documents"]), 1)
        self.assertGreater(result["count"], 1)
        self.assertTrue(result["truncated"])

    def test_no_match_returns_empty(self):
        result = tools.dispatch(self.conf, "filter_metadata", {"field": "category", "op": "eq", "value": ["不存在的分类"]})
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["documents"], [])
        self.assertFalse(result["truncated"])


class TestAnchorTextTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = load_conf_or_skip(cls)
        tool = tools.dispatch(cls.conf, "search_laws", {"query": QUERY, "top_k": 1})
        cls.chunk_id = tool["hits"][0]["chunk_id"]

    def test_returns_text_and_span(self):
        result = tools.dispatch(self.conf, "get_anchor_text", {"chunk_id": self.chunk_id})
        self.assertEqual(result["chunk_id"], self.chunk_id)
        self.assertTrue(result["text"])
        self.assertLess(result["char_start"], result["char_end"])
        self.assertFalse(result["truncated"])
        self.assertIn("source_url", result)

    def test_truncates_by_max_chars(self):
        result = tools.dispatch(self.conf, "get_anchor_text", {"chunk_id": self.chunk_id, "max_chars": 200})
        self.assertLessEqual(len(result["text"]), 200)
        self.assertGreater(result["char_end"] - result["char_start"], 200)
        self.assertTrue(result["truncated"])

    def test_unknown_chunk_raises_empty(self):
        with self.assertRaises(tools.ToolError) as ctx:
            tools.dispatch(self.conf, "get_anchor_text", {"chunk_id": "no-such-chunk:00000"})
        self.assertEqual(ctx.exception.code, "TOOL_RESULT_EMPTY")


class TestStatsTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = load_conf_or_skip(cls)

    def test_counts_match_corpus(self):
        result = tools.dispatch(self.conf, "get_stats", {})
        self.assertEqual(result["documents"], 150)
        self.assertEqual(result["chunks"], 2704)
        self.assertTrue(result["categories"])
        self.assertTrue(result["publish_date_range"]["from"])
        self.assertTrue(result["weights_sha256"])


class TestDispatchErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = load_conf_or_skip(cls)

    def test_unknown_tool(self):
        with self.assertRaises(tools.ToolError) as ctx:
            tools.dispatch(self.conf, "drop_tables", {})
        self.assertEqual(ctx.exception.code, "TOOL_NOT_FOUND")

    def test_invalid_args(self):
        with self.assertRaises(tools.ToolError) as ctx:
            tools.dispatch(self.conf, "search_laws", {"query": ""})
        self.assertEqual(ctx.exception.code, "TOOL_ARGS_INVALID")


if __name__ == "__main__":
    unittest.main()
