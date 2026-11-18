# 状态与数据流

## 1. 记忆策略

**v1 不存会话记忆，无失效策略**（D-002 / P1#9）。

- `f(query, config, 索引)` 为纯函数：同一输入恒得同一输出（REQ-021）。
- 系统里存在的三类「历史」都不参与下一次决策：`data/trace.jsonl`（只读分析）、`runs` 表（实验记录）、`data/index/`（索引产物，命中即返回同一结果）。
- 跨会话记忆与多轮问答属 v2，见 §6。

## 2. 单次查询状态机

```mermaid
stateDiagram-v2
    [*] --> VALIDATE
    VALIDATE --> RETRIEVE_DENSE: 参数合法
    VALIDATE --> [*]: INVALID_REQUEST
    RETRIEVE_DENSE --> FUSE: 正常
    RETRIEVE_DENSE --> RETRIEVE_BM25: 索引异常（v0.4）
    RETRIEVE_BM25 --> RESPOND: 标记 FALLBACK_BM25
    FUSE --> RERANK: 启用 rerank（v0.3）
    FUSE --> RESPOND: 未启用
    RERANK --> RESPOND: 正常
    RERANK --> RESPOND: 超时，标记 FALLBACK_RERANK_TIMEOUT
    RESPOND --> [*]: 写 trace + 返回
```

状态转移全在代码中固定，无模型决策。每一步的失败处理见 `11-errors.md`。

## 3. 阶段数据契约

| 阶段 | 输入 | 输出 | 持久化 | 版本 |
| --- | --- | --- | --- | --- |
| VALIDATE | 请求参数 | 校验后参数 | 无 | v0.1 |
| PARSE | DOCX 路径 | 基准文本、段落序列、元数据 | `documents` | v0.1 |
| SPLIT | 基准文本 + 段落序列 | chunk 列表（含偏移） | `chunks` | v0.1 |
| EMBED | chunk 文本 | 归一化向量 | `data/index/faiss.idx` | v0.1 |
| RETRIEVE_DENSE | query 向量 | `[(chunk_id, score)]` | 无（进 trace） | v0.1 |
| RETRIEVE_BM25 | 分词后 query | `[(chunk_id, score)]` | 无（进 trace） | v0.2 |
| FUSE | 两路排名 | 融合排序 | 无（进 trace） | v0.2 |
| RERANK | 融合后 top-N | 重排结果 | 无（进 trace） | v0.3 |
| RESPOND | 排序结果 | 响应体 | `data/runs/<run_id>/` | v0.1 |
| EVAL | 评测集 + 检索结果 | 指标 | `metrics.json` + `runs` | v0.1 |

## 4. trace 字段

每行一条 JSON（`data/trace.jsonl`），字段固定，只增不改：

| 字段 | 类型 | 说明 | 版本 |
| --- | --- | --- | --- |
| `run_id` | str | 本次运行标识 | v0.2 |
| `case_id` | str \| null | 评测用例编号；手工查询为 null | v0.2 |
| `query_raw` | str | 原始查询 | v0.2 |
| `query_norm` | str | 归一化后查询 | v0.3 |
| `dense` | list | `[{chunk_id, score, rank}]`，前 top-N | v0.2 |
| `bm25` | list | 同上 | v0.2 |
| `fused` | list | 融合后顺序 | v0.2 |
| `reranked` | list | 重排后顺序 | v0.3 |
| `hit_chunk_id` | str \| null | 命中的 gold 所在 chunk | v0.2 |
| `hit_rank` | int \| null | 命中排名，未命中为 null | v0.2 |
| `excerpt` | str | 命中 chunk 前 80 码点（D-009） | v0.2 |
| `latency_ms` | dict | 各阶段耗时；落表时序列化为 `traces.latency_json` | v0.2 |
| `flags` | list | `FALLBACK_*` / `FILTER_RELAXED` | v0.4 |

**不写入**：完整原文、密钥、绝对路径中的用户目录、模型权重路径。

### 4.1 trace 的读取路径

| 用途 | 读什么 | 说明 |
| --- | --- | --- |
| 明细分析、失败案例归类 | `data/trace.jsonl`（**权威**） | `eval.py` 与失败案例归因直接读 JSONL，按 `run_id` 过滤，不经 SQLite |
| SQL 聚合、`/trace` 摘要 | `traces` 表（派生） | 由 `cli/import_traces.py` 从 JSONL 导入，记 `source_run_id` 与 `imported_at`；只存摘要字段 |
| 复现比对 | `data/runs/<run_id>/attempt-N/metrics.json` | 与 trace 无关，避免把日志当结果 |

写入方式：追加写，一行一条 JSON，字段只增不改。默认单进程写（CLI 单进程）；若并发写，用标准库平台文件锁（POSIX `fcntl.flock` / Windows `msvcrt.locking`）包住整行写入，**不新增依赖**。JSONL 与 `traces` 表允许短暂不一致，导入命令幂等重跑即可对齐。

## 5. 中断与恢复

| 场景 | 行为 |
| --- | --- |
| ingest 中途失败 | 单事务回滚，不留半批数据；失败条目写 `ingest_log`（v0.4） |
| 索引文件缺失但 DB 有 chunk | 报 `INDEX_EMPTY`，提示重建；不自动重建（避免误覆盖） |
| eval 中途中断 | 该 attempt 目录缺少 `metrics.json` 即为无效运行；`runs.metrics_json` 不更新 |
| 同一 `run_id` 重跑 | **不覆盖旧结果**：新开 `data/runs/<run_id>/attempt-N/`，`runs.metrics_json` 记最后一次 attempt；其余行幂等（REQ-048） |
| 复现验证 | 同 `run_id` 连跑两次 → `attempt-1/` 与 `attempt-2/`，逐字节 diff 两份 `metrics.json`；`run_id` 不变 |
| 需要并列保留多份结果 | 人工给 `run_id` 加 `-2`、`-3` 后缀；该后缀不参与复现判定 |
| 模型权重缺失 | 首次加载自动下载到 `HF_HOME`；离线环境报明确错误，不静默降级 |

## 6. v2 记忆隔离约束（规划，不可违反）

1. 记忆只作用于多轮问答层；`/search`、`/eval`、CI 回归永远无状态。
2. `run_id` 增加 `stateless_mode=true` 标记，评测时记忆模块强制关闭。
3. 最小实现：会话 id + SQLite 存 `(query, top_k, 选中 chunk)` + 规则式指代替换，0 次 API。
4. 评测重建：样本从「单条 query + gold 锚点」变为「对话串 + 每轮锚点」，按会话切分 holdout。
5. 新增记忆属架构与能力边界变更，走变更单、更新本文件、重新过 G2。
