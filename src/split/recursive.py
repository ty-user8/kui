"""按标题递归切分：先按章节边界分段，段内超长再按段落、句子递归下切。

与固定窗口的区别：chunk 不跨章节、尽量不跨句，长度只作为上限而非固定值；
`overlap` 在此策略下按「回退若干完整句子」实现，不会把一句话切成两半。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from src.parse.anchor import Structure
from src.parse.docx_reader import ParsedDocument
from src.split.fixed import Chunk


def _segments(parsed: ParsedDocument, structure: Structure) -> list[tuple[int, int]]:
    """按标题把基准文本切成 [start, end) 段；无标题时整篇为一段。"""
    starts = [index for index, _ in structure.headings]
    if not starts:
        return [(0, len(parsed.base_text))]
    offsets = [structure.paragraphs[index].start for index in starts]
    bounds = [0] + offsets[1:] if offsets[0] != 0 else offsets
    bounds.append(len(parsed.base_text))
    cleaned = sorted({b for b in bounds})
    return [(cleaned[i], cleaned[i + 1]) for i in range(len(cleaned) - 1)]


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in "。！？；":
            out.append(buffer)
            buffer = ""
    if buffer:
        out.append(buffer)
    return out


def _units(text: str, max_len: int) -> list[str]:
    """把一段文本拆成不超过 `max_len` 的单元：先按段落，段过长再按句，单句仍过长才硬切。

    早期实现只按段落拆，遇到超长段落会产出一个远超窗口的 chunk，被模型截断后语义受损。
    """
    pieces = [piece for piece in text.split("\n") if piece] if "\n" in text else [text]
    units: list[str] = []
    for piece in pieces:
        if len(piece) <= max_len:
            units.append(piece)
            continue
        for sentence in _sentences(piece):
            if len(sentence) <= max_len:
                units.append(sentence)
            else:
                units.extend(sentence[i : i + max_len] for i in range(0, len(sentence), max_len))
    return units


def _pack(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    """把单元合并成不超过 `chunk_size` 的块；相邻块之间回退至少 `overlap` 字符的完整单元。"""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        if length + len(unit) > chunk_size and current:
            chunks.append("".join(current))
            back: list[str] = []
            back_len = 0
            for item in reversed(current):
                if back_len >= overlap:
                    break
                back.insert(0, item)
                back_len += len(item)
            current = back
            length = back_len
        current.append(unit)
        length += len(unit)
    if current:
        chunks.append("".join(current))
    return chunks


@dataclass
class _Span:
    start: int
    end: int
    text: str


def split_recursive(
    parsed: ParsedDocument,
    structure: Structure,
    doc_id: str,
    chunk_size: int,
    overlap: int,
    seq_offset: int = 0,
) -> list[Chunk]:
    """按标题递归切分，返回与非空 chunk 列表。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    base = parsed.base_text
    metas = list(structure.paragraphs)
    starts = [meta.start for meta in metas]
    chunks: list[Chunk] = []
    seq = seq_offset

    for seg_start, seg_end in _segments(parsed, structure):
        text = base[seg_start:seg_end]
        if not text.strip():
            continue
        pieces = _pack(_units(text, chunk_size), chunk_size, overlap)
        cursor = seg_start
        for piece in pieces:
            if not piece.strip():
                cursor += len(piece)
                continue
            index = bisect.bisect_right(starts, cursor) - 1
            meta = metas[index] if index >= 0 else None
            chunks.append(
                Chunk(
                    chunk_id="%s:%05d" % (doc_id, seq),
                    doc_id=doc_id,
                    seq=seq,
                    text=piece,
                    char_start=cursor,
                    char_end=cursor + len(piece),
                    article_no=meta.article_no if meta else None,
                    heading_path=meta.heading_path if meta else "",
                    n_chars=len(piece),
                )
            )
            seq += 1
            cursor += len(piece)
    return chunks


def main() -> int:
    """自检：对 v0.2 语料按标题递归切分，打印 chunk 数与跨章节情况。"""
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
        chunks = split_recursive(parsed, structure, "demo", conf.split.chunk_size, conf.split.overlap)
        heads = {chunk.heading_path for chunk in chunks}
        print(
            "%s | chunk %d | 覆盖 %d / %d 字符 | 章节 %d 个"
            % (name[:22], len(chunks), sum(c.n_chars for c in chunks), parsed.base_chars, len(heads))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
