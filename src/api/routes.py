"""四个 HTTP 接口的路由定义（`specs/07-api/README.md`）。

这一层只做三件事：解析与校验请求、调 `service`、把结果原样返回。
业务判断（检索编排、过滤降级、入库决策）全部在 `service` 与各领域模块里，改逻辑不用动这里。
接口无鉴权参数、无用户维度（REQ-056）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from src.api import service
from src.api.errors import ApiError
from src.config import ConfigError, load

router = APIRouter()


def current_config():
    """每次请求读一次配置：环境变量（如 `RAG_DB_PATH`）变化后无需重启即可生效。"""
    try:
        return load()
    except ConfigError as exc:
        raise ApiError("CONFIG_MISSING_KEY", str(exc)) from exc


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_ids: list[str] | None = None
    category: str | None = None
    authority: str | None = None
    publish_date_from: str | None = None
    publish_date_to: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=service.MAX_TOP_K)
    filters: SearchFilters | None = None


class EvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: Literal["all", "dev", "holdout"] = "all"


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["v01_subset", "full"]
    doc_ids: list[str] | None = None


@router.post("/search")
def post_search(payload: SearchRequest) -> dict:
    conf = current_config()
    filters = payload.filters.model_dump(exclude_none=True) if payload.filters else None
    return service.search(conf, payload.query, payload.top_k, filters)


@router.post("/eval")
def post_eval(payload: EvalRequest | None = None) -> dict:
    conf = current_config()
    split = payload.split if payload else "all"
    return service.eval_metrics(conf, split)


@router.post("/ingest")
def post_ingest(payload: IngestRequest) -> dict:
    conf = current_config()
    return service.ingest(conf, payload.source, payload.doc_ids)


@router.get("/trace")
def get_trace(
    run_id: str = Query(min_length=1),
    case_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=service.TRACE_LIMIT_MAX),
) -> dict:
    conf = current_config()
    return {"items": service.trace_items(conf, run_id, case_id, limit)}
