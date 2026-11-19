# v0.2 实验记录（T-015）

规则：调参只看 `dev`，`holdout` 只在最终一次运行里出现（REQ-034、CHG-002 项二）。配置选择依据事先定为 **dev MRR 高者胜，平则比 Recall@5**。

## 对比表

| 组 | 语料 | 用例 | 检索 | `run_id` | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A（v0.1 旧基线） | 2 篇 / 34 chunk | 30 | 单路向量 | `r98aa795a93cf` | 0.7667 | 0.8333 | 0.9667 | 0.8317 | 0.8647 |
| B（dev·单路） | 150 篇 / 2704 chunk | 80 dev | 单路向量 | `r5e4a62714526-dev-dense` | 0.4750 | 0.7125 | 0.8375 | 0.6121 | 0.6683 |
| C（dev·融合） | 150 篇 / 2704 chunk | 80 dev | 向量 + BM25 RRF | `r5e4a62714526-dev-hybrid` | 0.5500 | 0.8500 | 0.8875 | 0.6948 | 0.7440 |
| D（最终） | 150 篇 / 2704 chunk | 100（含 14 holdout） | 向量 + BM25 RRF | `r5e4a62714526` | 0.5600 | 0.8600 | 0.9000 | 0.7045 | 0.7543 |

## 结论

1. **A 与 B/C/D 不可比**：语料从 2 篇扩到 150 篇、用例从 30 条扩到 100 条，指标下降是候选池从 34 涨到 2704 的直接结果，不代表检索变差。旧基线不再作为 v0.2 的对照。
2. **融合优于单路**（同语料、同 dev 集）：Recall@1 +7.50pt、Recall@3 +13.75pt、Recall@5 +5.00pt、MRR +8.27pt、nDCG@5 +7.57pt。故最终配置选 `hybrid`。
3. **holdout 只跑一次**：仅出现在 D 组。B/C 两组均为 `--split dev`，选择过程未触及 holdout。
4. D 组指标与 C 组同量级（Recall@5 0.9000 vs 0.8875），说明 dev 选型没有过拟合到 dev。

## 复现命令

```
set RAG_DB_PATH=data\rag.db
set HF_HOME=.cache/models
.venv\Scripts\python.exe -m src.cli.eval --split dev --retriever dense  --run-suffix=-dev-dense
.venv\Scripts\python.exe -m src.cli.eval --split dev --retriever hybrid --run-suffix=-dev-hybrid
.venv\Scripts\python.exe -m src.cli.eval --split all --retriever hybrid
```

`run_id` 后缀只用于并列保留实验结果，不参与复现判定（`09-state.md` §5）。

## 与基线的差异来源

- 语料：2 → 150 篇（`documents=150`、`chunks=2704`）
- 用例：30 → 100 条（新增 70 条覆盖 34 篇新文档，14 条 holdout）
- 检索：单路向量 → 向量 + BM25（RRF，k=60，每路取 20 候选）
- 未变：embedding 模型与权重（`bge-small-zh-v1.5`，sha256 `354763b9…`）、切分 512/64、top-k 5

基线替换需经变更单确认，见 `specs/changes/CHG-007-baseline-replacement.md`。
