# 接口约定

v0.4 起提供 4 个 HTTP 接口，v0.5 追加 `/ask`。全部 JSON 进出，字段与 `06-schemas/` 对应；契约文件为同目录 `openapi.yaml`。

## 1. 接口一览

| 方法 | 路径 | 作用 | 版本 | 幂等 |
| --- | --- | --- | --- | --- |
| POST | `/search` | 检索 top-k，返回锚点与分数 | v0.4 | 是（同 query 同 `run_id` 结果恒定，REQ-021） |
| POST | `/eval` | 跑评测集，返回指标 | v0.4 | 是（不写入新 `run_id` 时复用） |
| POST | `/ingest` | 入库文档集，返回条目级结果 | v0.4 | 是（REQ-048） |
| GET | `/trace` | 按 `run_id`/`case_id` 取 trace 摘要 | v0.4 | 是 |
| POST | `/ask` | 检索 + 生成答案 + 引用校验 | v0.5 | 否（生成结果不保证逐字一致，不进指标） |

## 2. 请求与响应要点

### POST /search

```json
{"query": "发明专利权的期限是几年", "top_k": 5, "filters": {"category": "法律", "publish_date_from": "2020-01-01"}}
```

```json
{
  "run_id": "r20261116-3f9a1c02b7d4",
  "reason": null,
  "flags": [],
  "results": [
    {"chunk_id": "ff808081752b7d430175e4651cbd1547:00012", "doc_id": "ff808081752b7d430175e4651cbd1547",
     "article_no": "第四十二条", "heading_path": "第五章专利权的期限、终止和无效",
     "char_start": 4210, "char_end": 4298, "score": 0.7134, "path": "dense"}
  ]
}
```

- 无结果时 `results` 为 `[]`、`reason` 为 `"NO_MATCH"`，HTTP 200（REQ-017）。
- `score` 为归一化内积（余弦）原值，区间 −1~1，不做 0~1 映射（REQ-017a）。
- `filters` 仅在 v0.4 生效；过滤后为空时按 REQ-025 放宽一次并在 `reason` 标 `FILTER_RELAXED`。
- `reason` 只报一个最需要用户知道的标记（优先级：`FILTER_RELAXED` > `NO_MATCH` > `FALLBACK_BM25`）；全部标记在 `flags` 数组里，同时原样写进 trace（`09-state.md` §4）。
- `path` 标明分数出自哪一段，`score` 只在同一响应内可比（`dense` 余弦、`fused` RRF、`rerank` 交叉编码器分）。

### POST /eval

请求 `{"split": "all" | "dev" | "holdout"}`，响应：

```json
{"run_id": "r20261116-3f9a1c02b7d4",
 "metrics": {"recall@1": 0.4, "recall@3": 0.7, "recall@5": 0.8, "mrr": 0.55, "ndcg@5": 0.62, "hitrate@5": 0.8},
 "unmapped": 0, "unconfirmed": 0, "case_count": 30}
```

- `unconfirmed` 为 `anchor_status != confirmed` 的条数，单独计数、不计入指标（REQ-033）。

### POST /ingest

请求 `{"source": "v01_subset" | "full", "doc_ids": []}`，响应：

```json
{"run_id": "r20261116-3f9a1c02b7d4", "documents": 2, "chunks": 18, "skipped": 0,
 "failed": [{"file_name": "x.docx", "reason": "PARSE_FAILED"}]}
```

- 失败率超过 10% 时返回 422 与 `PARSE_FAILURE_RATE_EXCEEDED`，`failed` 列出全部失败条目（REQ-006）。
- 同一 `run_id` 重复调用不产生重复行（REQ-048）。

### GET /trace

`?run_id=...&case_id=C001&limit=50`，返回 `{"items": [{...}]}`，`items` 字段见 `09-state.md` 的 trace 字段表。

**读取路径**：`/trace` 直接读 `data/trace.jsonl`（明细权威），按 `run_id` 与 `case_id` 过滤后按 `limit` 截断；不经 SQLite。SQLite 的 `traces` 表是派生的摘要副本（`source_run_id`、`imported_at`），只用于 SQL 聚合，不参与接口读取——避免导入时差导致「刚跑完查不到」。若 JSONL 文件不存在，返回 404 `RUN_NOT_FOUND`。

