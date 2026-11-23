# 变更单 #013：法律知识库问答 Agent（v2）

- 日期 / 发起方：2026-11-22 / 用户
- 状态：**已确认**（2026-11-22 用户定稿五个决策点，D1 取方案 A）；实现按 S1→S5 分阶段推进，待用户下达 S1 指令后开工
- 影响级别：架构 + 能力边界（技术方案 §7.3 约束 5 要求走变更单、更新 `09-state.md`、重过 G2）

## 1. 目标与非目标

**目标**：在现有检索服务之上加一层「多轮问答 Agent」——用户用自然语言提问，模型输出工具调用（工具名 + 参数），确定性代码执行并回填结果，最多两轮后给出带条款引用的答案；会话内支持规则式指代/省略补全（0 次额外 API）。

**非目标（本单不做）**：

| 不做 | 原因 |
| --- | --- |
| 新索引 / 新检索链 | 全部复用现有 FAISS + BM25 + RRF 与 SQLite，避免第二套口径 |
| ReAct 式多轮自主规划 | 口径已定：最多两轮、工具白名单固定，防不可控调用与配额失控 |
| 多轮评测集重建 | 技术方案 §7.3 约束 3：工作量为单轮的 ×3~5，须单独立项 |
| LLM 摘要压缩历史 | §7.3 约束 2：属进阶，须重新评估配额 |
| 鉴权 / 用户体系 | 守 REQ-056（无鉴权、单机单用户） |
| 改 `/ask`、`/search`、`/eval` 行为 | 三者的语义与基线必须保持原样 |

## 2. 口径确认（用户 2026-11-22 已定）

| # | 口径 | 落成设计约束 |
| --- | --- | --- |
| 1 | 不加鉴权，参数校验沿用 Pydantic | 无 token、无用户维度；所有工具入参与 Agent 请求都走 pydantic 模型校验，非法参数折成结构化错误码 |
| 2 | 工具层新建，仅 4 个工具，全部复用现有检索链与 SQLite/manifest | 工具内部只调 `src.api.service.search`、`src/store/dao`、`corpus/metadata/manifest.json`、`data/index/index-meta.json`；不允许工具自己拼 SQL 或另建索引 |
| 3 | function call 混合式：LLM 出工具名+参数（JSON Schema），代码执行回填，最多两轮 | 编排是确定性状态机（见 §6），不解析自然语言计划、不允许模型自选工具之外的动作 |
| 4 | 记忆按技术方案 §7 最小实现：会话 id + SQLite 轮次表 + 规则式指代替换（0 次 API） | 新增两张表（§8.2），不进 `traces`；指代规则是纯函数，单测可覆盖 |
| 5 | 评测回路 0 次 LLM 不变；agent 独立配额、单次 30 s、不进 CI；key 只读 `RAG_LLM_API_KEY` | 配额与超时独立于 `llm.*`（§7）；`eval.yml` 不新增步骤；agent 路径 grep 不到额外 key 变量 |
| 6 | 新页面独立端口 8502，不动 `app.py`／8501；`config.yaml` 新增配置项 | 新入口 `app_agent.py` + `server.ui_port_agent`；`app.py` 零改动 |

## 3. 调研结论（现状盘点，作为可行性依据）

**可直接复用的既有能力**

| 能力 | 位置 | 复用方式 |
| --- | --- | --- |
| 检索主链（向量 + BM25 + RRF + 可选 rerank） | `src/api/service.py: search(conf, query, top_k, filters, write_trace)` | 工具内部直接调用，`write_trace=False`（与 `/ask` 同款处理） |
| 元数据过滤（4 字段，含降级 `FILTER_RELAXED`） | `src/retrieve/filtering.py: MetadataFilter(doc_ids, categories, authorities, publish_from, publish_to)` | `search_laws` 的 `filters` 直接映射到该结构，不新写过滤逻辑 |
| 条文正文与锚点 | `chunks(chunk_id, doc_id, seq, text, char_start, char_end, article_no, heading_path, parent_id)` | `get_anchor_text` 按 `chunk_id` 取正文与区间；`parent_of` 可回溯父块 |
| 文档元数据 | `documents(doc_id, title, category, authority, publish_date, effective_date, source_url, …)` + `corpus/metadata/manifest.json`（150 条，字段齐全） | `filter_metadata`、`get_stats` 的数据源 |
| 计数与索引指纹 | `dao.count_documents / count_chunks / format_sources`、`data/index/index-meta.json` | `get_stats` 的规模统计与权重指纹 |
| 生成与引用校验 | `src/generate/ask.py`（Prompt 版本化、30 s 线程超时、`citation.validate`） | 复用 Prompt 与引用校验；Agent 只在「最后一轮」产出答案 |

**现有约束与已知冲突（本单必须处理）**

1. **`run_id` 与 `stateless_mode`（决策点 D1）**：技术方案 §7.3 约束 1 写「`run_id` 增加 `stateless_mode=true`」，但 `run_id` 由 `build_run_id` 的规范串决定（seed／embedding／chunk／topk／cases／corpus／docs／nv）。**把该字段直接放进规范串会让现有基线 `r31a95a0e1de6` 变成新值**，触发 REQ-037 重测基线——与「评测指标与基线不动」冲突。见 §9.1 的两个方案。
2. **评测回路 0 次 LLM**：现有 `eval`／`ci_check` 路径不 import 任何生成模块。Agent 模块必须同样不被这两条路径 import（§9.3 用单测静态断言守住）。
3. **`traces` 表只服务检索分析**（按 gold 锚点做失败归因）：Agent 的会话轮次若写进 `traces`，会让按 `run_id` 的归因多出无 gold 噪声。故会话记录进新表，不碰 `traces`。
4. **`/ask` 已有进程级配额 `llm.max_calls=50`**：Agent 若共用，一次多轮问答会挤占演示用的 `/ask` 余量。故 Agent 用独立配额（§7）。
5. **`server` 段只有 `api_port=8000`／`ui_port=8501`**：新页面要独立端口，需加 `ui_port_agent=8502`，且不改变现有两项的解析。

