"""`/ask` 生成层：检索结果拼 Prompt → 调 LLM → 引用校验。

四条硬约束（`08-prompts/README.md`、REQ-049~052）：

1. 单次调用超时 **30 秒**（取 `llm.timeout_seconds`），超时返回检索结果、答案留空、标 `ASK_TIMEOUT`；
2. 答案里的引用必须落在本次 top-k 内，否则标 `CITATION_INVALID`，**答案不丢弃**；
3. `/ask` 不进任何指标、不进 CI 回归（CI workflow 里没有这一步，`metrics.json` 也不含它）；
4. `RAG_LLM_API_KEY` 缺失直接抛 `CONFIG_MISSING_KEY`，不静默降级、不伪造答案。

超时用线程 + `future.result(timeout)` 实现：Python 无法强杀线程，超时后请求线程可能仍在跑完，
所以并发上限靠 `llm.max_calls` 配额守住，不靠线程回收。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor

from src.generate import citation

PROMPT_VERSION = "ask.system.v1"
SYSTEM_PROMPT = "specs/08-prompts/ask.system.v1.md"
USER_TEMPLATE = "specs/08-prompts/ask.user.template.v1.md"
CONTEXT_CHARS_PER_CHUNK = 400
REASON_TIMEOUT = "ASK_TIMEOUT"
REASON_CITATION_INVALID = "CITATION_INVALID"
PLACEHOLDERS = ("{query}", "{context}")

_CALLS = {"n": 0}


class AskError(RuntimeError):
    """生成层的结构化错误；`code` 与 `11-errors.md` 的码表一致。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass
class AskResult:
    answer: str
    citations: list[str]
    citation_valid: bool
    invalid_citations: list[str]
    reason: str | None
    model: str
    prompt_version: str
    elapsed_ms: float


def reset_quota() -> None:
    _CALLS["n"] = 0


def quota_used() -> int:
    return _CALLS["n"]


def load_prompts(root: pathlib.Path | str) -> tuple[str, str]:
    """读系统提示与用户模板，并校验占位符——模板写错要在启动时报，而不是让模型猜。"""
    base = pathlib.Path(root)
    system = (base / SYSTEM_PROMPT).read_text(encoding="utf-8")
    template = (base / USER_TEMPLATE).read_text(encoding="utf-8")
    missing = [token for token in PLACEHOLDERS if token not in template]
    if missing:
        raise AskError("INTERNAL_ERROR", "用户模板缺少占位符：%s" % ", ".join(missing))
    return system, template


def build_context(hits: list[dict], texts: dict[str, str], limit_chars: int = CONTEXT_CHARS_PER_CHUNK) -> str:
    """把命中片段拼成 `<context>` 内容：每条一行标签 + 截断正文，标签里的 id 与引用校验一致。"""
    lines = []
    for hit in hits:
        chunk_id = hit["chunk_id"]
        # 没有条号时写「片段」，不拿序号冒充条款号——系统提示明确禁止补条款号
        label = "[%s] %s" % (chunk_id, hit.get("article_no") or "片段")
        heading = (hit.get("heading_path") or "").strip()
        if heading:
            label += "（%s）" % heading
        body = (texts.get(chunk_id) or "").replace("\n", " ")[:limit_chars]
        lines.append("%s %s" % (label, body))
    return "\n".join(lines)


def _resolve_client(conf, client):
    """没有注入 client 时按环境变量建真实客户端；缺 key / 缺模型名都在这里拦。"""
    if client is not None:
        return client
    api_key = os.environ.get(conf.llm.api_key_env, "").strip()
    if not api_key:
        raise AskError("CONFIG_MISSING_KEY", "环境变量 %s 未设置，/ask 需要它才能调用模型" % conf.llm.api_key_env)
    model = os.environ.get(conf.llm.model_env, "").strip()
    if not model:
        raise AskError("CONFIG_MISSING_KEY", "环境变量 %s 未设置，无法确定模型名" % conf.llm.model_env)
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 依赖缺失属环境问题
        raise AskError("INTERNAL_ERROR", "openai 客户端未安装，无法调用 /ask") from exc
    base_url = os.environ.get(conf.llm.base_url_env, "").strip() or None
    return OpenAI(api_key=api_key, base_url=base_url, timeout=conf.llm.timeout_seconds)


