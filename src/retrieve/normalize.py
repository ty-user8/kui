"""查询侧归一化：全角半角统一、空白折叠、可选繁转简。

只作用于 query，不改基准文本，也不产生任何偏移（`01-requirements.md` 5.3.2）；原 query 由
trace 的 `query_raw` 保留，归一化结果写 `query_norm`（REQ-026）。

繁转简依赖 OpenCC 词典。本项目语料与 query 均为简体、无繁体来源，按 D-023 不引入该依赖：
分支保留但不启用（`t2s=False`），不报错也不静默乱转；将来接入繁体语料时再装上并打开开关即可。
"""

from __future__ import annotations

import re
import unicodedata

SPACE = re.compile(r"\s+")
CJK_GAP = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")


def _load_converter():
    try:
        import opencc  # type: ignore

        return opencc.OpenCC("t2s")
    except Exception:
        return None


_CONVERTER = _load_converter()


def normalize_query(text: str, enable_t2s: bool = True) -> tuple[str, dict]:
    """返回（归一化文本, 过程信息）。过程信息含 `nfkc` / `collapsed` / `t2s` 三个布尔位。"""
    info = {"nfkc": False, "collapsed": False, "t2s": False}
    original = text
    normalized = unicodedata.normalize("NFKC", text)
    info["nfkc"] = normalized != original

    collapsed = SPACE.sub(" ", normalized).strip()
    # 中文词间的空白通常是分词留白，直接删掉；中英文之间的空格保留
    collapsed = CJK_GAP.sub("", collapsed)
    info["collapsed"] = collapsed != normalized
    normalized = collapsed

    if enable_t2s and _CONVERTER is not None:
        converted = _CONVERTER.convert(normalized)
        info["t2s"] = converted != normalized
        normalized = converted

    return normalized, info
