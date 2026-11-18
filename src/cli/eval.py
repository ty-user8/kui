"""评测入口：算指标、定 `run_id`、按 attempt 目录落盘、写 runs 记录。

`run_id` 只由配置指纹决定（不含日期）：同配置跨天、跨次运行都得到同一个 id，
复现验证靠 `attempt-1/` 与 `attempt-2/` 两个目录比对（REQ-031／REQ-032、6.3 节）。

`metrics.json` 只放稳定的数值字段——不含时间戳、不含逐条明细，保证两次运行逐字节可比；
耗时进 `timing.json`，运行元数据进 `meta.json`。`meta.json` 额外记录本地权重指纹
`weights_sha256`（读 `data/index/index-meta.json`），用于发现「权重被换过但配置没变」。

用法（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    set HF_HOME=.cache/models
    .venv\\Scripts\\python.exe -m src.cli.eval
    .venv\\Scripts\\python.exe -m src.cli.eval --split holdout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ConfigError, load  # noqa: E402
from src.eval import runner  # noqa: E402
from src.store import dao  # noqa: E402
from src.store.db import apply_migrations, connect, transaction  # noqa: E402

METRIC_ORDER = ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "hitrate@5")
METRIC_NOTE = (
    "单 gold 口径下 Recall@k 与 HitRate@k 数值相同：一条 query 只有一个相关目标，"
    "命中即 1、否则 0，两者共用同一判定；保留两个名字是因为报告中含义不同。"
)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_run_id(conf, cases_sha: str, corpus_sha: str, doc_count: int) -> tuple[str, str, str]:
    """返回（run_id, config_hash, 规范串）。规范串字段与 6.3 节一致。"""
    cfg = (
        "seed=%d;model=%s@%s;chunk=%d/%d;topk=%d;cases=%s;corpus=%s;docs=%d;nv=%d"
        % (
            conf.run.seed,
            conf.model.embedding_name,
            conf.model.embedding_revision,
            conf.split.chunk_size,
            conf.split.overlap,
            conf.retrieval.top_k,
            cases_sha,
            corpus_sha,
            doc_count,
            conf.run.normalizer_version,
        )
    )
    config_hash = hashlib.sha256(cfg.encode("utf-8")).hexdigest()
    return "r" + config_hash[:12], config_hash, cfg


def next_attempt(run_dir: pathlib.Path) -> int:
    if not run_dir.is_dir():
        return 1
    existing = [int(p.name.split("-")[1]) for p in run_dir.glob("attempt-*") if p.name.split("-")[1].isdigit()]
    return max(existing, default=0) + 1


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="跑评测并按 attempt 落盘")
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    args = parser.parse_args()

    try:
        conf = load()
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2

    started = time.time()
    cases_sha = sha256_file(conf.eval.cases_file)
    corpus_sha = sha256_file(conf.corpus.manifest)

    conn = connect(db_path)
    try:
        apply_migrations(conn, conf.paths.migrations_dir)
        doc_count = dao.count_documents(conn)
        chunk_count = dao.count_chunks(conn)
    finally:
        conn.close()

    run_id, config_hash, cfg_string = build_run_id(conf, cases_sha, corpus_sha, doc_count)
    result = runner.run_eval(conf, split=args.split)

    run_dir = conf.paths.runs_dir / run_id
    attempt = next_attempt(run_dir)
    attempt_dir = run_dir / ("attempt-%d" % attempt)
    attempt_dir.mkdir(parents=True, exist_ok=True)

    metrics = {name: round(float(result["metrics"].get(name, 0.0)), 6) for name in METRIC_ORDER}
    metrics_payload = {
        "run_id": run_id,
        "split": result["split"],
        "top_k": result["top_k"],
        "case_count": result["case_count"],
        "unmapped": result["unmapped"],
        "unconfirmed": result["unconfirmed"],
        "overlap_cases": result["overlap_cases"],
        "metrics": metrics,
        "note": METRIC_NOTE,
    }
    write_json(attempt_dir / "metrics.json", metrics_payload)

    index_meta_file = conf.paths.index_dir / "index-meta.json"
    index_meta = json.loads(index_meta_file.read_text(encoding="utf-8")) if index_meta_file.is_file() else {}
    lock_file = PROJECT_ROOT / "requirements.lock.txt"
    deps_sha = sha256_file(lock_file) if lock_file.is_file() else ""

    meta = {
        "run_id": run_id,
        "attempt": attempt,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config_string": cfg_string,
        "config_hash": config_hash,
        "seed": conf.run.seed,
        "model_name": conf.model.embedding_name,
        "model_version": conf.model.embedding_revision,
        "chunk_size": conf.split.chunk_size,
        "overlap": conf.split.overlap,
        "top_k": conf.retrieval.top_k,
        "cases_sha256": cases_sha,
        "corpus_sha256": corpus_sha,
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "normalizer_version": conf.run.normalizer_version,
        "deps_sha256": deps_sha,
        "weights_sha256": index_meta.get("weights_sha256"),
        "weights_file": index_meta.get("weights_file"),
        "index_bytes": index_meta.get("total_bytes"),
    }
    write_json(attempt_dir / "meta.json", meta)

    timing = {
        "run_id": run_id,
        "attempt": attempt,
        "total_seconds": round(time.time() - started, 3),
        "eval_seconds": result["elapsed_seconds"],
    }
    write_json(attempt_dir / "timing.json", timing)

    conn = connect(db_path)
    try:
        with transaction(conn):
            dao.upsert_run(
                conn,
                {
                    "run_id": run_id,
                    "seed": conf.run.seed,
                    "model_name": conf.model.embedding_name,
                    "model_version": conf.model.embedding_revision,
                    "chunk_size": conf.split.chunk_size,
                    "overlap": conf.split.overlap,
                    "top_k": conf.retrieval.top_k,
                    "cases_sha256": cases_sha,
                    "corpus_sha256": corpus_sha,
                    "doc_count": doc_count,
                    "normalizer_version": conf.run.normalizer_version,
                    "config_hash": config_hash,
                    "deps_sha256": deps_sha,
                    "metrics_json": json.dumps(metrics_payload, ensure_ascii=False, sort_keys=True),
                },
            )
    finally:
        conn.close()

    print("run_id %s | attempt %d | split %s | 用例 %d 条（unmapped %d、unconfirmed %d）"
          % (run_id, attempt, result["split"], result["case_count"], result["unmapped"], result["unconfirmed"]))
    for name in METRIC_ORDER:
        print("  %-10s %.4f" % (name, metrics[name]))
    print("产物 %s" % attempt_dir.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