def _call_model(client, messages: list[dict], model: str, timeout_s: float) -> str:
    response = client.chat.completions.create(model=model, messages=messages, timeout=timeout_s)
    return (response.choices[0].message.content or "").strip()


def ask(
    conf,
    query: str,
    hits: list[dict],
    texts: dict[str, str],
    client=None,
    timeout_s: float | None = None,
    root: pathlib.Path | str = ".",
) -> AskResult:
    """生成答案并校验引用；`hits` 是本次检索结果（含 `chunk_id`、`article_no`、`heading_path`）。"""
    text = (query or "").strip()
    if not text:
        raise AskError("INVALID_REQUEST", "query 不能为空")
    if not hits:
        # 没有可依据的条文就不调模型：调用只会让它编
        return AskResult("", [], True, [], "NO_MATCH", "", PROMPT_VERSION, 0.0)

    client = _resolve_client(conf, client)
    model = os.environ.get(conf.llm.model_env, "").strip() or getattr(client, "model", "")
    timeout = float(timeout_s if timeout_s is not None else conf.llm.timeout_seconds)

    if _CALLS["n"] >= conf.llm.max_calls:
        raise AskError(
            "INTERNAL_ERROR",
            "本次进程内 /ask 调用已达配额 llm.max_calls=%d，拒绝继续调用" % conf.llm.max_calls,
        )

    system, template = load_prompts(root)
    context = build_context(hits, texts)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": template.replace("{query}", text).replace("{context}", context)},
    ]

    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        _CALLS["n"] += 1
        future = executor.submit(_call_model, client, messages, model, timeout)
        answer = future.result(timeout=timeout)
    except TimeoutError:
        return AskResult("", [], True, [], REASON_TIMEOUT, model, PROMPT_VERSION, round(timeout * 1000, 1))
    except Exception as exc:  # 模型侧报错不外抛成 500 裸栈，折成结构化错误
        raise AskError("INTERNAL_ERROR", "模型调用失败：%s" % type(exc).__name__) from exc
    finally:
        executor.shutdown(wait=False)

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    check = citation.validate(answer, {hit["chunk_id"] for hit in hits})
    reason = None if check["valid"] else REASON_CITATION_INVALID
    return AskResult(
        answer=answer,
        citations=check["citations"],
        citation_valid=check["valid"],
        invalid_citations=check["invalid"],
        reason=reason,
        model=model,
        prompt_version=PROMPT_VERSION,
        elapsed_ms=elapsed,
    )


def main() -> int:
    """自检：不调真实模型，只验证 Prompt 读取、上下文拼装与引用校验三条纯逻辑。"""
    import sys

    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    system, template = load_prompts(root)
    print("系统提示 %d 字、模板 %d 字，占位符齐全" % (len(system), len(template)))
    hits = [
        {"chunk_id": "doc:00012", "article_no": "第四十二条", "heading_path": "第五章"},
        {"chunk_id": "doc:00013", "article_no": None, "heading_path": ""},
    ]
    context = build_context(hits, {"doc:00012": "发明专利权的期限为二十年。", "doc:00013": "实用新型为十年。"})
    print(context)
    good = "发明专利权的期限是二十年 [doc:00012]。"
    bad = "期限二十年 [doc:00012]，另见 [doc:99999]。"
    print("合法引用:", citation.validate(good, {"doc:00012", "doc:00013"}))
    print("越界引用:", citation.validate(bad, {"doc:00012", "doc:00013"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
