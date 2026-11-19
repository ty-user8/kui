# 模块划分

## 1. 目录树

```
rag/
├── config.yaml                  # 运行参数（无密钥）
├── configs/                     # 实验配置覆盖（grid / ab）
├── data/                        # 运行产物：rag.db、trace.jsonl、runs/、pdf-refs/
├── evals/
│   ├── cases.csv                # 评测集（gold 锚点）
│   ├── rubric.md                # 生成质量人工观察维度（v1 不启用自动评分）
│   └── tools/
│       └── fill_anchors.py       # 锚点回填（按 5.3 从 DOCX 抽取 anchor_text 与区间）
├── specs/                       # 规格与变更单
├── src/
│   ├── config.py                # 配置加载：YAML + 环境变量，校验必填项
│   ├── cli/
│   │   ├── ingest.py            # 入库入口
│   │   ├── eval.py              # 评测入口（双输出）
│   │   └── import_traces.py     # trace JSONL → SQLite（v0.4）
│   ├── parse/
│   │   ├── docx_reader.py       # DOCX → 基准文本 + 段落序列
│   │   └── anchor.py            # 标题路径、条号识别（样式 + 正则双判）
│   ├── split/
│   │   ├── fixed.py             # 固定长度切分（v0.1）
│   │   ├── recursive.py         # 按标题递归（v0.3）
│   │   └── sliding.py           # 句子滑窗 + overlap（v0.3）
│   ├── index/
│   │   ├── embedder.py          # 模型加载、批量编码、L2 归一化
│   │   ├── faiss_index.py       # 建库、保存、加载、检索
│   │   └── bm25_index.py        # jieba 分词 + BM25Okapi（v0.2）
│   ├── retrieve/
│   │   ├── dense.py             # 向量单路
│   │   ├── hybrid.py            # 两路并行 + RRF（v0.2）
│   │   ├── rerank.py            # cross-encoder 重排（v0.3）
│   │   └── normalize.py         # 查询归一化（v0.3）
│   ├── eval/
│   │   ├── mapping.py           # gold 锚点 → chunk 映射
│   │   ├── metrics.py           # Recall / MRR / nDCG / HitRate
│   │   └── bootstrap.py         # 置信区间（v0.3）
│   ├── store/
│   │   ├── db.py                # 连接（RAG_DB_PATH）、事务、迁移执行
│   │   └── dao.py               # documents / chunks / runs / eval_cases / traces
│   ├── trace.py                 # JSONL 写入与字段裁剪（≤80 字摘要）
│   ├── api/                     # v0.4
│   │   ├── main.py              # FastAPI 应用与启动
│   │   ├── routes.py            # /search /eval /ingest /trace
│   │   └── errors.py           # 错误码 → HTTP 响应
│   └── generate/                # v0.5
│       ├── ask.py               # 检索 → 拼 Prompt → 生成
│       └── citation.py          # 引用 id 落在 top-k 的规则式校验
├── app.py                       # Streamlit 入口（v0.5）
├── tests/
│   ├── __init__.py
│   ├── test_hybrid.py           # RRF 融合单测（8 例）
│   ├── test_trace.py            # trace 写入与 excerpt 单测（6 例）
│   └── test_parent.py           # 父子折叠与锚点映射单测（4 例）
├── scripts/
│   ├── normalize_lock.py        # 规范化 requirements.lock.txt 的本地 wheel 行，打印 deps_sha256
│   ├── download_model.py        # 从官方 API 元数据下载模型权重并按 sha256 校验
│   └── smoke.py                 # 冒烟脚本（v0.5）
└── requirements.txt / requirements.lock.txt
```

## 2. 模块职责

