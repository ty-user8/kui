"""Agent 编排（`CHG-013` §6）：确定性两轮状态机，不做 ReAct 自主规划。

流程（写死，不看模型心情）：

```
query → [规则式改写，S3] → 第 1 轮 LLM(tools, tool_choice=auto)
      → 有 tool_calls：代码执行（白名单 + pydantic 校验 + 上限截断）→ 回填
      → 第 2 轮 LLM(tool_choice=none) → 最终答案 → 引用校验
```

硬约束：

- **两轮封顶**：第 2 轮强制 `tool_choice="none"`；模型若仍吐工具调用，按 `TURN_LIMIT_HIT` 记，
  不做第三轮、也不解析其 content 里的"工具名"。
- **工具数封顶**：每轮最多 `max_tool_calls_per_turn` 个，多出的丢弃并标 `TOOL_CALLS_TRUNCATED`。
- **参数非法不回灌重试**：pydantic 校验失败直接把结构化错误当成工具结果回填，标 `TOOL_ARGS_INVALID`。
- **不产出评测/追踪产物**：所有检索经 `tools.search_laws`（内部 `write_trace=False`），
  本模块不写 `traces`／`runs`／`metrics.json`（`CHG-013` §8.1 D1）。

S2 只做编排与配额；记忆改写、`config.agent.*` 接线、8502 页面分别在 S3／S4。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

from src.agent import schema, tools
from src.agent.quota import AgentSettings, Quota, QuotaExceeded
from src.generate import citation
from src.generate.ask import resolve_model

PROMPT_VERSION = "ask.agent.v1"

AGENT_SYSTEM_PROMPT = """你是法律法规检索助手。只能依据工具返回的条文作答，禁止凭记忆补条款。

工具使用规则：
1. 需要条文时调用 search_laws，**同一 query 只查一次**；若命中片段只是章标题或不含答案，
   用 get_anchor_text 取命中 chunk 的原文再判断，不要重复检索同一 query。
   问"哪些法规/某机关/某时间段"这类枚举用 filter_metadata；问规模用 get_stats。
2. **必须通过接口提供的 function calling 发起调用**（即返回 tool_calls）；严禁把工具调用写成正文，
   正文里出现 <｜｜DSML｜｜>、<invoke>、<parameter> 之类标记一律视为错误。
