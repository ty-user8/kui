# 错误与降级

原则：**不静默兜底**。能降级就降级并标记，不能降级就报错并说清原因；任何情况下不返回伪造结果。

## 1. 错误矩阵

| 错误类型 | 检测方式 | 处理策略 | 告知用户 | 错误码 |
| --- | --- | --- | --- | --- |
| 输入格式不支持 | 扩展名白名单 | 拒收，跳过该条 | 是 | `ENTRY_UNSUPPORTED_FORMAT` |
| 请求参数不合法 | 字段缺失、类型错误、`top_k` 越界（1~50） | 拒收，指到字段 | 是 | `INVALID_REQUEST` |
| 输入超大 | 文件字节数 / 解压后正文字节数 | 拒收该条 | 是 | `ENTRY_TOO_LARGE` |
| 路径不安全 | 含 `..`、绝对路径、符号链接 | 拒收 | 是 | `ENTRY_UNSAFE_PATH` |
| DOCX 损坏 / 空正文 | 解析异常、基准文本长度为 0 | 记录该条，继续；累计失败率 | 是，条目级 | `PARSE_FAILED` |
| 失败率超限 | 失败数 / 总数 > 10% | 中止整批 ingest，事务回滚 | 是，列全部失败条目 | `PARSE_FAILURE_RATE_EXCEEDED` |
| 索引未建立 | 索引文件缺失或空 | 拒绝检索 | 是，提示先 ingest | `INDEX_EMPTY` |
| `run_id` 查不到 | `runs` 表或 trace 文件无对应记录 | 返回不存在 | 是 | `RUN_NOT_FOUND` |
| 向量检索异常 | FAISS 调用异常（v0.4） | 退回 BM25，`reason=FALLBACK_BM25` | 是，标记降级 | 200 + reason |
| rerank 超时 | 超过 `retrieval.rerank_timeout_ms`（默认 3000） | 返回融合排序，`reason=FALLBACK_RERANK_TIMEOUT` | 是，标记降级 | 200 + reason |
| 过滤后 0 结果 | 过滤后 `len(results)==0` | 放宽过滤重试一次，`reason=FILTER_RELAXED` | 是，标记 | 200 + reason |
| 检索无结果 | top-k 为空 | 返回空数组，`reason=NO_MATCH` | 是 | 200 |
| 锚点无法映射 | gold 区间映射不到任何 chunk | 计 miss，累加 `unmapped`，不跳过 | 是，指标输出含 `unmapped` | — |
| 资源配置缺失 | 环境变量缺失 | 启动或调用时报错 | 是，只给变量名 | `CONFIG_MISSING_KEY` |
| 模型权重下载失败 | 加载异常 | 报错并给出缓存目录与离线提示 | 是 | `INTERNAL_ERROR` |
| `/ask` 超时 | 30 秒熔断 | 返回检索结果，`reason=ASK_TIMEOUT` | 是 | 200 + reason |
| 引用越界 | 输出引用 id 不在 top-k | `citation_valid=false`，`reason=CITATION_INVALID`，保留答案 | 是 | 200 + reason |
| Schema 校验失败 | 响应/DB 行不符合定义 | 报错，不写入 | 是 | `INTERNAL_ERROR` |
| 未预期异常 | 捕获兜底 | 记本地栈 + 追踪 id | 是，仅追踪 id | `INTERNAL_ERROR` |

## 2. 重试策略

| 场景 | 重试 | 说明 |
| --- | --- | --- |
| 网络类（模型下载） | 1 次，间隔 2 秒 | 仍失败则报错，不无限重试 |
| 解析类 | 不重试 | 同一文件同一解析器结果确定，重试无意义 |
| LLM 调用（v0.5） | **不重试** | 熔断优先，重试会放大配额消耗；超时即降级返回检索结果 |
| 数据库写入 | 不重试 | 事务失败即回滚并报错，避免半批数据 |

## 3. 降级顺序

```
向量 + BM25 + rerank（v0.3 最优）
  ↓ 向量异常
BM25 only（FALLBACK_BM25）
  ↓ BM25 也不可用（v0.4 才可能）
报 INDEX_EMPTY，不返回任何结果
```

降级必须写进 trace 的 `flags` 字段，指标统计时按 flag 分组，避免把降级结果与正常结果混在一起比较。

## 4. 不可降级项

| 项 | 原因 |
| --- | --- |
| 锚点映射失败 | 影响指标含义，必须显式计数（`unmapped`） |
| 评测集锚点未确认 | 未确认锚点不得计入指标，宁可少算（`unconfirmed` > 0 时报警） |
| `run_id` 生成失败 | 没有 `run_id` 的数字不可复现，直接失败 |
| 事务写入失败 | 半批数据会让索引与 DB 不一致，必须回滚 |

## 5. 错误与验收条款对应

| 条款 | 覆盖的错误 |
| --- | --- |
| REQ-006 | `PARSE_FAILED`、`PARSE_FAILURE_RATE_EXCEEDED` |
| REQ-007 / REQ-008 / REQ-054 | 格式、大小、路径三类校验 |
| REQ-023 / REQ-024 / REQ-025 | 三条降级路径 |
| REQ-030 | `unmapped` 显式计数 |
| REQ-046 | 结构化错误码，不裸 500 |
| REQ-049 / REQ-050 / REQ-052 | `/ask` 超时、引用越界、缺密钥 |
