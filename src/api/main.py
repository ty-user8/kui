"""FastAPI 应用装配与启动。

异常处理统一在这里收口（`11-errors.md`）：结构化错误按码表给状态码，
请求体校验失败折成 400 `INVALID_REQUEST`（而不是 FastAPI 默认的 422），
未预期异常只返回追踪 id、堆栈写服务端日志，不裸奔 500 页面。

启动（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    set HF_HOME=.cache/models
    .venv\\Scripts\\python.exe -m src.api.main
"""

from __future__ import annotations

import pathlib
import sys
import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.errors import ApiError  # noqa: E402
from src.api.routes import router  # noqa: E402


def _field_of(error: dict) -> str:
    """把 pydantic 的 loc 元组折成 `filters.publish_date_from` 这种可读字段名。"""
    parts = [str(item) for item in error.get("loc", ()) if item not in ("body", "query", "path")]
    return ".".join(parts) or "request"


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG 检索与评测接口",
        version="0.4",
        description="契约见 specs/07-api/openapi.yaml；无鉴权，单机单用户。",
    )
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        body = ApiError(
            "INVALID_REQUEST",
            "请求参数不合法",
            {
                "field": _field_of(first),
                "reason": str(first.get("msg", "校验失败")),
                "errors": [
                    {"field": _field_of(item), "reason": str(item.get("msg", ""))} for item in errors[:5]
                ],
            },
        ).body()
        return JSONResponse(status_code=400, content=body)

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        trace_id = uuid.uuid4().hex[:12]
        # 堆栈只进服务端日志；响应里只给追踪 id，避免把内部路径暴露给调用方
        print("[INTERNAL_ERROR %s] %s" % (trace_id, traceback.format_exc()), file=sys.stderr, flush=True)
        body = ApiError("INTERNAL_ERROR", "服务内部错误，请用 trace_id 定位", {"trace_id": trace_id}).body()
        return JSONResponse(status_code=500, content=body)

    return app


app = create_app()


def main() -> int:
    import uvicorn

    from src.config import ConfigError, load

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2
    uvicorn.run(app, host=conf.server.api_host, port=conf.server.api_port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
