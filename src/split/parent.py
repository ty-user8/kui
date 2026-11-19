"""父子 chunk：parent 存整条或若干条，child 是 parent 内的小窗口。

检索只索引 child（小粒度定位更准），命中后回溯到 parent 作为上下文（small-to-big）。
parent 以「条」为不可分单元聚合到 `parent_chars` 附近；无条号的段落按段聚合。
同一 parent 下的多个 child 命中时，只保留排名最好的那一条（去重）。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.parse.anchor import Structure
from src.parse.docx_reader import ParsedDocument
from src.split.fixed import Chunk

PARENT_CHARS = 1200


@dataclass(frozen=True)
class Parent:
    parent_id: str
    doc_id: str
    seq: int
    text: str
    char_start: int
    char_end: int
    article_no: str | None
    heading_path: str
    n_chars: int


def build_parents(
    parsed: ParsedDocument,
    structure: Structure,
    doc_id: str,
    parent_chars: int = PARENT_CHARS,
) -> list[Parent]:
    """按条聚合出 parent 列表；单条超过 `parent_chars` 时独占一个 parent。"""
    if parent_chars <= 0:
        raise ValueError("parent_chars 必须为正数")

    units: list[tuple[int, int, str | None, str]] = []
    for meta in structure.paragraphs:
        text = meta.text
        if not text.strip():
            continue
        units.append((meta.start, meta.end, meta.article_no, meta.heading_path))

    parents: list[Parent] = []
    seq = 0
    start = end = None
    article: str | None = None
    heading = ""
    for unit_start, unit_end, unit_article, unit_heading in units:
        if start is None:
            start, end = unit_start, unit_end
            article, heading = unit_article, unit_heading
            continue
        if unit_end - start > parent_chars:
            parents.append(_make(parents, doc_id, seq, parsed, start, end, article, heading))
            seq += 1
            start, end = unit_start, unit_end
            article, heading = unit_article, unit_heading
        else:
            end = unit_end
            heading = unit_heading or heading
    if start is not None:
        parents.append(_make(parents, doc_id, seq, parsed, start, end, article, heading))
    return parents


def _make(
    existing: list[Parent],
    doc_id: str,
    seq: int,
    parsed: ParsedDocument,
    start: int,
    end: int,
    article: str | None,
    heading: str,
) -> Parent:
    return Parent(
        parent_id="%s:p%04d" % (doc_id, seq),
        doc_id=doc_id,
        seq=seq,
        text=parsed.slice(start, end),
        char_start=start,
        char_end=end,
        article_no=article,
        heading_path=heading,
        n_chars=end - start,
    )


def build_children(
    parents: list[Parent],
    doc_id: str,
    chunk_size: int,
    overlap: int,
) -> list[Chunk]:
    """在 parent 内按固定窗口切 child；child 继承 parent_id 与 parent 的条号、标题。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap 应满足 0 <= overlap < chunk_size")

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    seq = 0
    for parent in parents:
        text = parent.text
        offset = 0
        while offset < len(text):
            piece = text[offset : offset + chunk_size]
            if piece.strip():
                chunks.append(
                    Chunk(
                        chunk_id="%s:c%05d" % (doc_id, seq),
                        doc_id=doc_id,
                        seq=seq,
                        text=piece,
                        char_start=parent.char_start + offset,
                        char_end=parent.char_start + offset + len(piece),
                        article_no=parent.article_no,
                        heading_path=parent.heading_path,
                        n_chars=len(piece),
                        parent_id=parent.parent_id,
                    )
                )
                seq += 1
            if offset + chunk_size >= len(text):
                break
            offset += step
    return chunks


def parent_at(children: list[Chunk], position: int) -> str | None:
    """把基准文本上的偏移映射到覆盖它的 child 的 parent（锚点映射用）。"""
    for child in children:
        if child.char_start <= position < child.char_end:
            return child.parent_id
    return None


def collapse(hits: list[tuple[str, float]], parent_by_chunk: dict[str, str | None], top_k: int) -> list[tuple[str, float]]:
    """把 child 命中折叠到 parent：同一 parent 只保留首次（排名最好）出现。"""
    seen: set[str] = set()
    collapsed: list[tuple[str, float]] = []
    for chunk_id, score in hits:
        parent_id = parent_by_chunk.get(chunk_id)
        key = parent_id or chunk_id
        if key in seen:
            continue
        seen.add(key)
        collapsed.append((key, score))
        if len(collapsed) >= top_k:
            break
    return collapsed


def main() -> int:
    """自检：对 v0.1 两篇文档建父子结构，打印 parent/child 数与折叠效果。"""
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
        doc_id = "demo"
        parents = build_parents(parsed, structure, doc_id)
        children = build_children(parents, doc_id, conf.split.chunk_size, conf.split.overlap)
        mapping = {child.chunk_id: child.parent_id for child in children}
        sample = [(child.chunk_id, 1.0 - i * 0.01) for i, child in enumerate(children[:6])]
        folded = collapse(sample, mapping, 3)
        print(
            "%s | parent %d、child %d | 前 6 条折叠为 %d 个 parent：%s"
            % (name[:20], len(parents), len(children), len(folded), [p[-5:] for p, _ in folded])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