| 模块 | 职责 | 输入 → 输出 | 版本 | 不得做的事 |
| --- | --- | --- | --- | --- |
| `config` | 读 `config.yaml` 与环境变量，校验端口、DB 路径、模型名、切分参数 | 文件 + env → 配置对象 | v0.1 | 不得写默认密钥；缺必填项必须报错 |
| `parse.docx_reader` | 按 5.3.1 生成基准文本与段落序列（含每段 `[start,end)`） | DOCX 路径 → 基准文本、段落表、元数据 | v0.1 | 不得 strip、不得合并空白、不得读表格 |
| `parse.anchor` | 样式 + 正则双判标题，跳过目录区，识别条号 | 段落表 → 标题路径、条号 → 段落映射 | v0.1 | 不得依赖固定样式名（145 篇无 `Heading`） |
| `split.*` | 按策略切分，产出带 `char_start/char_end` 的 chunk | 基准文本 + 段落表 → chunk 列表 | v0.1（一种）/ v0.3（三种） | 不得改变偏移语义；不得跨文档拼接 |
| `index.embedder` | 加载模型、批量编码、L2 归一化 | 文本列表 → 向量矩阵 | v0.1 | 不得在评测回路发起网络请求（首次下载除外，需预热步骤） |
| `index.faiss_index` | 建库、持久化、top-k 检索 | 向量 + chunk_id → 结果 | v0.1 | 不得用未归一化向量建 `IndexFlatIP` |
| `index.bm25_index` | 分词建倒排、按 query 检索 | 文本 + query → 结果 | v0.2 | 不得对未分词中文直接 split |
| `retrieve.*` | 单路 / 混合 / RRF / rerank / 归一化 | query + 索引 → 排序结果 | v0.1~v0.3 | 不得在检索层写指标口径 |
| `eval.mapping` | 锚点 → chunk（起点落入 / parent 覆盖） | 锚点 + chunk 区间 → chunk_id 或 unmapped | v0.1 | 不得静默跳过映射失败 |
| `eval.metrics` | Recall / MRR / nDCG / HitRate 纯计算 | 命中排名 → 指标 | v0.1 | 不得调用任何模型 |
| `store` | 建表迁移、事务写入、查询 | DDL / 行 → DB | v0.1 | 不得在事务外写 chunks |
| `trace` | 逐 query 写 JSONL（追加写，正文截断 80 字）；明细的**唯一权威** | 阶段结果 → JSONL 行 | v0.2 | 不得把 SQLite 表当权威；不得写完整原文与密钥 |
| `cli.import_traces` | 从 JSONL 导入摘要到 `traces` 表，记 `source_run_id`／`imported_at` | JSONL → 表行 | v0.4 | 不得反向覆盖 JSONL；重复导入须幂等 |
| `cli.*` | 参数解析、编排 usecase、输出 | argv → stdout / 文件 | v0.1 | 不得内嵌业务逻辑 |
| `api.*` | HTTP 契约、错误码映射 | 请求 → JSON 响应 | v0.4 | 不得绕过 usecase 直接调 domain |
| `generate.*` | 生成答案与引用校验 | query + top-k → 答案 + 引用 | v0.5 | 不得参与指标与 CI |

## 3. 依赖方向

```
cli / api / app                （入口层）
   ↓ 只能调用
usecases = cli 内的编排函数     （读 store → 调 domain → 写 trace/metrics）
   ↓ 只能调用
parse / split / index / retrieve / eval     （domain）
   ↓ 只能调用
config / store / trace                      （infra）
```

- 单向向下，禁止反向 import；`domain` 不感知 HTTP 与文件路径细节。
- `eval.metrics`、`eval.mapping` 为纯函数模块，不 import `store`，便于单测。
- `parse` 不 import `split`：切分对解析结果只读。

### 3.1 trace 的读写分工

| 角色 | 路径 | 读者 |
| --- | --- | --- |
| 权威明细 | `data/trace.jsonl` | `eval.py`、失败案例归类、`/trace` 接口 |
| 派生摘要 | `traces` 表（`source_run_id` + `imported_at`） | SQL 聚合、报表 |

`eval.py` 与失败案例归类**直接读 JSONL**，不经 SQLite——避免导入步骤引入的时间差与不一致；表只在需要聚合查询时由 `import_traces` 生成。追加写默认单进程；并发时用标准库平台文件锁（`fcntl.flock`／`msvcrt.locking`）包住整行写，不引入新依赖。

## 4. 变更影响地图

| 改动位置 | 直接影响 | 必须同步 |
| --- | --- | --- |
| `parse.docx_reader`（基准文本规则） | 全部 chunk 偏移、全部锚点 | 重导基准文本、重填全部 `char_start/end`、重跑全部基线、出变更单 |
| `parse.anchor`（标题/条号规则） | `heading_path`、`article_no`、锚点定位 | 重跑 ingest；锚点回切校验 |
| `split.*`（切分参数） | chunk 边界、chunk 数 | 属实验变量，只记实验表；固定为正式配置后变更走单 |
| `index.embedder`（换模型） | 全部向量与指标 | 走选型变更单 + 重跑全部基线 + 更新 `run_id` |
| `retrieve.*`（融合权重、k、候选数） | 排序结果 | 实验变量；正式化后走单 |
| `eval.metrics`（指标定义） | 全部历史数字不可比 | 走变更单；`CHANGELOG-DECISIONS.md` 记录 |
| `store` DDL | 全部读写路径 | 新增迁移脚本，不改历史脚本 |
| `api` 契约 | 下游调用方 | 走变更单 + 更新 `07-api/` |
