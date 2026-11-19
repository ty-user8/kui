"""句子滑窗切分：以句子为单位累积到 `chunk_size` 附近，下一窗口回退 `overlap` 字符。

与固定窗口的区别：边界落在句子之间，不会把一句话切成两半；与按标题递归的区别：
不按章节分段，窗口可跨章节滑过，块数由窗口与回退量决定。
"""

from __future__ import annotations

import bisect

from src.parse.anchor import Structure
from src.parse.docx_reader import ParsedDocument
from src.split.fixed import Chunk

SENTENCE_END = "。！？；"


def _sentences(text: str) -> list[tuple[int, int]]:
    """按句末标点切成 [start, end) 列表；最后一段不足一句时保留到文末。"""
    spans: list[tuple[int, int]] = []
    start = 0
    for index, char in enumerate(text):
        if char in SENTENCE_END:
            spans.append((start, index + 1))
            start = index + 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def split_sliding(
    parsed: ParsedDocument,
    structure: Structure,
    doc_id: str,
    chunk_size: int,
    overlap: int,
    seq_offset: int = 0,
) -> list[Chunk]:
    """句子滑窗切分，返回非空 chunk 列表。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap 应满足 0 <= overlap < chunk_size")

    base = parsed.base_text
    spans = _sentences(base)
    metas = list(structure.paragraphs)
    starts = [meta.start for meta in metas]

    chunks: list[Chunk] = []
    seq = seq_offset
    index = 0
    while index < len(spans):
        # 单句超过窗口时独占一块并截断，避免死循环
        if spans[index][1] - spans[index][0] > chunk_size:
            start = spans[index][0]
            end = min(start + chunk_size, len(base))
            index += 1
        else:
            cursor = index
            total = 0
            while cursor < len(spans) and total + (spans[cursor][1] - spans[cursor][0]) <= chunk_size:
                total += spans[cursor][1] - spans[cursor][0]
                cursor += 1
            start = spans[index][0]
            end = spans[cursor - 1][1]
            # 下一窗口起点：回退若干整句，累计不超过 overlap，且至少前进一句
            back_index = cursor
            backed = 0
            while back_index - 1 > index and backed + (spans[back_index - 1][1] - spans[back_index - 1][0]) <= overlap:
                back_index -= 1
                backed += spans[back_index][1] - spans[back_index][0]
            index = back_index if back_index > index else index + 1

        text = base[start:end]
        if text.strip():
            position = bisect.bisect_right(starts, start) - 1
            meta = metas[position] if position >= 0 else None
            chunks.append(
                Chunk(
                    chunk_id="%s:%05d" % (doc_id, seq),
                    doc_id=doc_id,
                    seq=seq,
                    text=text,
                    char_start=start,
                    char_end=end,
                    article_no=meta.article_no if meta else None,
                    heading_path=meta.heading_path if meta else "",
                    n_chars=len(text),
                )
            )
            seq += 1
    return chunks


def main() -> int:
    """自检：对 v0.1 两篇文档句子滑窗切分，打印 chunk 数与覆盖字符。"""
    import pathlib
    import sys

    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.config import load
    from src.parse.anchor import build_structure
    from src.parse.docx_reader import read_docx

    conf = load()
    for name in conf.corpus.v01_subset:
        parsed = read_docx(conf.corpus.docs_dir / name)
        structure = build_structure(parsed)
        chunks = split_sliding(parsed, structure, "demo", conf.split.chunk_size, conf.split.overlap)
        print(
            "%s | chunk %d | 覆盖 %d / %d 字符 | 首块 [%d,%d)"
            % (name[:22], len(chunks), sum(c.n_chars for c in chunks), parsed.base_chars, chunks[0].char_start, chunks[0].char_end)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
