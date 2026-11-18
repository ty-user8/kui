"""单路向量检索：query 编码 → FAISS 检索 → 返回 (chunk_id, score)。

score 是归一化内积（等价余弦），原值输出、不做 0~1 映射（REQ-017a）。
索引为空或库中无 chunk 时返回空列表，由调用方标记 `NO_MATCH`，不抛异常（REQ-017）。
"""

from __future__ import annotations

import pathlib

import numpy as np

from src.index import faiss_index
from src.index.embedder import Embedder


class DenseRetriever:
    def __init__(self, conf, bundle: faiss_index.IndexBundle | None = None, embedder: Embedder | None = None) -> None:
        self.conf = conf
        self.embedder = embedder or Embedder(conf)
        self.bundle = bundle or self._load_or_none(conf.paths.index_dir)

    @staticmethod
    def _load_or_none(index_dir: pathlib.Path) -> faiss_index.IndexBundle | None:
        try:
            return faiss_index.load(index_dir)
        except FileNotFoundError:
            return None

    @property
    def ready(self) -> bool:
        return self.bundle is not None and self.bundle.ntotal > 0

    def search(self, query: str, top_k: int | None = None) -> list[tuple[str, float]]:
        """返回按分数降序的 [(chunk_id, score)]；索引为空返回 []。"""
        if not self.ready:
            return []
        k = top_k or self.conf.retrieval.top_k
        vector = self.embedder.encode([query])[0]
        vector = np.asarray(vector, dtype="float32")
        return self.bundle.search(vector, k)
