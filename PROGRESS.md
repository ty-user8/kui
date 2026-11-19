# 进度

## 当前阶段

v0.2 进行中（2026-11-18）。T-010 完成：150 篇 / 2704 chunk / 全量索引 5.42 MB，规模已按 CHG-006 回填。标注 100/100 全部 `confirmed`（覆盖 36 篇文档，dev 80 / holdout 20），可进 T-015。T-011（BM25 + jieba）在实施。

## Implement 进度

| 任务 | 文件 | 自检结果 |
| --- | --- | --- |
| T-001 | `src/config.py`、`src/__init__.py` | `compileall` 通过；缺 `RAG_DB_PATH` 返回配置错误并退出码 2；有变量时打印切分/端口/配额，切分 512/64、top_k 5、端口 8000/8501、超时 30 秒、上限 50 次 |
| T-002 | `src/parse/docx_reader.py`、`src/parse/__init__.py` | 专利法 210 段 / 基准 11319 字符；代理条例 71 段 / 3606 字符；两者字符守恒「基准 + 排除 = 可提取总量」通过；`text_sha256` 各自稳定 |
| T-003 | `src/parse/anchor.py` | 专利法标题 8（目录副本丢弃 9）、条号 82、无重复条号；代理条例标题 5（走 `Heading` 样式）、条号 32；无条号文档识别为 0 标题 0 条且不报错 |
| T-004 | `evals/tools/fill_anchors.py`、`evals/anchor-review.md` | 30/30 回填成功、0 失败；独立重解析逐条复核：前缀、条号、边界、区间一致四项全通过；核对表已加「整段文本」列（首句列保留扫读）；`--check` 只读模式验证不写文件（mtime 与大小不变）；`anchor_status` 仍全为 `candidate` |
| T-004b | `src/parse/anchor.py` 入口 | 修直接运行报 `ModuleNotFoundError`：路径注入提到模块顶部；`python src/parse/anchor.py` 与 `-m` 两种方式均可运行，输出一致 |
| T-005 | `src/split/fixed.py`、`src/store/db.py`、`src/store/dao.py`、`src/cli/ingest.py` | `documents=2`、`chunks=34`（26 + 8）、`source_format` 唯一值 `docx`；重复入库仍为 2/34；字符守恒随库落 `chars_total` / `excluded_chars`；迁移 1/2/3 已应用；`data/rag.db` 176 KB |
| T-005 回滚证据 | 复制 `data/rag.db` 为 `data/rag-rollback-check.db`，事务内写入后注入 `RuntimeError` | 事务内 3/35 → 回滚后 2/34，`rollback-demo` 残留 0 行，原库未被改动 |
| T-006 | `src/index/embedder.py`、`src/index/faiss_index.py`、`src/cli/build_index.py`、`src/index/__init__.py` | 向量 34 条、维度 512、归一化最大偏差 1.19e-07（阈值 1e-06）；索引可保存并重新加载（ntotal 34 = ids 34）；权重指纹写入 `data/index/index-meta.json` 的 `weights_sha256`（`model.safetensors` = `354763b9…a026`），`runs` 表未加列；索引体积 71,459 字节（faiss.idx 69,994 + ids.json 1,465）；两条查询返回到锚点与标题路径 |
| T-007 | `src/eval/mapping.py`、`src/eval/metrics.py`、`src/eval/runner.py`、`src/retrieve/dense.py` | 30 条全部映射成功（`unmapped=0`）、`unconfirmed=0`、多 chunk 映射 6 条（gold 起点落在 64 字符 overlap 内）；Recall@1 0.7667／@3 0.8333／@5 0.9667，MRR 0.8317，nDCG@5 0.8647，HitRate@5 0.9667；映射只按字符区间，未用 `chunks.article_no`；唯一未命中为 C015，多 chunk 命中按「任一命中即 hit、每条只计一次」 |
| T-008 | `src/cli/eval.py`、`src/store/dao.py`（`upsert_run`） | `run_id=r98aa795a93cf` 两次运行不变；`attempt-1`／`attempt-2` 两份 `metrics.json` 逐字节一致（544 字节，sha `a83df586…`）；`meta.json` 含 `weights_sha256`（取自 `index-meta.json`）、`deps_sha256`、`config_string`、`corpus_sha256`；`runs` 表一条记录，`metrics_json` 与文件同源；`metrics.json` 内注明「单 gold 下 Recall@k 与 HitRate@k 同值」 |
| T-010 | `config.yaml`（`--source full`）、`src/parse/docx_reader.py`（表格计数修复） | 150 篇全部入库：`documents=150`、`chunks=2704`、失败 0、耗时 4.3 s；基准文本合计 1,191,197 字；同名多版本 3 组 6 篇各占一行；表格文档 `excluded_chars=2205`（修复前 86）；全量索引 2704×512、体积 5,675,789 字节（5.42 MB）、编码 203 s；参考基线 `run_id=rcc22c5c40628`（30 条 confirmed）Recall@1 0.7333／@5 0.9667、MRR 0.8150、nDCG@5 0.8524 |
| T-013 | `src/trace.py`、`tests/test_trace.py` | 13 个字段齐全（`run_id`~`flags`）；`excerpt` 恒为 80 码点、换行折空格；追加写用独立 `.lock` 文件 + 平台锁（POSIX `flock`／Windows `msvcrt.locking`），4 线程×25 行并发写 100 行全部可解析；自检 3 条 trace 无 `sk-` 与用户目录；单测 6 例通过 |
| T-012 | `src/retrieve/hybrid.py`、`tests/test_hybrid.py`、`tests/__init__.py` | RRF 融合 `score = Σ 1/(k+rank)`；单测 8 例全过（单路、双路求和、排序、截断、单路缺失、双路空、同路重复、k 非正）；三条查询两路与融合均非空，前两条两路 top1 一致（`00012`／`00002`），融合 top1 分数 0.03279（两路均第 1） |
| T-011 | `src/index/bm25_index.py` | 2704 chunk 建 BM25，体积 5,442,894 字节（存分词结果 + 参数，加载时重建 `BM25Okapi`）；jieba 分词正确（「发明专利权的期限是几年」→ 发明/专利权/的/期限/是/几年）；三条查询 BM25 与向量两路均返回非空，前两条两路 top1 一致（`00012`／`00002`）；建索引 4.4 s |
| T-009 | 全链路排查与 DoD 逐条核对（无新增源文件） | 链路 `compileall` → `ingest` → `build_index` → `eval`×2 → `fill_anchors --check` 全部退出码 0；重建索引后 `run_id` 仍 `r98aa795a93cf`，attempt-1~4 的 `metrics.json` 均 544 字节、sha `a83df586…`；DoD 六项逐条成立（30/30 confirmed、区间无空、`unmapped=0`、四份一致、0 次 LLM、六项指标齐全）；`12-release-checklist.md` 勾选 10 项 |

