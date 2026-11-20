# 任务清单

约定：一次只做一个任务（规则 #3），完成后跑对应测试 + Doer-Verifier 自检 + 更新 `PROGRESS.md`。**v0.1 固定 2 篇 DOCX、30 条人工标注**（CHG-002 §0），不随 v0.2 的语料扩展而变。

## v0.1 最小闭环（2 篇 / 30 条 / 纯命令行）

| 编号 | 目标 | 涉及文件 | 依赖 | EARS | DoD |
| --- | --- | --- | --- | --- | --- |
| T-001 | 配置加载与项目骨架 | `src/config.py`、`config.yaml`、`src/__init__.py` | — | REQ-053 | 读 YAML + 环境变量；缺 `RAG_DB_PATH` 报错；端口与切分参数来自配置 |
| T-002 | DOCX → 基准文本 + 段落序列 | `src/parse/docx_reader.py` | T-001 | REQ-001、REQ-002、REQ-006、REQ-007、REQ-008 | 按 5.3.1 生成文本；`text_sha256` 稳定；表格/图片不入基准；损坏文件报 `PARSE_FAILED` |
| T-003 | 标题路径与条号识别 | `src/parse/anchor.py` | T-002 | REQ-003、REQ-004、REQ-005 | 专利法识别 8 章（非 16）；代理条例走 `Heading` 样式；无条号文档降级为段落锚点 |
| T-004 | 锚点回填工具（v0.1 首个交付） | `evals/tools/fill_anchors.py` | T-002、T-003 | REQ-002、REQ-027、REQ-030 | 按 `doc_id`+`article_no` 抽取 `anchor_text` 与区间并回写 CSV；回切逐字一致；30 条全部有区间 |
| T-005 | 固定长度切分 + 入库 | `src/split/fixed.py`、`src/store/db.py`、`src/store/dao.py`、`src/cli/ingest.py` | T-002、T-003 | REQ-009、REQ-010、REQ-012、REQ-054、REQ-055、REQ-058 | 2 篇入库，`chunks` 行数可复算；事务失败回滚；`documents` 行数 = 清单条数；索引内 `source_format` 只有 `docx` |
| T-006 | embedding 与 FAISS 索引 | `src/index/embedder.py`、`src/index/faiss_index.py`、`src/cli/build_index.py` | T-005 | REQ-002a、REQ-011、REQ-018 | 向量模长与 1 偏差 < 1e-6；索引侧零变换（`normalize_index(base)==base`）；索引可保存/加载；索引内向量数 = `chunks` 行数（34）；导出索引体积实测值并回填 CHG-006 第 30 行；权重指纹写入 `data/index/index-meta.json` 的 `weights_sha256`，防本地权重被替换后指标悄然变化（`runs` 表不加列） |
| T-007 | 单路检索与锚点映射 | `src/retrieve/dense.py`、`src/eval/mapping.py`、`src/eval/metrics.py` | T-006、T-004 | REQ-017、REQ-017a、REQ-021、REQ-027、REQ-030 | 返回锚点与分数；空结果 `NO_MATCH`；锚点按「起点落入」映射；`unmapped` 显式计数 |
| T-008 | eval 双输出与 `run_id` | `src/cli/eval.py` | T-007 | REQ-028、REQ-031、REQ-032 | `run_id` 不含日期、同配置恒定；写 `attempt-N/{metrics.json,timing.json,meta.json}`；六项指标齐全 |
| T-009 | 复现验证与 DoD 核对 | 无新增文件 | T-008 | REQ-032、REQ-029 | 连跑两次 `run_id` 不变、两份 `metrics.json` diff 为空；无 API key 跑通；记录 `deps_sha256` |

**v0.1 门禁**：T-004 产出的 30 条锚点须由人工改 `confirmed`；未确认不得进入 T-007 之后的评测判定（`02-scope.md` §2.2）。

## v0.2 可信 A/B

| 编号 | 目标 | 涉及文件 | 依赖 | EARS | DoD |
| --- | --- | --- | --- | --- | --- |
| T-010 | 语料扩至 150 篇（CHG-002 项一） | `config.yaml`、`src/cli/ingest.py` | T-005 | REQ-006、REQ-057、REQ-058 | 全量 ingest 成功；`chunks` 实测值以 T-010 运行记录为准（预估数字不作验收条件），完成后回填 `02-scope.md`／`03-architecture.md` 的规模数字；同名不同版本各占一行、不被合并；纯向量基线在新语料上重跑 |
| T-011 | BM25 + jieba | `src/index/bm25_index.py` | T-010 | REQ-019 | 两路结果均非空；中文按词切分 |
| T-012 | RRF 融合 | `src/retrieve/hybrid.py` | T-011 | REQ-020 | 单测构造两路排名验证 `score = Σ 1/(k+rank)` |
| T-013 | trace JSONL | `src/trace.py` | T-008 | REQ-038、REQ-039、REQ-041 | 字段齐全；`excerpt` ≤80；不含密钥与用户目录；追加写用平台锁 |
| T-014 | 评测集补至 100 条（+70 候选） | `evals/cases.csv` | T-004 | REQ-033、REQ-037 | 新增 70 条 `v0.2`（14 holdout）；全部 `confirmed` 后才计入指标 |
| T-015 | 2~3 组实验与基线重跑 | `configs/`、`data/runs/` | T-012、T-014 | REQ-034、REQ-037 | 对比表含单路/融合；holdout 只跑一次；替换基线走变更单 |

