"""Agent 编排层单测（`CHG-013` S2）：两轮上限、工具数截断、超时降级、配额拒绝、引用校验、
以及「跑完不产物」的隔离证据。

除最后一个集成用例外，全部用假客户端 + 假 dispatch，不依赖库/索引/网络。
"""

from __future__ import annotations

import json
import pathlib
import time
import unittest
from types import SimpleNamespace

from src.agent import orchestrator, quota, schema, tools
from src.config import ConfigError, load

QUERY = "发明专利权的期限是几年"


# ---------- 假客户端 ----------


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name: str, arguments: dict | str, call_id: str = "call_1") -> None:
        self.id = call_id
        self.function = FakeFunction(name, arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False))


class FakeClient:
    """按脚本逐次返回响应；脚本项可以是响应对象、异常、或 `callable(kwargs)`。"""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("脚本已用尽，模型被多调了一次")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(kwargs)
        if item == "sleep":
            time.sleep(0.5)
            return message("慢响应 [c1]")
        return item


def message(content: str = "", tool_calls: list | None = None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or []))])


def tool_call_response(*calls: FakeToolCall):
    return message("", list(calls))


def memory_dispatch(record: list):
    """假 dispatch：只认 4 个工具名，结果足够让编排继续跑。"""

    def _dispatch(conf, name, payload):
        record.append((name, payload))
        if name == "search_laws":
            return {
                "hits": [
                    {"chunk_id": "c1", "doc_id": "d1", "title": "专利法", "article_no": "第四十二条",
                     "heading_path": "第六章", "score": 0.9, "path": "fused"}
                ],
                "flags": [],
                "count": 1,
            }
        if name == "get_anchor_text":
            return {"chunk_id": payload["chunk_id"], "text": "发明专利权的期限为二十年。", "truncated": False,
                    "char_start": 0, "char_end": 13, "doc_id": "d1", "title": "专利法", "article_no": "第四十二条",
                    "heading_path": "第六章", "max_chars": 800, "source_url": "https://example.invalid"}
        if name == "filter_metadata":
            return {"documents": [{"doc_id": "d1", "title": "专利法"}], "count": 1, "truncated": False}
        if name == "get_stats":
            return {"documents": 150, "chunks": 2704, "categories": [], "authorities": [],
                    "publish_date_range": {"from": "2000-01-01", "to": "2026-11-06"},
                    "weights_sha256": "abc", "normalizer_version": 0, "index_bytes": 1}
        raise tools.ToolError("TOOL_NOT_FOUND", "未知工具：%s" % name)

    return _dispatch


def load_conf_or_skip(tc: unittest.TestCase):
    """缺环境变量或库不存在时真正 Skip（不是 ERROR）。"""
    try:
        conf = load()
        db = pathlib.Path(conf.require_db_path())
    except ConfigError as exc:
        raise unittest.SkipTest("配置缺失（%s）" % exc)
    if not db.is_file():
        raise unittest.SkipTest("库不存在：%s" % db)
    return conf


