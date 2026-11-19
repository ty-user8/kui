"""BM25 稀疏索引：jieba 分词 + rank_bm25.BM25Okapi，pickle 持久化。

与向量路的分数不可比（BM25 无上界、可负），只做组内排序，融合在 `retrieve/hybrid.py`
按排名做 RRF。分词只切词、不做同义扩展；标点与空白丢弃（REQ-019）。
"""

from __future__ import annotations

import json
import pathlib
import pickle
import re
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25Okapi

BM25_FILE = "bm25.pkl"
META_FILE = "bm25-meta.json"
DROP = re.compile(r"^[\s\W_]+$", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """中文按词切分，丢弃标点、空白与纯符号。"""
    return [token for token in jieba.lcut(text) if token and not DROP.match(token)]


@dataclass
class BM25Bundle:
    bm25: BM25Okapi
    chunk_ids: list[str]
    k1: float
    b: float
    tokens: list[list[str]]

    @property
    def ntotal(self) -> int:
        return len(self.chunk_ids)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """返回 [(chunk_id, score)]，按分数降序，只保留分数 > 0 的命中。"""
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = [(self.chunk_ids[i], float(scores[i])) for i in ranked[:top_k] if scores[i] > 0]
        return results


def build(texts: list[str], chunk_ids: list[str], k1: float = 1.5, b: float = 0.75) -> BM25Bundle:
    if len(texts) != len(chunk_ids):
        raise ValueError("文本数 %d 与 chunk 数 %d 不一致" % (len(texts), len(chunk_ids)))
    if not texts:
        raise ValueError("没有可索引的文本")
    corpus = [tokenize(text) for text in texts]
    if not any(corpus):
        raise ValueError("分词结果全为空，检查分词器")
    return BM25Bundle(
        bm25=BM25Okapi(corpus, k1=k1, b=b),
        chunk_ids=list(chunk_ids),
        k1=k1,
        b=b,
        tokens=corpus,
    )


def save(bundle: BM25Bundle, index_dir: pathlib.Path) -> pathlib.Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / BM25_FILE
    # 只持久化纯数据（分词结果 + 参数 + id 映射），加载时重建 BM25Okapi：
    # 直接 pickle 对象会把类路径写成 __main__（`python -m` 运行时），跨进程加载必失败。
    payload = {"tokens": bundle.tokens, "chunk_ids": bundle.chunk_ids, "k1": bundle.k1, "b": bundle.b}
    with path.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    meta = {
        "vectors": bundle.ntotal,
        "k1": bundle.k1,
        "b": bundle.b,
        "bytes": path.stat().st_size,
        "tokenizer": "jieba.lcut",
    }
    (index_dir / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load(index_dir: pathlib.Path) -> BM25Bundle:
    path = index_dir / BM25_FILE
    if not path.is_file():
        raise FileNotFoundError("BM25 索引缺失：%s" % path)
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or "tokens" not in payload:
        raise RuntimeError("BM25 索引格式不符")
    return BM25Bundle(
        bm25=BM25Okapi(payload["tokens"], k1=payload["k1"], b=payload["b"]),
        chunk_ids=list(payload["chunk_ids"]),
        k1=payload["k1"],
        b=payload["b"],
        tokens=payload["tokens"],
    )


def size_bytes(index_dir: pathlib.Path) -> dict:
    detail = {}
    for name in (BM25_FILE, META_FILE):
        path = index_dir / name
        detail[name] = path.stat().st_size if path.is_file() else 0
    detail["total"] = sum(detail.values())
    return detail


def main() -> int:
    """自检：从库里取 chunk 建 BM25，跑两条查询，打印分词与命中。"""
    import sys

    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.config import ConfigError, load
    from src.store.db import connect

    try:
        conf = load()
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY doc_id, seq").fetchall()
    finally:
        conn.close()
    ids = [row["chunk_id"] for row in rows]
    texts = [row["text"] for row in rows]

    bundle = build(texts, ids)
    path = save(bundle, conf.paths.index_dir)
    sizes = size_bytes(conf.paths.index_dir)
    print("chunk %d 条，BM25 索引 %d 字节；样例分词：%s" % (bundle.ntotal, sizes["total"], tokenize("发明专利权的期限是几年")))
    for query in ("发明专利权的期限是几年", "专利代理师执业前要实习多久"):
        hits = bundle.search(query, 3)
        print("查询 %s | 分词 %s" % (query, tokenize(query)))
        for chunk_id, score in hits:
            print("   %.3f %s" % (score, chunk_id))
        if not hits:
            print("   无命中")
    print("索引文件 %s" % path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
