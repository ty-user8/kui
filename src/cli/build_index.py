"""建索引入口：读 chunks → 编码 → 写 FAISS 索引与元数据。

元数据（`data/index/index-meta.json`）记录模型名、revision、权重文件 SHA-256、
向量数与索引体积，供 `runs` 表留痕与 CHG-006 的规模回填。

用法（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    .venv\\Scripts\\python.exe -m src.cli.build_index
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.index import faiss_index  # noqa: E402
from src.index.embedder import Embedder  # noqa: E402
from src.store.db import connect  # noqa: E402

NORM_TOLERANCE = 1e-6


def read_chunks(conn, doc_ids: list[str] | None = None) -> tuple[list[str], list[str], list[str]]:
    sql = "SELECT chunk_id, doc_id, text FROM chunks"
    params: tuple = ()
    if doc_ids:
        sql += " WHERE doc_id IN (%s)" % ", ".join("?" for _ in doc_ids)
        params = tuple(doc_ids)
    sql += " ORDER BY doc_id, seq"
    rows = conn.execute(sql, params).fetchall()
    return [row["chunk_id"] for row in rows], [row["doc_id"] for row in rows], [row["text"] for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 FAISS 向量索引")
    parser.add_argument("--model-dir", default=None, help="本地权重目录，默认取 $HF_HOME/<模型名>")
    args = parser.parse_args()

    try:
        conf = load()
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    conn = connect(db_path)
    try:
        chunk_ids, doc_ids, texts = read_chunks(conn)
    finally:
        conn.close()
    if not chunk_ids:
        print("库里没有 chunk，先跑 ingest")
        return 2

    started = time.time()
    embedder = Embedder(conf, pathlib.Path(args.model_dir) if args.model_dir else None)
    vectors = embedder.encode(texts)
    norm_error = embedder.max_norm_error(vectors)
    if norm_error >= NORM_TOLERANCE:
        print("归一化校验失败：范数与 1 的最大偏差 %.2e" % norm_error)
        return 3

    bundle = faiss_index.build(vectors, chunk_ids)
    index_dir = conf.paths.index_dir
    faiss_index.save(bundle, index_dir)
    sizes = faiss_index.size_bytes(index_dir)

    meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "normalizer_version": conf.run.normalizer_version,
        "chunk_size": conf.split.chunk_size,
        "overlap": conf.split.overlap,
        "documents": len(set(doc_ids)),
        "vectors": bundle.ntotal,
        "dim": int(vectors.shape[1]),
        "index_file": faiss_index.INDEX_FILE,
        "index_bytes": sizes[faiss_index.INDEX_FILE],
        "ids_bytes": sizes[faiss_index.IDS_FILE],
        "total_bytes": sizes["total"],
        **embedder.info(),
    }
    meta_file = faiss_index.write_meta(index_dir, meta)

    print("文档 %d 篇，chunk %d 个，向量 %d 条，维度 %d" % (meta["documents"], len(chunk_ids), bundle.ntotal, meta["dim"]))
    print("归一化最大偏差 %.2e（阈值 %.0e）" % (norm_error, NORM_TOLERANCE))
    print("权重 %s sha256 %s" % (meta["weights_file"], meta["weights_sha256"][:16]))
    print(
        "索引体积 %d 字节（%.1f KB）：%s %d + %s %d"
        % (sizes["total"], sizes["total"] / 1024, faiss_index.INDEX_FILE, sizes[faiss_index.INDEX_FILE],
           faiss_index.IDS_FILE, sizes[faiss_index.IDS_FILE])
    )
    print("元数据 %s，耗时 %.1f 秒" % (meta_file.relative_to(PROJECT_ROOT), time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
