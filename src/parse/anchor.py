"""标题路径与条号识别。

依据 `specs/01-requirements.md` 5.3 与 D-008：标题判定同时看段落样式与正文形态，
并对目录区做去重——同一标题文本出现多次时，只保留最后一次出现（正文侧），
前面的目录副本丢弃。语料实测 150 篇中仅 5 篇使用 `Heading` 样式，其余需靠正文正则。
"""

from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parse.docx_reader import ParsedDocument, ParagraphSpan  # noqa: E402

HEADING_RE = re.compile(r"^\s*第[一二三四五六七八九十百零〇]+[编章节]")
ARTICLE_RE = re.compile(r"^\s*(第[一二三四五六七八九十百零〇]+条)")
HEADING_STYLES = ("Heading", "标题")
TOC_TEXTS = ("目录", "目次")


@dataclass(frozen=True)
class ParagraphMeta:
    index: int
    start: int
    end: int
    text: str
    heading_path: str
    article_no: str | None
    is_heading: bool
    is_toc_copy: bool


@dataclass(frozen=True)
class Structure:
    paragraphs: tuple[ParagraphMeta, ...]
    headings: tuple[tuple[int, str], ...]
    articles: dict[str, tuple[int, int]]
    toc_dropped: int
    duplicate_articles: tuple[str, ...]

    @property
    def chapter_count(self) -> int:
        return len(self.headings)

    def article_span(self, article_no: str) -> tuple[int, int] | None:
        return self.articles.get(article_no)


def normalize_heading(text: str) -> str:
    """标题比较用规范化：去掉全角空格、半角空格、制表符与首尾空白，不做繁简或全半角转换。"""
    return re.sub(r"[\u3000\s]+", "", text)


def style_is_heading(style_name: str) -> bool:
    return any(style_name.startswith(prefix) for prefix in HEADING_STYLES)


def is_heading(paragraph) -> bool:
    style = getattr(paragraph.style, "name", "") or ""
    if style_is_heading(style):
        return True
    return bool(HEADING_RE.match(paragraph.text))


def _is_toc_label(text: str) -> bool:
    return normalize_heading(text) in TOC_TEXTS


def _heading_candidates(parsed: ParsedDocument) -> list[tuple[int, str, bool]]:
    """返回（段落序号, 原文, 是否为目录标签）。样式与正文正则双判。"""
    candidates: list[tuple[int, str, bool]] = []
    for span in parsed.paragraphs:
        text = span.text
        if _is_toc_label(text):
            candidates.append((span.index, text, True))
            continue
        if style_is_heading(span.style_name) or HEADING_RE.match(text):
            candidates.append((span.index, text, False))
    return candidates


def _drop_toc_copies(candidates: list[tuple[int, str, bool]]) -> tuple[list[tuple[int, str]], int]:
    """同一标题文本出现多次时保留最后一次；目录标签本身丢弃。"""
    kept: list[tuple[int, str]] = []
    seen: set[str] = set()
    dropped = 0
    for index, text, is_label in reversed(candidates):
        if is_label:
            dropped += 1
            continue
        key = normalize_heading(text)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append((index, text))
    kept.reverse()
    return kept, dropped


def build_structure(parsed: ParsedDocument) -> Structure:
    """构造段落元信息、标题序列与条号索引。标题判定用段落样式加正文正则。"""
    merged = _heading_candidates(parsed)
    kept, toc_dropped = _drop_toc_copies(merged)
    kept_index = {index for index, _ in kept}

    metas: list[ParagraphMeta] = []
    articles: dict[str, tuple[int, int]] = {}
    duplicates: list[str] = []
    current_path = ""
    for span in parsed.paragraphs:
        text = span.text
        if span.index in kept_index:
            current_path = normalize_heading(text)
        match = ARTICLE_RE.match(text)
        article_no = match.group(1) if match else None
        if article_no is not None:
            if article_no in articles:
                duplicates.append(article_no)
            else:
                articles[article_no] = (span.start, span.end)
        metas.append(
            ParagraphMeta(
                index=span.index,
                start=span.start,
                end=span.end,
                text=text,
                heading_path=current_path,
                article_no=article_no,
                is_heading=span.index in kept_index,
                is_toc_copy=span.index in {i for i, _, label in merged if label},
            )
        )

    return Structure(
        paragraphs=tuple(metas),
        headings=tuple(kept),
        articles=articles,
        toc_dropped=toc_dropped,
        duplicate_articles=tuple(duplicates),
    )


def article_text(parsed: ParsedDocument, structure: Structure, article_no: str) -> str | None:
    """按条号取该条整段原文。"""
    span = structure.article_span(article_no)
    if span is None:
        return None
    return parsed.slice(span[0], span[1])


def heading_of(structure: Structure, position: int) -> str:
    """给定基准文本偏移，返回该位置所属的标题路径。"""
    current = ""
    for meta in structure.paragraphs:
        if meta.start <= position:
            current = meta.heading_path
        else:
            break
    return current


def main() -> int:
    """自检：目录去重、样式与正则双判、无条号文档降级。"""
    from src.config import load
    from src.parse.docx_reader import read_docx

    conf = load()
    targets = list(conf.corpus.v01_subset) + [
        "全国人民代表大会常务委员会关于县级以下人民代表大会代表直接选举的若干规定_19830305_2c909fdd.docx"
    ]
    for name in targets:
        path = conf.corpus.docs_dir / name
        if not path.is_file():
            print("跳过（语料中不存在）：%s" % name)
            continue
        parsed = read_docx(path)
        structure = build_structure(parsed)
        print(
            "%s | 标题 %d | 目录丢弃 %d | 条号 %d | 重复条号 %s"
            % (
                name[:28],
                structure.chapter_count,
                structure.toc_dropped,
                len(structure.articles),
                structure.duplicate_articles or "无",
            )
        )
        if structure.headings:
            print("  首个标题: %s | 末个标题: %s" % (structure.headings[0][1], structure.headings[-1][1]))
        first = next(iter(structure.articles), None)
        if first:
            span = structure.article_span(first)
            print("  %s 区间 [%d, %d) 所属标题: %s" % (first, span[0], span[1], heading_of(structure, span[0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
