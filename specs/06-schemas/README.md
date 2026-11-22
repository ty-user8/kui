# 数据结构

## 1. 存储清单

| 载体 | 内容 | 版本 |
| --- | --- | --- |
| `data/rag.db`（SQLite） | `documents`、`chunks`、`eval_cases`、`runs` | v0.1 |
| 同上 | `parents` | v0.3 |
| 同上 | `traces`、`ingest_log` | v0.4 |
| 同上 | `agent_sessions`、`agent_turns`（问答会话与轮次） | v2（`CHG-013`，2026-11-22） |
| `data/index/faiss.idx` + `faiss.ids.json` | 向量索引与 id 映射 | v0.1 |
| `data/index/bm25.pkl` | 稀疏索引 | v0.2 |
| `data/trace.jsonl` | trace 明细的**唯一权威**（追加写） | v0.2 |
| `data/runs/<run_id>/attempt-N/` | `metrics.json`、`timing.json`、`meta.json`；每次运行一个 attempt 目录 | v0.1 |

DDL 全部在 `migrations/`，按编号顺序执行；当前全量 = `0001_init.sql` → `0002_parents.sql` → `0003_runtime.sql` → `0004_agent.sql`（v2，2026-11-22，依据 `CHG-013` §8.2；只新增两张表与一个索引，`0001`~`0003` 未改）。

## 2. 建表要点

| 表 | 关键约束 | 说明 |
| --- | --- | --- |
| `documents` | `doc_id` UNIQUE | 同名不同版本靠 `doc_id` 区分（D-017），不按标题去重 |
| `documents` | `text_sha256` NOT NULL | 基准文本指纹，判内容是否变化（5.3.4） |
| `documents` | `normalizer_version`、`index_text_sha256` | 索引侧变换留痕；后者为空表示零变换 |
| `documents` | `chars_total`、`excluded_chars` | 表格排除的守恒校验；**以 CHG-002 项五批准为生效前提**，未批准前实现不得写入非 0 值 |
| `chunks` | `chunk_id` UNIQUE、`UNIQUE(doc_id, seq)` | 切分策略变更后 `seq` 会重排，故锚点不存 `chunk_id`（B1） |
| `chunks` | `CHECK (char_end > char_start)` | 偏移左闭右开且非空 |
| `chunks` | `source_format` CHECK | v1 只允许 `docx`，`pdf` 为预留值（REQ-009） |
| `chunks` | `parent_id` 可空 | v0.3 起填；v0.1~v0.2 为 NULL |
| `eval_cases` | `anchor_status` CHECK | 只有 `confirmed` 计入指标（REQ-033） |
| `eval_cases` | `split` CHECK | `dev` / `holdout`，holdout 调参期不读 |
| `runs` | `run_id` 主键 | 一次实验一行；`metrics_json` 为快照，便于跨版本对比 |
| `traces` | 无外键到 `runs` | 由 JSONL 导入，允许先有 trace 后有 run 记录补写；`source_run_id` 记录来源，`imported_at` 记录导入时间；只存摘要字段，`dense`／`bm25`／`fused`／`reranked` 明细只留在 JSONL |
| `agent_sessions` | `session_id` 主键；`stateless_mode` CHECK（0/1） | v2 起：一次问答会话一行，`turn_count` 记累计轮数。会话过期按 `session_ttl_hours` **读时判定**，不设后台清理任务（D2）；`stateless_mode` 恒写 1，评测路径不经此表 |
| `agent_turns` | `UNIQUE(session_id, turn_no)`；外键 `ON DELETE CASCADE` | v2 起：一轮问答一行；同一 `(session_id, turn_no)` 重写即覆盖，不插重复行。`query_raw` 与 `query_rewritten` 都存，`rewrite_rule` 记规则名（`pronoun_carryover`／`ellipsis_append`／`date_inherit`／`none`）；`tool_calls_json` **只存摘要**（工具名、参数、是否成功、条数、top-1 `chunk_id`），不复制正文 |
| `agent_*` | 与 `documents`／`chunks`／`runs`／`traces` 无外键 | v2 起：会话数据独立存储；`/search`、`/eval`、`scripts/ci_check.py` 与 CI 均不读这两张表，问答调用不写 `traces`／`runs`／`metrics.json` |

## 3. `run_id` 生成规则