## 步骤 5 复核结果（G3 确认后重跑，2026-11-18）

| 核对项 | 结果 |
| --- | --- |
| EARS 覆盖 | 定义 60、`tasks.md` 引用 60、差集为空 |
| `config.yaml` 键引用 | 7 个被引用键全部存在 |
| 错误码对齐 | `07-api` 12 个码在 `11-errors` 中全部可查 |
| 变更单状态 | 4 单均为模板内状态（001/002/003 已确认，004 待确认）——此列为 2026-11-18 复核时的状态；`004` 已于同日流转至「已完成」 |
| 规格快照 | `constitution`／`01`／`02` 三份当前值与表中「新值」一致 |
| 锁文件哈希 | 实测 `ae2cc83b…d6f3` 与记录一致 |
| 目录树引用 | `05-modules` 所列 `scripts/normalize_lock.py` 存在 |
| 检查单引用 | `12-release-checklist.md` 已含规范化脚本与 Verify 口径 |
| 版本段落 | v0.1~v0.5 五段齐全 |

## 步骤 5 核对结果（落盘）

| 项 | 结果 |
| --- | --- |
| EARS 条款覆盖 | 定义 60 条，`tasks.md` 引用 60 条，未覆盖 0、未定义 0 |
| 修复 1 | 9 条未被引用的条款（REQ-002a/009/026/043/044/046/047/056/057）补挂到 T-005/006/010/019/023 |
| 修复 2 | `11-errors.md` 补 `INVALID_REQUEST`、`RUN_NOT_FOUND` |
| 修复 3 | `10-security.md` 白名单补官方 wheel 下载与本地安装 |
| 修复 4 | `06-schemas/` §5 补「v0.1 实现前可整体改写」例外 |
| 修复 5 | `requirements.txt` 补 CPU 索引说明与「禁止 `-r`」声明 |
| config 键引用 | 规格引用的 7 个键在 `config.yaml`（46 个叶子键）中全部存在 |
| 配额一致性 | `constitution.md` 0/50/30 ↔ `config.yaml`（`llm.max_calls=50`、`timeout_seconds=30`）一致 |
| 记忆版本归属 | `09-state.md` v1 无状态 ↔ `02-scope.md` 不做清单一致 |
| `08-prompts` 豁免 | v0.1~v0.4 豁免、v0.5 启用，与 `tasks.md` T-027 一致 |

