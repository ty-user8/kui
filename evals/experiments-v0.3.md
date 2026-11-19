# v0.3 实验记录

## T-018 标题路径注入前后对比

条件：150 篇 / 2704 chunk，`dev` 80 条，单路向量（隔离融合的影响）；两组仅索引文本不同。

| 组 | 索引文本 | `run_id` | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A 不注入 | chunk 原文 | `r6c23283f2577-dev-nohead` | 0.4750 | 0.7125 | 0.8375 | 0.6121 | 0.6683 |
| B 注入标题 | 标题路径 + 换行 + 原文 | `r6c23283f2577-dev-head` | 0.4375 | 0.7750 | 0.8250 | 0.5958 | 0.6540 |

差值（B − A）：Recall@1 −3.75pt、Recall@3 **+6.25pt**、Recall@5 −1.25pt、MRR −1.63pt、nDCG@5 −1.43pt。

结论：除 Recall@3 上升外，其余四项均下降，**不启用**标题注入。可能原因：2704 条中有 255 条在注入后触发模型 512-token 截断，正文尾部被切掉；标题里的「第X章」「第X节」对语义贡献有限，却占用了窗口。

路径截断（>60 字）0 条，说明截断策略本身没有浪费：问题在 token 截断，而非路径长度。

复现：
```
set RAG_DB_PATH=data\rag.db
set HF_HOME=.cache/models
.venv\Scripts\python.exe -m src.cli.build_index --inject-heading --out data/index-head
.venv\Scripts\python.exe -m src.cli.eval --split dev --retriever dense --index-dir data/index --run-suffix=-dev-nohead
.venv\Scripts\python.exe -m src.cli.eval --split dev --retriever dense --index-dir data/index-head --run-suffix=-dev-head
```

## T-019 覆盖率曲线（定 rerank 候选数）

条件：150 篇 / 2704 chunk，`dev` 80 条，融合检索取 top-50，统计 Recall@N。

| N | Recall@N | 增量 |
| --- | --- | --- |
| 5 | 0.8375 | — |
| 10 | 0.9250 | +8.75pt（+7 条） |
| 15 | 0.9500 | +2.50pt（+2 条） |
| 20 | **0.9625** | +1.25pt（+1 条） |
| 25 | 0.9625 | 0 |
| 30 | 0.9625 | 0 |
| 40 | 0.9625 | 0 |
| 50 | 0.9625 | 0 |

结论：**N = 20** —— 第一个达到 Recall 上限（0.9625）的点，之后再扩候选零增益。与 `config.yaml` 里的 `rerank_top_n: 20` 一致，无需改配置；该值现在有实测依据，不是拍脑袋定的。

## T-019 查询归一化

| 写法 | 归一后 |
| --- | --- |
| `发明专利权的期限是几年` | 同左 |
| `发明专利权 的 期限是几年` | `发明专利权的期限是几年` |
| `发明专利权　的　期限是几年`（全角空格） | `发明专利权的期限是几年` |
| `ＡＢＣ　１２３` | `ABC 123` |

中文词间空白属分词留白，直接删除；中英文之间的空格保留。繁转简需 OpenCC 词典，当前 venv 未装，该步跳过并置 `t2s=False`，不静默乱转。

## T-019 rerank 前后对比（真实模型）

模型：`BAAI/bge-reranker-base`，权重 1,112,206,140 字节（safetensors）+ tokenizer 文件，落 `.cache/models/bge-reranker-base/`；加载 1.1 s（`HF_HUB_OFFLINE=1`，CPU）。
条件：`dev` 80 条，融合检索 + 候选 N=20。

| 组 | `run_id` | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- |
| A 融合，无 rerank | `r6c23283f2577-dev-hybrid` | 0.5500 | 0.8500 | 0.8875 | 0.6948 | 0.7440 |
| B 融合 + rerank | `r6c23283f2577-dev-rerank` | **0.5625** | 0.8500 | 0.8875 | **0.6990** | **0.7470** |

差值（B − A）：Recall@1 +1.25pt、MRR +0.42pt、nDCG@5 +0.30pt，Recall@3/@5 持平。

判读：提升幅度小，**不足以据此宣称改进**——按 REQ-035 需 bootstrap 区间且不得在有重叠时声明提升（T-020 处理）。当前 `use_rerank` 保持 `false`。

原因假设：候选 N=20 已被融合排得较准，可改判的空间本来就小；此外 chunk 是 512 字固定窗口，一个 chunk 混装 2~4 条，rerank 读到的文本里包含大量与 query 无关的条款，削弱了它对目标条的判断力。

## T-020 bootstrap 区间与延迟基线

配对重采样 1000 轮、α=0.05、seed=20261116，对 `dev` 80 条同一批 query 做 A/B 配对。

| 指标 | 基线（无 rerank） | 候选（+rerank） | 差值 | 95% 区间 | 判定 |
| --- | --- | --- | --- | --- | --- |
| Recall@1 | 0.4750 | 0.4875 | +0.0125 | [+0.0000, +0.0375] | overlap |
| Recall@5 | 0.8375 | 0.8375 | 0.0000 | [+0.0000, +0.0000] | overlap |
| MRR | 0.6121 | 0.6173 | +0.0052 | [−0.0031, +0.0187] | overlap |

**结论：三项区间全部与 0 重叠，不得声明提升，`use_rerank` 保持 `false`。** Recall@1 的下界恰好落在 0.0000，按「区间整体在 0 之上才算提升」的口径判为 overlap，不做四舍五入式的宽松解读。

### 延迟基线（REQ-040）

| 阶段 | p50 | p95 |
| --- | --- | --- |
| 检索（融合 + 重排，单条） | **5,288.8 ms** | 7,385.7 ms |

**关键发现**：重排单条 p50 约 5.3 s，已超过 `rerank_timeout_ms` 的 3000 ms。也就是说在默认超时下，CPU 上跑重排大部分请求会走 `FALLBACK_RERANK_TIMEOUT` 降级路径回退到融合序——T-019 观察到的 +1.25pt 是在「部分降级」条件下取得的，既不能当作完整重排效果，也不能据此启用。

若将来要真正评估重排，需要先解决延迟（换 GPU、缩候选文本、或改用更小的重排模型），并单独出变更单调整 `rerank_timeout_ms`。当前不改配置。