3. 最多两轮：第一轮取证，第二轮给结论；第二轮不要再请求工具。
4. 答案用中文，结论在前；每个事实后面用 [chunk_id] 标注依据，chunk_id 必须来自工具结果。
5. 工具没给到依据时，直接说"现有条文不足以回答"，不要编造。"""

FLAG_NO_TOOL = "NO_TOOL"
FLAG_TOOL_CALLS_TRUNCATED = "TOOL_CALLS_TRUNCATED"
FLAG_TURN_LIMIT_HIT = "TURN_LIMIT_HIT"
FLAG_AGENT_TIMEOUT = "AGENT_TIMEOUT"
FLAG_TOOL_ARGS_INVALID = "TOOL_ARGS_INVALID"
FLAG_CITATION_INVALID = "CITATION_INVALID"
FINAL_ROUND_NUDGE = (
    "现在只输出最终中文答案：结论在前，用 [chunk_id] 标注依据。"
    "禁止输出任何工具调用或标记（<｜｜DSML｜｜>、<invoke>、<parameter> 等一律不要出现）。"
)

FLAG_TOOL_CALL_IN_CONTENT = "TOOL_CALL_IN_CONTENT"

# 模型把工具调用写进正文时常见的标记（2026-11-22 真实调用遇到 DeepSeek 的 DSML 形态）
_TOOL_MARKUP_MARKERS = ("<｜｜DSML｜｜", "<|DSML|>", "<invoke", "<parameter")


class AgentError(RuntimeError):
    """编排层的结构性错误（入参非法、配额拒绝）；`code` 与 `11-errors.md` 同族命名。"""

    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def tool_payload() -> list[dict]:
    """转成 chat.completions 认的形态：`{"type": "function", "function": {...}}`。

    `TOOL_SCHEMAS` 是扁平结构（name/description/parameters），直接塞给接口会被拒：
    `422 ... tools[0]: missing field type`（2026-11-22 真实调用实测）。
    """
    return [{"type": "function", "function": item} for item in schema.TOOL_SCHEMAS]


def _call_model(
    client, model: str, messages: list[dict], tool_choice: str | None, timeout: float
) -> object:
    """一次模型调用；`tool_choice=None` 表示**不挂工具**（末轮只出答案）。

    实测（2026-11-22，deepseek-flash）：末轮只把 `tool_choice` 设成 `none`、工具清单还在时，
    模型仍会把工具调用写进正文（DSML 形态）；连 `tools` 一起摘掉才回到正常作答。
    """
    kwargs = {"model": model, "messages": messages, "timeout": timeout}
    if tool_choice is not None:
        kwargs["tools"] = tool_payload()
        kwargs["tool_choice"] = tool_choice
    return client.chat.completions.create(**kwargs)


def _looks_like_tool_markup(content: str) -> bool:
    return any(marker in (content or "") for marker in _TOOL_MARKUP_MARKERS)


def _message_of(response) -> tuple[str, list]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "", []
    message = getattr(choices[0], "message", None)
    if message is None:
        return "", []
    content = getattr(message, "content", "") or ""
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    return str(content).strip(), tool_calls


def _assistant_message(content: str, tool_calls: list) -> dict:
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": getattr(call, "id", "call_%d" % index),
                "type": "function",
                "function": {
                    "name": getattr(getattr(call, "function", None), "name", ""),
                    "arguments": getattr(getattr(call, "function", None), "arguments", "{}"),
                },
            }
            for index, call in enumerate(tool_calls)
        ],
    }


def _digest(result: dict) -> dict:
    """工具结果只留摘要进 trace/会话表，不复制正文（`CHG-013` §8.2）。"""
    if "hits" in result:
        first = result["hits"][0]["chunk_id"] if result["hits"] else None
        return {"count": result.get("count", len(result["hits"])), "first_chunk_id": first}
    if "documents" in result:
        return {"count": result.get("count", len(result["documents"])), "truncated": result.get("truncated")}
    if "chunk_id" in result:
        return {"chunk_id": result["chunk_id"], "chars": len(result.get("text") or ""), "truncated": result.get("truncated")}
    return {"keys": sorted(result)}


def run(
    conf,
    query: str,
    *,
    client,
    settings: AgentSettings | None = None,
    quota: Quota | None = None,
    history: list[dict] | None = None,
    dispatch_fn=None,
    root: str = ".",
) -> dict:
    """跑一次问答。`client` 必须注入（真客户端或假客户端），本函数不自己建连接。"""
    text = (query or "").strip()
    if not text:
        raise AgentError("INVALID_REQUEST", "query 不能为空")

    settings = settings or AgentSettings.from_conf(conf)
    quota = quota or Quota(settings)
    dispatch = dispatch_fn or tools.dispatch

    try:
        quota.start_question()
    except QuotaExceeded as exc:
        raise AgentError(exc.code, exc.message, exc.detail) from exc

    model = resolve_model(conf)
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    for item in (history or [])[-settings.max_context_turns :]:
        messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
    messages.append({"role": "user", "content": text})

    flags: list[str] = []
    tool_trace: list[dict] = []
    allowed_ids: set[str] = set()
    answer = ""
    started = time.perf_counter()

    for turn in range(1, settings.max_turns + 1):
        try:
            quota.take_call()
        except QuotaExceeded as exc:
            raise AgentError(exc.code, exc.message, exc.detail) from exc

        tool_choice = "auto" if turn == 1 else None  # 末轮摘掉工具，见 `_call_model` 注释
        if tool_choice is None:
            messages.append({"role": "system", "content": FINAL_ROUND_NUDGE})
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_call_model, client, model, list(messages), tool_choice, settings.timeout_seconds)
            response = future.result(timeout=settings.timeout_seconds)
        except TimeoutError:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return _result("", [], True, [], [FLAG_AGENT_TIMEOUT], model, tool_trace, elapsed, quota)
        finally:
            executor.shutdown(wait=False)

        content, tool_calls = _message_of(response)

        if not tool_calls:
            if _looks_like_tool_markup(content):
                # 模型把工具调用写进了正文：既有害又不可用，标错并丢弃正文，避免把标记当答案入库
                flags.append(FLAG_TOOL_CALL_IN_CONTENT)
                answer = ""
                break
            if turn == 1:
                flags.append(FLAG_NO_TOOL)
            answer = content
            break

        if turn == settings.max_turns:
            flags.append(FLAG_TURN_LIMIT_HIT)
            answer = content
            break

        kept = tool_calls[: settings.max_tool_calls_per_turn]
        if len(tool_calls) > len(kept):
            flags.append(FLAG_TOOL_CALLS_TRUNCATED)
        messages.append(_assistant_message(content, kept))

        for call in kept:
            name = getattr(getattr(call, "function", None), "name", "")
            raw_args = getattr(getattr(call, "function", None), "arguments", "{}") or "{}"
            call_id = getattr(call, "id", "call_0")
            try:
                quota.take_tool()
            except QuotaExceeded:
                flags.append(FLAG_TOOL_CALLS_TRUNCATED)
                break

            entry = {"name": name, "args": raw_args, "ok": False}
            begin = time.perf_counter()
            try:
                payload = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                result = dispatch(conf, name, payload)
                entry["ok"] = True
                entry["digest"] = _digest(result)
                allowed_ids.update(_collect_ids(result))
                tool_content = json.dumps(result, ensure_ascii=False)
            except tools.ToolError as exc:
                entry["code"] = exc.code
                if exc.code == schema.ToolArgError.code:
                    flags.append(FLAG_TOOL_ARGS_INVALID)
                tool_content = json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                entry["code"] = schema.ToolArgError.code
                flags.append(FLAG_TOOL_ARGS_INVALID)
                tool_content = json.dumps(
                    {"error": schema.ToolArgError.code, "message": "arguments 不是合法 JSON：%s" % exc},
                    ensure_ascii=False,
                )
            entry["elapsed_ms"] = round((time.perf_counter() - begin) * 1000, 1)
            tool_trace.append(entry)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_content})

    check = citation.validate(answer, allowed_ids)
    if not check["valid"]:
        flags.append(FLAG_CITATION_INVALID)
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return _result(
        answer,
        check["citations"],
        check["valid"],
        check["invalid"],
        flags,
        model,
        tool_trace,
        elapsed,
        quota,
    )


def _collect_ids(result: dict) -> set[str]:
    """把工具结果里出现过的 chunk_id 收进白名单，供引用校验。"""
    ids: set[str] = set()
    for hit in result.get("hits") or []:
        if hit.get("chunk_id"):
            ids.add(hit["chunk_id"])
    if result.get("chunk_id"):
        ids.add(result["chunk_id"])
    return ids


def _result(
    answer: str,
    citations: list[str],
    valid: bool,
    invalid: list[str],
    flags: list[str],
    model: str,
    tool_trace: list[dict],
    elapsed_ms: float,
    quota: Quota,
) -> dict:
    return {
        "answer": answer,
        "citations": citations,
        "citation_valid": valid,
        "invalid_citations": invalid,
        "flags": flags,
        "model": model,
        "tool_trace": tool_trace,
        "prompt_version": PROMPT_VERSION,
        "stateless_mode": True,
        "elapsed_ms": elapsed_ms,
        "quota": quota.snapshot(),
    }