## 已完成

| 阶段 | 产出 | 状态 |
| --- | --- | --- |
| P0 核对表 | 六项决策 | 已确认，落入 `constitution.md` |
| 变更单 | `CHG-001-input-format-scope.md` | 已确认 |
| 步骤 0 | `specs/constitution.md`、`CHANGELOG-DECISIONS.md`（D-001~D-011）、`.gitignore` | G0 通过 |
| 步骤 1 | `specs/00-source/`、`01-requirements.md`（60 条 EARS）、`02-scope.md`、`evals/cases.csv`（30 条候选）、`evals/rubric.md` | G1 已冻结 |
| 步骤 2 | 8 项歧义澄清（D-013~D-018）+ G1 补齐三项（5.3 扩写、REQ-002a、v0.1 DoD） | 已回写并冻结 |
| 步骤 3 | `03-architecture.md`、`04-tech-choice.md`、`05-modules.md`、`06-schemas/`（3 个迁移脚本）、`07-api/`（README + openapi.yaml）、`08-prompts/`、`09-state.md`、`10-security.md`、`11-errors.md`、`config.yaml`、`requirements.txt` | G2 通过 |
| 变更单 | `CHG-002-corpus-expansion.md`（五项） | 已确认 |
| G2 补齐 | `CHG-003-reproducibility-and-trace-path.md`（八处口径修正） | 已确认 |
| 步骤 4 | `specs/tasks.md`：29 个任务，按 v0.1~v0.5 分段，每条含目标/文件/依赖/EARS/DoD；v0.1 固定 2 篇 + 30 条人工标注 | G3 通过 |
| 步骤 5 | 一致性核对：REQ 覆盖 60/60、config 键引用全存在、错误码两侧对齐、权限白名单补 wheel 下载、迁移脚本例外说明 | 已修复 5 项 |
| G3 补齐 | 冻结快照改为「旧值 + 新值 + 依据单号」；`CHG-004` 按状态流流转至「已完成」、执行记录单列；锁文件规范化落为 `scripts/normalize_lock.py`，Verify 口径写入 `04-tech-choice.md` §3.1 与 `12-release-checklist.md` C-06/C-07 | 已完成 |
| Implement | T-001 `src/config.py`；T-002 `src/parse/docx_reader.py`；T-003 `src/parse/anchor.py`；T-004 `evals/tools/fill_anchors.py` + `evals/anchor-review.md` | T-001~T-004 完成，T-005 起未开工 |

## 冻结快照（随已确认变更单演进）

G1 于 2026-11-16 冻结。此后 `constitution.md`、`01-requirements.md`、`02-scope.md` 经 CHG-003／CHG-004 修订，下表同时保留冻结值（旧）与当前值（新）并标注依据；无变更的文件只列一次。**比对口径：Verify 以「新值」为准，旧值仅作追溯。**

