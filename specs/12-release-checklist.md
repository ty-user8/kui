# 上线检查单

本清单自 v0.1 起逐版增补；未到 Verify 阶段的条目状态记为「待执行」，不预先勾选。每版完成后按本版段落逐条核对，结果与 `eval.py` 输出、回归对比一起提交。

## 通用项（每版都查）

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| C-01 | 输入材料未改：SOP、技术方案、`corpus/**`（含 `manifest.json` 的 `file_name`）、`collect.py` | 与 `specs/00-source/README.md` 记录的大小与 SHA-256 比对 | 通过：技术方案 29920 / `76b18223…` 未变；manifest 150 条与 150 个文件一致（抽样 3 篇 sha256 与记录相符） |
| C-02 | 规格快照与 `PROGRESS.md` 的「当前值」一致 | 逐文件 `sha256sum` | 待执行 |
| C-03 | 变更单状态无「已执行」等非模板状态 | 读 `specs/changes/` 各单头部 | 通过：001~003 已确认、004~007 已完成 |
| C-04 | 交付说明文本按附录 C 扫描，扫描范围仅限 C.1 适用对象 | 关键词扫描 `src/**`、`README.md`、脚本用法文本 | 通过：`src/`、`scripts/` 扫「本文/初稿/配套/低配额版/本次改动/由…生成」零命中 |
| C-05 | 密钥未进入任何文件与 git 历史 | `git grep -iE "sk-\|api_key="` 无命中；只出现变量名 | 通过：`src/`、`scripts/`、`specs/`、`config.yaml` 扫描零命中 |
| C-06 | 环境一致性：`deps_sha256` 等于 `runs` 表记录值 | 读 `requirements.lock.txt` 文本哈希，**不重跑 `pip freeze`** | 通过：`ae2cc83b…d6f3` 与 `runs`／`meta.json` 一致 |
| C-07 | `requirements.lock.txt` 已规范化（torch 行为 `torch==2.15.0+cpu`） | 跑 `scripts/normalize_lock.py`，输出「改写行数: 0」 | 通过：改写行数 0，幂等 |
| C-08 | 无删除类命令入口 | 检查 CLI 参数与接口清单 | 通过：CLI 无 delete/rm/purge；`unlink()` 仅见于 trace 自检临时文件与下载分片清理 |
| C-09 | 默认账号表写「无」 | `README.md` 存在该节且值为「无」 | 未开始：`README.md` 属 v0.5（T-029），届时补 |

## v0.1 专项

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| V01-01 | 30 条锚点全部 `anchor_status=confirmed`，未确认数 0 | 读 `evals/cases.csv` 计数 | 通过：30/30，未确认 0（2026-11-18） |
| V01-02 | 30 条 `char_start`/`char_end` 非空，回切文本与 `anchor_text` 逐字一致 | 回填工具日志 | 通过：`fill_anchors.py --check` 30 条逐字一致，区间无空值 |
| V01-03 | 锚点可映射率 100%，`unmapped=0` | `eval.py` 输出 | 通过：`unmapped=0`、`unconfirmed=0`、多 chunk 映射 6 条 |
| V01-04 | 同一 `run_id` 连跑两次，`attempt-1/` 与 `attempt-2/` 的 `metrics.json` 逐字节一致 | `diff` 两文件 | 通过：attempt-1~4 均 544 字节、sha `a83df586…` |
| V01-05 | 两次运行 `run_id` 相同（不含日期） | 对比两次输出 | 通过：四次均为 `r98aa795a93cf` |
| V01-06 | 评测回路 LLM 调用 0 次 | 清空 `RAG_LLM_API_KEY` 后完整跑通 | 通过：key 未设置跑通，`src/` 无 openai 引用 |
| V01-07 | 指标齐全：Recall@1/3/5、MRR、nDCG@5、HitRate@5 | `eval.py` 输出 | 通过：0.7667／0.8333／0.9667／0.8317／0.8647／0.9667 |
| V01-08 | v0.1 语料仍为 2 篇 DOCX（未被 v0.2 的全量配置污染） | `documents` 行数 = 2 | 通过：`doc_count=2`，`chunks=34`，`source_format` 仅 docx |
| V01-09 | `requirements.lock.txt` 与 `deps_sha256` 已记录 | 读文件与 `PROGRESS.md` | 已就绪（2026-11-17） |
| V01-10 | 四件套 import 冒烟通过（numpy / faiss / torch / sentence-transformers） | `.venv\Scripts\python.exe -c "import numpy, faiss, torch, sentence_transformers"` | 已就绪（2026-11-17） |

