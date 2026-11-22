"""Agent 工具层（v2）：工具白名单、模型可见 schema、确定性执行。

入口见 `schema.TOOL_SCHEMAS`（模型看到的工具定义）与 `tools.dispatch`（代码侧执行）。
本包不参与评测与 CI（`CHG-013` §8.4）：`src/eval`、`src/cli/eval`、`scripts/ci_check` 均不 import 它。
"""

from __future__ import annotations

from src.agent.schema import MAX_TOOL_CHARS, TOOL_NAMES, TOOL_SCHEMAS, ToolArgError, validate_args
from src.agent.tools import ToolError, dispatch

__all__ = [
    "MAX_TOOL_CHARS",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "ToolArgError",
    "ToolError",
    "dispatch",
    "validate_args",
]
