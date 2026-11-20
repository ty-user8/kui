"""生成层单测：不调真实模型，用注入的假客户端覆盖正常、越界、超时、缺 key、配额、无命中。"""

from __future__ import annotations

import dataclasses
import os
import time
import unittest
from types import SimpleNamespace

from src.config import load
from src.generate import ask as ask_mod


class FakeClient:
    """模仿 openai 的调用形状：client.chat.completions.create(...)。"""

    def __init__(self, answer: str = "结论 [doc:00012]。", delay: float = 0.0, boom: bool = False):
        self._answer = answer
        self._delay = delay
        self._boom = boom
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, timeout=None):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._boom:
            raise RuntimeError("boom")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._answer))])


HITS = [
    {"chunk_id": "doc:00012", "article_no": "第四十二条", "heading_path": "第五章"},
    {"chunk_id": "doc:00013", "article_no": None, "heading_path": ""},
]
TEXTS = {"doc:00012": "发明专利权的期限为二十年。", "doc:00013": "实用新型专利权的期限为十年。"}


def conf_with(**llm):
    conf = load()
    return dataclasses.replace(conf, llm=dataclasses.replace(conf.llm, **llm))


class TestAsk(unittest.TestCase):
    def setUp(self):
        ask_mod.reset_quota()
        self._saved = {key: os.environ.pop(key, None) for key in ("RAG_LLM_API_KEY", "RAG_LLM_MODEL")}
        os.environ["RAG_LLM_MODEL"] = "fake-model"

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        ask_mod.reset_quota()

    def test_valid_answer_passes_citation_check(self):
        result = ask_mod.ask(conf_with(), "期限是几年", HITS, TEXTS, client=FakeClient())
        self.assertEqual(result.reason, None)
        self.assertTrue(result.citation_valid)
        self.assertEqual(result.citations, ["doc:00012"])
        self.assertEqual(result.prompt_version, "ask.system.v1")
        self.assertEqual(result.model, "fake-model")

    def test_out_of_range_citation_keeps_answer(self):
        client = FakeClient(answer="期限二十年 [doc:00012]，另见 [doc:99999]。")
        result = ask_mod.ask(conf_with(), "期限", HITS, TEXTS, client=client)
        self.assertEqual(result.reason, "CITATION_INVALID")
        self.assertFalse(result.citation_valid)
        self.assertEqual(result.invalid_citations, ["doc:99999"])
        self.assertIn("doc:99999", result.answer)  # 答案不丢

    def test_timeout_returns_empty_answer_and_flag(self):
        client = FakeClient(delay=0.5)
        result = ask_mod.ask(conf_with(), "期限", HITS, TEXTS, client=client, timeout_s=0.05)
        self.assertEqual(result.reason, "ASK_TIMEOUT")
        self.assertEqual(result.answer, "")
        self.assertEqual(result.citations, [])

    def test_missing_api_key_raises_config_error(self):
        with self.assertRaises(ask_mod.AskError) as ctx:
            ask_mod.ask(conf_with(), "期限", HITS, TEXTS)
        self.assertEqual(ctx.exception.code, "CONFIG_MISSING_KEY")
        self.assertIn("RAG_LLM_API_KEY", ctx.exception.message)

    def test_missing_model_name_raises_config_error(self):
        os.environ.pop("RAG_LLM_MODEL", None)
        os.environ["RAG_LLM_API_KEY"] = "k"
        with self.assertRaises(ask_mod.AskError) as ctx:
            ask_mod.ask(conf_with(), "期限", HITS, TEXTS)
        self.assertEqual(ctx.exception.code, "CONFIG_MISSING_KEY")
        self.assertIn("RAG_LLM_MODEL", ctx.exception.message)

    def test_quota_exhausted_refuses_call(self):
        conf = conf_with(max_calls=1)
        ask_mod.ask(conf, "期限", HITS, TEXTS, client=FakeClient())
        with self.assertRaises(ask_mod.AskError) as ctx:
            ask_mod.ask(conf, "期限", HITS, TEXTS, client=FakeClient())
        self.assertEqual(ctx.exception.code, "INTERNAL_ERROR")
        self.assertEqual(ask_mod.quota_used(), 1)

    def test_no_hits_skips_model(self):
        client = FakeClient()
        result = ask_mod.ask(conf_with(), "无关问题", [], {}, client=client)
        self.assertEqual(result.reason, "NO_MATCH")
        self.assertEqual(client.calls, 0)
        self.assertEqual(result.answer, "")

    def test_model_error_becomes_structured_error(self):
        with self.assertRaises(ask_mod.AskError) as ctx:
            ask_mod.ask(conf_with(), "期限", HITS, TEXTS, client=FakeClient(boom=True))
        self.assertEqual(ctx.exception.code, "INTERNAL_ERROR")

    def test_empty_query_rejected(self):
        with self.assertRaises(ask_mod.AskError) as ctx:
            ask_mod.ask(conf_with(), "   ", HITS, TEXTS, client=FakeClient())
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")


class TestServiceWiring(unittest.TestCase):
    """端到端：真实索引与库 + 假模型，验证 /ask 的响应拼装（不需要 API key）。"""

    def setUp(self):
        ask_mod.reset_quota()
        self._saved = {key: os.environ.pop(key, None) for key in ("RAG_LLM_API_KEY", "RAG_LLM_MODEL")}
        os.environ["RAG_LLM_MODEL"] = "fake-model"

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        ask_mod.reset_quota()

    def test_response_shape_and_citations_inside_retrieval(self):
        from src.api import service

        conf = load()
        conf.require_db_path()  # 没有 RAG_DB_PATH 时跳过，避免 CI 误报
        client = FakeClient(answer="发明专利权的期限为二十年，自申请日起计算。")
        payload = service.answer(conf, "发明专利权的期限是几年", 3, client=client)
        self.assertEqual(sorted(payload), sorted([
            "answer", "citations", "citation_valid", "retrieval", "reason", "model", "prompt_version", "elapsed_ms",
        ]))
        self.assertEqual(payload["prompt_version"], "ask.system.v1")
        self.assertGreaterEqual(len(payload["retrieval"]["results"]), 1)
        allowed = {item["chunk_id"] for item in payload["retrieval"]["results"]}
        self.assertEqual(payload["citations"], [])
        self.assertTrue(payload["citation_valid"])
        self.assertTrue(allowed)

    def test_out_of_range_citation_marks_invalid_over_http_shape(self):
        from src.api import service

        conf = load()
        conf.require_db_path()
        client = FakeClient(answer="见 [zzz:99999]。")
        payload = service.answer(conf, "发明专利权的期限是几年", 3, client=client)
        self.assertFalse(payload["citation_valid"])
        self.assertEqual(payload["reason"], "CITATION_INVALID")
        self.assertEqual(payload["citations"], ["zzz:99999"])


class TestContext(unittest.TestCase):
    def test_labels_use_article_or_generic_word(self):
        context = ask_mod.build_context(HITS, TEXTS)
        self.assertIn("[doc:00012] 第四十二条（第五章）", context)
        self.assertIn("[doc:00013] 片段", context)
        self.assertNotIn("第2条", context)  # 没有条号时不得拿序号冒充

    def test_context_truncates_body(self):
        long_text = {"doc:00012": "字" * 1000}
        context = ask_mod.build_context([HITS[0]], long_text, limit_chars=50)
        body = context.rsplit(" ", 1)[-1]
        self.assertLessEqual(len(body), 50)


if __name__ == "__main__":
    unittest.main()
