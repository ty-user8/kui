"""S4／展示层单测（`CHG-013` §10）：可读引用渲染、错误话术、客户端建法、8502 入口冒烟。

冒烟只验证「页面能起、会话能建、不抛异常」，不发模型请求（无 key 时也不应崩）；
用户端不得出现会话 id、配额数字、工具链与错误码。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest
import unittest.mock

from src import config as config_mod
from src.agent import ui

REFS = {
    "c1": {"title": "中华人民共和国专利法", "article_no": "第四十二条"},
    "c2": {"title": "中华人民共和国专利法", "article_no": "第六十八条"},
}


class TestRenderAnswer(unittest.TestCase):
    def test_known_id_becomes_readable(self):
        rendered = ui._render_answer("期限为二十年 [c1]。", REFS)
        self.assertIn("（《中华人民共和国专利法》第四十二条起）", rendered)
        self.assertNotIn("c1", rendered)

    def test_article_omitted_when_prose_already_names_it(self):
        """片段锚点是第三条/第四十条起，正文已写「第四十二条」时只标法规名，避免条号自相矛盾。"""
        rendered = ui._render_answer("依据《专利法》第四十二条：期限二十年 [c1]", REFS)
        self.assertIn("（《中华人民共和国专利法》）", rendered)
        self.assertEqual(rendered.count("第四十二条"), 1)

    def test_multiple_ids_all_replaced(self):
        rendered = ui._render_answer("[c1] 与 [c2]", REFS)
        self.assertNotIn("c1", rendered)
        self.assertNotIn("c2", rendered)
        self.assertEqual(rendered.count("（《中华人民共和国专利法》"), 2)

    def test_adjacent_duplicate_brackets_merged(self):
        rendered = ui._render_answer("期限二十年 [c1] [c1]", REFS)
        self.assertEqual(rendered.count("（《"), 1)

    def test_unknown_id_hidden(self):
        self.assertEqual(ui._render_answer("见 [c9]。", REFS), "见 。")

    def test_partial_marker_trimmed(self):
        self.assertEqual(ui._render_answer("期限二十年 [ff8080", REFS), "期限二十年 ")

    def test_title_only_and_article_only(self):
        self.assertEqual(ui._render_answer("[x]", {"x": {"title": "专利法"}}), "（《专利法》）")
        self.assertEqual(ui._render_answer("[y]", {"y": {"article_no": "第四十二条"}}), "（第四十二条起）")

    def test_no_marker_and_empty(self):
        self.assertEqual(ui._render_answer("二十年。", REFS), "二十年。")
        self.assertEqual(ui._render_answer(""), "")


class TestHumanError(unittest.TestCase):
    def test_quota_message_is_friendly(self):
        exc = type("E", (Exception,), {"code": "AGENT_QUOTA_EXCEEDED"})()
        text = ui._human_error(exc)
        self.assertIn("会话", text)
        self.assertNotIn("AGENT_QUOTA_EXCEEDED", text)

    def test_unknown_code_uses_default(self):
        exc = type("E", (Exception,), {"code": "SOMETHING_NEW"})()
        self.assertEqual(ui._human_error(exc), ui.DEFAULT_ERROR_TEXT)


class TestCitationsOf(unittest.TestCase):
    def test_parses_ids_and_ignores_broken_json(self):
        self.assertEqual(ui._citations_of({"citations_json": '["c1", "c2"]'}), ["c1", "c2"])
        self.assertEqual(ui._citations_of({"citations_json": "{not json"}), [])
        self.assertEqual(ui._citations_of({}), [])


class TestLoadRefs(unittest.TestCase):
    def test_missing_db_returns_empty(self):
        conf = unittest.mock.MagicMock()
        with unittest.mock.patch.object(ui.tools, "describe_chunks", side_effect=RuntimeError("no db")):
            self.assertEqual(ui._load_refs(conf, ["c1"]), {})

    def test_empty_ids_skips_lookup(self):
        with unittest.mock.patch.object(ui.tools, "describe_chunks") as fake:
            self.assertEqual(ui._load_refs(object(), []), {})
        fake.assert_not_called()


class TestMakeClient(unittest.TestCase):
    def setUp(self):
        self.conf = config_mod.load()

    def test_missing_key_is_explicit(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.conf.llm.api_key_env, None)
            with self.assertRaises(RuntimeError) as ctx:
                ui._make_client(self.conf)
        self.assertIn(self.conf.llm.api_key_env, str(ctx.exception))

    def test_client_uses_config_literals(self):
        fake_openai = unittest.mock.MagicMock()
        with unittest.mock.patch.dict(os.environ, {self.conf.llm.api_key_env: "sk-test"}), unittest.mock.patch(
            "openai.OpenAI", fake_openai
        ):
            ui._make_client(self.conf)
        kwargs = fake_openai.call_args.kwargs
        self.assertEqual(kwargs["base_url"], self.conf.llm.base_url)
        self.assertEqual(kwargs["timeout"], float(self.conf.agent.timeout_seconds))


class TestPageSmoke(unittest.TestCase):
    """用官方 AppTest 无头跑 `app_agent.py`：不输入问题，只确认页面能起、会话能建、内部信息不上页面。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="agent-ui-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / "rag.db"
        self.env = unittest.mock.patch.dict(os.environ, {"RAG_DB_PATH": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _app(self):
        from streamlit.testing.v1 import AppTest

        return AppTest.from_file(str(pathlib.Path(config_mod.PROJECT_ROOT) / "app_agent.py"), default_timeout=60)

    def test_page_boots(self):
        app = self._app()
        app.run()
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.title)
        self.assertIn("Agent", app.title[0].value)
        captions = " ".join(caption.value for caption in app.caption)
        self.assertIn("条文", captions)

    def test_internal_details_not_on_page(self):
        app = self._app()
        app.run()
        visible = " ".join(
            [element.value for element in app.title]
            + [element.value for element in app.caption]
            + [element.value for element in app.markdown]
        )
        for hidden in ("会话", "配额", "超时", "最多", "轮"):
            self.assertNotIn(hidden, visible, "用户端不应出现 %s" % hidden)

    def test_first_connect_migrates_db(self):
        app = self._app()
        app.run()
        self.assertTrue(self.db.is_file())
        import sqlite3

        conn = sqlite3.connect(str(self.db))
        try:
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        self.assertEqual(versions, [1, 2, 3, 4])
        self.assertIn("agent_sessions", tables)
        self.assertIn("agent_turns", tables)


if __name__ == "__main__":
    unittest.main()
