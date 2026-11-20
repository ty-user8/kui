"""错误码到 HTTP 状态码的映射（`specs/07-api/README.md` §3、`specs/11-errors.md` §1）。

接口层只做两件事：把业务层抛出的结构化错误转成响应、把未预期异常收成 `INTERNAL_ERROR`。
错误码字符串与规格表逐字一致，不在这里另造名字。
"""

from __future__ import annotations

CODE_TO_STATUS = {
    "INVALID_REQUEST": 400,
    "ENTRY_UNSAFE_PATH": 400,
    "ENTRY_TOO_LARGE": 413,
    "ENTRY_UNSUPPORTED_FORMAT": 415,
    "PARSE_FAILED": 422,
    "PARSE_FAILURE_RATE_EXCEEDED": 422,
    "INDEX_EMPTY": 409,
    "RUN_NOT_FOUND": 404,
    "CONFIG_MISSING_KEY": 500,
    "INTERNAL_ERROR": 500,
    # 降级类不是错误码，HTTP 仍为 200，只在 reason 里标
    "ASK_TIMEOUT": 200,
    "CITATION_INVALID": 200,
}

# 检索降级标记：放在响应的 reason 字段，不进错误通道
REASON_NO_MATCH = "NO_MATCH"
REASON_FALLBACK_BM25 = "FALLBACK_BM25"
REASON_FILTER_RELAXED = "FILTER_RELAXED"


class ApiError(Exception):
    """带错误码的异常；`detail` 只放字段级信息（哪个字段错、给了什么），不放堆栈。"""

    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    @property
    def status(self) -> int:
        return CODE_TO_STATUS.get(self.code, 500)

    def body(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def error_body(code: str, message: str, detail: dict | None = None) -> dict:
    return ApiError(code, message, detail).body()
