"""Streamlit 单页：输入 query，看两路召回、rerank 前后、命中 chunk 与指标。

只做展示，不参与评测也不写 trace——检索链路、指标口径与 `eval` 完全同一套代码
（`DenseRetriever` / `bm25_index` / `hybrid.fuse` / `Reranker`），页面上看到的分数
就是接口与评测里用的分数。

启动（项目根目录下，先设环境变量）：
    set RAG_DB_PATH=data\\rag.db
    set HF_HOME=.cache/models
    .venv\\Scripts\\python.exe -m streamlit run app.py
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.config import ConfigError, load  # noqa: E402
from src.index import bm25_index  # noqa: E402
from src.retrieve.dense import DenseRetriever  # noqa: E402
from src.retrieve.hybrid import fuse  # noqa: E402
from src.retrieve.rerank import Reranker  # noqa: E402
from src.store.db import connect  # noqa: E402
from src.ui import view  # noqa: E402

RERANK_NOTE = "rerank 在 CPU 上单条约 5 秒（v0.3 延迟基线），默认关闭"


@st.cache_resource(show_spinner=False)
def load_stack():
    """配置与索引只加载一次；索引缺失时返回 None，由页面提示先建索引。"""
    conf = load()
    index_dir = conf.paths.index_dir
    if not (index_dir / "faiss.idx").is_file():
        return conf, None, None
    dense = DenseRetriever(conf)
    try:
        bundle = bm25_index.load(index_dir)
    except FileNotFoundError:
        bundle = None
    return conf, dense, bundle


@st.cache_data(show_spinner=False)
def load_chunks(db_path: str, _stamp: float) -> dict[str, dict]:
    """chunk 元数据（含正文前段，用于页面摘要）；`_stamp` 用数据库 mtime 触发失效。"""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT c.chunk_id, c.doc_id, c.article_no, c.heading_path, c.char_start, c.char_end,"
            " c.n_chars, c.text, d.title FROM chunks c JOIN documents d ON d.doc_id = c.doc_id"
        ).fetchall()
    finally:
        conn.close()
    return {row["chunk_id"]: dict(row) for row in rows}


@st.cache_resource(show_spinner="加载重排模型…")
def load_reranker():
    return Reranker(load())


def show_metrics(conf) -> None:
    baseline = view.baseline_metrics(PROJECT_ROOT / "evals" / "baseline.json")
    if baseline is None:
        st.info("没有找到 `evals/baseline.json`，跳过指标区")
        return
    latest = view.latest_attempt(conf.paths.runs_dir, baseline["run_id"])
    st.subheader("指标")
    if latest is None:
        st.caption("基准 `%s`：尚未在本机跑过评测，只显示基准值" % baseline["run_id"])
    else:
        st.caption(
            "基准 `%s` ／ 本次本机 attempt-%d（%d 条用例）"
            % (baseline["run_id"], latest["attempt"], latest.get("case_count", 0))
        )

    names = ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "hitrate@5")
    current = (latest or {}).get("metrics", {})
    columns = st.columns(len(names))
    for column, name in zip(columns, names):
        base_value = baseline["metrics"][name]
        if name in current:
            delta = view.metric_delta(current[name], base_value)
            column.metric(name, "%.4f" % current[name], delta="%+.4f" % delta)
        else:
            column.metric(name, "%.4f" % base_value)
    if latest is None:
        st.caption("基准值与 `evals/baseline.json` 同源；跑一次 `python -m src.cli.eval` 后这里会出现本机实测与差值")


def main() -> None:
    st.set_page_config(page_title="法规检索 · 单页回放", layout="wide")
    st.title("法规检索 · 单页回放")
    st.caption("展示两路召回、RRF 融合与 rerank 前后的名次变化；分数与 `eval` / `/search` 同源，不做二次加工。")

    try:
        conf, dense, bundle = load_stack()
    except ConfigError as exc:
        st.error("配置错误：%s" % exc)
        st.stop()

    with st.sidebar:
        st.header("查询")
        query = st.text_input("问题", placeholder="例如：发明专利权的期限是几年")
        top_k = st.slider("最终返回条数 top_k", 1, 10, 5)
        candidate_n = st.slider("每路候选数与展示行数", 5, 30, 15)
        want_rerank = st.checkbox("显示 rerank 前后对比", value=False, help=RERANK_NOTE)
        rerank_timeout = st.number_input(
            "重排超时（毫秒）",
            min_value=500,
            max_value=60000,
            value=int(conf.retrieval.rerank_timeout_ms),
            step=500,
            help="默认取 config 的 rerank_timeout_ms（3000）。CPU 上单条实测 p50 约 5.3 秒，"
            "按默认值多半会回退到融合序；想看清重排效果可调到 15000 以上。",
        )
        submitted = st.button("检索", type="primary")
        st.divider()
        st.caption("数据库：`%s`" % conf.db_path_env)
        st.caption("索引：`%s`" % conf.paths.index_dir)

    show_metrics(conf)
    st.divider()

    if dense is None:
        st.warning("索引未建立或为空。先执行：\n\n```\npython -m src.cli.ingest --source full\npython -m src.cli.build_index\npython -m src.index.bm25_index\n```")
        return
    if not submitted or not query.strip():
        st.info("在左侧输入问题后点「检索」")
        return

    try:
        db_path = conf.require_db_path()
    except ConfigError as exc:
        st.error("配置错误：%s" % exc)
        return
    chunks = load_chunks(str(db_path), db_path.stat().st_mtime)

    dense_hits = dense.search(query, candidate_n)
    bm25_hits = bundle.search(query, candidate_n) if bundle is not None else []
    rankings = [[chunk_id for chunk_id, _ in dense_hits]]
    if bm25_hits:
        rankings.append([chunk_id for chunk_id, _ in bm25_hits])
    fused_all = fuse(rankings, conf.retrieval.rrf_k, candidate_n)

    st.subheader("两路召回与融合")
    st.caption(
        "向量路 %d 条、BM25 路 %d 条；RRF k=%d。两路分数不同量纲（余弦 / BM25），只并排看，不互相换算。"
        % (len(dense_hits), len(bm25_hits), conf.retrieval.rrf_k)
    )
    st.dataframe(
        view.route_rows(dense_hits, bm25_hits, fused_all, chunks, limit=candidate_n),
        width="stretch",
        hide_index=True,
    )

    final_hits = fused_all[:top_k]
    flags: list[str] = []
    if want_rerank:
        reranker = load_reranker()
        texts = {chunk_id: chunks.get(chunk_id, {}).get("text", "") for chunk_id, _ in fused_all}
        result = reranker.rerank(
            query,
            fused_all,
            texts,
            top_k=top_k,
            top_n=conf.retrieval.rerank_top_n,
            timeout_ms=int(rerank_timeout),
        )
        flags.extend(result.flags)
        st.subheader("rerank 前后（%s）" % ("已完成" if result.scored else "回退到融合序"))
        st.caption(
            "候选 %d 条、耗时 %.0f ms；rerank 分与融合分不可比，不看数值只看名次移动。"
            % (result.candidates, result.elapsed_ms)
        )
        st.dataframe(
            view.rerank_rows(final_hits, result.hits, chunks, limit=top_k),
            width="stretch",
            hide_index=True,
        )
        if result.scored:
            final_hits = result.hits

    st.subheader("最终 top-%d" % len(final_hits))
    st.dataframe(view.hit_rows(final_hits, chunks, limit=top_k), width="stretch", hide_index=True)
    note = view.flags_note(flags)
    if note:
        st.warning(note)


main()