## v0.2 专项

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| V02-01 | 全量语料入库：150 篇、2704 chunk、失败 0 | `ingest --source full` 输出 | 通过：`documents=150`、`chunks=2704`、失败 0、4.3 s |
| V02-02 | 100 条用例全部 `confirmed`，id 与 query 无重复、编号连续 | 读 `cases.csv` 统计 | 通过：100/100，C001~C100 连续 |
| V02-03 | `unmapped=0`、`unconfirmed=0` | 最终运行 `metrics.json` | 通过 |
| V02-04 | 复现：同配置两次 `metrics.json` 逐字节一致（**用 dev 集，不碰 holdout**） | `diff` 两份文件 | 通过：`-dev-hybrid` attempt-1/2 一致 |
| V02-05 | `run_id` 不含日期；实验后缀不参与复现判定 | 读 `meta.json` 的 `config_string` | 通过：`r5e4a62714526`，后缀 `-dev-*` 仅并列保留 |
| V02-06 | 对比表含单路与融合两组 | `evals/experiments-v0.2.md` | 通过：B/C 两组 dev 对比 + D 最终 |
| V02-07 | holdout 只在最终运行出现一次 | 检查各组 `--split` 参数 | 通过：B/C 为 `--split dev`，仅 D 为 `all` |
| V02-08 | 两路索引均存在且条数一致 | 读 `index-meta.json` 与 `bm25-meta.json` | 通过：向量 2704×512（5.68 MB）、BM25 2704（5.44 MB） |
| V02-09 | 评测回路 0 次 LLM 调用 | 不设 `RAG_LLM_API_KEY` 跑通 | 通过 |

## v0.3 专项

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| V03-01 | 三种切分可切换且 chunk 数互不相同 | `ingest --strategy {fixed,recursive,sliding}` 各跑一次 | 通过：2704 / 3402 / 2918 |
| V03-02 | 父子结构：只索引 child、命中折叠到 parent、锚点映射到 parent | `ingest --parent-child` + 单测 + 映射统计 | 通过：v0.1 的 30/30 映射到 parent；折叠去重单测 4 例 |
| V03-03 | rerank 默认关闭，启用需显式开关 | 读 `config.yaml` 的 `use_rerank` | 通过：`false`；`eval` 需 `--rerank on` 才启用 |
| V03-04 | bootstrap 给出区间，区间重叠不得声明提升 | `python -m src.eval.bootstrap` | 通过：R@1 [+0.0000,+0.0375]、R@5 [0,0]、MRR [−0.0031,+0.0187] 三项 overlap，文档未写「提升」 |
| V03-05 | 延迟基线已记录 p50/p95 与索引体积 | `evals/experiments-v0.3.md` | 通过：检索 p50 5,288.8 ms／p95 7,385.7 ms；索引体积三档均已记 |
| V03-06 | 三处否决有据且默认路径未变 | 对照 `experiments-v0.3.md` 与 `config.yaml` | 通过：标题注入、rerank、recursive/sliding 与父子结构均未启用，基线切分 fixed 不变 |
| V03-07 | 查询归一化：全半角与空白折叠后结果一致 | 单测 `tests/test_normalize.py` | 通过：5 例（繁转简按 D-023 不适用） |

