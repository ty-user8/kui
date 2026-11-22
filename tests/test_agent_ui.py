"""S4 单测（`CHG-013` §10）：页面辅助函数、客户端建法、以及 8502 入口的无头冒烟。

冒烟只验证「页面能起、会话能建、不抛异常」，不发模型请求（无 key 时也不应崩）。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import unittest
import unittest.mock

from src import config as config_mod
from src.agent import memory, ui


class TestFlagsNote(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(ui._flags_note([]))

    def test_known_flags_translated(self):
        note = ui._flags_note(["AGENT_TIMEOUT", "CITATION_INVALID"])
        self.assertIn("超时", note)
        self.assertIn("引用越界", note)

    def test_unknown_flag_passthrough(self):
        self.assertEqual(ui._flags_note(["SOMETHING_NEW"]), "SOMETHING_NEW")


class TestToolSummary(unittest.TestCase):
    def test_ok_and_failed_calls(self):
        raw = json.dumps(
            [
                {"name": "search_laws", "ok": True, "digest": {"count": 3}},
                {"name": "get_anchor_text", "ok": False, "code": "TOOL_RESULT_EMPTY"},
            ]
        )
        summary = ui._tool_summary(raw)
        self.assertIn("search_laws(3)", summary)
        self.assertIn("TOOL_RESULT_EMPTY", summary)

    def test_broken_json(self):
        self.assertEqual(ui._tool_summary("{not json"), "")


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
    """用官方 AppTest 无头跑 `app_agent.py`：不输入问题，只确认页面能起、会话能建。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="agent-ui-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / "rag.db"
        self.env = unittest.mock.patch.dict(os.environ, {"RAG_DB_PATH": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_page_boots(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(pathlib.Path(config_mod.PROJECT_ROOT) / "app_agent.py"), default_timeout=60)
        app.run()
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.title)
        self.assertIn("Agent", app.title[0].value)
        self.assertIn("会话", " ".join(caption.value for caption in app.caption))

    def test_first_connect_migrates_db(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(pathlib.Path(config_mod.PROJECT_ROOT) / "app_agent.py"), default_timeout=60)
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
