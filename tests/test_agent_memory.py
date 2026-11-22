"""S3 单测（`CHG-013` §10）：规则式改写、会话存取与隔离、TTL 读时判定、迁移只加不改、
以及 `config.yaml` 的 `agent.*` 与 `AgentSettings` 默认值逐项一致。

全部用临时库 + 临时目录，不碰 `data/rag.db`，也不依赖模型权重。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta

from src import config as config_mod
from src.agent import memory, quota
from src.store.db import apply_migrations, connect

MIGRATIONS = pathlib.Path(config_mod.PROJECT_ROOT) / "specs" / "06-schemas" / "migrations"


class TempDbCase(unittest.TestCase):
    """每个用例一个临时库；`RAG_DB_PATH` 在用例期间指向它。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="agent-s3-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db_path = self.tmp / "rag.db"
        self.env = unittest.mock.patch.dict(os.environ, {"RAG_DB_PATH": str(self.db_path)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.conf = config_mod.load()

    def count(self, sql: str, args: tuple = ()) -> int:
        conn = connect(self.db_path)
        try:
            return int(conn.execute(sql, args).fetchone()[0])
        finally:
            conn.close()


class TestRewriteRules(unittest.TestCase):
    """规则式改写：0 次 API，纯函数。"""

    TODAY = datetime(2026, 11, 22, 10, 0, 0)

    def test_pronoun_carryover(self):
        turns = [{"turn_no": 1, "query_raw": "专利法第四十二条怎么规定的"}]
        result = memory.rewrite_query("它还有效吗", turns, today=self.TODAY)
        self.assertEqual(result.rule, memory.RULE_PRONOUN)
        self.assertIn("专利法第四十二条怎么规定的", result.query)
        self.assertEqual(result.source_turn, 1)

    def test_ellipsis_append(self):
        turns = [{"turn_no": 1, "query_raw": "发明专利权的期限"}]
        result = memory.rewrite_query("那实用新型呢", turns, today=self.TODAY)
        self.assertEqual(result.rule, memory.RULE_ELLIPSIS)
        self.assertIn("发明专利权的期限", result.query)

    def test_date_inherit(self):
        result = memory.rewrite_query("去年发布了哪些专利法规", [], today=self.TODAY)
        self.assertEqual(result.rule, memory.RULE_DATE)
        self.assertIn("2025", result.query)
        self.assertNotIn("去年", result.query)

    def test_explicit_year_is_kept(self):
        result = memory.rewrite_query("2024年发布的专利法规", [], today=self.TODAY)
        self.assertEqual(result.rule, memory.RULE_NONE)
        self.assertIn("2024", result.query)

    def test_no_history_no_rule(self):
        result = memory.rewrite_query("发明专利权的期限是几年", [], today=self.TODAY)
        self.assertEqual(result.rule, memory.RULE_NONE)
        self.assertEqual(result.query, "发明专利权的期限是几年")

    def test_empty_query(self):
        self.assertEqual(memory.rewrite_query("   ", [], today=self.TODAY).rule, memory.RULE_NONE)

    def test_previous_rewritten_preferred(self):
        turns = [{"turn_no": 2, "query_raw": "那实用新型呢", "query_rewritten": "发明专利权的期限；那实用新型呢"}]
        result = memory.rewrite_query("它呢", turns, today=self.TODAY)
        self.assertIn("发明专利权的期限", result.query)
        self.assertEqual(result.query.count("发明专利权的期限"), 1)  # 不重复叠加


class TestSessionStore(TempDbCase):
    def test_create_and_reuse(self):
        first = memory.open_session(self.conf, now=datetime(2026, 11, 22, 9, 0, 0))
        self.assertFalse(first["expired"])
        self.assertTrue(first["session_id"])
        self.assertTrue(first["stateless_mode"])
        again = memory.open_session(self.conf, first["session_id"], now=datetime(2026, 11, 22, 9, 30, 0))
        self.assertEqual(again["session_id"], first["session_id"])
        self.assertFalse(again["expired"])

    def test_record_and_reload(self):
        session = memory.open_session(self.conf)["session_id"]
        self.assertEqual(memory.next_turn_no(self.conf, session), 1)
        memory.record_turn(
            self.conf, session, turn_no=1, query_raw="专利期限", query_rewritten="专利期限",
            rewrite_rule=memory.RULE_NONE, tool_calls=[{"name": "search_laws", "ok": True}],
            answer="二十年 [c1]", citations=["c1"], citation_valid=True, flags=[], elapsed_ms=12.5,
        )
        memory.record_turn(
            self.conf, session, turn_no=2, query_raw="它呢", query_rewritten="专利期限；它呢",
            rewrite_rule=memory.RULE_PRONOUN, answer="十年 [c2]", citations=["c2"], citation_valid=True,
        )
        self.assertEqual(memory.next_turn_no(self.conf, session), 3)
        turns = memory.load_turns(self.conf, session, limit=5)
        self.assertEqual([turn["turn_no"] for turn in turns], [1, 2])
        self.assertEqual(turns[1]["rewrite_rule"], memory.RULE_PRONOUN)

        history = memory.history_for_prompt(self.conf, session, limit=5)
        self.assertEqual([item["role"] for item in history], ["user", "assistant", "user", "assistant"])
        self.assertEqual(history[0]["content"], "专利期限")
        self.assertEqual(history[3]["content"], "十年 [c2]")

    def test_idempotent_same_turn(self):
        session = memory.open_session(self.conf)["session_id"]
        for answer in ("第一版", "第二版"):
            memory.record_turn(self.conf, session, turn_no=1, query_raw="问", answer=answer)
        self.assertEqual(self.count("SELECT COUNT(*) FROM agent_turns WHERE session_id = ?", (session,)), 1)
        self.assertEqual(memory.load_turns(self.conf, session)[0]["answer"], "第二版")

    def test_sessions_isolated(self):
        s1 = memory.open_session(self.conf)["session_id"]
        s2 = memory.open_session(self.conf)["session_id"]
        self.assertNotEqual(s1, s2)
        memory.record_turn(self.conf, s1, turn_no=1, query_raw="只属于 s1", answer="a1")
        memory.record_turn(self.conf, s2, turn_no=1, query_raw="只属于 s2", answer="a2")
        self.assertEqual([t["query_raw"] for t in memory.load_turns(self.conf, s1)], ["只属于 s1"])
        self.assertEqual([t["query_raw"] for t in memory.load_turns(self.conf, s2)], ["只属于 s2"])
        self.assertEqual(memory.load_turns(self.conf, "不存在的会话"), [])

    def test_ttl_expiry_creates_new_session(self):
        t0 = datetime(2026, 11, 22, 9, 0, 0)
        old = memory.open_session(self.conf, now=t0)["session_id"]
        memory.record_turn(self.conf, old, turn_no=1, query_raw="旧会话", answer="a")
        # 24h TTL：25 小时后再来，应按新会话处理
        renewed = memory.open_session(self.conf, old, now=t0 + timedelta(hours=25))
        self.assertTrue(renewed["expired"])
        self.assertNotEqual(renewed["session_id"], old)
        self.assertEqual(memory.load_turns(self.conf, renewed["session_id"]), [])

    def test_unknown_session_starts_new(self):
        fresh = memory.open_session(self.conf, "nope-session-id")
        self.assertFalse(fresh["expired"])
        self.assertNotEqual(fresh["session_id"], "nope-session-id")


class TestMigration(TempDbCase):
    def test_agent_tables_created(self):
        conn = connect(self.db_path)
        try:
            applied = apply_migrations(conn, MIGRATIONS)
        finally:
            conn.close()
        self.assertIn(4, applied)
        rows = sqlite3.connect(str(self.db_path)).execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {row[0] for row in rows}
        for expected in ("agent_sessions", "agent_turns", "documents", "chunks", "runs", "traces"):
            self.assertIn(expected, names)
        versions = sqlite3.connect(str(self.db_path)).execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        self.assertEqual([row[0] for row in versions], [1, 2, 3, 4])

    def test_sql_only_adds_agent_tables(self):
        text = (MIGRATIONS / "0004_agent.sql").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("create table if not exists agent_sessions", lowered)
        self.assertIn("create table if not exists agent_turns", lowered)
        for forbidden in ("alter table", "drop table", "update documents", "update chunks", "delete from"):
            self.assertNotIn(forbidden, lowered)
        for legacy in ("0001_init.sql", "0002_parents.sql", "0003_runtime.sql"):
            old = (MIGRATIONS / legacy).read_text(encoding="utf-8").lower()
            self.assertNotIn("agent_", old, "旧迁移不应被改动：%s" % legacy)


class TestAgentConfig(unittest.TestCase):
    """配置与 `AgentSettings` 的默认值逐项绑定，防止改一边漏一边。"""

    def test_config_defaults_match_quota_defaults(self):
        self.assertEqual(config_mod.AGENT_DEFAULTS, quota.DEFAULTS)

    def test_settings_field_defaults_match(self):
        fields = {field.name: field.default for field in dataclasses.fields(quota.AgentSettings)}
        self.assertEqual(fields, quota.DEFAULTS)

    def test_repo_config_values_equal_defaults(self):
        conf = config_mod.load()
        for name, default in config_mod.AGENT_DEFAULTS.items():
            self.assertEqual(getattr(conf.agent, name), default, "config.yaml 的 agent.%s 与默认值不一致" % name)

    def test_ui_port_agent_does_not_move_existing_ports(self):
        conf = config_mod.load()
        self.assertEqual(conf.server.api_port, 8000)
        self.assertEqual(conf.server.ui_port, 8501)
        self.assertEqual(conf.server.ui_port_agent, 8502)

    def test_hard_caps_rejected_in_config(self):
        source = pathlib.Path(config_mod.DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")
        for key in ("max_turns", "max_tool_calls_per_turn", "max_context_turns"):
            broken = source.replace("  %s: 2" % key, "  %s: 9" % key).replace("  %s: 3" % key, "  %s: 9" % key)
            with tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp) / "config.yaml"
                path.write_text(broken, encoding="utf-8")
                with self.assertRaises(config_mod.ConfigError, msg="agent.%s 应拒绝上调" % key):
                    config_mod.load(path)

    def test_settings_still_validate_caps(self):
        """配置读进来后仍走 `AgentSettings` 的同一条校验（不是两套口径）。"""
        with self.assertRaises(ValueError):
            quota.AgentSettings(max_turns=9)
        conf = config_mod.load()
        settings = quota.AgentSettings.from_conf(conf)
        self.assertEqual(settings.max_turns, conf.agent.max_turns)
        self.assertEqual(settings.session_ttl_hours, conf.agent.session_ttl_hours)


if __name__ == "__main__":
    unittest.main()