| 文件 | 冻结时字节 / SHA-256 前 16 | 当前字节 / SHA-256 前 16 | 依据 |
| --- | --- | --- | --- |
| `specs/00-source/RAG检索项目技术方案_2026-11-14.md` | 29920 / `76b18223f807fff0` | 同左（未改） | 只读归档 |
| `specs/00-source/README.md` | 1837 / `9300d2cfc74c4c44` | 同左（未改） | 只读归档说明 |
| `specs/constitution.md` | 10472 / `69f9565c50c9edf5` | 10687 / `ed9214b57aedc3e4` | CHG-004：工程约定增「Python 解释器」行 |
| `specs/01-requirements.md` | 22871 / `ffe192c2895c71b5` | 23319 / `461b49f31bfee035` | CHG-003：5.3.2 保序约束与 `normalizer_version` 分支、REQ-031/032/036；CHG-005：5.1 的 `anchor_text` 口径改「区间回切的整段文本」 |
| `specs/02-scope.md` | 9942 / `1b856b27b710ec7f` | 10588 / `a2b94c1eedc76cf7` | CHG-003：§2.2 改 attempt 目录；CHG-006：§2 改 v0.1 实测值；T-010：新增 v0.2 全量实测段（150 篇 / 2704 chunk / 1,191,197 字） |
| `specs/03-architecture.md` | —（G2 阶段产出，未入 G1 快照） | 5558 / `c39cc1d12a2cffed` | CHG-006：§5 chunk 数改实测；T-010：回填全量 2704 / 1,191,197 字 |
| `specs/tasks.md` | —（G3 阶段产出） | 8010 / `e0b8673d2316b06b` | CHG-006：T-010 DoD 降为参考；T-006 DoD 增索引体积回填与权重指纹 |
| `evals/cases.csv` | 9687 / `01e558389a817d9b` | 44530 / `9c8a51c764ffb166`（100 条全部 `confirmed`） | T-004 回填区间与整段文本；用户本人把 30 条 `anchor_status` 改为 `confirmed`。中间态：12004 / `18a09fdaa4d6f326`（首句版，作废）、12303 / `fe2b8eb8d86e8fe7`（已回填未确认） |
| `evals/rubric.md` | 1084 / `92d874d9ff3659c1` | 同左（未改） | — |

`01-requirements.md` 与 `02-scope.md` 在此后如需改动，一律走变更单并在 `CHANGELOG-DECISIONS.md` 记因。

## P0 决策结论

1. 成功指标：只认可复现，不设 Recall 绝对门槛（D-005）。
2. 用户与场景：面试演示为主，单轮法规检索；检索不到返回空并说明。
3. 数据合规：允许出域（公开法规、无 PII）；trace 只存锚点 + 80 字摘要（D-009）。
4. 能力边界：A1 收窄为 DOCX + 官方同源 PDF（仅对照），见 CHG-001 / D-004。
5. 权限安全：只读 `corpus/docs`，只写 `data/`、`.cache/`，全程无删除。
6. 工作流形态：纯确定性流水线（D-001）。

## 语料实测结论

| 事实 | 数据 | 规格含义 |
| --- | --- | --- |
| 单格式 | 150 篇全为 `.docx` | 触发 CHG-001 |
| 标题样式缺失 | 仅 5/150 有 `Heading` 样式 | 标题路径需样式 + 正则双判（D-008 / REQ-004） |
| 目录污染 | 专利法章名行 16 行，去重后 8 章 | 章节识别须跳过目录区（REQ-003） |
| 无条号文档 | 3 篇为人大《决定》《若干规定》 | 解析与锚点需容错分支（REQ-005） |
| 篇幅跨度 | 143~34434 字，条数 0~306 | 切分参数须覆盖长短两端 |

## v0.1 语料规模实测

| 项 | 值 |
| --- | --- |
| 专利法 | 82 条，正文 5925 字，条长 18~295 字（中位 68） |
| 专利代理条例 | 32 条，正文 2191 字，条长 23~131 字（中位 64） |
| 合计 | 114 条；条文本合计 8116 字，基准文本合计 14925 字（含前言、章名、分隔符） |
| 实测 chunk | 专利法 26 + 代理条例 8 = **34 个**（512 / overlap 64，步长 448） |

已知影响：chunk 总数 34，Recall@5 的随机基线约 15%，指标区分度有限。v0.1 的目标是跑通闭环与可复现，不用它判断检索质量。

**待核对的口径差异**：`02-scope.md` §2 写「按 512 字 / overlap 64 切分约 18 个 chunk」，实测 34。差异原因：18 是按条文本 8116 字估算，实际切分对象是基准文本 14925 字。该数字属冻结规格内的事实描述，修订需变更单，未擅自改。

## 环境现状

