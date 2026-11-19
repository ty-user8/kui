"""按基准层定义回填评测集锚点，并逐字校验。

规格语义（`specs/01-requirements.md` 5.3.3、5.3.4）：
- 锚点区间取该条整段，左闭右开；
- `anchor_text` 是 `[char_start, char_end)` 回切的整段文本，二者必须逐字一致；
- 校验不通过时停止，不写文件、不降级为前缀或包含判断。

两种运行方式：
- 默认：只填 `char_start` / `char_end`，用区间回切校验 CSV 里已有的 `anchor_text`，
  任一不符即整体中止并列出明细（不改文件）。
- `--reset-anchor-text`：把 `anchor_text` 重置为区间回切的整段文本。仅用于把历史
  不一致的标注纠正到规格口径；运行后必须再用默认模式复核一次。
- `--check`：只读校验，不写 `cases.csv` 也不重出核对表，供 Verify 阶段使用。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe evals/tools/fill_anchors.py
    .venv\\Scripts\\python.exe evals/tools/fill_anchors.py --reset-anchor-text
    .venv\\Scripts\\python.exe evals/tools/fill_anchors.py --check
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.parse.anchor import build_structure  # noqa: E402
from src.parse.docx_reader import EntryError, check_entry, read_docx  # noqa: E402

CASES = PROJECT_ROOT / "evals" / "cases.csv"
REVIEW = PROJECT_ROOT / "evals" / "anchor-review.md"
LEAD_CHARS = 60
TOTAL_CASES = 100
SENTENCE_END = "。"


def lead_sentence(text: str) -> str:
    """仅用于核对表展示：取整段开头的第一句，含句号，最长 LEAD_CHARS 字。"""
    cut = text.find(SENTENCE_END)
    sentence = text[: cut + 1] if cut != -1 else text
    return sentence[:LEAD_CHARS]


def load_manifest(path: pathlib.Path) -> dict[str, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {record["doc_id"]: record for record in records}


def read_cases() -> tuple[list[str], list[dict[str, str]]]:
    with CASES.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_cases(fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with CASES.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="回填锚点区间并按规格逐字校验")
    parser.add_argument(
        "--reset-anchor-text",
        action="store_true",
        help="把 anchor_text 重置为区间回切的整段文本（纠正历史不一致标注）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只读校验：不写 cases.csv、不重出核对表，返回码表示是否全部通过",
    )
    parser.add_argument(
        "--fill-empty",
        action="store_true",
        help="只填新增行的空 anchor_text 与空 heading_path，非空行仍按逐字校验，不一致即中止",
    )
    args = parser.parse_args()
    if args.check and (args.reset_anchor_text or args.fill_empty):
        parser.error("--check 不能与写入类开关同时使用")
    if args.reset_anchor_text and args.fill_empty:
        parser.error("--reset-anchor-text 与 --fill-empty 不能同时使用")

    try:
        conf = load()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    manifest = load_manifest(conf.corpus.manifest)
    fieldnames, rows = read_cases()

    cache: dict[str, tuple] = {}
    failures: list[tuple[str, str]] = []

    for row in rows:
        case_id = row["case_id"]
        doc_id = row["doc_id"]
        article_no = (row.get("article_no") or "").strip()
        record = manifest.get(doc_id)
        if record is None:
            failures.append((case_id, "manifest 中无此 doc_id"))
            continue
        if not article_no:
            failures.append((case_id, "article_no 为空，需按段落锚点处理"))
            continue

        if doc_id not in cache:
            path = conf.corpus.docs_dir / record["file_name"]
            try:
                check_entry(path, conf.ingest.max_file_mb, conf.ingest.max_unpacked_mb)
                parsed = read_docx(path)
                cache[doc_id] = (parsed, build_structure(parsed), record["title"])
            except EntryError as exc:
                failures.append((case_id, "解析失败 %s" % exc.code))
                continue
        parsed, structure, _title = cache[doc_id]

        span = structure.article_span(article_no)
        if span is None:
            failures.append((case_id, "未找到 %s" % article_no))
            continue
        start, end = span
        segment = parsed.slice(start, end)

        if start != 0 and parsed.base_text[start - 1] != "\n":
            failures.append((case_id, "左边界不在段落起点"))
            continue
        if end != len(parsed.base_text) and parsed.base_text[end] != "\n":
            failures.append((case_id, "右边界不在段落终点"))
            continue

        existing = row.get("anchor_text") or ""
        if args.reset_anchor_text or (args.fill_empty and not existing):
            anchor_text = segment
        else:
            anchor_text = existing
        if anchor_text != segment:
            failures.append(
                (case_id, "回切与 anchor_text 不一致（回切 %d 字 / 文本 %d 字）" % (len(segment), len(anchor_text)))
            )
            continue

        meta = next(p for p in structure.paragraphs if p.start == start)
        row["char_start"] = str(start)
        row["char_end"] = str(end)
        row["anchor_text"] = anchor_text
        if not (row.get("heading_path") or "").strip():
            row["heading_path"] = meta.heading_path
        row["note"] = "整段 %d 字；逐字校验一致" % len(segment)

    if failures:
        print("校验未通过 %d 条，未写入任何文件：" % len(failures))
        for case_id, reason in failures:
            print("  %s: %s" % (case_id, reason))
        return 1

    if args.check:
        print("只读校验通过：%d 条回切与 anchor_text 逐字一致，未写入任何文件" % len(rows))
        return 0

    write_cases(fieldnames, rows)
    write_review(rows, {row["doc_id"]: manifest[row["doc_id"]]["title"] for row in rows})
    print("回填 %d / %d 条，逐字校验通过" % (len(rows), len(rows)))
    mode = "重置 anchor_text 为整段" if args.reset_anchor_text else (
        "只填新增行的空 anchor_text，其余逐字校验" if args.fill_empty else "只填区间并校验既有 anchor_text")
    print("模式: %s" % mode)
    print("核对表: %s" % REVIEW.relative_to(PROJECT_ROOT))
    return verify_written()


def write_review(rows: list[dict[str, str]], titles: dict[str, str]) -> None:
    lines = [
        "# 锚点人工核对表",
        "",
        "区间与 `anchor_text` 均由 `evals/tools/fill_anchors.py` 从 DOCX 基准文本抽取，二者逐字一致。",
        "「整段文本」列即 `anchor_text` 全文，是核对对象；「首句」列只截前 60 字，仅供扫读。",
        "`anchor_status`：已确认 %d 条、待确认 %d 条（共 %d 条）。"
        % (sum(1 for r in rows if (r.get("anchor_status") or "") == "confirmed"),
           sum(1 for r in rows if (r.get("anchor_status") or "") != "confirmed"), len(rows)),
        "",
        "确认方式：逐条核对「条号 / 区间 / 整段文本」是否指向正确条款，确认后在 `evals/cases.csv`",
        "把该行 `anchor_status` 改为 `confirmed`。当前 %d 条，最终 %d 条全部 `confirmed` 后再进 T-015 指标。"
        % (len(rows), TOTAL_CASES),
        "",
        "| 用例 | split | 查询 | 文档 | 条号 | 章节 | 区间 | 整段文本 | 首句（前 60 字，仅供扫读） |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| %s | %s | %s | %s | %s | %s | [%s, %s) %d 字 | %s | %s |"
            % (
                row["case_id"],
                row.get("split", ""),
                row.get("query", ""),
                titles.get(row["doc_id"], ""),
                row.get("article_no", ""),
                row.get("heading_path", ""),
                row["char_start"],
                row["char_end"],
                int(row["char_end"]) - int(row["char_start"]),
                row["anchor_text"].replace("\n", "⏎").replace("|", "／"),
                lead_sentence(row["anchor_text"]).replace("\n", "⏎").replace("|", "／"),
            )
        )
    lines += ["", "合计：%d 条，逐字校验全部通过。" % len(rows), ""]
    REVIEW.write_text("\n".join(lines), encoding="utf-8")


def verify_written() -> int:
    """重读磁盘文件并重新解析，确认落盘后仍满足「回切 == anchor_text」。"""
    conf = load()
    manifest = load_manifest(conf.corpus.manifest)
    _, rows = read_cases()
    cache: dict[str, tuple] = {}
    bad: list[str] = []
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in cache:
            parsed = read_docx(conf.corpus.docs_dir / manifest[doc_id]["file_name"])
            cache[doc_id] = (parsed, build_structure(parsed))
        parsed, structure = cache[doc_id]
        span = structure.article_span(row["article_no"])
        if span is None or str(span[0]) != row["char_start"] or str(span[1]) != row["char_end"]:
            bad.append("%s 区间不一致" % row["case_id"])
            continue
        if parsed.slice(span[0], span[1]) != row["anchor_text"]:
            bad.append("%s 回切与 anchor_text 不一致" % row["case_id"])
    if bad:
        print("落盘后复核未通过：")
        for item in bad:
            print("  %s" % item)
        return 1
    print("落盘后复核：%d 条回切与 anchor_text 逐字一致" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
