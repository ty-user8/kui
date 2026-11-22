# 法规检索与评测（RAG）

把 150 篇法律法规 DOCX 解析成可检索的条文片段，提供「向量 + BM25 融合」检索、可复现评测、HTTP 接口与两个演示页面。**单机 CPU 可跑，无外部向量库，评测回路 0 次 LLM 调用。**

一句话看结果：150 篇 / 2704 个 chunk / 100 条人工标注用例，基线 `r31a95a0e1de6` 的 Recall@5 **0.9000**、MRR **0.7045**。

## 1. 它做什么

| 环节 | 做法 | 关键约束 |
| --- | --- | --- |
| 解析 | `python-docx` 取段落与字符区间，表格单独计数并排除 | 字符守恒：基准文本 + 排除字符 = 可提取总量 |
| 切分 | 512 字固定窗口、64 字重叠（另备 recursive / sliding，实测更差，未启用） | chunk 存基准文本偏移，锚点可回切逐字校验 |
| 索引 | `bge-small-zh-v1.5`（本地权重）+ FAISS `IndexFlatIP`；jieba + BM25 | 归一化内积即余弦；索引侧零变换 |
| 检索 | 两路各取 20 候选，RRF（k=60）融合 | 两路分数量纲不同，只用排名，不归一 |
| 重排 | `bge-reranker-base` 可选，默认关闭 | CPU 上 p50 约 5.3 s，超 3 s 熔断即回退融合序 |
| 评测 | gold 锚点为「doc_id + 标题路径 + 字符区间」，按起点落入映射 | 6 项指标 + bootstrap 区间；`run_id` 由配置指纹决定 |
| 接口 / 页面 | FastAPI 五接口；两个 Streamlit 页面（8501 检索回放、8502 问答 Agent） | 无鉴权、单用户；`/ask` 与 Agent 问答都不进指标与 CI |

## 2. 目录结构

```
rag/
├── config.yaml          # 运行参数（端口、切分、检索、配额；无密钥）
├── corpus/              # 150 篇 DOCX + manifest.json（只读）
├── src/parse|split|index|retrieve|eval|store|api|generate|ui/
├── src/agent/           # 工具、两轮编排、会话记忆、配额
├── evals/               # cases.csv（100 条）、baseline.json、实验与失败归因
├── specs/               # 需求、架构、Schema、接口契约、变更单
├── scripts/             # 下载权重、CI 判定、规范化锁文件、冒烟
├── tests/               # 205 例单测
├── app.py               # Streamlit 检索回放页（8501）
├── app_agent.py         # Streamlit 问答 Agent 页（8502）
└── data/                # 运行产物：rag.db、index/、runs/、trace.jsonl（不入库）
```

## 3. 快速开始（Windows PowerShell，项目根目录）

```powershell
# 1) 建虚拟环境与依赖（torch 必须走 CPU 索引，见 requirements.txt 顶部说明）
python -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt

# 2) 环境变量（缺 RAG_DB_PATH 会直接报配置错误，不猜默认值）
$env:RAG_DB_PATH = "data\rag.db"
$env:HF_HOME = ".cache/models"

# 3) 下载模型权重（约 92MB，按官方 sha256 校验）
.venv\Scripts\python.exe scripts\download_model.py --repo BAAI/bge-small-zh-v1.5

# 4) 入库 + 建两路索引
.venv\Scripts\python.exe -m src.cli.ingest --source full
.venv\Scripts\python.exe -m src.cli.build_index
.venv\Scripts\python.exe -m src.index.bm25_index

# 5) 评测（打印指标，同时落 data/runs/<run_id>/attempt-N/）
.venv\Scripts\python.exe -m src.cli.eval
```

预计首次建索引约 200 秒（2704 条 × 512 维，CPU）；之后评测单次约 3 秒。

## 4. 常用命令

| 目的 | 命令 |
| --- | --- |
| 冒烟（可重复执行） | `.venv\Scripts\python.exe scripts\smoke.py` |
| 回归判定（等同 CI） | `.venv\Scripts\python.exe scripts\ci_check.py` |
| 起接口 | `.venv\Scripts\python.exe -m src.api.main`（默认 `127.0.0.1:8000`） |
| 起页面 | `.venv\Scripts\python.exe -m streamlit run app.py`（默认 `8501`） |
| 起问答页面 | `.venv\Scripts\python.exe -m streamlit run app_agent.py --server.port 8502` |
| trace 入库表 | `.venv\Scripts\python.exe -m src.cli.import_traces` |
| 单元测试 | `.venv\Scripts\python.exe -m unittest discover -s tests -t .` |

