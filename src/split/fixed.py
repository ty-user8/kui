"""固定长度切分。

在基准文本上按窗口滑动：窗口长度 `chunk_size`，步长 `chunk_size - overlap`，
每个 chunk 记录左闭右开的字符区间，并按区间起点继承所属段落的标题路径与条号。
切分不改变偏移语义——区间始终相对基准文本（`specs/01-requirements.md` 5.3.2）。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from src.parse.anchor import ParagraphMeta, Structure
from src.parse.docx_reader import ParsedDocument


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    seq: int
    text: str
    char_start: int
    char_end: int
    article_no: str | None
    heading_path: str
    n_chars: int


def _paragraph_at(metas: list[ParagraphMeta], starts: list[int], position: int) -> ParagraphMeta | None:
    """返回起点不大于 `position` 的最后一个段落。"""
    index = bisect.bisect_right(starts, position) - 1
    return metas[index] if index >= 0 else None


def split_fixed(
    parsed: ParsedDocument,
    structure: Structure,
    doc_id: str,
    chunk_size: int,
    overlap: int,
    seq_offset: int = 0,
) -> list[Chunk]:
    """按固定窗口切分，返回非空 chunk 列表。

    空白 chunk（整段落在空行之间）会被跳过，`seq` 仍连续编号，避免出现空切片进入索引。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap 应满足 0 <= overlap < chunk_size")

    base = parsed.base_text
    step = chunk_size - overlap
    metas = list(structure.paragraphs)
    starts = [meta.start for meta in metas]
    chunks: list[Chunk] = []
    seq = seq_offset
    start = 0
    while start < len(base):
        end = min(start + chunk_size, len(base))
        text = base[start:end]
        if text.strip():
            meta = _paragraph_at(metas, starts, start)
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
        if end >= len(base):
            break
        start += step
    return chunks


def main() -> int:
    """自检：对 v0.1 两篇文档切分，打印 chunk 数与区间覆盖情况。"""
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
        chunks = split_fixed(parsed, structure, "demo", conf.split.chunk_size, conf.split.overlap)
        covered = sum(chunk.n_chars for chunk in chunks)
        last = chunks[-1]
        print(
            "%s | chunk %d | 覆盖 %d / %d 字符 | 首个 [%d,%d) seq=%d | 末个 [%d,%d)"
            % (
                name[:24],
                len(chunks),
                covered,
                parsed.base_chars,
                chunks[0].char_start,
                chunks[0].char_end,
                chunks[0].seq,
                last.char_start,
                last.char_end,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
