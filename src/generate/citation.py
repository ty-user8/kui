"""引用校验：从答案里抽出 `[chunk_id]`，判断是否都落在本次 top-k 内。

纯规则式字符串匹配，**不调用模型**（REQ-050、`08-prompts/README.md` 硬约束 2）。
校验只做「有没有越界」这一件事：不判断引用是否贴切、不重排、不改写答案——
越界时保留答案并标 `CITATION_INVALID`，由调用方决定怎么展示。
"""

from __future__ import annotations

import re

# 只认方括号，全角【】一并兼容（模型常把半角写成全角，属格式偏差而非编造）
CITATION_RE = re.compile(r"[\[【]\s*([A-Za-z0-9][A-Za-z0-9_:.\-]*?)\s*[\]】]")


def extract_citations(answer: str) -> list[str]:
    """按出现顺序抽引用 id，重复的只保留第一次。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in CITATION_RE.finditer(answer or ""):
        chunk_id = match.group(1).strip()
        if chunk_id and chunk_id not in seen:
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return ordered


def validate(answer: str, allowed: set[str] | list[str]) -> dict:
    """返回 {citations, invalid, valid}。`valid` 为 True 表示没有越界引用（空引用也算通过）。"""
    allowed_set = set(allowed)
    citations = extract_citations(answer)
    invalid = [chunk_id for chunk_id in citations if chunk_id not in allowed_set]
    return {"citations": citations, "invalid": invalid, "valid": not invalid}
