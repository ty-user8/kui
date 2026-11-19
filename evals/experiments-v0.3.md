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