## v0.4 专项

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| V04-01 | 元数据过滤四类字段生效（doc_id／category／authority／日期区间），候选层 oversample×5 | 接口实测 `filters.category=行政法规` | 通过：返回 5 条全为行政法规；日期区间与 doc_id 由单测覆盖（7 例） |
| V04-02 | 三条降级各自可达且标记 | 单测 + 实测 | 通过：仅保留 `bm25.pkl` → `FALLBACK_BM25`；注入 50 ms 延迟 → `FALLBACK_RERANK_TIMEOUT`；`publish_date_from=2099-01-01` → `FILTER_RELAXED` 并返回未过滤结果 |
| V04-03 | 增量入库幂等 | `ingest --source full` 连跑两次 | 通过：两次均「待写入 0／内容未变 150」，`documents=150`、`chunks=2704` 不变 |
| V04-04 | `--force` 重写不产生重复行 | `ingest --source full --force` | 通过：待写入 150 但行数仍为 150/2704，`ingest_log` 记 `insert/content_changed` |
| V04-05 | 质量报告含 `excluded_chars` 与条号覆盖 | 读 `data/ingest-report.json` | 通过：字符 1,191,197、排除 2,205（0.19%）、含表格文档 1 篇、条号覆盖 53.8% |
| V04-06 | 四接口响应符合 `07-api/openapi.yaml` | 起服务后按契约逐字段校验 | 通过：`/search`、`/eval`、`/ingest`、`/trace` 及 2 个错误响应共 6 个响应全通过；`flags` 与 `excerpt nullable` 已在契约中声明 |
| V04-07 | `/ingest` 重复调用幂等（REQ-048） | 连调两次 `POST /ingest` | 通过：两次均 `documents=150`／`chunks=2704`／`skipped=2` |
| V04-08 | 错误码逐条可达、不裸 500 | 逐条触发 | 通过：400 `INVALID_REQUEST`（空 query、`top_k=99`、未知 filter 键、非法 split、非法 source）、404 `RUN_NOT_FOUND`、409 `INDEX_EMPTY`（单测构造索引缺失）；500 类仅由码表与异常处理器覆盖，未构造生产级故障 |
| V04-09 | 接口无鉴权参数（REQ-056） | 读 `app.openapi()` | 通过：无 `securitySchemes`／`bearerAuth`／`apiKey`，四个接口均无 token 字段 |
| V04-10 | trace 导入幂等且记 `source_run_id`／`imported_at` | `import_traces` 连跑 + `--rebuild` | 通过：首次写 10 行、二次写 0 跳 10、行数稳定 10；`--rebuild` 清 4 写 10；单测 9 例 |
| V04-11 | CI 判定顺序（REQ-036）：复现一致 → `run_id` 未变 → 指标无退化 | 本地 `scripts/ci_check.py` | 通过（**仅本地**）：PASS ①attempt-2/3 均 576 字节逐字节一致、②`run_id=r6c23283f2577`、③六项 0.5600/0.8600/0.9000/0.7045/0.7543/0.9000；人为劣化基准 → 退出码 1 并列出 2 项退化 |
| V04-12 | GitHub Actions workflow 可执行 | `.github/workflows/eval.yml` | **未验证**：本地只解析了 YAML 结构与 12 个步骤，逻辑与 `ci_check.py` 同源；**未在真实 GitHub runner 上跑过**，缓存命中率与首次安装 torch 的耗时均未实测 |
| V04-13 | 默认检索链与 `CHG-007` 基线一致（`CHG-008`） | 默认配置重算全量 100 条 | 通过：六项与基线逐项相同；`/search` 返回 `path=fused` |
| V04-14 | 单元测试全绿 | `unittest discover -s tests -t .` | 通过：100 例（接口 23 + 导入 9 + CI 10 + 页面 11 + 其余 47） |

说明：T-026（Streamlit 单页）归属 v0.5、按用户指示提前实施，**不进 v0.4 DoD**，故不在本表；其自检记录见 `PROGRESS.md` T-026 行。
