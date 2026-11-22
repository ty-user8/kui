"""Agent 工具层（v2，`CHG-013`）：模型可见的 JSON Schema 与参数模型。

三条硬规则（`CHG-013` §5「通用规则」）：

1. **模型可见 schema 不使用 `oneOf` / `anyOf` / `allOf` / `if-then`**——只用 `type` / `enum` /
   `items` / `minItems` / `maxItems` / `minLength` / `maxLength` / `minimum` / `maximum` /
   `required` / `additionalProperties:false`。DeepSeek 的 strict function call 对条件构造支持
   有限，会 400 或误读；pydantic 自动生成的 `Optional` schema 会带 `anyOf`，所以这里的 schema
   是手写的，不用 `model_json_schema()` 直接吐。
2. **字段间组合约束写在工具 description 的自然语言里，并由本模块的 pydantic 校验器兜底**；
   违反组合规则的调用一律 `TOOL_ARGS_INVALID`，不回灌给模型重试。
3. **只暴露必要入口**：`get_anchor_text` 只收 `chunk_id`（D3），`doc_id + article_no` 属内部入参。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOOL_NAMES = ("search_laws", "filter_metadata", "get_anchor_text", "get_stats")

# 单个工具结果回填的字符上限；S3 接 `config.agent.max_tool_chars` 时下调，这里是不许越过的硬顶
MAX_TOOL_CHARS = 2000
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_DATE_RE = re.compile(DATE_PATTERN)


class ToolArgError(ValueError):
    """工具入参不合法；`code` 固定 `TOOL_ARGS_INVALID`，与 `11-errors.md` 的码表同族。"""

    code = "TOOL_ARGS_INVALID"

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class SearchFilters(BaseModel):
    """`search_laws` 的过滤条件，字段名与现有 `service.parse_filters` 的可接受键对应。"""

    model_config = ConfigDict(extra="forbid")

    category: list[str] | None = Field(default=None, max_length=5)
    authority: list[str] | None = Field(default=None, max_length=5)
    publish_from: str | None = Field(default=None, pattern=DATE_PATTERN)
    publish_to: str | None = Field(default=None, pattern=DATE_PATTERN)
    doc_ids: list[str] | None = Field(default=None, max_length=10)


class SearchLawsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: SearchFilters | None = None


class FilterMetadataArgs(BaseModel):
    """按元数据筛选；组合规则与 `description` 里写给模型的话逐条一致。"""

    model_config = ConfigDict(extra="forbid")

    field: Literal["category", "authority", "publish_date", "title", "doc_id"]
    op: Literal["eq", "in", "between", "contains"]
    value: list[str] = Field(min_length=1, max_length=10)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def _check_combination(self) -> "FilterMetadataArgs":
        if self.op == "eq" and len(self.value) != 1:
            raise ValueError("op=eq 需要恰好 1 个 value")
        if self.op == "between":
            if self.field != "publish_date":
                raise ValueError("op=between 只支持 field=publish_date")
            if len(self.value) != 2:
                raise ValueError("op=between 需要 [起始日, 结束日] 两个 value")
            for item in self.value:
                if not _DATE_RE.match(item):
                    raise ValueError("op=between 的 value 必须是 YYYY-MM-DD")
        if self.op == "contains":
            if self.field != "title":
                raise ValueError("op=contains 只支持 field=title")
            if len(self.value) != 1:
                raise ValueError("op=contains 需要恰好 1 个 value")
        return self


class GetAnchorTextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=80)
    max_chars: int = Field(default=800, ge=200, le=MAX_TOOL_CHARS)


class GetStatsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


_ARGS_MODEL = {
    "search_laws": SearchLawsArgs,
    "filter_metadata": FilterMetadataArgs,
    "get_anchor_text": GetAnchorTextArgs,
    "get_stats": GetStatsArgs,
}


def validate_args(name: str, payload: dict | None) -> BaseModel:
    """按工具名把原始入参校成模型；未知工具抛 `TOOL_NOT_FOUND`，参数不合法抛 `ToolArgError`。"""
    if name not in _ARGS_MODEL:
        raise KeyError(name)
    model = _ARGS_MODEL[name]
    try:
        return model.model_validate(payload or {})
    except Exception as exc:  # pydantic.ValidationError，但不在这里 import 它的内部类型
        raise ToolArgError(
            "工具 %s 的入参不合法：%s" % (name, _short_error(exc)),
            {"tool": name, "errors": _error_items(exc)},
        ) from exc


def _error_items(exc: Exception) -> list[dict]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return []
    items = []
    for item in errors():
        items.append({"loc": [str(part) for part in item.get("loc", ())], "msg": str(item.get("msg", ""))})
    return items


def _short_error(exc: Exception) -> str:
    items = _error_items(exc)
    if not items:
        return str(exc)
    first = items[0]
    return "%s %s" % (".".join(first["loc"]) or "<root>", first["msg"])


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "search_laws",
        "description": (
            "按语义检索法规条文，返回 top-k 片段及其锚点、分数与来源（向量 + BM25 融合，复用现有检索链）。"
            "filters 可选，用于把结果限制在指定的分类、发布机关、发布日期区间或文档集合内；"
            "过滤后为空时会自动放宽并返回 flags=FILTER_RELAXED。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "filters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "category": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                        "authority": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                        "publish_from": {"type": "string", "pattern": DATE_PATTERN},
                        "publish_to": {"type": "string", "pattern": DATE_PATTERN},
                        "doc_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    },
                },
            },
        },
    },
    {
        "name": "filter_metadata",
        "description": (
            "按文档元数据筛选（不走检索），用于「哪些是行政法规」「应急管理部有哪些文件」「2025 年之后发布的法」这类枚举型问题。"
            "field/op/value 组合规则：eq=单值精确匹配（value 长度 1）；in=集合匹配（value 可多个）；"
            "between 仅用于 publish_date，value 必须是 [起始日, 结束日] 两个 YYYY-MM-DD；"
            "contains 仅用于 title，value 长度 1 的子串匹配。"
            "组合规则由代码侧校验，违反时返回 TOOL_ARGS_INVALID。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "op", "value"],
            "properties": {
                "field": {"enum": ["category", "authority", "publish_date", "title", "doc_id"]},
                "op": {"enum": ["eq", "in", "between", "contains"]},
                "value": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 100},
                    "minItems": 1,
                    "maxItems": 10,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
        },
    },
    {
        "name": "get_anchor_text",
        "description": (
            "按 chunk_id 取条文原文与锚点（条号、标题路径、字符区间、来源链接），供最终答案标注依据。"
            "chunk_id 只能取自 search_laws 的返回结果；正文按 max_chars 截断并标记 truncated。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["chunk_id"],
            "properties": {
                "chunk_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": MAX_TOOL_CHARS, "default": 800},
            },
        },
    },
    {
        "name": "get_stats",
        "description": "返回语料与索引的规模统计（文档数、chunk 数、分类与机关分布、发布年份范围、权重指纹），不消耗模型调用。",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]
