"""会话记忆（`CHG-013` §8.2，D2）：会话与轮次落 SQLite，指代/省略/日期用规则式改写。

三条口径：

1. **规则式，0 次 API**：`rewrite_query` 是纯函数（代词表 + 上一轮问题 + 相对年份替换），
   不调模型、不读网络；规则名写进 `agent_turns.rewrite_rule`，便于解释"改写用了哪条规则"。
2. **读时判定过期**（D2）：`open_session` 比对 `last_active_at` 与 `session_ttl_hours`，
   过期就当新会话返回新 id；**没有后台清理任务**，旧行留在表里不影响功能。
3. **与评测隔离**：两张 `agent_*` 表不被 `/search`、`/eval`、`ci_check` 读取；
   本模块不写 `traces`／`runs`／`metrics.json`。
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.store.db import apply_migrations, connect

RULE_PRONOUN = "pronoun_carryover"
RULE_ELLIPSIS = "ellipsis_append"
RULE_DATE = "date_inherit"
RULE_NONE = "none"

# 指代词：出现即认为「这句话依赖上一轮的主语」
PRONOUNS = ("它", "他", "她", "该法", "该条", "这部", "这条", "上述", "其中", "其")
# 省略句：长度不超过这个值且带疑问语气，视为把上一轮问题当主语
ELLIPSIS_MAX_CHARS = 8
ELLIPSIS_MARKERS = ("呢", "吗", "还有", "再", "那", "怎么", "多少", "哪些")
RELATIVE_YEARS = {"今年": 0, "去年": -1, "前年": -2}
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

_STORED_TIME = "%Y-%m-%d %H:%M:%S"
_SCHEMA_READY: set[str] = set()


@dataclass(frozen=True)
class Rewrite:
    """改写结果：`rule` 为 `pronoun_carryover`／`ellipsis_append`／`date_inherit`／`none`。"""

    query: str
    rule: str
    source_turn: int | None = None
    note: str = ""


def _now(now: datetime | None) -> datetime:
    if now is not None:
        return now if now.tzinfo is None else now.astimezone(timezone.utc).replace(tzinfo=None)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rewrite_query(query: str, turns: list[dict] | None = None, today: datetime | None = None) -> Rewrite:
    """把「它／那期限呢／去年」这类依赖上下文的问法补成可检索的句子。

    `turns` 按时间正序（旧 → 新），每条至少含 `turn_no` 与 `query_raw`；优先用上一轮的
    `query_rewritten`（已经是补全后的句子）作为主语来源。
    """
    text = (query or "").strip()
    if not text:
        return Rewrite("", RULE_NONE)

    history = turns or []
    last = history[-1] if history else None
    base = ""
    if last:
        base = (last.get("query_rewritten") or last.get("query_raw") or "").strip()

    # 1) 相对年份 → 具体年份（纯替换，不依赖历史）
    date_changed = False
    if not YEAR_RE.search(text):
        for token, offset in RELATIVE_YEARS.items():
            if token in text:
                year = _now(today).year + offset
                text = text.replace(token, str(year))
                date_changed = True

    source_turn = last.get("turn_no") if last else None

    # 2) 指代词 → 把上一轮问句作为上下文前置
    if base and any(token in text for token in PRONOUNS) and base not in text:
        return Rewrite("%s；%s" % (base, text), RULE_PRONOUN, source_turn, "含指代词，前置上一轮问句")

    # 3) 省略句 → 同上（短问句 + 疑问语气）
    if base and len(text) <= ELLIPSIS_MAX_CHARS and any(mark in text for mark in ELLIPSIS_MARKERS) and base not in text:
        return Rewrite("%s；%s" % (base, text), RULE_ELLIPSIS, source_turn, "短问句，前置上一轮问句")

    if date_changed:
        return Rewrite(text, RULE_DATE, None, "相对年份换成了具体年份")
    return Rewrite(text, RULE_NONE)


def _connect(conf) -> sqlite3.Connection:
    """连库并确保迁移已应用（`apply_migrations` 幂等，进程内只跑一次）。"""
    db_path = str(conf.require_db_path())
    conn = connect(db_path)
    if db_path not in _SCHEMA_READY:
        apply_migrations(conn, pathlib.Path(conf.paths.migrations_dir))
        _SCHEMA_READY.add(db_path)
    return conn


def _row_to_session(row: sqlite3.Row, expired: bool = False) -> dict:
    return {
        "session_id": row["session_id"],
        "created_at": row["created_at"],
        "last_active_at": row["last_active_at"],
        "stateless_mode": bool(row["stateless_mode"]),
        "turn_count": row["turn_count"],
        "expired": expired,
    }


def open_session(conf, session_id: str | None = None, now: datetime | None = None) -> dict:
    """开或续一个会话；过期会话（超过 `session_ttl_hours`）按新会话处理（D2 读时判定）。"""
    stamp = _now(now).strftime(_STORED_TIME)
    ttl_hours = float(getattr(conf.agent, "session_ttl_hours", 24.0))
    conn = _connect(conf)
    try:
        if session_id:
            row = conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is not None:
                last = datetime.strptime(row["last_active_at"], _STORED_TIME)
                if _now(now) - last <= timedelta(hours=ttl_hours):
                    conn.execute("UPDATE agent_sessions SET last_active_at = ? WHERE session_id = ?", (stamp, session_id))
                    return _row_to_session(row)
                expired = True
            else:
                expired = False
        else:
            expired = False

        new_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO agent_sessions (session_id, created_at, last_active_at, stateless_mode, turn_count)"
            " VALUES (?, ?, ?, 1, 0)",
            (new_id, stamp, stamp),
        )
        row = conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (new_id,)).fetchone()
        return _row_to_session(row, expired=expired)
    finally:
        conn.close()


def next_turn_no(conf, session_id: str) -> int:
    conn = _connect(conf)
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_no), 0) AS last FROM agent_turns WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["last"]) + 1
    finally:
        conn.close()


def record_turn(
    conf,
    session_id: str,
    *,
    turn_no: int,
    query_raw: str,
    query_rewritten: str | None = None,
    rewrite_rule: str = RULE_NONE,
    tool_calls: list[dict] | None = None,
    answer: str = "",
    citations: list[str] | None = None,
    citation_valid: bool | None = None,
    flags: list[str] | None = None,
    elapsed_ms: float | None = None,
    now: datetime | None = None,
) -> None:
    """写入一轮；同一 `(session_id, turn_no)` 重复写就覆盖（重跑同一轮不会插两行）。"""
    import json

    stamp = _now(now).strftime(_STORED_TIME)
    conn = _connect(conf)
    try:
        conn.execute(
            "INSERT INTO agent_turns (session_id, turn_no, query_raw, query_rewritten, rewrite_rule,"
            " tool_calls_json, answer, citations_json, citation_valid, flags, elapsed_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id, turn_no) DO UPDATE SET"
            " query_raw = excluded.query_raw, query_rewritten = excluded.query_rewritten,"
            " rewrite_rule = excluded.rewrite_rule, tool_calls_json = excluded.tool_calls_json,"
            " answer = excluded.answer, citations_json = excluded.citations_json,"
            " citation_valid = excluded.citation_valid, flags = excluded.flags, elapsed_ms = excluded.elapsed_ms",
            (
                session_id,
                int(turn_no),
                query_raw,
                query_rewritten,
                rewrite_rule,
                json.dumps(tool_calls or [], ensure_ascii=False),
                answer,
                json.dumps(citations or [], ensure_ascii=False),
                None if citation_valid is None else int(bool(citation_valid)),
                ",".join(flags or []),
                elapsed_ms,
                stamp,
            ),
        )
        conn.execute(
            "UPDATE agent_sessions SET turn_count = ?, last_active_at = ? WHERE session_id = ?",
            (int(turn_no), stamp, session_id),
        )
    finally:
        conn.close()


def load_turns(conf, session_id: str, limit: int = 3) -> list[dict]:
    """按时间正序取最近 `limit` 轮；空会话返回空列表。"""
    conn = _connect(conf)
    try:
        rows = conn.execute(
            "SELECT turn_no, query_raw, query_rewritten, rewrite_rule, answer, citations_json, flags"
            " FROM agent_turns WHERE session_id = ? ORDER BY turn_no DESC LIMIT ?",
            (session_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in reversed(rows)]


def history_for_prompt(conf, session_id: str, limit: int = 3) -> list[dict]:
    """拼成模型消息：每轮两条（用户问句用改写后的，助手用答案）。"""
    messages: list[dict] = []
    for turn in load_turns(conf, session_id, limit):
        question = (turn.get("query_rewritten") or turn.get("query_raw") or "").strip()
        if question:
            messages.append({"role": "user", "content": question})
        answer = (turn.get("answer") or "").strip()
        if answer:
            messages.append({"role": "assistant", "content": answer})
    return messages