问答页面（8502，与 8501 各自独立进程）：

- 端口取 `config.yaml` 的 `server.ui_port_agent`（默认 `8502`）；`--server.port` 显式给同一值即可。
- 环境变量：`RAG_DB_PATH`、`HF_HOME`、`RAG_LLM_API_KEY`；模型名与接口地址取 `config.yaml` 的 `llm.model_name`／`llm.base_url`。
- 会话数据存 SQLite 的 `agent_sessions`（会话）与 `agent_turns`（轮次）两张表；首次连库自动应用迁移 `0004_agent.sql`。这两张表不被 `/search`、`/eval` 与 CI 读取。

## 5. 接口

契约见 [`specs/07-api/openapi.yaml`](specs/07-api/openapi.yaml)，说明见 [`specs/07-api/README.md`](specs/07-api/README.md)。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/search` | 检索 top-k，返回锚点、分数、`path`（dense/fused/rerank）与 `flags` |
| POST | `/eval` | 跑评测集，返回 `run_id` 与六项指标 |
| POST | `/ingest` | 增量入库，返回条目级结果（幂等） |
| GET | `/trace` | 按 `run_id` 取 trace 摘要（读 JSONL，不经 SQLite） |
| POST | `/ask` | 检索 + 生成 + 引用校验（需 `RAG_LLM_API_KEY`） |

错误码与降级标记刻意分开：`FALLBACK_BM25`、`FALLBACK_RERANK_TIMEOUT`、`FILTER_RELAXED` 是 200 响应里的 `reason`／`flags`，不是错误。

## 6. 指标与基线

基线 `r31a95a0e1de6`（150 篇 / 2704 chunk / 100 条 / 融合检索；`CHG-011` 行尾归一后由 `r6c23283f2577` 变更，六项数值未变）：

| Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 | HitRate@5 |
| --- | --- | --- | --- | --- | --- |
| 0.5600 | 0.8600 | 0.9000 | 0.7045 | 0.7543 | 0.9000 |

- `run_id` 由配置指纹（种子、模型与版本、切分参数、top_k、用例哈希、语料哈希、文档数、`normalizer_version`）决定，不含日期；同配置跨天复现得到同一 id。
- 回归口径：计数型指标任何下降即 fail，连续型允许 1e-6 容差；判定顺序为「两次 attempt 逐字节一致 → `run_id` 未变 → 指标无退化」。见 `scripts/ci_check.py`。
- 改语料、用例、切分或依赖锁属**有意变更**，须在新配置上重跑基线并走变更单，不按回归失败处理。

## 7. 已知限制

1. **固定窗口会切断条款**：44 条 `hit_rank != 1` 的用例里，8 条是「命中块与 gold 同条、正文被切到下一块」。归因与证据见 [`evals/badcases-v0.5.md`](evals/badcases-v0.5.md)。v0.3 试过的 recursive / sliding / 父子结构指标均更低，未启用。
2. **跨文档混淆 5 条**：短法规在向量空间被同主题长文档压制；文档级召回尚未实现。
3. **rerank 未启用**：bootstrap 三区间全部与 0 重叠，CPU 延迟 p50 超熔断阈值，只保留开关。
4. **`/ask` 已接真实模型跑通，但运行时仍要 key**：2026-11-21 用 `deepseek-flash`（`config.yaml` 的 `llm.model_name`，接口 `https://api.deepseek.com`）实测两条 query，均 HTTP 200、耗时 3152～7009 ms、引用校验 `valid=true` 无越界；`RAG_LLM_API_KEY` 仍须在运行时用环境变量提供，未设置时 `/ask` 返回 `CONFIG_MISSING_KEY`。
5. **CI 已在真实 runner 跑通，但首跑要装依赖**：`eval-regression` 14 步在 GitHub Actions 全绿（run `44729212536`，6m38s；缓存命中场景约 50 s）。冷缓存首次需装 torch（约 120 MB）并重建索引，耗时 6~7 分钟。
6. **v0.1 语料规模过小**（2 篇 / 34 chunk），其指标不可用于判断检索质量。

## 8. 架构