## 4. 工具层设计（4 个工具）

统一约定：入参出参都是 JSON；入参在 pydantic 侧 `extra="forbid"`（多传字段直接判非法）；出参只回「可核验的事实」（分数、锚点、区间、来源），不回自然语言。

### 4.1 `search_laws` — 语义检索

| 项 | 内容 |
| --- | --- |
| 用途 | 把用户问题变成 top-k 条文片段（向量 + BM25 融合） |
| 入参 | `query`（必填，1–200 字）、`top_k`（1–20，默认 5）、`filters`（可选：`category`／`authority`／`publish_from`／`publish_to`／`doc_ids`） |
| 出参 | `hits[]`：`chunk_id`、`doc_id`、`title`、`article_no`、`heading_path`、`score`、`path`（`dense`/`fused`/`rerank`）；`flags[]`（如 `FILTER_RELAXED`、`FALLBACK_BM25`）；`count` |
| 实现 | `service.search(conf, query, top_k, filters, write_trace=False)`，只做字段裁剪 |
| 错误 | 索引空 → `INDEX_EMPTY`；参数越界 → `INVALID_REQUEST`；过滤后为空且已降级 → 200 + `flags=FILTER_RELAXED` |

### 4.2 `filter_metadata` — 元数据筛选（不发检索）

| 项 | 内容 |
| --- | --- |
| 用途 | 回答「哪些是 2025 年之后的行政法规」「应急管理部有哪些文件」这类**枚举型**问题，不消耗检索 |
| 入参 | `field`（枚举：`category`／`authority`／`publish_date`／`title`／`doc_id`）、`op`（枚举：`eq`／`in`／`between`／`contains`）、`value`（**统一为字符串数组**，1–10 项：`eq` 取 1 项、`in` 取多项、`between` 取 `[起始日, 结束日]`、`contains` 取 1 项）、`limit`（1–50，默认 20）。组合规则写进工具 description、由代码侧校验 |
| 出参 | `documents[]`：`doc_id`、`title`、`category`、`authority`、`publish_date`、`effective_date`；`count`；`truncated`（是否因 limit 截断） |
| 实现 | 读 `manifest.json`（或 `documents` 表）做**白名单字段**比较；字段与算子组合不在白名单内 → `TOOL_ARGS_INVALID`；不接受自由 SQL、不接受未列字段 |
| 备注 | 这是唯一「不走向量」的工具，用于省一次检索；结果仍可交给 `get_anchor_text` 取正文 |

### 4.3 `get_anchor_text` — 取条文原文与锚点

| 项 | 内容 |
| --- | --- |
| 用途 | 把检索命中的片段取成可引用的原文（带条号、字符区间），供最终答案标注依据 |
| 入参 | `chunk_id`（必填）或 `doc_id` + `article_no`（二选一）；`max_chars`（200–2000，默认 800） |
| 出参 | `chunk_id`、`doc_id`、`title`、`article_no`、`heading_path`、`char_start`、`char_end`、`text`（按 `max_chars` 截断，`truncated` 标记）、`source_url` |
| 实现 | `chunks` 表按 `chunk_id` 直查；`doc_id + article_no` 走 `idx_chunks_doc`；不存在的 id → `TOOL_RESULT_EMPTY` |
| 防越界 | `max_chars` 上限硬编码在配置 `agent.max_tool_chars`，模型传更大值按上限截断 |

### 4.4 `get_stats` — 语料与索引规模

| 项 | 内容 |
| --- | --- |
| 用途 | 回答「这个库有多少法、哪个年份最多」这类**元问题**，也用于答案里给出可信规模 |
| 入参 | 无（空对象） |
| 出参 | `documents`、`chunks`、`categories`（分布 top-10）、`authorities`（top-10）、`publish_date_range`、`weights_sha256`、`normalizer_version`、`index_bytes` |
| 实现 | `dao.count_documents`／`count_chunks` + `manifest.json` 聚合 + `data/index/index-meta.json` |
| 成本 | 纯本地计算，0 次模型调用 |

