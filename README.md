# 法规检索与评测（RAG）

把 150 篇法律法规 DOCX 解析成可检索的条文片段，提供「向量 + BM25 融合」检索、可复现评测、HTTP 接口与单页演示。**单机 CPU 可跑，无外部向量库，评测回路 0 次 LLM 调用。**

一句话看结果：150 篇 / 2704 个 chunk / 100 条人工标注用例，基线 `r6c23283f2577` 的 Recall@5 **0.9000**、MRR **0.7045**。

## 1. 它做什么

| 环节 | 做法 | 关键约束 |
| --- | --- | --- |
| 解析 | `python-docx` 取段落与字符区间，表格单独计数并排除 | 字符守恒：基准文本 + 排除字符 = 可提取总量 |
| 切分 | 512 字固定窗口、64 字重叠（另备 recursive / sliding，实测更差，未启用） | chunk 存基准文本偏移，锚点可回切逐字校验 |
| 索引 | `bge-small-zh-v1.5`（本地权重）+ FAISS `IndexFlatIP`；jieba + BM25 | 归一化内积即余弦；索引侧零变换 |
| 检索 | 两路各取 20 候选，RRF（k=60）融合 | 两路分数量纲不同，只用排名，不归一 |
| 重排 | `bge-reranker-base` 可选，默认关闭 | CPU 上 p50 约 5.3 s，超 3 s 熔断即回退融合序 |
| 评测 | gold 锚点为「doc_id + 标题路径 + 字符区间」，按起点落入映射 | 6 项指标 + bootstrap 区间；`run_id` 由配置指纹决定 |
| 接口 / 页面 | FastAPI 五接口；Streamlit 单页（v0.5） | 无鉴权、单用户；`/ask` 不进指标与 CI |

## 2. 目录结构

```
rag/
├── config.yaml          # 运行参数（端口、切分、检索、配额；无密钥）
├── corpus/              # 150 篇 DOCX + manifest.json（只读）
├── src/parse|split|index|retrieve|eval|store|api|generate|ui/
├── evals/               # cases.csv（100 条）、baseline.json、实验与失败归因
├── specs/               # 需求、架构、Schema、接口契约、变更单
├── scripts/             # 下载权重、CI 判定、规范化锁文件、冒烟
├── tests/               # 121 例单测
├── app.py               # Streamlit 单页
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
| trace 入库表 | `.venv\Scripts\python.exe -m src.cli.import_traces` |
| 单元测试 | `.venv\Scripts\python.exe -m unittest discover -s tests -t .` |

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

基线 `r6c23283f2577`（150 篇 / 2704 chunk / 100 条 / 融合检索）：

| Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 | HitRate@5 |
| --- | --- | --- | --- | --- | --- |
| 0.5600 | 0.8600 | 0.9000 | 0.7045 | 0.7543 | 0.9000 |

- `run_id` 由配置指纹（种子、模型与版本、切分参数、top_k、用例哈希、语料哈希、文档数、`normalizer_version`）决定，不含日期；同配置跨天复现得到同一 id。
- 回归口径：计数型指标任何下降即 fail，连续型允许 1e-6 容差；判定顺序为「两次 attempt 逐字节一致 → `run_id` 未变 → 指标无退化」。见 `scripts/ci_check.py`。
- 改语料、用例、切分或依赖锁属**有意变更**，须在新配置上重跑基线并走变更单，不按回归失败处理。

## 7. 已知限制（如实列出）

1. **固定窗口会切断条款**：44 条 `hit_rank != 1` 的用例里，8 条是「命中块与 gold 同条、正文被切到下一块」。归因与证据见 [`evals/badcases-v0.5.md`](evals/badcases-v0.5.md)。v0.3 试过的 recursive / sliding / 父子结构指标均更低，未启用。
2. **跨文档混淆 5 条**：短法规在向量空间被同主题长文档压制；文档级召回尚未实现。
3. **rerank 未启用**：bootstrap 三区间全部与 0 重叠，CPU 延迟 p50 超熔断阈值，只保留开关。
4. **`/ask` 未用真实模型跑过**：开发机无 `RAG_LLM_API_KEY`，200 路径仅由假客户端与 service 层验证；接真 key 后需补一次真跑。
5. **CI 已在真实 runner 跑通，但首跑要装依赖**：`eval-regression` 14 步在 GitHub Actions 全绿（run `44729212536`，6m38s；缓存命中场景约 50 s）。冷缓存首次需装 torch（约 120 MB）并重建索引，耗时 6~7 分钟。
6. **v0.1 语料规模过小**（2 篇 / 34 chunk），其指标不可用于判断检索质量。
7. **架构图渲染未在本机验证**：第 8 节的 mermaid 只做了语法自查，本机无渲染环境；GitHub 页面上的实际渲染待确认。

## 8. 架构

```mermaid
flowchart LR
    A[corpus/*.docx<br/>150 篇] --> B[parse<br/>基准文本 + 段落区间]
    B --> C[split<br/>512/64 固定窗口]
    C --> D[(SQLite<br/>documents/chunks)]
    C --> E[embed<br/>bge-small-zh-v1.5]
    C --> F[tokenize<br/>jieba + BM25]
    E --> G[(FAISS<br/>2704×512)]
    F --> H[(bm25.pkl)]
    Q[query] --> I[归一化]
    I --> G
    I --> H
    G --> J[RRF 融合<br/>k=60]
    H --> J
    J --> K{rerank?<br/>默认关}
    K -->|开| L[bge-reranker-base]
    K -->|关| M[top-k]
    L --> M
    M --> N[/search/]
    M --> O[/eval/]
    M --> P[Streamlit 单页]
    M --> R[/ask/<br/>v0.5]
    R --> S[引用校验<br/>规则式]
    D --> O
    O --> T[(runs/<br/>metrics.json)]
    T --> U[ci_check<br/>基线比对]
```

## 9. 安全与账号

| 项 | 值 |
| --- | --- |
| 鉴权 | **无**（单机单用户，REQ-056）：接口无 token 参数、无用户维度 |
| 默认账号 | **无** |
| 密钥 | 只从环境变量读（`RAG_LLM_API_KEY`／`RAG_LLM_BASE_URL`／`RAG_LLM_MODEL`），仓库内无密钥 |
| 删除能力 | 无删除类命令；重建索引需人工覆盖 `data/index/` |
| 外部调用 | 仅 `/ask` 调云端模型；`eval` 与 CI **0 次**调用 |

## 10. 版本与推送

- 版本线：v0.1 闭环 → v0.2 语料与融合 → v0.3 切分/rerank 实验 → v0.4 工程化（接口、过滤、增量、CI）→ v0.5 演示与生成。
- 日常只推 `dev`；v0.5 交付时按 `CHG-009` 用 `--ff-only` 把 `dev` 快进合并到 `main` 推一次，全程不 force。
- 进度与决策：`PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md`、`specs/changes/`。