```text
入库（一次性）
  corpus 150 篇 DOCX
    -> parse      基准文本 + 段落字符区间（字符守恒校验）
    -> split      512 字固定窗口，64 字重叠
    -> SQLite     documents / chunks
    -> embed      bge-small-zh-v1.5 -> FAISS（2704 x 512 维）
    -> tokenize   jieba + BM25      -> bm25.pkl

检索（每次请求）
  query
    -> 归一化（NFKC + 空白折叠 + L2）
       |- 向量路：FAISS top-20 --+
       `- 稀疏路：BM25  top-20 --+-> RRF 融合（k=60）
    -> rerank？（默认关；CPU 上超 3 秒熔断即回退融合序）
    -> top-k（默认 5）

出口
  /search      检索结果（含 path / flags / 降级标记）
  /eval        评测 -> runs/metrics.json -> ci_check 基线比对
  /ask         检索 + 生成 + 引用校验（需 RAG_LLM_API_KEY）
  8501 页面     检索回放：两路对照 / 融合 / rerank 前后名次变化

问答 Agent（8502 页面，独立进程）
  query
    -> 规则改写    指代 / 省略 / 相对年份补全，0 次模型调用
    -> 两轮编排    第 1 轮带工具取证，第 2 轮只出答案
    -> 4 个工具    search_laws / filter_metadata / get_anchor_text / get_stats
                   （复用上面的检索链与 SQLite / manifest，不另建索引）
    -> 引用校验    答案引用须落在当轮工具结果内
    -> 会话落库    agent_sessions / agent_turns
  隔离：不写 data/runs/、不追加 data/trace.jsonl、不写 runs 表与 metrics
```

mermaid 源码（可复制到任意 mermaid 渲染器）：

```text
flowchart LR
  A["corpus DOCX 150 篇"] --> B["parse 基准文本 + 段落区间"]
  B --> C["split 512 + 64 固定窗口"]
  C --> D["SQLite documents chunks"]
  C --> E["embed bge-small-zh-v1.5"]
  C --> F["tokenize jieba + BM25"]
  E --> G["FAISS 2704 x 512"]
  F --> H["bm25.pkl"]
  Q["query"] --> I["归一化"]
  I --> G
  I --> H
  G --> J["RRF 融合 k=60"]
  H --> J
  J --> K{"rerank 默认关"}
  K -->|开| L["bge-reranker-base"]
  K -->|关| M["top-k"]
  L --> M
  M --> N["search 接口"]
  M --> O["eval 接口"]
  M --> P["8501 检索回放页"]
  M --> R["ask 接口"]
  R --> S["引用校验 规则式"]
  M --> V["8502 问答页"]
  V --> W["规则改写 0 次 API"]
  W --> X["两轮编排 每轮最多 3 个工具"]
  X --> Y["4 个工具 复用检索链"]
  Y --> I
  X --> Z["引用校验 规则式"]
  Z --> AA["agent_sessions 与 agent_turns"]
  Z -.->|不写 runs 与 trace| AB["隔离 评测与 CI 不受影响"]
  D --> O
  O --> T["runs metrics.json"]
  T --> U["ci_check 基线比对"]
```

## 9. 安全与账号

| 项 | 值 |
| --- | --- |
| 鉴权 | **无**（单机单用户，REQ-056）：接口无 token 参数、无用户维度 |
| 默认账号 | **无** |
| 密钥 | **只有 key** 从环境变量读（`RAG_LLM_API_KEY`），仓库内无密钥值；模型名与接口地址属非密钥，写在 `config.yaml` 的 `llm.model_name`／`llm.base_url`，`RAG_LLM_MODEL`／`RAG_LLM_BASE_URL` 可覆盖（`CHG-012`） |
| 删除能力 | 无删除类命令；重建索引需人工覆盖 `data/index/` |
| 外部调用 | `/ask` 与 8502 问答页面调云端模型；`eval` 与 CI **0 次**调用 |

## 10. 版本与推送

- 版本线：v0.1 闭环 → v0.2 语料与融合 → v0.3 切分/rerank 实验 → v0.4 工程化（接口、过滤、增量、CI）→ v0.5 演示与生成 → v2 多轮问答 Agent（4 个工具、两轮编排、会话记忆、8502 页面）。
- 日常只推 `dev`；v0.5 交付时按 `CHG-009` 用 `--ff-only` 把 `dev` 快进合并到 `main` 推一次，全程不 force。
- 进度与决策：`PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md`、`specs/changes/`。