## 5. 工具 JSON Schema（可直接落 pydantic，`strict: true`）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["tools"],
  "properties": {
    "tools": {
      "type": "array",
      "minItems": 4,
      "maxItems": 4,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "description", "parameters"],
        "properties": {
          "name": { "enum": ["search_laws", "filter_metadata", "get_anchor_text", "get_stats"] },
          "description": { "type": "string" },
          "parameters": { "type": "object" }
        }
      }
    }
  },
  "$defs": {
    "search_laws": {
      "type": "object",
      "additionalProperties": false,
      "required": ["query"],
      "properties": {
        "query": { "type": "string", "minLength": 1, "maxLength": 200 },
        "top_k": { "type": "integer", "minimum": 1, "maximum": 20, "default": 5 },
        "filters": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "category": { "type": "array", "items": { "type": "string" }, "maxItems": 5 },
            "authority": { "type": "array", "items": { "type": "string" }, "maxItems": 5 },
            "publish_from": { "type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" },
            "publish_to": { "type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" },
            "doc_ids": { "type": "array", "items": { "type": "string" }, "maxItems": 10 }
          }
        }
      }
    },
    "filter_metadata": {
      "description": "按文档元数据筛选（不走检索）。field/op/value 组合规则：eq=单值精确匹配（value 长度 1）；in=集合匹配（value 可多个）；between 仅用于 publish_date，value 必须是 [起始日, 结束日] 两个 YYYY-MM-DD；contains 仅用于 title，value 长度 1 的子串匹配。组合规则由代码侧校验，违反时返回 TOOL_ARGS_INVALID。",
      "type": "object",
      "additionalProperties": false,
      "required": ["field", "op", "value"],
      "properties": {
        "field": { "enum": ["category", "authority", "publish_date", "title", "doc_id"] },
        "op": { "enum": ["eq", "in", "between", "contains"] },
        "value": {
          "type": "array",
          "items": { "type": "string", "maxLength": 100 },
          "minItems": 1,
          "maxItems": 10
        },
        "limit": { "type": "integer", "minimum": 1, "maximum": 50, "default": 20 }
      }
    },
    "get_anchor_text": {
      "type": "object",
      "additionalProperties": false,
      "required": ["chunk_id"],
      "properties": {
        "chunk_id": { "type": "string", "minLength": 1, "maxLength": 80 },
        "max_chars": { "type": "integer", "minimum": 200, "maximum": 2000, "default": 800 }
      }
    },
    "get_stats": { "type": "object", "additionalProperties": false, "properties": {} }
  }
}
```

> **通用规则（模型可见 schema 一律遵守）**：**不使用 `oneOf` / `anyOf` / `allOf` / `if-then` 等条件构造**——DeepSeek 的 strict function call 对这类构造支持有限，存在 400 拒绝或模型误读的风险（§5 早期草案里 `filter_metadata.value` 用过 `oneOf`、`op` 与 `field` 的组合用过 `allOf+if/then`，已按本规则改掉）。落地方式：
>
> 1. 模型可见 schema 只用 `type` / `enum` / `items` / `minItems` / `maxItems` / `minLength` / `maxLength` / `minimum` / `maximum` / `required` / `additionalProperties:false`；
> 2. **字段间的组合约束写进工具 `description` 的自然语言**（如 `between` 只配 `publish_date` 且要两个日期），并在 `tools.py` 用 pydantic 校验器**代码侧兜底**；不合法结构的调用一律 `TOOL_ARGS_INVALID`，不回灌给模型重试；
> 3. 同一规则适用于 `get_anchor_text` 的「`doc_id` + `article_no` 二选一」——故 v2 只暴露 `chunk_id`（检索结果里已带 `chunk_id`），`doc_id + article_no` 仅作内部函数入参，不进模型可见 schema（**D3 已定稿：不暴露**）；
> 4. 单测里加一条结构性断言：递归扫描 `TOOL_SCHEMAS`，命中 `oneOf` / `anyOf` / `allOf` / `if` / `then` / `not` 任一键即失败——防止以后有人手滑加回来。

## 6. function call 编排（混合式，两轮封顶）

```
用户问题
  ├─ 规则式改写（0 次 API）：指代/省略/继承日期 → rewritten_query
  ├─ 第 1 轮：LLM(tools=schema, tool_choice="auto") → 期望得到 1~3 个 tool_calls
  │    ├─ 无 tool_call 且给了答案 → 走引用校验（视为直接回答，记 flags=NO_TOOL）
  │    └─ 有 tool_call → 代码执行（白名单 + pydantic 校验 + 超时/配额）
  ├─ 第 2 轮：LLM(messages + tool 结果, tools=schema, tool_choice="none") → 只出最终答案
  │    └─ 若仍想调工具 → 拒绝并降级：用已有结果直接作答（记 flags=TURN_LIMIT_HIT）
  └─ 引用校验（复用 citation.validate）→ 返回 {answer, citations, tool_trace}
