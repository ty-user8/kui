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

**交付状态**：本单为已确认的设计基线，2026-11-22 已入库留档（仅本文件，`dev` 分支）；未改任何现有代码、规格、配置与基线，未开始实现。
