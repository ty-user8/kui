"""8502 页面：多轮问答（`CHG-013` S4）。

- 问答只在本进程内走 `orchestrator.run`，**不新增 HTTP 接口**（D4）；
- 会话与轮次存 SQLite 的 `agent_sessions`／`agent_turns`（`memory` 首次连库时自动应用 0004）；
- 每轮先把当前问法交给 `memory.rewrite_query` 做规则式补全（0 次 API），再决定检索；
- 模型客户端在 `_make_client` 里现建，缺 `RAG_LLM_API_KEY` 就明确提示，不静默降级。
"""

from __future__ import annotations

import os

import streamlit as st

from src.agent import memory, orchestrator, quota
from src.config import ConfigError, load
from src.generate.ask import resolve_base_url, resolve_model

FLAG_LABELS = {
    "NO_TOOL": "未调用工具，直接作答",
    "TOOL_CALLS_TRUNCATED": "工具调用超出上限，已截断",
    "TURN_LIMIT_HIT": "已达两轮上限，用现有结果作答",
    "AGENT_TIMEOUT": "模型超时，答案留空",
    "TOOL_ARGS_INVALID": "工具参数非法，已跳过该调用",
    "CITATION_INVALID": "引用越界（答案保留）",
}

REWRITE_LABELS = {
    memory.RULE_PRONOUN: "指代补全",
    memory.RULE_ELLIPSIS: "省略补全",
    memory.RULE_DATE: "相对年份替换",
}


def _make_client(conf):
    """按 `config.yaml` 的 `llm` 段建客户端；key 仍只从环境变量读。"""
    key = os.environ.get(conf.llm.api_key_env, "").strip()
    if not key:
        raise RuntimeError("环境变量 %s 未设置，无法调用模型" % conf.llm.api_key_env)
    from openai import OpenAI

    return OpenAI(
        api_key=key,
        base_url=resolve_base_url(conf) or None,
        timeout=float(conf.agent.timeout_seconds),
    )


def _session_state(conf) -> dict:
    """页面级的会话/配额放在 `st.session_state`，刷新页面不丢（同一浏览器会话内）。"""
    if "agent_session" not in st.session_state:
        st.session_state["agent_session"] = memory.open_session(conf)
        st.session_state["agent_quota"] = quota.Quota(quota.AgentSettings.from_conf(conf))
    return st.session_state["agent_session"]


def _flags_note(flags: list[str]) -> str | None:
    if not flags:
        return None
    return "；".join(FLAG_LABELS.get(flag, flag) for flag in flags)


def _tool_summary(tool_calls_json: str) -> str:
    """把入库的 tool_calls 摘要折成一行，便于页面上核对"这轮查了什么"。"""
    import json

    try:
        calls = json.loads(tool_calls_json or "[]")
    except json.JSONDecodeError:
        return ""
    parts = []
    for call in calls:
        name = call.get("name", "?")
        if call.get("ok"):
            digest = call.get("digest") or {}
            detail = digest.get("count", digest.get("chunk_id", ""))
            parts.append("%s(%s)" % (name, detail))
        else:
            parts.append("%s ✗ %s" % (name, call.get("code", "ERROR")))
    return " · ".join(parts)


def _render_history(conf, session_id: str) -> None:
    for turn in memory.load_turns(conf, session_id, limit=20):
        question = turn.get("query_rewritten") or turn.get("query_raw") or ""
        st.chat_message("user").write(question)
        with st.chat_message("assistant"):
            if turn.get("answer"):
                st.markdown(turn["answer"])
            else:
                st.caption("（本轮没有答案）")
            note = _flags_note([flag for flag in (turn.get("flags") or "").split(",") if flag])
            if note:
                st.caption(note)
            summary = _tool_summary(turn.get("tool_calls_json") or "[]")
            if summary:
                st.caption("工具：" + summary)


def render() -> None:
    """页面主体；`app_agent.py` 只负责 set_page_config 后调用它。"""
    try:
        conf = load()
    except ConfigError as exc:
        st.error("配置错误：%s" % exc)
        return

    session = _session_state(conf)
    settings = quota.AgentSettings.from_conf(conf)
    used = st.session_state["agent_quota"].snapshot()

    st.title("法规问答 Agent")
    st.caption(
        "会话 %s · 已用 %d/%d 次调用 · 单次超时 %d s · 最多 %d 轮"
        % (
            session["session_id"][:8],
            used["session_calls"],
            settings.max_calls_per_session,
            settings.timeout_seconds,
            settings.max_turns,
        )
    )

    if session.get("expired"):
        st.info("上一个会话已超过 %g 小时未活动，已开启新会话。" % settings.session_ttl_hours)

    _render_history(conf, session["session_id"])

    prompt = st.chat_input("用一句话问，例如：发明专利权的期限是几年")
    if not prompt:
        return

    st.chat_message("user").write(prompt)
    with st.chat_message("assistant"):
        try:
            client = _make_client(conf)
        except RuntimeError as exc:
            st.error(str(exc))
            return

        turns = memory.load_turns(conf, session["session_id"], limit=settings.max_context_turns)
        rewrite = memory.rewrite_query(prompt, turns)
        if rewrite.rule in REWRITE_LABELS:
            st.caption("%s：%s" % (REWRITE_LABELS[rewrite.rule], rewrite.query))

        history = memory.history_for_prompt(conf, session["session_id"], limit=settings.max_context_turns)
        with st.spinner("检索并生成…"):
            try:
                result = orchestrator.run(
                    conf,
                    rewrite.query,
                    client=client,
                    settings=settings,
                    quota=st.session_state["agent_quota"],
                    history=history,
                )
            except orchestrator.AgentError as exc:
                st.error("%s：%s" % (exc.code, exc.message))
                return

        if result["answer"]:
            st.markdown(result["answer"])
        else:
            st.caption("（模型没有给出答案）")
        note = _flags_note(result["flags"])
        if note:
            st.caption(note)
        if result["tool_trace"]:
            st.caption(
                "工具："
                + " · ".join(
                    "%s%s" % (item["name"], "" if item.get("ok") else " ✗ %s" % item.get("code", ""))
                    for item in result["tool_trace"]
                )
            )

        memory.record_turn(
            conf,
            session["session_id"],
            turn_no=memory.next_turn_no(conf, session["session_id"]),
            query_raw=prompt,
            query_rewritten=rewrite.query,
            rewrite_rule=rewrite.rule,
            tool_calls=result["tool_trace"],
            answer=result["answer"],
            citations=result["citations"],
            citation_valid=result["citation_valid"],
            flags=result["flags"],
            elapsed_ms=result["elapsed_ms"],
        )
        st.rerun()
