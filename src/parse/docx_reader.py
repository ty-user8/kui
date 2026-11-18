"""DOCX → 基准文本与段落序列。

基准层定义见 `specs/01-requirements.md` 5.3.1：按正文段落顺序拼接，段间插入单个
换行符；不做 strip、不做全半角与繁简转换；表格、图片、页眉页脚不计入基准。
偏移以 Unicode 码点为单位，区间左闭右开，段落起点在 0 偏移处开始累计。
"""

from __future__ import annotations

import hashlib
import pathlib
import zipfile
from dataclasses import dataclass

import docx
from docx.oxml.ns import qn

OOXML_MAGIC = b"PK\x03\x04"
SEPARATOR = "\n"


class EntryError(ValueError):
    """输入条目不可用。`code` 对应 specs/07-api 的错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParagraphSpan:
    """一个段落在基准文本中的位置。"""

    index: int
    start: int
    end: int
    text: str
    style_name: str = ""


@dataclass(frozen=True)
class ParsedDocument:
    """一篇文档的解析结果。基准文本与计数满足 `base_chars + excluded_chars == chars_total`。"""

    path: pathlib.Path
    file_name: str
    base_text: str
    paragraphs: tuple[ParagraphSpan, ...]
    text_sha256: str
    tables_count: int
    non_text_count: int
    para_chars: int
    sep_chars: int
    table_chars: int
    chars_total: int
    excluded_chars: int

    @property
    def base_chars(self) -> int:
        return len(self.base_text)

    def slice(self, start: int, end: int) -> str:
        return self.base_text[start:end]


def safe_entry_path(root: pathlib.Path, candidate: str | pathlib.Path) -> pathlib.Path:
    """把候选路径限制在根目录内；拒绝绝对路径、上跳与解析后越界。"""
    raw = pathlib.Path(candidate)
    if raw.is_absolute():
        raise EntryError("ENTRY_UNSAFE_PATH", "不接受绝对路径：%s" % raw)
    if any(part == ".." for part in raw.parts):
        raise EntryError("ENTRY_UNSAFE_PATH", "路径不得包含上跳：%s" % raw)
    root_resolved = root.resolve()
    target = (root_resolved / raw).resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise EntryError("ENTRY_UNSAFE_PATH", "路径越出语料目录：%s" % raw)
    return target


def check_entry(path: pathlib.Path, max_file_mb: int, max_unpacked_mb: int) -> None:
    """入库前校验：扩展名、文件大小、OOXML 包结构与解压后正文规模。"""
    if path.suffix.lower() != ".docx":
        raise EntryError("ENTRY_UNSUPPORTED_FORMAT", "只接受 .docx：%s" % path.name)
    if not path.is_file():
        raise EntryError("PARSE_FAILED", "文件不存在：%s" % path.name)
    size = path.stat().st_size
    if size > max_file_mb * 1024 * 1024:
        raise EntryError("ENTRY_TOO_LARGE", "%s 超过 %d MB（实际 %d 字节）" % (path.name, max_file_mb, size))
    with path.open("rb") as handle:
        if handle.read(4) != OOXML_MAGIC:
            raise EntryError("PARSE_FAILED", "不是合法的 OOXML 包：%s" % path.name)
    try:
        with zipfile.ZipFile(path) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise EntryError("PARSE_FAILED", "压缩包损坏：%s（%s）" % (path.name, exc)) from exc
    if unpacked > max_unpacked_mb * 1024 * 1024:
        raise EntryError(
            "ENTRY_TOO_LARGE", "%s 解压后 %d 字节，超过上限 %d MB" % (path.name, unpacked, max_unpacked_mb)
        )


def _count_non_text(body) -> int:
    return len(body.findall(".//" + qn("w:drawing"))) + len(body.findall(".//" + qn("w:pict")))


def _table_chars(document: docx.document.Document) -> tuple[int, int]:
    """返回（表格单元格文本长度和, 表格个数）。合并单元格由 python-docx 重复返回，按内容去重计数。"""
    total = 0
    for table in document.tables:
        seen: set[str] = set()
        for row in table.rows:
            for cell in row.cells:
                key = str(id(cell._tc))
                if key in seen:
                    continue
                seen.add(key)
                total += len(cell.text)
    return total, len(document.tables)


def read_docx(path: str | pathlib.Path) -> ParsedDocument:
    """解析单个 DOCX，返回基准文本、段落序列与计数。

    段内软换行（`w:br`）在 `paragraph.text` 中表现为换行符，按 5.3.1 原样计入；
    段落边界由返回的段落序列决定，不从基准文本反推。
    """
    file_path = pathlib.Path(path)
    try:
        document = docx.Document(str(file_path))
    except Exception as exc:  # python-docx 对损坏包抛出的异常类型不统一
        raise EntryError("PARSE_FAILED", "无法解析 %s（%s）" % (file_path.name, type(exc).__name__)) from exc

    texts = [paragraph.text for paragraph in document.paragraphs]
    styles = [(getattr(paragraph.style, "name", "") or "") for paragraph in document.paragraphs]
    spans: list[ParagraphSpan] = []
    cursor = 0
    for index, text in enumerate(texts):
        spans.append(
            ParagraphSpan(index=index, start=cursor, end=cursor + len(text), text=text, style_name=styles[index])
        )
        cursor += len(text) + len(SEPARATOR)
    base_text = SEPARATOR.join(texts)

    para_chars = sum(len(text) for text in texts)
    sep_chars = max(0, len(texts) - 1)
    if len(base_text) != para_chars + sep_chars:
        raise EntryError("PARSE_FAILED", "基准文本长度与段落累计不一致：%s" % file_path.name)
    if not base_text.strip():
        raise EntryError("PARSE_FAILED", "正文为空：%s" % file_path.name)

    table_chars, tables_count = _table_chars(document)
    chars_total = para_chars + sep_chars + table_chars
    if len(base_text) + table_chars != chars_total:
        raise EntryError("PARSE_FAILED", "字符守恒校验失败：%s" % file_path.name)

    return ParsedDocument(
        path=file_path,
        file_name=file_path.name,
        base_text=base_text,
        paragraphs=tuple(spans),
        text_sha256=hashlib.sha256(base_text.encode("utf-8")).hexdigest(),
        tables_count=tables_count,
        non_text_count=_count_non_text(document.element.body),
        para_chars=para_chars,
        sep_chars=sep_chars,
        table_chars=table_chars,
        chars_total=chars_total,
        excluded_chars=table_chars,
    )


def summarize(parsed: ParsedDocument) -> str:
    """单行摘要，供命令行核对。"""
    return "%s | 段落 %d | 基准 %d 字符 | 表格 %d 个（排除 %d 字符）| 非文本 %d 处 | sha256 %s" % (
        parsed.file_name,
        len(parsed.paragraphs),
        parsed.base_chars,
        parsed.tables_count,
        parsed.excluded_chars,
        parsed.non_text_count,
        parsed.text_sha256[:16],
    )


def main() -> int:
    """自检：解析 v0.1 的两篇文档并核对字符守恒与摘要。"""
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from src.config import ConfigError, load

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2
    for name in conf.corpus.v01_subset:
        path = conf.corpus.docs_dir / name
        check_entry(path, conf.ingest.max_file_mb, conf.ingest.max_unpacked_mb)
        parsed = read_docx(path)
        print(summarize(parsed))
        print(
            "  守恒: 基准 %d + 排除 %d = %d | 段落字符 %d + 分隔 %d = 基准"
            % (parsed.base_chars, parsed.excluded_chars, parsed.chars_total, parsed.para_chars, parsed.sep_chars)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
