"""Agent 配额与运行参数（`CHG-013` §7）。

三条口径：

1. **独立于 `/ask`**：本模块的计数器只服务 Agent；`llm.max_calls` 仍只管 `/ask`，互不挤占。
2. **可下调、不可上调**：`max_turns` / `max_tool_calls_per_turn` / `max_context_turns` 是成本闸门，
   配置只能 ≤ 默认值，超过直接拒绝启动（S3 接 `config.agent.*` 时在这里拦，不在调用处拦）。
3. **拒绝要结构化**：超限抛 `QuotaExceeded`（`AGENT_QUOTA_EXCEEDED`），由编排层折成响应，
   不静默降级成"少调一次"。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULTS = {
    "max_turns": 2,
    "timeout_seconds": 30.0,
    "max_calls_per_question": 2,
    "max_calls_per_session": 20,
    "max_tool_calls_per_turn": 3,
    "max_context_turns": 3,
    "max_tool_chars": 2000,
    "session_ttl_hours": 24.0,
}

# 这三项只允许下调：它们直接决定一轮问答最多烧多少次调用/多少上下文
HARD_CAPS = {
    "max_turns": 2,
    "max_tool_calls_per_turn": 3,
    "max_context_turns": 3,
}


class QuotaExceeded(RuntimeError):
    """配额拒绝；`code` 与 `11-errors.md` 同族命名。"""

    code = "AGENT_QUOTA_EXCEEDED"

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True)
class AgentSettings:
    """Agent 运行参数；S3 起由 `config.yaml` 的 `agent` 段覆盖，默认值即本文件 `DEFAULTS`。"""

    max_turns: int = DEFAULTS["max_turns"]
    timeout_seconds: float = DEFAULTS["timeout_seconds"]
    max_calls_per_question: int = DEFAULTS["max_calls_per_question"]
    max_calls_per_session: int = DEFAULTS["max_calls_per_session"]
    max_tool_calls_per_turn: int = DEFAULTS["max_tool_calls_per_turn"]
    max_context_turns: int = DEFAULTS["max_context_turns"]
    max_tool_chars: int = DEFAULTS["max_tool_chars"]
    session_ttl_hours: float = DEFAULTS["session_ttl_hours"]

    def __post_init__(self) -> None:
        for name, cap in HARD_CAPS.items():
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError("%s 必须是正整数（当前 %r）" % (name, value))
            if value > cap:
                raise ValueError("%s 只能下调，不能超过默认上限 %d（当前 %d）" % (name, cap, value))
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须为正数")
        for name in ("max_calls_per_question", "max_calls_per_session", "max_tool_chars"):
            if getattr(self, name) < 1:
                raise ValueError("%s 必须为正整数" % name)
        if self.session_ttl_hours <= 0:
            raise ValueError("session_ttl_hours 必须为正数")

    @classmethod
    def from_conf(cls, conf) -> "AgentSettings":
        """读 `config.agent`（S3 起）；缺段时退回默认值，保证单独用工具/编排的测试不依赖配置。

        三项硬上限仍走 `__post_init__` 的同一条校验：配置把 `max_turns` 写到 3 会在构造时抛错。
        """
        section = getattr(conf, "agent", None)
        if section is None:
            return cls()
        values = {}
        for name in DEFAULTS:
            value = getattr(section, name, None)
            if value is not None:
                values[name] = value
        return cls(**values)


class Quota:
    """一次问答 + 一个会话的调用计数；`start_question()` 重置问题级计数，会话级累计不清零。"""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or AgentSettings()
        self.session_calls = 0
        self.question_calls = 0
        self.question_tools = 0

    def start_question(self) -> None:
        if self.session_calls >= self.settings.max_calls_per_session:
            raise QuotaExceeded(
                "本会话模型调用已达上限 max_calls_per_session=%d" % self.settings.max_calls_per_session,
                {"scope": "session", "used": self.session_calls},
            )
        self.question_calls = 0
        self.question_tools = 0

    def take_call(self) -> None:
        if self.question_calls >= self.settings.max_calls_per_question:
            raise QuotaExceeded(
                "本次问答模型调用已达上限 max_calls_per_question=%d" % self.settings.max_calls_per_question,
                {"scope": "question", "used": self.question_calls},
            )
        if self.session_calls >= self.settings.max_calls_per_session:
            raise QuotaExceeded(
                "本会话模型调用已达上限 max_calls_per_session=%d" % self.settings.max_calls_per_session,
                {"scope": "session", "used": self.session_calls},
            )
        self.question_calls += 1
        self.session_calls += 1

    def take_tool(self) -> None:
        if self.question_tools >= self.settings.max_tool_calls_per_turn:
            raise QuotaExceeded(
                "本轮工具调用已达上限 max_tool_calls_per_turn=%d" % self.settings.max_tool_calls_per_turn,
                {"scope": "turn", "used": self.question_tools},
            )
        self.question_tools += 1

    def snapshot(self) -> dict:
        return {
            "session_calls": self.session_calls,
            "question_calls": self.question_calls,
            "question_tools": self.question_tools,
            "limits": {
                "max_calls_per_question": self.settings.max_calls_per_question,
                "max_calls_per_session": self.settings.max_calls_per_session,
                "max_tool_calls_per_turn": self.settings.max_tool_calls_per_turn,
                "max_turns": self.settings.max_turns,
                "timeout_seconds": self.settings.timeout_seconds,
            },
        }