class TestTwoRoundFlow(unittest.TestCase):
    def setUp(self):
        self.conf = SimpleNamespace(llm=SimpleNamespace(model_name="fake-model", model_env="RAG_LLM_MODEL",
                                                        base_url="", base_url_env="RAG_LLM_BASE_URL"))
        self.seen: list = []
        self.dispatch = memory_dispatch(self.seen)

    def run_agent(self, script, **kwargs):
        client = FakeClient(script)
        result = orchestrator.run(self.conf, QUERY, client=client, dispatch_fn=self.dispatch, **kwargs)
        return result, client

    def test_happy_path_two_rounds(self):
        result, client = self.run_agent(
            [tool_call_response(FakeToolCall("search_laws", {"query": QUERY, "top_k": 5})), message("期限二十年。[c1]")]
        )
        self.assertEqual(result["answer"], "期限二十年。[c1]")
        self.assertEqual(result["citations"], ["c1"])
        self.assertTrue(result["citation_valid"])
        self.assertEqual(result["flags"], [])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["tool_choice"], "auto")
        self.assertNotIn("tool_choice", client.calls[1])  # 末轮摘掉工具，只给 messages
        self.assertNotIn("tools", client.calls[1])
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertTrue(result["tool_trace"][0]["ok"])
        self.assertEqual(result["tool_trace"][0]["digest"]["count"], 1)
        self.assertTrue(result["stateless_mode"])
        self.assertEqual(self.seen[0][0], "search_laws")

    def test_tools_payload_matches_chat_api(self):
        """真实调用要求 `{"type":"function","function":{...}}`，扁平结构会被 422 拒。"""
        _, client = self.run_agent([message("好。")])
        tools = client.calls[0]["tools"]
        self.assertEqual(len(tools), 4)
        for item in tools:
            self.assertEqual(item["type"], "function")
            self.assertIn("name", item["function"])
            self.assertIn("parameters", item["function"])
            self.assertNotIn("name", item)  # 扁平字段不能留在外层

    def test_no_tool_call_answers_directly(self):
        result, client = self.run_agent([message("现有条文不足以回答。")])
        self.assertEqual(len(client.calls), 1)
        self.assertIn(orchestrator.FLAG_NO_TOOL, result["flags"])
        self.assertEqual(result["answer"], "现有条文不足以回答。")

    def test_history_trimmed_to_max_context_turns(self):
        history = [{"role": "user", "content": "第%d轮" % i} for i in range(5)]
        result, client = self.run_agent(
            [message("好。")], history=history, settings=quota.AgentSettings(max_context_turns=2)
        )
        sent = client.calls[0]["messages"]
        self.assertEqual(len(sent), 1 + 2 + 1)  # system + 2 条历史 + 本轮
        self.assertEqual(sent[1]["content"], "第3轮")
        self.assertEqual(sent[0]["role"], "system")

    def test_second_round_tool_call_hits_turn_limit(self):
        result, client = self.run_agent(
            [
                tool_call_response(FakeToolCall("search_laws", {"query": QUERY})),
                tool_call_response(FakeToolCall("get_anchor_text", {"chunk_id": "c1"})),
            ]
        )
        self.assertEqual(len(client.calls), 2)
        self.assertIn(orchestrator.FLAG_TURN_LIMIT_HIT, result["flags"])
        self.assertEqual(result["answer"], "")
        self.assertEqual(len(result["tool_trace"]), 1)

    def test_tool_calls_truncated_to_limit(self):
        calls = [FakeToolCall("search_laws", {"query": QUERY}, call_id="call_%d" % i) for i in range(4)]
        result, _ = self.run_agent([tool_call_response(*calls), message("好。[c1]")])
        self.assertEqual(len(result["tool_trace"]), 3)
        self.assertIn(orchestrator.FLAG_TOOL_CALLS_TRUNCATED, result["flags"])

    def test_invalid_arguments_flagged_and_skipped(self):
        result, client = self.run_agent(
            [tool_call_response(FakeToolCall("search_laws", "{not-json")), message("换一种问法。[c1]")]
        )
        self.assertEqual(result["tool_trace"][0]["code"], "TOOL_ARGS_INVALID")
        self.assertIn(orchestrator.FLAG_TOOL_ARGS_INVALID, result["flags"])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result["answer"], "换一种问法。[c1]")

    def test_unknown_tool_not_in_whitelist(self):
        result, _ = self.run_agent([tool_call_response(FakeToolCall("drop_tables", {})), message("好。")])
        self.assertEqual(result["tool_trace"][0]["code"], "TOOL_NOT_FOUND")

    def test_invalid_citation_kept_but_flagged(self):
        result, _ = self.run_agent(
            [tool_call_response(FakeToolCall("search_laws", {"query": QUERY})), message("见 [c1]，另见 [c9]。")]
        )
        self.assertFalse(result["citation_valid"])
        self.assertEqual(result["invalid_citations"], ["c9"])
        self.assertIn(orchestrator.FLAG_CITATION_INVALID, result["flags"])
        self.assertIn("另见", result["answer"])  # 答案不因引用越界被丢弃

    def test_timeout_degrades(self):
        client = FakeClient(["sleep"])
        result = orchestrator.run(
            self.conf,
            QUERY,
            client=client,
            dispatch_fn=self.dispatch,
            settings=quota.AgentSettings(timeout_seconds=0.05),
        )
        self.assertIn(orchestrator.FLAG_AGENT_TIMEOUT, result["flags"])
        self.assertEqual(result["answer"], "")
        self.assertEqual(result["citations"], [])
        self.assertEqual(len(client.calls), 1)

    def test_quota_per_question_rejects_second_call(self):
        with self.assertRaises(orchestrator.AgentError) as ctx:
            orchestrator.run(
                self.conf,
                QUERY,
                client=FakeClient([tool_call_response(FakeToolCall("search_laws", {"query": QUERY})), message("好。")]),
                dispatch_fn=self.dispatch,
                settings=quota.AgentSettings(max_calls_per_question=1),
            )
        self.assertEqual(ctx.exception.code, "AGENT_QUOTA_EXCEEDED")

    def test_session_quota_exhausted(self):
        settings = quota.AgentSettings(max_calls_per_session=1)
        q = quota.Quota(settings)
        q.session_calls = 1
        with self.assertRaises(orchestrator.AgentError) as ctx:
            orchestrator.run(self.conf, QUERY, client=FakeClient([message("好。")]), dispatch_fn=self.dispatch, quota=q)
        self.assertEqual(ctx.exception.code, "AGENT_QUOTA_EXCEEDED")

    def test_empty_query_rejected(self):
        with self.assertRaises(orchestrator.AgentError) as ctx:
            orchestrator.run(self.conf, "   ", client=FakeClient([]), dispatch_fn=self.dispatch)
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")


