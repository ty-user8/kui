"""冒烟：在现有库上把「增量入库 → 索引一致性 → 评测 → 接口装配」跑一遍。

设计目标是**可重复执行**：完整入库走增量路径，第二次跑应当是「待写入 0、行数不变」；
索引只做一致性检查（向量数 = chunk 数），不重建——重建一次要 200 秒，不适合冒烟。
接口只检查路由装配，不起服务、不占端口。

用法（项目根目录下，先设 RAG_DB_PATH 与 HF_HOME）：
    .venv\\Scripts\\python.exe scripts/smoke.py
    .venv\\Scripts\\python.exe scripts/smoke.py --source v01_subset
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.ingest import IngestAborted, run_ingest  # noqa: E402
from src.config import ConfigError, load  # noqa: E402
from src.eval import runner  # noqa: E402
from src.store.db import connect  # noqa: E402

EXPECTED_ROUTES = {"/search", "/eval", "/ingest", "/trace", "/ask"}
METRIC_KEYS = ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "hitrate@5")


def counts(db_path: pathlib.Path) -> tuple[int, int]:
    conn = connect(db_path)
    try:
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    return int(documents), int(chunks)


def index_vectors(index_dir: pathlib.Path) -> tuple[int, int]:
    faiss_meta = index_dir / "index-meta.json"
    bm25_meta = index_dir / "bm25-meta.json"
    vectors = json.loads(faiss_meta.read_text(encoding="utf-8"))["vectors"] if faiss_meta.is_file() else 0
    bm25 = json.loads(bm25_meta.read_text(encoding="utf-8")).get("vectors", 0) if bm25_meta.is_file() else 0
    return int(vectors), int(bm25)


def main() -> int:
    parser = argparse.ArgumentParser(description="冒烟：入库 → 索引一致性 → 评测 → 接口装配")
    parser.add_argument("--source", choices=("v01_subset", "full"), default="full")
    parser.add_argument("--skip-eval", action="store_true", help="跳过评测（只查入库与索引）")
    args = parser.parse_args()

    problems: list[str] = []
    try:
        conf = load()
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("FAIL 配置：%s" % exc)
        return 1

    print("[1/4] 环境：db=%s、index=%s、source=%s" % (db_path, conf.paths.index_dir, args.source))
    before = counts(db_path)
    print("      入库前 documents=%d、chunks=%d" % before)

    print("[2/4] 增量入库（重复执行应为「待写入 0」）")
    try:
        result = run_ingest(conf, source=args.source)
    except IngestAborted as exc:
        print("FAIL 入库：%s" % exc.message)
        return 1
    print(
        "      待写入 %d、内容未变 %d、重复内容 %d、失败 %d"
        % (result["inserted"], result["skipped_unchanged"], result["skipped_duplicate"], len(result["failed"]))
    )
    after = counts(db_path)
    if result["inserted"] == 0 and after != before:
        problems.append("未写入新文档但行数变化：%s → %s" % (before, after))
    if result["failed"]:
        problems.append("有 %d 篇入库失败" % len(result["failed"]))

    print("[3/4] 索引一致性：chunk 数 vs 向量数 / BM25 条数")
    vectors, bm25 = index_vectors(conf.paths.index_dir)
    print("      chunks=%d、向量=%d、BM25=%d" % (after[1], vectors, bm25))
    if vectors != after[1]:
        problems.append("向量数与 chunk 数不一致：%d vs %d" % (vectors, after[1]))
    if bm25 != after[1]:
        problems.append("BM25 条数与 chunk 数不一致：%d vs %d" % (bm25, after[1]))

    if not args.skip_eval:
        print("[4/4] 评测（dev 80 条，纯计算，不调用 LLM）")
        result_eval = runner.run_eval(conf, split="dev")
        metrics = result_eval["metrics"]
        missing = [name for name in METRIC_KEYS if name not in metrics]
        print("      用例 %d 条、unmapped %d、unconfirmed %d" % (
            result_eval["case_count"], result_eval["unmapped"], result_eval["unconfirmed"]))
        print("      " + " / ".join("%s %.4f" % (name, metrics[name]) for name in METRIC_KEYS if name in metrics))
        if missing:
            problems.append("指标缺失：%s" % ", ".join(missing))
        if result_eval["unmapped"]:
            problems.append("unmapped=%d，锚点映射失败" % result_eval["unmapped"])
    else:
        print("[4/4] 评测已跳过（--skip-eval）")

    from src.api.main import app

    paths = set(app.openapi()["paths"])
    if paths != EXPECTED_ROUTES:
        problems.append("接口路径不符：%s" % sorted(paths))

    if problems:
        print("\nFAIL 共 %d 项：" % len(problems))
        for item in problems:
            print("  - %s" % item)
        return 1
    print("\nPASS：入库增量、索引一致、评测可跑、五接口装配正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