```

硬约束：

- **两轮上限**：第 2 轮强制 `tool_choice="none"`；模型若在 content 里写工具名，不做解析、直接当答案正文。
- **每次请求最多 3 个 tool_calls**，超出按顺序取前 3 个，其余丢弃并记 `flags=TOOL_CALLS_TRUNCATED`。
- **参数非法不重试**：pydantic 校验失败 → 把错误结构化回填给模型一次（不算一轮工具执行），仍非法则该工具跳过、记 `TOOL_ARGS_INVALID`。
- **确定性执行**：工具调用顺序按模型给出的顺序串行执行，不并发（避免同一 SQLite 连接上的写竞争）。
- **不写 `traces`、不写 `runs`、不产生 `metrics.json`**：`search_laws` 调 `service.search(..., write_trace=False)`。

## 7. 配额方案（独立于 `/ask`）

| 配置项（新增于 `config.yaml` 的 `agent` 段） | 默认值 | 作用 |
| --- | --- | --- |
| `agent.max_turns` | 2 | 模型往返轮数硬上限（含工具回填后那一轮） |
| `agent.timeout_seconds` | 30 | 单次模型调用超时（与 `llm.timeout_seconds` 同值但独立，便于单独放宽/收紧） |
| `agent.max_calls_per_question` | 2 | 单次提问最多几次模型调用（= `max_turns`，留作未来压缩时的余量） |
| `agent.max_calls_per_session` | 20 | 单会话累计调用上限，超出返回 `AGENT_QUOTA_EXCEEDED` |
| `agent.max_tool_calls_per_turn` | 3 | 每轮最多执行几个工具 |
| `agent.max_context_turns` | 3 | 拼进 Prompt 的历史轮数上限（token 随轮数累加，故设死） |
| `agent.max_tool_chars` | 2000 | 单个工具结果回填的最大字符数 |
| `agent.session_ttl_hours` | 24 | 会话过期时间（读时判定，不后台清理） |

- **与 `/ask` 的关系**：两套计数器完全独立（`agent` 用自己的计数，`llm.max_calls` 只管 `/ask`），互不挤占。
- **不可放大的地方**：`max_turns`、`max_tool_calls_per_turn`、`max_context_turns` 三项为**代码常量级**设计（配置可下调不可上调，超默认值启动即报 `CONFIG_INVALID`），防止一次改配置把成本放大 10 倍。
- **超时语义**：单次调用 30 s 超时 → 若有已完成的工具结果，直接基于结果作答并标 `AGENT_TIMEOUT`；无结果 → 返回空答案 + 检索结果（与 `/ask` 的降级语义一致）。
- **成本口径**：一次典型问答 ≤ 2 次调用、≤ 3 个工具、回填 ≤ 6 KB；单会话 20 次上限意味着一次演示最多 10 个问题。

## 8. 与现有基线的隔离设计

### 8.1 `run_id` 与 `stateless_mode`（D1，已定稿：方案 A）

**结论：`stateless_mode` 不进 `run_id` 规范串。**

| 项 | 做法 |
| --- | --- |
| 评测路径 | 恒为无状态（`stateless_mode=true`）；`build_run_id` 的规范串保持现样（seed／embedding／chunk／topk／cases／corpus／docs／nv），`run_id` 仍是 **`r31a95a0e1de6`**，`evals/baseline.json` 与六项指标不动 |
| 声明位置 | Agent 响应体字段 `stateless_mode: true`；`agent_sessions.stateless_mode` 列（默认 `0`，本单所有会话写 `1`）；`agent_turns.flags` 里可带同名标记 |
| 守门方式 | 单测断言：`build_run_id` 的规范串字段集合不含 `stateless`／`agent` 相关键；跑一次 agent 问答后 `data/runs/` 无新目录、`traces` 与 `runs` 表无新行 |

**为什么不再塞进哈希输入**：`run_id` 的定义是「配置指纹」——用来判断「这次结果能不能和上次比」。把「这轮有没有开记忆」塞进同一个哈希，会让两种完全不同的原因（换了配置 / 加了个开关）落成同一个「id 变了」的现象，反而丢掉可解释性；而且一改指纹就要按 REQ-037 重测基线、换 `baseline.json`、改快照表与 C-06、CI 红一次——为一条自证字段付这个代价不划算。v2 路径本来就不产出 `metrics.json`、不参与回归，用响应字段 + 表列即可自证。

**技术方案 §7.3 约束 1 的落地方式**：该条原文写「`run_id` 增加 `stateless_mode=true`」，本单按上述口径实现——**目的（评测路径无状态、记忆模块强制关闭、可被审计）保留，手段（写进指纹）替换为响应字段 + 表列 + 单测断言**。`specs/00-source/` 属只读归档（C-01 保护），正文不改；差异按 `CHG-001`／`CHG-011` 的先例以「本单 + `CHANGELOG-DECISIONS.md` 决策条目」追溯（决策条目随 S1 落地时一并补记，本轮只交本单）。

> 未采用方案 B（把 `stateless_mode` 加进规范串）：会让 `run_id` 立刻变值，必须重测基线并同步 `evals/baseline.json`、`PROGRESS` 快照表、检查单 C-06，CI 也会红一次；收益仅是「多一个哈希输入」，与上面说的可解释性损失不对等。

### 8.2 数据隔离（新增表，不改既有表）

```sql
-- 拟作为 specs/06-schemas/migrations/0004_agent.sql（新文件，不改 0001~0003）
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id      TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at  TEXT NOT NULL DEFAULT (datetime('now')),
    stateless_mode  INTEGER NOT NULL DEFAULT 0 CHECK (stateless_mode IN (0, 1)),
    turn_count      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_turns (
    pk               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    turn_no          INTEGER NOT NULL,
    query_raw        TEXT NOT NULL,
    query_rewritten  TEXT,
    rewrite_rule     TEXT,           -- pronoun_carryover / ellipsis_append / date_inherit / none
    tool_calls_json  TEXT,           -- [{name, args, ok, elapsed_ms, result_digest}]
    answer           TEXT,
    citations_json   TEXT,
    citation_valid   INTEGER,
    flags            TEXT,           -- TURN_LIMIT_HIT / AGENT_TIMEOUT / FILTER_RELAXED …
    elapsed_ms       REAL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, turn_no)
);
```

- 不写 `traces`、不写 `runs`、不写 `metrics.json`；会话数据只在这两张表里。
- `agent_turns.tool_calls_json` 只存**摘要**（结果条数、top-1 chunk_id、是否截断），不存全文，避免把语料复制进数据库。

### 8.3 进程与端口隔离

| 组件 | 端口 | 是否进 CI | 说明 |
| --- | --- | --- | --- |
| 检索接口 `/search` `/eval` `/ingest` `/trace` `/ask` | 8000 | 否（CI 只跑 `src.cli.eval`） | 不动 |
| 单页回放 `app.py` | 8501 | 否 | **零改动** |
| Agent 页面 `app_agent.py` | **8502**（`server.ui_port_agent`） | 否 | 新文件，独立进程；起法写进 README 维护段或变更单执行记录 |

### 8.4 评测隔离的三道闸

1. **目录闸**：新增代码只落 `src/agent/` 与 `app_agent.py`；`src/eval/`、`src/cli/eval.py`、`scripts/ci_check.py`、`.github/workflows/eval.yml` 全部不改。
2. **导入闸**（单测）：`tests/test_agent_isolation.py` 断言 `src.eval`、`src.cli.eval`、`scripts.ci_check` 的模块图里不含 `src.agent`、`openai`。
3. **调用闸**（单测）：monkeypatch `openai` 的构造，跑一次 `src.cli.eval` 全流程，断言 0 次客户端实例化。

## 9. 影响范围（本单确认后才会落地）

| 类型 | 新增/改动 | 说明 |
| --- | --- | --- |
| 新增模块 | `src/agent/{tools.py, schema.py, orchestrator.py, memory.py, quota.py}` | 工具、Schema、编排、记忆、配额 |
| 新增页面 | `app_agent.py`、`src/agent/ui.py` | 8502 独立页面，不做流式 |
| 新增迁移 | `specs/06-schemas/migrations/0004_agent.sql` | 两张新表，不动 0001~0003 |
| 配置 | `config.yaml` 新增 `agent:` 段与 `server.ui_port_agent` | 只增键，不改既有键 |
| 规格 | `09-state.md` 增会话状态机；`01-requirements.md` 增 EARS；`06-schemas/README.md` 增两表说明 | **须本单确认后**再改，本轮不动 |
| 不动 | `app.py`、`src/api/**`、`src/eval/**`、`scripts/ci_check.py`、`eval.yml`、`evals/**`、`requirements.lock.txt` | — |

## 10. 分阶段执行方案（确认后）

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| S1 | `src/agent/schema.py` + `tools.py`（4 工具）+ 单测（正常/边界/非法参数/空结果） | 工具层单测全绿；同一 query 与 `/search` 的 top-k 逐条一致（复用同一链路的证明） |
| S2 | `orchestrator.py`（两轮状态机）+ `quota.py` + 假客户端单测 | 两轮上限、工具数截断、超时降级、配额拒绝各有用例 |
| S3 | `memory.py` + `0004_agent.sql` + 指代规则单测 | 0 次 API；指代/省略/日期继承各有用例；会话隔离（不同 session 不串） |
| S4 | `app_agent.py` 8502 页面 + `README` 维护段 | 页面可起、会话内多轮可用、`app.py` 未变 |
| S5 | 验收与留痕 | 评测六项不变、CI 14 步不变、`/ask` 配额不受影响 |

## 11. 回归验证（本单要求，落地时逐条跑）

- 单测：现有 124 例全绿 + 新增 ≥20 例（工具 8、编排 6、记忆 4、隔离 3）。
- 基线：`run_id` 与六项指标不变（`r31a95a0e1de6`，0.5600/0.8600/0.9000/0.7045/0.7543/0.9000）；`evals/baseline.json` 不动。
- CI：`eval.yml` 步骤数仍 14；`ci_check.py` 三项判定不变。
- 隔离：跑一次 agent 问答后，`data/runs/` 无新目录、`trace.jsonl` 无新行、`runs` 表无新行。
- 依赖：不新增第三方库（`openai` 已在锁内）。

## 12. 回滚方式

删 `src/agent/`、`app_agent.py`、`0004_agent.sql` 与 `config.yaml` 的 `agent` 段即可回到 v1；两张新表可保留（不被任何既有代码读取，等同无影响），若要清干净再 `DROP TABLE agent_turns, agent_sessions`。评测与基线全程未改，回滚不需要重测。

## 13. 决策记录（2026-11-22 用户定稿）

| # | 决策 | 落点 |
| --- | --- | --- |
| **D1** | **方案 A**：`stateless_mode` **不进** `run_id` 规范串；用响应字段 `stateless_mode` + `agent_sessions.stateless_mode` 列声明；评测恒 `true`，基线 `r31a95a0e1de6` 与六项指标不动 | §8.1（含不塞进哈希输入的理由与技术方案 §7.3 的追溯方式） |
| **D2** | 会话过期**读时判定**：按 `agent.session_ttl_hours`（默认 24 h）在每次读写会话时比对 `last_active_at`，过期即视为新会话；**不做后台清理任务** | §7 配置项、§8.2 表结构；实现不引入定时器/线程 |
| **D3** | `get_anchor_text` **只对模型暴露 `chunk_id`**（+ `max_chars`），不暴露 `doc_id + article_no` 组合入口 | §4.3、§5 schema（`get_anchor_text.required=["chunk_id"]`） |
| **D4** | **不新增 `POST /agent`**；问答只从 8502 页面内部调用 `src.agent.orchestrator`，不扩 HTTP 接口面（守 REQ-056） | §8.3、§9（`src/api/**` 不动） |
| **D5** | 多轮评测集**不现在立项**，按技术方案 §7.3 约束 3 单独立项（工作量 ×3~5、需按会话切分 holdout） | §1 非目标、§11（基线不动） |

阶段推进顺序不变：**S1 → S5**，等用户下达 S1 指令后开工；S1 只做 `src/agent/schema.py` + `tools.py` + 工具层单测。

---

## 14. 执行记录

### S1（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 新增文件 | `src/agent/__init__.py`、`src/agent/schema.py`、`src/agent/tools.py`、`tests/test_agent_tools.py` |
| schema 构造方式 | 手写（不用 `model_json_schema()`，以避开 pydantic 给 `Optional` 自动加的 `anyOf`）；结构断言递归扫描 `oneOf`/`anyOf`/`allOf`/`if`/`then`/`not`/`$ref`/`$defs` 命中即失败 |
| 参数校验 | pydantic 模型 `extra="forbid"` + `filter_metadata` 的 `model_validator` 兜底组合规则；非法一律 `TOOL_ARGS_INVALID` |
| 与 `/search` 一致性 | 单测断言「同一 query（含带 `filters` 的场景）下 `chunk_id` 序列、`score`、`flags` 与 `service.search` 全等」 |
| 隔离 | 单测断言工具调用前后 `trace.jsonl` 大小与 `data/runs/` 目录列表不变（D1 的第四道证据） |
| 单测 | S1 新增 32 例全绿；全量 156 例 OK（14.0 s） |
| 未动 | `config.yaml`（`agent.*` 配额 S3 才接）、`src/api/**`、`src/eval/**`、`scripts/ci_check.py`、`eval.yml`、`app.py`、DB 迁移 |

### S2（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 新增文件 | `src/agent/quota.py`（`AgentSettings` + `Quota`）、`src/agent/orchestrator.py`（两轮状态机）、`tests/test_agent_orchestrator.py`（17 例） |
| 轮数 | 第 1 轮 `tool_choice="auto"`、第 2 轮强制 `"none"`；第 2 轮仍吐工具调用 → `TURN_LIMIT_HIT`，不开第 3 轮 |
| 工具数 | 每轮上限 3，超出丢弃并标 `TOOL_CALLS_TRUNCATED`（单测用 4 个调用验证只执行 3 个） |
| 超时 | 单次调用 `timeout_seconds`（默认 30 s，可注入更小值测），超时返回空答案 + `AGENT_TIMEOUT`，不再追加调用 |
| 配额 | `Quota` 分问题级/会话级计数；超限抛 `AGENT_QUOTA_EXCEEDED`；`max_turns`／`max_tool_calls_per_turn`／`max_context_turns` 三项只能下调（`AgentSettings.__post_init__` 拦截） |
| 参数非法 | tool arguments 非 JSON 或校验失败 → 该次结果折成错误 JSON 回填、标 `TOOL_ARGS_INVALID`，不重试、不中断本轮 |
| 引用 | 复用 `citation.validate`；越界引用保留答案并标 `CITATION_INVALID` |
| 隔离证据 | 集成用例（真 dispatch + 假客户端）断言 `trace.jsonl` 大小与 `data/runs/` 目录列表在 agent 调用前后不变 |
| 单测 | S2 新增 17 例全绿；全量 173 例 OK（14.2 s）；无环境变量跑时 `test_agent_tools` 为 skip 而非 error |
| 顺手修 | `tests/test_agent_tools.py` 的 `load_conf_or_skip` 原先在 `setUpClass` 里调 `tc.skipTest()`（实例方法），实际抛 `TypeError` 表现为 5 个 ERROR；改为 `raise unittest.SkipTest(...)`，现在缺 `RAG_DB_PATH` 时结构断言照跑、其余 5 类 skip |
| 未动 | `config.yaml`（`agent.*` 接线 S3）、DB 迁移（S3）、8502 页面（S4）、`src/api/**`、`src/eval/**`、`ci_check.py`、`eval.yml` |

### S3（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 新增文件 | `src/agent/memory.py`（会话/轮次 + 规则式改写）、`specs/06-schemas/migrations/0004_agent.sql`、`tests/test_agent_memory.py`（21 例） |
| 迁移 | 只 `CREATE TABLE IF NOT EXISTS agent_sessions / agent_turns` + 一个索引 + `INSERT OR IGNORE INTO schema_migrations (4,'agent')`；单测断言 0004 内无 `ALTER TABLE`／`DROP TABLE`／`UPDATE documents`／`DELETE FROM`，且 0001~0003 文本里不含 `agent_`；应用后 4 个版本齐全、既有 6 张表仍在 |
| 改写规则（0 次 API） | `pronoun_carryover`（含 它/该法/上述 等 → 前置上一轮问句）、`ellipsis_append`（≤8 字且带 呢/吗/还有 等语气 → 同上）、`date_inherit`（今年/去年/前年 → 具体年份，已带 4 位年份则不替换）；三条各有用例，另有「无历史不改写」「上一轮已改写句不重复叠加」两条 |
| 会话存取 | `open_session` / `next_turn_no` / `record_turn`（同 `(session, turn_no)` 覆盖写）/ `load_turns` / `history_for_prompt`；单测覆盖建会话、续会话、轮次正序、幂等覆盖、历史拼装 |
| 会话隔离 | 两个 session 各写一轮，互相 `load_turns` 只见自己的；不存在的会话返回空列表（新会话 id 不复用传入值） |
| TTL（D2） | 25 h 后再用旧 id → `expired=True` 且换新 id，旧轮次不挂到新会话；无后台清理任务 |
| 配置接线 | `config.yaml` 只增 `server.ui_port_agent: 8502` 与 `agent:` 8 项；`src/config.py` 新增 `AgentConfig`、`AGENT_DEFAULTS`、`AGENT_HARD_CAPS` 与 `_parse_agent`；既有 `api_port`/`ui_port` 等键未动 |
| 默认值一致性 | 三条断言绑定：`config.AGENT_DEFAULTS == quota.DEFAULTS`、`AgentSettings` 字段默认值 == `DEFAULTS`、`config.yaml` 实际加载值 == `DEFAULTS` |
| 硬上限单一入口 | 配置侧 `_parse_agent` 拒绝上调（`ConfigError`），代码侧 `AgentSettings.__post_init__` 仍拒绝（`ValueError`）；`from_conf` 走同一构造，不绕校验 |
| 单测 | S3 新增 21 例全绿；全量 194 例 OK（14.9 s）；无环境变量 178 例 OK（6 skip，0 error） |
| 未动 | 8502 页面（S4）、`src/api/**`、`src/eval/**`、`ci_check.py`、`eval.yml`、`evals/**`、锁文件、基线 |
| 遗留（S5 一并做） | `06-schemas/README.md` 的两表说明、`09-state.md` 的会话状态机、`01-requirements.md` 的 EARS 条款尚未回填；`quota` 硬上限文案与配置端口文档待 S5 统一 |

### S4（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 新增文件 | `app_agent.py`（8502 入口，仅 set_page_config + 调 ui.render）、`src/agent/ui.py`（页面主体）、`tests/test_agent_ui.py`（9 例，含 AppTest 冒烟） |
| 页面可起 | 8502 起服务后浏览器实测：标题「法规问答 Agent」、副标题「会话 … · 已用 0/20 次调用 · 单次超时 30 s · 最多 2 轮」、底部输入框正常；8501 同时在线未受影响 |
| 首连库迁移 | 页面真实会话执行脚本后，本地 `data/rag.db` 从 `[1,2,3]` 变为 **`[1,2,3,4]`**，`agent_sessions`／`agent_turns` 两表出现且写入 1 条会话；未手写建表，全由 `memory._connect` 应用 0004 |
| 多轮可用 | 真实模型两轮实测：第 1 轮 `search_laws` 取证 + 出答案，第 2 轮「那实用新型呢」被规则改写为「…；那实用新型呢」并带上轮历史，两轮均 `citation_valid=true`、无 flags、每问 2 次调用（配额内）；会话表存 2 行 |
| 隔离 | `app.py`／8501 零改动；未新增 `POST /agent`（D4），问答只在页面进程内调 `orchestrator.run` |

**真实调用暴露并修掉的三处接线缺陷**（本地假客户端测不出，均已在 S4 修复并有断言）：

1. **tools 报文格式**：`TOOL_SCHEMAS` 是扁平 `{name, description, parameters}`，直接传会被接口拒——`422 ... tools[0]: missing field type`。改为 `{"type":"function","function":{...}}`（`orchestrator.tool_payload()`），并加单测断言外层有 `type`、内层有 `name`/`parameters`。
2. **末轮仍吐工具调用**：只把 `tool_choice` 设成 `none`、工具清单还在时，模型会把调用写进正文（DeepSeek 的 `<｜｜DSML｜｜>` 形态）。改为**末轮不挂 `tools`**；单测断言第 2 次调用既无 `tools` 也无 `tool_choice`。
3. **末轮正文仍可能是工具标记**：历史里已有 tool_calls 时模型仍会模仿输出标记。追加末轮 system 提醒，并加正文标记防御——命中即标 `TOOL_CALL_IN_CONTENT`、答案置空，不把标记当答案入库。

**质量观察（非 S4 缺陷，如实记录）**：「发明专利权的期限是几年」的 top-5 命中里没有含「二十年」的第四十二条片段（`service.search` 与工具返回逐条一致：00012 是第三十八～四十条），模型因此如实答「现有条文不足以回答」。这属既有固定窗口切分的检索局限（`evals/badcases-v0.5.md`），演示时选命中更好的问题更合适。

| 验证 | 结果 |
| --- | --- |
| 单测 | S4 新增 9 例 + 编排修缺陷加 1 例；全量 **204 例 OK**（18.9 s）；无环境变量 188 例 OK（6 skip，0 error） |
| 未动 | `app.py`、`src/api/**`、`src/eval/**`、`ci_check.py`、`eval.yml`、`evals/**`、锁文件、基线 |

### S5（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 规格回填 | 三处，均带版本／日期／依据（C.1 留痕材料，不按规则 #11 删元信息）：① `06-schemas/README.md` —— 存储清单加 `agent_sessions`／`agent_turns`（版本列 `v2（CHG-013，2026-11-22）`）、DDL 链补 `0004_agent.sql`、建表要点加 3 行（含「`tool_calls_json` 只存摘要」「不被 `/search`／`/eval`／CI 读取」）、对应表加 3 行；② `09-state.md` —— §6 由「规划」转「已落地」，逐条写落地位置，第 2 条按 D1 改写并说明为何不进 `run_id`；新增 §7（7.1 会话生命周期、7.2 单轮两轮状态机、7.3 v2 数据契约），并标注与 §3 的分界；③ `01-requirements.md` —— 新增 §6-I「问答 Agent（v2）」，REQ-059~REQ-068 共 10 条，含模式／版本／验证方式 |
| 验收：单测 | 全量 **205 例 OK**（17.0 s，原 204 + 1 条新增 `/ask` 配额独立性用例）；无环境变量 189 例 OK（6 skip、0 error） |
| 验收：基线 | `src.cli.eval` 落 `attempt-5`：`run_id=r31a95a0e1de6`，六项 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 与 `evals/baseline.json` 逐项相同；本地 `ci_check.py` 三项 PASS（`attempt-6`／`attempt-7` 的 `metrics.json` 逐字节一致 576 B、`run_id` 未变、无退化），退出码 0 |
| 验收：隔离（真实调用） | 用户级 key 进程内注入，`deepseek-flash` 跑一问「假冒专利要承担什么法律责任」：`elapsed_ms=15964.0`、`citation_valid=true`、`invalid_citations=[]`、`flags=[]`、`stateless_mode=true`、2 次模型调用。前后比对：`data/runs/` 仍 15 个目录、`data/trace.jsonl` 仍 26695 B、`runs` 表 12 行、`traces` 表 10 行；只 `agent_sessions` +1、`agent_turns` +1 |
| 验收：`/ask` 配额 | 新增 `tests/test_agent_orchestrator.py::test_agent_calls_do_not_touch_ask_quota`：agent 两次调用后 `ask._CALLS` 计数不变（记在 agent 自己的 `Quota` 上）；把 `ask._CALLS` 置 1e6（假设 `/ask` 配额打满）后 agent 仍能正常作答 |
| 验收：依赖 | `requirements.txt`（995 B / `64a3227bc91c6b42`）与 `requirements.lock.txt`（1379 B / `da26d417ec5466fa`，73 行）均未动；`git status` 只有 3 份规格 + 1 个测试文件 |
| 验收：CI | 14 步不变，回归判定 PASS（run 见 `CHANGELOG.md` 同批流水） |
| 边界 | 未动 `evals/baseline.json`、锁文件、`src/api/**`、`src/eval/**`、`scripts/ci_check.py`、`.github/workflows/eval.yml`、`app.py`／8501 |
| 交付 | 按 `D-025` 快进推 `main`（`merge-base --is-ancestor main dev` 退出码 0 → `--ff-only` → `push origin main`），不 force／不 amend／不 rebase |

### 缺陷修复：第 2 轮取不到正文（2026-11-22，S5 后）

| 项 | 结果 |
| --- | --- |
| 现象 | 两轮封顶 + 末轮摘 `tools`，使 `get_anchor_text` 没有执行窗口：第 1 轮 `search_laws` 只回元数据（chunk_id / 条号 / 分数，无正文），拿到 chunk_id 时已是第 2 轮，而第 2 轮不允许再调工具。结果是模型只能看到条号，答「现有条文不足以回答」 |
| 修法 | 把 `get_anchor_text` 从「模型显式调用的工具」改为**编排层确定性取证**：第 1 轮工具回填后、第 2 轮生成前，由 `_collect_anchor_texts` 对本次 `search_laws` 的命中自动取正文（按 chunk_id 去重、封顶 `AUTO_ANCHOR_LIMIT=5`、单个正文受 `max_tool_chars` 截断），以 system 消息并入第 2 轮上下文；命中为空或取值失败时不阻断，只在 `tool_trace` 记 `ok=false` 与错误码 |
| 工具轨迹 | 自动取的每条都进 `tool_trace`，带 `auto=true`、`name=get_anchor_text`、参数、耗时与摘要，和模型发起的调用可区分可审计 |
| 系统提示 | 删掉「用 `get_anchor_text` 取命中 chunk 的原文」这条模型做不到的指令，改为「正文由系统自动附在下一轮上下文里」，并要求引用只能来自工具结果或附带正文 |
| 铁律未动 | `max_turns=2` 不变；第 2 轮仍不挂 `tools`（`tool_choice=None`）；评测回路仍 0 次 LLM 调用；自动取证只调本地 SQLite，不产生模型调用 |
| 单测 | 新增 5 例：第 2 轮上下文含正文与定位信息、正文按 `max_tool_chars` 截断、取证失败仍出答案、非 `search_laws` 不触发取证、命中数封顶 5；既有 3 处计数断言随轨迹变化同步（`tool_trace` 由 1 变 2、去重后为 4）。`TestTwoRoundFlow` 19 例 OK |
| 真数据抽验 | 用真实库 `...:00012` 跑 `tools.dispatch` + `_format_anchor_block`：块内含 `[chunk_id] 中华人民共和国专利法 第三十八条 第四章… 字符 5376-5888` 与真实条文正文，200 字截断标记 `truncated=true` |
| 真模型验证（2026-11-22，停掉三服务后） | `deepseek-flash` 两问均 `citation_valid=true`、`flags=[]`、`auto_anchor=5` 条：①「假冒专利要承担什么法律责任」15851.1 ms，答案给出「民事责任 + 行政责任 + 刑事责任」并引《专利法》第六十八条罚则，与命中块最长连续重合 17 字（`...的罚款；没有违法所得或者违法所得在...`）；②「发明专利权的期限是几年」4381.4 ms，答案「二十年，自申请日起计算」并引第四十二条，与命中块最长连续重合 20 字（`授权过程中的不合理延迟给予专利权期限补偿`）。回查命中块：`00012` 含「第四十二条　发明专利权的期限为二十年」，`00020` 含「第六十八条／假冒专利／罚款」，答案依据均在附带的正文里，非模型记忆 |
| 本地套件 | 完整套件（含真 dispatch 的集成用例）在本机曾因 `OSError: 页面文件太小 (1455)` 中断——三个演示服务占用提交内存；同一用例已在 CI 干净 runner 上通过（run `45008867160`） |
| 隔离复验 | 真模型两问后 `data/runs/` 仍 15 个目录、`data/trace.jsonl` 仍 26695 B 不变 |
| 边界 | 未动 `src/api/**`、`src/eval/**`、`scripts/ci_check.py`、`.github/workflows/eval.yml`、`evals/**`、锁文件与基线 |

### 展示层整理：8502 用户可见面（2026-11-22）

| 项 | 结果 |
| --- | --- |
| 目标 | 用户端只留问题、答案、可读法规依据与进度提示；ID、配额参数、工具链、flags、改写过程、错误码一律不上页面 |
| 流式 | `orchestrator.run` 新增 `on_token`／`on_refs` 两个展示层回调（不传时行为与之前完全一致，测试与 CI 走该路径）。末轮以 `stream=True` 逐块产出并回调；总时限仍为 `agent.timeout_seconds`，超时抛 `_StreamTimeout` 保留已产出的半截答案并标 `AGENT_TIMEOUT`。页面每 60 ms 合并一次分块刷新，收尾再渲染一次完整文本，避免「闪一下」 |
| 引用 | 生成层仍保留 `[chunk_id]`（`citation.validate` 靠它判定越界）；`run` 额外返回 `citation_refs`（`chunk_id → {title, article_no}`，来自命中的 `search_laws` 结果与自动取证），页面把标记换成 `（《法规名》）` 或 `（《法规名》第X条起）`。规则：**正文同句已写「第X条」时只标法规名**（避免「引第四十二条、括号写第三十八条」的自相矛盾）；正文没写条号才补片段起始条，并写成「第X条起」（一块常横跨数条，不冒充精确条号）；未知 id 与末尾半截 `[` 一律隐藏；相邻重复括号合并 |
| 历史回放 | `_render_history` 不再直出原文：批量取轮次里的引用 id，用新增的 `tools.describe_chunks`（只读标题与条号、不读正文）换可读依据后再渲染；取不到元数据时退回只显示答案，不崩、不露 id |
| 移除项 | 标题下的「会话／已用 N／超时／最多 N 轮」整行删除；flags 说明、工具调用链、查询改写提示、错误码原文不再渲染。错误改为对用户有意义的话（配额耗尽 →「本轮提问次数已用完，请新开一个会话继续问」），原始 code 与 message 走 `logging.warning` |
| 未动 | 检索链、`/ask`、评测与 CI、配额数值与校验、两轮上限、末轮不挂 `tools`、自动取证机制、`base_url`／key 读取；未新增 HTTP 接口（D4） |
| 实测（浏览器，真实模型） | ① 单问「假冒专利要承担什么法律责任」：13.0 s 出现「正在作答」，随后 10 次增量刷新，结束文本 724 字、`[0-9a-f]{32}` 零命中、内部词（会话／配额／已用／超时／工具名／错误码／改写）零命中；引用渲染为「（《中华人民共和国专利法》第六十七条起）」等。② 连问两轮（「发明专利权的期限是几年」→「那期限补偿呢」）：第一轮答案在第二轮时以可读依据正常回放，页面 326 → 840 字，仍零 id。③ 刷新页面开新会话（原有行为），无残留 |
| 单测 | 全量 **221 例 OK**（新增／改写：流式回调拼接与 `citation_refs`、引用替换（含条号省略、去重、半截标记、未知 id）、历史引用解析、错误话术、页面无内部词断言）；无环境变量 205 例 OK（6 skip） |

**交付状态**：本单为已确认的设计基线，2026-11-22 已入库留档（仅本文件，`dev` 分支）；未改任何现有代码、规格、配置与基线，未开始实现。