```
cfg = "seed={seed};model={model_name}@{model_version};chunk={chunk_size}/{overlap};topk={top_k};"
      "cases={cases_sha256};corpus={corpus_sha256};docs={doc_count};nv={normalizer_version}"
config_hash = sha256(cfg).hexdigest()
run_id      = "r" + config_hash[:12]
```

- **只由配置指纹决定，不含日期**。同一配置跨天运行得到同一 `run_id`；跨天差异只体现在 `runs.created_at` 与产物目录的写入时间，不出现在 id 里。
- **`run_id` 是哈希，不可反解**。要取五项明细查 `runs` 表的 `seed`／`model_name`＋`model_version`／`chunk_size`＋`overlap`／`top_k`／`cases_sha256` 等列；REQ-031 的验证方式据此为「可反查」。
- `cases_sha256`：`evals/cases.csv` 的 SHA-256（含未确认行，保证换集必换 id）。
- `corpus_sha256`：`corpus/metadata/manifest.json` 的 SHA-256（D-012）。
- `nv`：`normalizer_version`，进指纹而非只记 `documents`（5.3.2）。
- **复现验证**：同一 `run_id` 连跑两次，分别写 `data/runs/<run_id>/attempt-1/` 与 `attempt-2/`，逐字节 diff 两份 `metrics.json`；`run_id` 不变。`-2`／`-3` 后缀**只用于人工并列保留多份结果**，不用于复现验证——复现永远走 attempt 目录。
- **`deps_sha256`**：`requirements.lock.txt` 的内容哈希，作为 `runs` 表的同级字段与 `config_hash` 并列记录。不进 `config_hash`：锁是内容哈希，与配置指纹分开才能独立比对「环境变了」还是「配置变了」。Verify 时逐条比对。

## 4. 示例数据生成规则

| 字段 | 格式 | 取值范围 | 去重与约束 |
| --- | --- | --- | --- |
| `doc_id` | 官方 32 位十六进制；本地样例用 `demo-` + 4 位数字 | `demo-0001` ~ `demo-9999` | 全局唯一（UNIQUE） |
| `chunk_id` | `{doc_id}:{seq:05d}` | `seq` 0~99999 | `UNIQUE(doc_id, seq)` 保证唯一 |
| `parent_id` | `{doc_id}:P{seq:05d}` | `seq` 0~99999 | 主键唯一 |
| `case_id` | `C` + 3 位数字 | `C001` ~ `C999` | 主键；删除后编号不复用 |
| `run_id` | `r` + 12 位十六进制（`config_hash` 前 12 位） | 固定 13 字符 | 主键；同配置恒同 id。并列保留多份结果时人工追加 `-2`、`-3`（不参与复现判定） |
| `trace_id` | 自增整数 | — | 主键 |
| `excerpt` | 命中正文前 80 个码点 | 0~80 字符 | 不切半个码位；不含元数据 |

## 5. 结构变更规则

1. 新增结构一律新建 `migrations/000N_xxx.sql`，**不修改已发布的脚本**。v0.1 实现前三个脚本尚未发布，允许整体改写并同步本文件（CHG-003 即按此处理）；首个版本发布后该例外关闭。
2. 每个脚本末尾写入 `schema_migrations` 一行，便于启动时校验版本。
3. 涉及字段语义变化（如 `char_start` 基准）必须走变更单，并在脚本头注明变更单编号。
4. 迁移脚本随版本提交，`data/rag.db` 不入库。

## 6. 与规格的对应

| 表/字段 | 支撑条款 |
| --- | --- |
| `chunks.char_start/char_end` | REQ-001、REQ-002 |
| `documents.text_sha256` | 5.3.4、REQ-002 |
| `chunks.source_format` | REQ-009、CHG-001 |
| `eval_cases.anchor_status/split` | REQ-027、REQ-033 |
| `runs.*` | REQ-031、REQ-032、D-012、B8 |
| `runs.deps_sha256` | 依赖锁比对，Verify 环境一致性 |
| `traces.excerpt`、`traces.source_run_id` | REQ-039、D-009；trace 读取路径 |
| `agent_sessions.session_id/stateless_mode/last_active_at` | REQ-063、REQ-067、`CHG-013` §8.1（D1）、§8.2 |
| `agent_turns.query_raw/query_rewritten/rewrite_rule` | REQ-064、`CHG-013` §8.2 |
| `agent_turns.tool_calls_json/flags` | REQ-059、REQ-060、REQ-065、`CHG-013` §8.2（只存摘要） |