class TestSettingsAndQuota(unittest.TestCase):
    def test_hard_caps_cannot_be_raised(self):
        for kwargs in ({"max_turns": 3}, {"max_tool_calls_per_turn": 4}, {"max_context_turns": 5}):
            with self.assertRaises(ValueError):
                quota.AgentSettings(**kwargs)

    def test_lowering_is_allowed(self):
        settings = quota.AgentSettings(max_turns=1, max_tool_calls_per_turn=1, max_context_turns=1)
        self.assertEqual(settings.max_turns, 1)

    def test_quota_counters(self):
        q = quota.Quota(quota.AgentSettings(max_calls_per_question=2, max_tool_calls_per_turn=1))
        q.start_question()
        q.take_call()
        q.take_tool()
        self.assertEqual(q.question_calls, 1)
        with self.assertRaises(quota.QuotaExceeded):
            q.take_tool()
        q.take_call()
        with self.assertRaises(quota.QuotaExceeded):
            q.take_call()
        snapshot = q.snapshot()
        self.assertEqual(snapshot["session_calls"], 2)
        self.assertEqual(snapshot["limits"]["max_turns"], 2)


class TestSchemaGuardStillHolds(unittest.TestCase):
    """S2 不改 schema，但回归时顺手确认 S1 的守门仍然有效。"""

    def test_no_conditional_keywords(self):
        def find(node, hits, path="root"):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"oneOf", "anyOf", "allOf", "if", "then", "not", "else", "$ref", "$defs"}:
                        hits.append(path + "/" + key)
                    find(value, hits, path + "/" + key)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    find(value, hits, "%s[%d]" % (path, index))
            return hits

        for item in schema.TOOL_SCHEMAS:
            self.assertEqual(find(item["parameters"], []), [])


class TestIntegrationIsolation(unittest.TestCase):
    """真 dispatch + 假客户端：跑一遍后不新增 runs 目录、不写 trace（D1 证据）。"""

    def test_no_runs_and_trace_untouched(self):
        conf = load_conf_or_skip(self)
        trace_file = pathlib.Path(conf.paths.trace_file)
        runs_dir = pathlib.Path(conf.paths.runs_dir)
        trace_before = trace_file.stat().st_size if trace_file.is_file() else None
        runs_before = sorted(p.name for p in runs_dir.iterdir()) if runs_dir.is_dir() else []

        def answer_with_real_chunk(kwargs):
            # 末轮会追加一条 system 提醒，工具结果不是最后一条 → 倒着找 role=tool
            tool_message = next(msg for msg in reversed(kwargs["messages"]) if msg.get("role") == "tool")
            tool_payload = json.loads(tool_message["content"])
            chunk_id = tool_payload["hits"][0]["chunk_id"]
            return message("依据条文，期限为二十年。[%s]" % chunk_id)

        client = FakeClient([tool_call_response(FakeToolCall("search_laws", {"query": QUERY, "top_k": 3})), answer_with_real_chunk])
        result = orchestrator.run(conf, QUERY, client=client)

        self.assertEqual(result["citations"], result["citations"][:1])
        self.assertTrue(result["citation_valid"])
        self.assertTrue(result["tool_trace"][0]["ok"])

        trace_after = trace_file.stat().st_size if trace_file.is_file() else None
        runs_after = sorted(p.name for p in runs_dir.iterdir()) if runs_dir.is_dir() else []
        self.assertEqual(trace_before, trace_after, "agent 调用写入了 trace")
        self.assertEqual(runs_before, runs_after, "agent 调用新增了 runs 目录")


if __name__ == "__main__":
    unittest.main()