```json
{"items": [{"case_id": "C001", "query_raw": "发明专利权的期限是几年", "query_norm": null,
            "hit_chunk_id": "ff808081752b7d430175e4651cbd1547:00012", "hit_rank": 1,
            "excerpt": "发明专利权的期限为二十年，实用新型专利权的期限为十年……",
            "latency_json": "{\"dense_ms\": 3.1, \"total_ms\": 4.0}"}]}
```

### POST /ask（v0.5）

```json
{"query": "专利代理师执业前要实习多久", "top_k": 5}
```

```json
{"answer": "……", "citations": ["...:00007"], "citation_valid": true,
 "retrieval": {"run_id": "r...", "results": []}, "reason": null}
```

- 超时 30 秒返回 200 + `retrieval` 完整、`answer` 为空、`reason="ASK_TIMEOUT"`（REQ-049）。
- 引用越界时 `citation_valid=false` 并标 `CITATION_INVALID`（REQ-050），不丢弃答案。
- 检索无命中时**不调用模型**，直接 `answer=""`、`reason="NO_MATCH"`，避免模型凭空作答。
- `RAG_LLM_API_KEY` 或 `RAG_LLM_MODEL` 缺失返回 500 `CONFIG_MISSING_KEY`（REQ-052），不降级、不伪造。
- `/ask` 的检索**不写 trace**，也不进指标与 CI（REQ-051）；`model` 与 `prompt_version` 随响应返回，不进 `run_id`。

### `/ask` 的验证状态（如实记录）

`/ask` 的 200 路径**尚未用真实模型跑过**：开发机没有 `RAG_LLM_API_KEY`。已验证的是——引用校验、超时熔断、配额、缺 key 报错、无命中不调模型，以及「真实索引 + 假客户端」的响应拼装；这些都由单测与服务层覆盖。接上真 key 后需完整跑一次并补记录，才算这一条链路验证完毕。

边界不变：`/ask` 不进任何指标、不进 CI 回归，也不影响 `run_id` 与基线。

## 3. 错误码表

| 错误码 | HTTP | 触发条件 | 是否返回细节 |
| --- | --- | --- | --- |
| `INVALID_REQUEST` | 400 | 字段缺失、类型错误、`top_k` 越界（1~50） | 是，指到字段 |
| `ENTRY_UNSUPPORTED_FORMAT` | 415 | 非 `.docx` 输入（REQ-007） | 是，给出文件名 |
| `ENTRY_TOO_LARGE` | 413 | 单文件超过配置上限（REQ-008） | 是，给出字节数 |
| `ENTRY_UNSAFE_PATH` | 400 | 路径含 `..` 或为绝对路径（REQ-054） | 是 |
| `PARSE_FAILED` | 422 | 单篇解析失败或正文为空（REQ-006） | 是，条目级 |
| `PARSE_FAILURE_RATE_EXCEEDED` | 422 | 失败率 > 10% | 是，全部失败条目 |
| `INDEX_EMPTY` | 409 | 检索前索引未建立 | 是，提示先跑 ingest |
| `RUN_NOT_FOUND` | 404 | `/trace` 查不到 `run_id` | 是 |
| `CONFIG_MISSING_KEY` | 500 | 缺少 `RAG_LLM_API_KEY` 等必填变量（REQ-052） | 是，仅变量名，不含值 |
| `ASK_TIMEOUT` | 200 | `/ask` 超 30 秒熔断（REQ-049） | 是，`reason` 字段 |
| `CITATION_INVALID` | 200 | 引用 id 不在本次 top-k（REQ-050） | 是，`reason` 字段 |
| `INTERNAL_ERROR` | 500 | 未预期异常 | 否，仅返回追踪 id |

降级类标记（`FALLBACK_BM25`、`FALLBACK_RERANK_TIMEOUT`、`FILTER_RELAXED`）不是错误码，放在响应的 `reason` 字段，HTTP 仍为 200。

## 4. 契约约束

1. 响应字段只增不改：删除或改语义须走变更单并升版本。
2. `run_id` 必出现在所有响应中，便于把结果对回 `data/runs/<run_id>/`。
3. 接口层不实现业务逻辑，只做参数校验与错误码映射（见 `05-modules.md`）。
4. 无鉴权：不设 token 参数、不设用户维度（REQ-056）。
