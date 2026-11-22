"""Agent 工具层（v2，`CHG-013`）：4 个工具的确定性实现。

约束（写在这里就不用每次回查变更单）：

- **只复用现有链路**：`search_laws` 走 `service.search(..., write_trace=False)`；`get_anchor_text`
  用 `service.load_chunk_index` / `load_chunk_texts`；`filter_metadata` 与 `get_stats` 读
  `manifest.json`、`index-meta.json` 与 `dao.count_*`。不另建索引、不自己拼 SQL、不写 `trace`。
- **不产生评测产物**：不写 `data/runs/`、不写 `traces`、不写 `runs` 表（`CHG-013` §8.1 D1）。
- **错误结构化**：参数不合法 → `TOOL_ARGS_INVALID`；目标不存在 → `TOOL_RESULT_EMPTY`；
  索引缺失 → `INDEX_EMPTY`；未知工具 → `TOOL_NOT_FOUND`。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

from src.agent import schema
from src.api import service
from src.api.errors import ApiError
from src.store import dao
from src.store.db import connect

_INDEX_META = "index-meta.json"


class ToolError(RuntimeError):
    """工具执行期的结构化错误；`code` 供编排层决定是否回灌给模型。"""

    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _manifest_docs(conf) -> list[dict]:
    """读 `corpus/metadata/manifest.json`（150 条，纯本地）。"""
    path = pathlib.Path(conf.corpus.manifest)
    docs = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(docs, dict):  # 兼容 {"documents": [...]} 形状
        docs = docs.get("documents", [])
    return docs


def _doc_titles(conf) -> dict[str, str]:
    return {doc["doc_id"]: doc.get("title") or "" for doc in _manifest_docs(conf)}


def _doc_by_id(conf) -> dict[str, dict]:
    return {doc["doc_id"]: doc for doc in _manifest_docs(conf)}


def _index_meta(conf) -> dict:
    path = pathlib.Path(conf.paths.index_dir) / _INDEX_META
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _filter_payload(args: schema.SearchLawsArgs) -> dict | None:
    """把工具入参翻译成 `service.parse_filters` 认得的键（单数键 + `publish_date_from/to`）。"""
    flt = args.filters
    if flt is None:
        return None
    payload: dict[str, object] = {}
    if flt.category:
        payload["category"] = list(flt.category)
    if flt.authority:
        payload["authority"] = list(flt.authority)
    if flt.publish_from:
        payload["publish_date_from"] = flt.publish_from
    if flt.publish_to:
        payload["publish_date_to"] = flt.publish_to
    if flt.doc_ids:
        payload["doc_ids"] = list(flt.doc_ids)
    return payload or None


def search_laws(conf, args: schema.SearchLawsArgs) -> dict:
    """语义检索：与 `/search` 同一条链路、同样参数，只是不写 trace。"""
    try:
        result = service.search(conf, args.query, args.top_k, _filter_payload(args), write_trace=False)
    except ApiError as exc:
        raise ToolError(exc.code, exc.message, exc.detail) from exc

    titles = _doc_titles(conf)
    hits = []
    for item in result["results"]:
        hits.append(
            {
                "chunk_id": item["chunk_id"],
                "doc_id": item["doc_id"],
                "title": titles.get(item["doc_id"] or "", ""),
                "article_no": item["article_no"],
                "heading_path": item["heading_path"],
                "score": item["score"],
                "path": item["path"],
            }
        )
    return {"hits": hits, "flags": list(result["flags"]), "count": len(hits)}


def _match(doc: dict, args: schema.FilterMetadataArgs) -> bool:
    value = args.value
    raw = doc.get(args.field) or ""
    if args.op == "eq":
        return raw == value[0]
    if args.op == "in":
        return raw in set(value)
    if args.op == "between":
        published = (raw or "")[:10]
        return bool(published) and value[0] <= published <= value[1]
    if args.op == "contains":
        return value[0] in raw
    return False


def filter_metadata(conf, args: schema.FilterMetadataArgs) -> dict:
    """按元数据筛选文档；字段与算子的组合已在 `schema.FilterMetadataArgs` 里校验过。"""
    docs = [doc for doc in _manifest_docs(conf) if _match(doc, args)]
    total = len(docs)
    kept = docs[: args.limit]
    return {
        "documents": [
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "category": doc.get("category"),
                "authority": doc.get("authority"),
                "publish_date": doc.get("publish_date"),
                "effective_date": doc.get("effective_date"),
            }
            for doc in kept
        ],
        "count": total,
        "truncated": total > len(kept),
    }


def get_anchor_text(conf, args: schema.GetAnchorTextArgs) -> dict:
    """按 `chunk_id` 取正文与锚点；不存在的 id 报 `TOOL_RESULT_EMPTY`。"""
    meta = service.load_chunk_index(conf).get(args.chunk_id)
    if meta is None:
        raise ToolError(
            "TOOL_RESULT_EMPTY",
            "chunk_id 不存在：%s（只能取自 search_laws 的返回结果）" % args.chunk_id,
            {"chunk_id": args.chunk_id},
        )
    text = service.load_chunk_texts(conf, [args.chunk_id]).get(args.chunk_id, "")
    truncated = len(text) > args.max_chars
    doc = _doc_by_id(conf).get(meta.get("doc_id") or "", {})
    return {
        "chunk_id": args.chunk_id,
        "doc_id": meta.get("doc_id"),
        "title": meta.get("title") or doc.get("title"),
        "article_no": meta.get("article_no"),
        "heading_path": meta.get("heading_path"),
        "char_start": meta.get("char_start"),
        "char_end": meta.get("char_end"),
        "text": text[: args.max_chars],
        "truncated": truncated,
        "max_chars": args.max_chars,
        "source_url": doc.get("source_url"),
    }


def get_stats(conf, args: schema.GetStatsArgs) -> dict:
    """语料与索引规模；纯本地计算，0 次模型调用。"""
    conn = connect(conf.require_db_path())
    try:
        documents = dao.count_documents(conn)
        chunks = dao.count_chunks(conn)
    finally:
        conn.close()

    docs = _manifest_docs(conf)
    categories = Counter(doc.get("category") or "" for doc in docs)
    authorities = Counter(doc.get("authority") or "" for doc in docs)
    dates = sorted((doc.get("publish_date") or "")[:10] for doc in docs if doc.get("publish_date"))
    meta = _index_meta(conf)
    return {
        "documents": documents,
        "chunks": chunks,
        "categories": [{"name": name, "count": count} for name, count in categories.most_common(10)],
        "authorities": [{"name": name, "count": count} for name, count in authorities.most_common(10)],
        "publish_date_range": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None},
        "weights_sha256": meta.get("weights_sha256"),
        "normalizer_version": meta.get("normalizer_version"),
        "index_bytes": meta.get("total_bytes"),
    }


_HANDLERS = {
    "search_laws": search_laws,
    "filter_metadata": filter_metadata,
    "get_anchor_text": get_anchor_text,
    "get_stats": get_stats,
}


def dispatch(conf, name: str, payload: dict | None) -> dict:
    """校验后执行：模型给什么就执行什么，不接受白名单外的工具名。"""
    try:
        args = schema.validate_args(name, payload)
    except KeyError as exc:
        raise ToolError("TOOL_NOT_FOUND", "工具不在白名单内：%s" % name, {"tool": name}) from exc
    except schema.ToolArgError as exc:
        raise ToolError(exc.code, exc.message, exc.detail) from exc
    return _HANDLERS[name](conf, args)