## v0.3 检索质量

| 编号 | 目标 | 涉及文件 | 依赖 | EARS | DoD |
| --- | --- | --- | --- | --- | --- |
| T-016 | 三种切分策略 | `src/split/recursive.py`、`src/split/sliding.py` | T-005 | REQ-014 | 三种可切换，chunk 数不同且均成功 |
| T-017 | 父子 chunk | `src/split/parent.py`、`0002` 迁移 | T-016 | REQ-015 | 只索引 child；命中返回 parent；同 parent 去重；锚点映射到 parent |
| T-018 | 标题路径注入 | `src/index/embedder.py` | T-017 | REQ-016 | 路径拼在正文前；超长截断；前后指标对比 |
| T-019 | rerank、查询归一化与覆盖率曲线 | `src/retrieve/rerank.py`、`src/retrieve/normalize.py` | T-012 | REQ-022、REQ-024、REQ-026 | 覆盖率曲线定候选数；超时降级；分数只做组内比较；全半角/简繁归一后结果一致 |
| T-020 | bootstrap 与延迟基线 | `src/eval/bootstrap.py` | T-019 | REQ-035、REQ-040 | 输出区间与 p50/p95；区间重叠不得声明提升 |

## v0.4 工程化

| 编号 | 目标 | 涉及文件 | 依赖 | EARS | DoD |
| --- | --- | --- | --- | --- | --- |
| T-021 | 元数据过滤 + 三条降级 | `src/retrieve/dense.py`、`src/retrieve/hybrid.py` | T-019 | REQ-023、REQ-024、REQ-025 | 过滤可用；三条降级各有对应用例与 flag |
| T-022 | 增量入库、去重、质量报告 | `src/cli/ingest.py`、`0003` 迁移 | T-010 | REQ-013、REQ-058 | 内容哈希去重；`ingest_log` 记录；质量报告含 `excluded_chars`（CHG-002 项五） |
| T-023 | 状态机编排与四接口 | `src/api/*`、`src/cli/*` | T-021 | REQ-042、REQ-043、REQ-044、REQ-046、REQ-047、REQ-048、REQ-056 | Schema 校验通过；错误码逐条可达；重复 `/ingest` 幂等；接口无鉴权参数 |
| T-024 | trace 导入 | `src/cli/import_traces.py` | T-013、T-023 | REQ-045 | 记 `source_run_id`/`imported_at`；重复导入幂等 |
| T-025 | CI 回归 | `.github/workflows/eval.yml` | T-023 | REQ-036 | 用缓存向量跑纯计算评测；非零退化 fail；不重装 torch |

## v0.5 交付演示

| 编号 | 目标 | 涉及文件 | 依赖 | EARS | DoD |
| --- | --- | --- | --- | --- | --- |
| T-026 | Streamlit 单页 | `app.py` | T-023 | — | 输入 query，展示两路召回、rerank 前后、命中 chunk 与指标。**归属 v0.5**；2026-11-20 按用户指示提前实施，**不进 v0.4 DoD** |
| T-027 | `/ask` 生成层与引用校验 | `src/generate/*`、`specs/08-prompts/ask.system.v1.md` | T-023 | REQ-049、REQ-050、REQ-051、REQ-052 | 30 秒熔断；引用越界标记；缺 key 报错；不进指标 |
| T-028 | 失败案例批量归因 | `data/`、`PROGRESS.md` | T-019、T-027 | — | 15~20 条 bad case 归类；假设由人固化为规则 |
| T-029 | README、架构图、冒烟脚本 | `README.md`、`scripts/smoke.py` | T-026 | — | 冒烟可重复执行且自动清理；环境要求/快速开始/默认账号（无）齐全 |

## 并行与顺序

- 可并行：T-002 与 T-004 的前置部分（回填工具可先按 5.3 写解析）；T-016 的三种切分实现可并行；T-026 与 T-027 可并行。
- 严格串行：T-004 → 人工确认 → T-007 起的所有评测判定；T-008 → T-009；T-010 → T-011 → T-012 → T-015。
- **依赖就绪门禁**：从 **T-006** 起需要模型权重（embedding）。T-001~T-005 不依赖模型，可在 torch 与 sentence-transformers 就绪前完成；三者 import 冒烟未通过前不得开始 T-006。
- **G3 确认后的顺序**：先重跑一次 Analyze（复核本文件有无改动），结果经用户看过再进 Implement；不得确认后直接按 T-001 开工。
- 所有实现命令用 `.venv\Scripts\python.exe`（CHG-004）。
- 版本推进门槛：指标可复现 + 代码可运行无半成品 + 决策写入 `CHANGELOG-DECISIONS.md`。
