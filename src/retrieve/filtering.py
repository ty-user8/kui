"""元数据过滤与三条降级。

FAISS 的 `IndexFlatIP` 不支持带条件的检索，因此过滤在候选层做：先取 `top_k × oversample`
个候选，再按文档元数据筛，最后截到 `top_k`。

三条降级（REQ-023／REQ-024／REQ-025）：
- 向量路不可用（索引缺失或调用异常）→ 只用 BM25，标记 `FALLBACK_BM25`
- 重排超时 → 融合序，标记 `FALLBACK_RERANK_TIMEOUT`（由 rerank 模块给出）
- 过滤后为空 → 去掉过滤条件重试一次，标记 `FILTER_RELAXED`
"""

from __future__ import annotations

from dataclasses import dataclass, field

FALLBACK_BM25 = "FALLBACK_BM25"
FILTER_RELAXED = "FILTER_RELAXED"
OVERSAMPLE = 5


@dataclass
class MetadataFilter:
    """按文档元数据筛候选；每个字段为 None 表示不限。日期按 ISO `YYYY-MM-DD` 字符串比较。"""

    doc_ids: set[str] | None = None
    categories: set[str] | None = None
    authorities: set[str] | None = None
    publish_from: str | None = None
    publish_to: str | None = None

    def matches(self, meta: dict | None) -> bool:
        if meta is None:
            return False
        if self.doc_ids and meta.get("doc_id") not in self.doc_ids:
            return False
        if self.categories and meta.get("category") not in self.categories:
            return False
        if self.authorities and meta.get("authority") not in self.authorities:
            return False
        published = (meta.get("publish_date") or "")[:10]
        if self.publish_from and published < self.publish_from:
            return False
        if self.publish_to and published > self.publish_to:
            return False
        return True

    @property
    def active(self) -> bool:
        return any((self.doc_ids, self.categories, self.authorities, self.publish_from, self.publish_to))


def apply_filter(hits: list[tuple[str, float]], meta_of: dict[str, dict], flt: MetadataFilter, top_k: int) -> list[tuple[str, float]]:
    """按元数据保留候选，保持原有顺序。"""
    kept = [(chunk_id, score) for chunk_id, score in hits if flt.matches(meta_of.get(chunk_id))]
    return kept[:top_k]


@dataclass
class FilteredResult:
    hits: list[tuple[str, float]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    relaxed: bool = False


class FilteredRetriever:
    """在已有检索器外面套一层过滤与降级；`meta_of` 由调用方提供（chunk_id → 文档元数据）。"""

    def __init__(self, base, meta_of, oversample: int = OVERSAMPLE) -> None:
        self.base = base
        self.meta_of = meta_of
        self.oversample = oversample

    @property
    def ready(self) -> bool:
        return self.base.ready

    def search(self, query: str, top_k: int = 5, flt: MetadataFilter | None = None) -> FilteredResult:
        if flt is None or not flt.active:
            return FilteredResult(self.base.search(query, top_k), [])

        width = top_k * self.oversample
        hits = self.base.search(query, width)
        kept = apply_filter(hits, self.meta_of(hits), flt, top_k)
        if kept:
            return FilteredResult(kept, [])
        # 过滤后为空：放宽（丢弃过滤条件）重试一次，明确标记，不静默返回空
        return FilteredResult(self.base.search(query, top_k), [FILTER_RELAXED], relaxed=True)
