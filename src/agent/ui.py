"""8502 页面：多轮问答（`CHG-013` S4／展示层整理）。

用户端只出现四类东西：问题、答案、可读的法规依据、以及「正在检索／正在作答」的进度提示。
会话 id、配额数字、超时与轮数、flags、工具链、改写过程、错误码都留在数据层与日志里，不上页面。

- 问答只在本进程内走 `orchestrator.run`，**不新增 HTTP 接口**（D4）；
- 会话与轮次存 SQLite 的 `agent_sessions`／`agent_turns`（`memory` 首次连库时自动应用 0004）；
- 生成层的 `[chunk_id]` 标注保留（`citation.validate` 靠它判定越界），只在渲染时替换成
  《法规名》第X条；未知 id 与半截标记一律隐藏。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import streamlit as st

from src.agent import memory, orchestrator, quota, tools
from src.config import ConfigError, load
from src.generate.ask import resolve_base_url, resolve_model

LOGGER = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[([^\[\]]{1,80})\]")
PARTIAL_CITATION_RE = re.compile(r"\[[^\[\]]*$")
ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+条")
SENTENCE_END_RE = re.compile(r"[。；;！？\n]")

ERROR_TEXT = {
    "AGENT_QUOTA_EXCEEDED": "本轮提问次数已用完，请新开一个会话继续问。",
    "INVALID_REQUEST": "这个问题没法处理，换个问法再试试。",
}
DEFAULT_ERROR_TEXT = "暂时无法生成答案，请稍后再试。"
NO_ANSWER_TEXT = "这轮没有生成答案，换个问法再试试。"
WAITING_TEXT = "正在检索条文…"
WRITING_TEXT = "已取到 %d 段条文，正在作答…"


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


def _readable_ref(chunk_id: str, refs: dict | None, *, with_article: bool = True) -> str:
    """`chunk_id` → `（《专利法》第四十二条）`；查不到就给空串，绝不回显 id。"""
    meta = (refs or {}).get(chunk_id) or {}
    title = (meta.get("title") or "").strip()
    article = (meta.get("article_no") or "").strip() if with_article else ""
    if title and article:
        # 片段锚点是「从哪条开始」，一块常横跨数条 → 用「起」标明，不冒充精确条号
        return "（《%s》%s起）" % (title, article)
    if title:
        return "（《%s》）" % title
    if article:
        return "（%s起）" % article
    return ""


def _render_answer(text: str, refs: dict | None = None) -> str:
    """展示用答案：`[chunk_id]` 换成可读依据；末尾未完的 `[` 先切掉，避免闪出半截 id。

    条号的处理：片段锚点是「这一块从哪条开始」，可能与正文点名的条号不同（一块常横跨数条）。
    正文同句已写出「第X条」时只标法规名，避免出现「引第四十二条、括号写第三十八条」这种矛盾；
    正文没写条号时才补片段起始条，并写成「第三十八条起」以表明这是片段起点（一块常横跨数条）。
    相邻完全相同的括号合并为一个。
    """
    if not text:
        return ""
    cleaned = PARTIAL_CITATION_RE.sub("", text)
    parts: list[str] = []
    cursor = 0
    previous = ""
    for match in CITATION_RE.finditer(cleaned):
        segment = cleaned[cursor:match.start()]
        parts.append(segment)
        sentence = SENTENCE_END_RE.split(segment)[-1] if segment else ""
        ref = _readable_ref(
            match.group(1), refs, with_article=not ARTICLE_RE.search(sentence)
        )
        if ref and ref == previous:
            ref = ""
        parts.append(ref)
        previous = ref or previous
        cursor = match.end()
    parts.append(cleaned[cursor:])
    return "".join(parts)


def _human_error(exc) -> str:
    return ERROR_TEXT.get(getattr(exc, "code", ""), DEFAULT_ERROR_TEXT)


def _citations_of(turn: dict) -> list[str]:
    try:
        ids = json.loads(turn.get("citations_json") or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in ids if isinstance(item, str)]


def _load_refs(conf, chunk_ids) -> dict:
    """历史回放用：按 id 批量取标题与条号；库或索引读不到就退回空映射（标记自然隐藏）。"""
    unique = {chunk_id for chunk_id in chunk_ids if chunk_id}
    if not unique:
        return {}
    try:
        return tools.describe_chunks(conf, sorted(unique))
    except Exception as exc:  # 展示层不因查不到元数据而崩
        LOGGER.warning("取引用元数据失败：%s", exc)
        return {}


def _render_history(conf, session_id: str) -> None:
    turns = memory.load_turns(conf, session_id, limit=20)
    refs = _load_refs(conf, [chunk_id for turn in turns for chunk_id in _citations_of(turn)])
    for turn in turns:
        question = turn.get("query_rewritten") or turn.get("query_raw") or ""
        st.chat_message("user").write(question)
        with st.chat_message("assistant"):
            if turn.get("answer"):
                st.markdown(_render_answer(turn["answer"], refs))
            else:
                st.caption(NO_ANSWER_TEXT)


def render() -> None:
    """页面主体；`app_agent.py` 只负责 set_page_config 后调用它。"""
    try:
        conf = load()
    except ConfigError as exc:
        LOGGER.error("配置加载失败：%s", exc)
        st.error("配置有误，暂时无法打开问答页面。")
        return

    session = _session_state(conf)
    settings = quota.AgentSettings.from_conf(conf)

    st.title("法规问答 Agent")
    st.caption("只依据语料库条文作答；答案后附法规名与条号，条文不足时会直接说明。")

    if session.get("expired"):
        st.info("上一个会话已过期，已开启新会话。")

    _render_history(conf, session["session_id"])

    prompt = st.chat_input("用一句话问，例如：发明专利权的期限是几年")
    if not prompt:
        return

    st.chat_message("user").write(prompt)
    with st.chat_message("assistant"):
        try:
            client = _make_client(conf)
        except RuntimeError as exc:
            LOGGER.warning("%s", exc)
            st.warning("尚未配置模型访问凭证，暂时无法生成答案。")
            return

        turns = memory.load_turns(conf, session["session_id"], limit=settings.max_context_turns)
        rewrite = memory.rewrite_query(prompt, turns)
        history = memory.history_for_prompt(conf, session["session_id"], limit=settings.max_context_turns)

        placeholder = st.empty()
        placeholder.caption(WAITING_TEXT)
        streamed = {"text": "", "refs": {}}

        def on_refs(refs: dict) -> None:
            streamed["refs"] = dict(refs)
            if refs:
                placeholder.caption(WRITING_TEXT % len(refs))

        last_paint = {"at": 0.0}

        def on_token(delta: str) -> None:
            streamed["text"] += delta
            now = time.monotonic()
            if now - last_paint["at"] < 0.06:  # 合并高频分块，避免每 token 都推一次前端
                return
            last_paint["at"] = now
            placeholder.markdown(_render_answer(streamed["text"], streamed["refs"]))

        try:
            result = orchestrator.run(
                conf,
                rewrite.query,
                client=client,
                settings=settings,
                quota=st.session_state["agent_quota"],
                history=history,
                on_token=on_token,
                on_refs=on_refs,
            )
        except orchestrator.AgentError as exc:
            LOGGER.warning("问答失败：%s %s", getattr(exc, "code", ""), exc)
            placeholder.empty()
            st.warning(_human_error(exc))
            return

        answer = result["answer"] or streamed["text"]
        if answer:
            placeholder.markdown(_render_answer(answer, result.get("citation_refs") or streamed["refs"]))
        else:
            placeholder.empty()
            st.caption(NO_ANSWER_TEXT)

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
