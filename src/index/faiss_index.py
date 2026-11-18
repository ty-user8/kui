"""FAISS 向量索引：建库、保存、加载、检索。

`IndexIDMap2(IndexFlatIP(dim))` 做精确内积检索；向量入库前已 L2 归一化，
因此内积等价余弦（REQ-017a）。FAISS 内部用递增整数 id，`ids.json` 保存
整数 id → `chunk_id` 的映射，避免把字符串塞进 FAISS。
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import faiss
import numpy as np

INDEX_FILE = "faiss.idx"
IDS_FILE = "ids.json"


@dataclass
class IndexBundle:
    index: faiss.Index
    ids: list[str]

    @property
    def ntotal(self) -> int:
        return int(self.index.ntotal)

    def search(self, query: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        """单条查询，返回 [(chunk_id, score)]，按分数降序。"""
        vector = np.asarray(query, dtype="float32")
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        scores, positions = self.index.search(vector, top_k)
        results: list[tuple[str, float]] = []
        for score, position in zip(scores[0], positions[0]):
            if position < 0:
                continue
            results.append((self.ids[int(position)], float(score)))
        return results


def build(vectors: np.ndarray, chunk_ids: list[str]) -> IndexBundle:
    if vectors.dtype != np.float32:
        vectors = vectors.astype("float32")
    if vectors.shape[0] != len(chunk_ids):
        raise ValueError("向量数 %d 与 chunk 数 %d 不一致" % (vectors.shape[0], len(chunk_ids)))
    base = faiss.IndexFlatIP(vectors.shape[1])
    index = faiss.IndexIDMap2(base)
    index.add_with_ids(vectors, np.arange(vectors.shape[0], dtype="int64"))
    return IndexBundle(index=index, ids=list(chunk_ids))


def save(bundle: IndexBundle, index_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / INDEX_FILE
    ids_path = index_dir / IDS_FILE
    faiss.write_index(bundle.index, str(index_path))
    ids_path.write_text(json.dumps(bundle.ids, ensure_ascii=False, indent=0), encoding="utf-8")
    return index_path, ids_path


def load(index_dir: pathlib.Path) -> IndexBundle:
    index_path = index_dir / INDEX_FILE
    ids_path = index_dir / IDS_FILE
    if not index_path.is_file() or not ids_path.is_file():
        raise FileNotFoundError("索引文件缺失：%s" % index_dir)
    index = faiss.read_index(str(index_path))
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    if index.ntotal != len(ids):
        raise RuntimeError("索引向量数 %d 与 id 映射数 %d 不一致" % (index.ntotal, len(ids)))
    return IndexBundle(index=index, ids=list(ids))


def size_bytes(index_dir: pathlib.Path) -> dict:
    """索引体积实测值：分文件与合计，供 CHG-006 第 30 行与 B6 表回填。"""
    detail = {}
    for name in (INDEX_FILE, IDS_FILE):
        path = index_dir / name
        detail[name] = path.stat().st_size if path.is_file() else 0
    detail["total"] = sum(detail.values())
    return detail


def meta_path(index_dir: pathlib.Path) -> pathlib.Path:
    return index_dir / "index-meta.json"


def write_meta(index_dir: pathlib.Path, payload: dict) -> pathlib.Path:
    path = meta_path(index_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