- **项目 venv 已建并就绪**：`.venv\Scripts\python.exe`（Python 3.13.14，pip 26.1.2）；`.venv/` 已在 `.gitignore` 排除。
- venv 内版本：numpy 2.5.5、faiss-cpu 1.16.0、**torch 2.15.0+cpu**（`cuda.is_available()=False`）、sentence-transformers 3.4.1（transformers 4.57.6）、python-docx 1.2.0、PyYAML 6.0.3、pydantic 2.14.3。
- **四件套 import 冒烟通过**（同进程一次跑通）：numpy / faiss / torch / sentence-transformers；`IndexFlatIP` 自检命中正确。
- torch wheel：官方 `download-r2` 直链，**126,626,022 字节 ≈ 120.8 MB**，sha256 `086f79c7…c619` 与官方索引一致；6 段并行下载聚合约 215 KB/s（D-020）。此前「约 220 MB」为进度估算错误，已订正。
- 锁文件：`requirements.lock.txt` 40 行，`deps_sha256 = ae2cc83b6ae374acfc373bd8fdd19c1454ae62a045d58019f2e1377c1790d6f3`；torch 行由 `scripts/normalize_lock.py` 规范为 `torch==2.15.0+cpu`（幂等，重跑输出改写行数 0）。Verify 比对锁文件文本哈希，不重跑 `pip freeze`。
- **模型权重已就绪**：`.cache/models/bge-small-zh-v1.5/`，12 个文件、96,407,485 字节（91.9 MB）；`model.safetensors` 95,827,648 字节、sha256 `354763b9b1357bc9…` 与官方 LFS 元数据一致；6 段并行下载 372.5 s（聚合约 258 KB/s）。中断留下的 20,971,520 字节 `.part` 分片已清理，目录现为 92 MB。
- **权重可用性已验证**：`HF_HUB_OFFLINE=1` 下加载 0.2 s、编码 2 条 0.09 s、维度 512、L2 范数 1.0。
- **HF 下载路径偏差**：`huggingface_hub` 因 CDN 剥离 `X-Repo-Commit`／`X-Linked-Etag` 抛 `FileMetadataError`，改用 `scripts/download_model.py`（D-022）；模型目录为普通目录，加载走本地路径。
- **索引已建**：`data/index/` 下 `faiss.idx`（69,994 字节）+ `ids.json`（1,465 字节）+ `index-meta.json`，合计 71,459 字节；34 条 512 维向量，`ntotal` 与 id 映射一致；`index-meta.json` 记模型名、revision、权重 sha256、向量数、体积、`normalizer_version`。
- **已知现象**：固定长度切分把部分条款切断，查询「发明专利权的期限是几年」的 top-3 未含第四十二条所在段（chunk 00012 以「当予以驳回。第三十九条…」开头）。v0.1 不做切分优化，T-007 用锚点映射量化，v0.3 再改切分。
- 工具解释器内的 faiss／numpy 不作依赖依据，也未进锁文件（CHG-004）。
- v0.2 的 `jieba`、`rank_bm25`、v0.4 的 `fastapi`／`uvicorn`、v0.5 的 `streamlit` 尚未安装。
- 迁移脚本在内存库执行通过：8 张表，`runs` 15 列含 `deps_sha256`，`traces` 10 列含 `source_run_id`／`imported_at`。
- 目录尚未 `git init`；按版本提交规则在 v0.1 完成时建仓并只做本地 commit。

## 下一步

1. 等人工把 `evals/cases.csv` 的 30 条 `anchor_status` 改为 `confirmed`（核对表见 `evals/anchor-review.md`）。
2. 确认后继续 T-005（固定长度切分 + 入库），再 T-006 起用 embedding。
3. v0.1 全部任务完成 + 全链路排查 + 用户确认后才按 push 规则执行；本批不构成小版本，不 push。

## 仓库与发布

| 项 | 值 |
| --- | --- |
| 初始化 | `git init -b main`；提交 `a9ee1afce1f9696581e7051cca11103676fad46e`（v0.1 全量） |
| 分支 | `dev` 已建并处于其上；`main` 未 push |
| 忽略 | `.gitignore` 排除 `.venv/`、`.cache/`、`data/`（`git check-ignore` 逐条确认） |
| 密钥 | 全工作区扫描 `sk-`／私钥头／`api_key=`／`password=` 无命中，无 `.env` 类文件 |
| 待提交文件 | 221 |
| 远端 | `origin` = `https://github.com/ty-user8/kui.git` |
| 已推送 | `dev`：v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，其后为记录类提交；远端仅此一个分支（记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准） |
| 未推送 | `main`（本地停在 `a9ee1af`，未 push、未 force） |

## 待确认

- v0.1 已推送完成（`origin/dev` = `587cdf9`），下一步待你决定是否开 v0.2（T-010 语料扩至 150 篇，需先有 CHG-002 项一的执行与标注人力安排）。
- 其余非阻塞事项：`CHG-001/002/003` 仍为「已确认」并附剩余执行清单（随 v0.2/v0.4 落地后转已完成）；`02-scope.md` 全量规模数字待 T-010 回填。
