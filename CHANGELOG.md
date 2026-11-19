# 变更流水

## 2026-11-16

- **CHG-001** 输入格式范围由「PDF/DOCX/MD」收窄为「DOCX + 官方同源 PDF（仅解析对照）」：已确认，执行中（规格落点见 `01-requirements.md` / `02-scope.md` / `04-tech-choice.md`）。
- 建立 `specs/constitution.md`（步骤 0）、`CHANGELOG-DECISIONS.md`（D-001~D-011）、`PROGRESS.md`、`.gitignore`。
- 步骤 1 · Specify：归档 `specs/00-source/`（技术方案原件 + 校验值 + SOP 版本记录），产出 `specs/01-requirements.md`（REQ-001~056）、`specs/02-scope.md`、`evals/cases.csv`（30 条候选锚点，24 dev + 6 holdout）、`evals/rubric.md`（v1 不启用自动评分）。
- CHG-001 规格落点：`01-requirements.md` REQ-007 / REQ-009，`02-scope.md` §5 两条「不做」与 §9 差异说明。
- 步骤 2 · Clarify：8 项歧义澄清并回写规格——`01-requirements.md` 改 REQ-006（失败率 >10% 中止）、REQ-017/017a（空结果语义、分数原值）、REQ-028（双输出）、REQ-032（`metrics.json` 比对）、REQ-033/036/037（人工确认前置、非零退化判据、有意变更重跑基线），新增 REQ-057/058（同名多版本、索引行数断言）；`02-scope.md` 改 §1/§2/§4/§5/§9。
- 新增 `specs/changes/CHG-002-corpus-expansion.md`（三项分列：语料 150 篇、评测集 100 条、`run_id` 语料指纹），状态待确认。
- 新增决策 D-012～D-018。
- G1 补齐：`01-requirements.md` 5.3 节扩写为「基准文本构造表（tab／软换行／域代码／脚注／超链接／图片／表格）+ 索引侧等长映射规则 + SHA-256 计算范围」，新增 REQ-002a；`02-scope.md` 新增 2.2 v0.1 DoD（6 项，前 3 项硬门禁）；`constitution.md` 两处未决措辞清零。
- `CHG-002` 按意见改写：项二明确 `candidate` 只指 query、锚点由工具抽取；§3.5 澄清「144 倍」为 chunk 数倍数（文档新增 148 篇）、2600 chunk 与 5 MB 标注为估算并挂 B6 实测。
- G1 冻结：`00-source/`、`constitution.md`、`01-requirements.md`、`02-scope.md`、`evals/cases.csv`、`evals/rubric.md` 记录 SHA-256 快照于 `PROGRESS.md`。
- `01-requirements.md` 5.3.2 补两条：`idx2base` 保序约束（禁止重排）与断言按 `normalizer_version` 分支；`normalizer_version` 写入 `run_id`。
- `CHG-002` 追加项四（`anchor_text` 回切保留段内 `\n`）与项五（表格排除守恒校验），状态转「已定稿，待用户确认」。
- 步骤 3 · Plan：产出 `03-architecture.md`、`04-tech-choice.md`、`05-modules.md`、`06-schemas/`（README + `0001_init.sql`／`0002_parents.sql`／`0003_runtime.sql`）、`07-api/`（README + `openapi.yaml`）、`08-prompts/README.md`、`09-state.md`、`10-security.md`、`11-errors.md`、`config.yaml`、`requirements.txt`。
- 校验：`config.yaml` 通过 YAML 解析；3 个迁移脚本在内存库连续执行成功，产出 8 张表并写入 `schema_migrations` 版本 1/2/3。
- 新增 `specs/changes/CHG-003-reproducibility-and-trace-path.md`（8 处口径修正，随 G2 确认）。据此改动：`run_id` 去日期只由配置指纹决定、复现验证改 `attempt-1/attempt-2` 目录、`-2/-3` 仅人工并列保留、`runs.deps_sha256`、trace 读取路径（JSONL 权威／表为派生）、`chars_total` 以 CHG-002 批准为生效前提。
- 同步修订：`01-requirements.md` REQ-031/032/036、`02-scope.md` §2.2、`03-architecture.md` §2、`04-tech-choice.md` §2+新增 §3、`05-modules.md` §3.1、`06-schemas/`（README + `0001_init.sql` + `0003_runtime.sql`）、`07-api/README.md`、`09-state.md` §4.1/§5。迁移脚本改动后重新在内存库执行通过：`runs` 15 列含 `deps_sha256`，`traces` 10 列含 `source_run_id`/`imported_at`。

## 2026-11-17

- G2、`CHG-002`、`CHG-003` 确认，两单状态改为已确认。
- 依赖获取改法（D-019）：解析官方 `download-r2` 直链 + 断点续传 + 官方 SHA-256 校验 + 本地 wheel 安装；`04-tech-choice.md` §3 记直链、wheel 名、sha256、实测速率与防回退说明；`requirements.txt` 注明 torch 须走 CPU 索引或本地 wheel；`requirements.lock.txt` 将固定 `torch==2.15.0+cpu`。
- 步骤 4 · Tasks：产出 `specs/tasks.md`（29 个任务，v0.1 固定 2 篇 / 30 条人工标注）。
- 步骤 5 · Analyze：修复 5 项——9 条 EARS 条款补挂任务（覆盖 60/60）、`11-errors.md` 补 `INVALID_REQUEST` 与 `RUN_NOT_FOUND`、`10-security.md` 白名单补官方 wheel 下载与本地安装、`06-schemas/` §5 补「实现前可整体改写」例外、`requirements.txt` 补 CPU 索引说明。
- `faiss-cpu 1.16.0` 安装完成并通过 `IndexFlatIP` 检索自检；numpy 2.5.4 兼容。torch 仍在下（约 11 MB / 220 MB），依赖未就绪。
- 新增 `specs/changes/CHG-004-venv-and-gate-order.md`：建项目 venv、依赖装进 venv、解释器口径统一 `.venv\Scripts\python.exe`、`requirements.txt` 禁 `-r`、依赖门禁起点改 T-006、G3 后先重跑 Analyze。
- 建立 `.venv`（Python 3.13.14）；venv 内装 numpy 2.5.5、faiss-cpu 1.16.0、torch 2.15.0+cpu、sentence-transformers 3.4.1、python-docx 1.2.0、PyYAML 6.0.3、pydantic 2.14.3；四件套 import 与 `IndexFlatIP` 自检全部通过。
- torch wheel 下载完成并校验：126,626,022 字节，sha256 与官方 `086f79c7…c619` 一致；改 6 段并行后聚合吞吐约 215 KB/s（D-020）。
- 生成 `requirements.lock.txt`（40 行，torch 行规范为 `torch==2.15.0+cpu`）并计算 `deps_sha256 = ae2cc83b…d6f3`。

## 2026-11-18

- G3 确认（`tasks.md` 任务拆分、版本归属、DoD 通过）。
- 冻结快照表改为「旧值 + 新值 + 依据单号」：`constitution.md` 10472→10687（CHG-004）、`01-requirements.md` 22871→23243（CHG-003）、`02-scope.md` 9942→10033（CHG-003）；未改文件保持单值。
- `CHG-004` 状态由「已执行」回退为「待确认」，实施内容移入 §9 执行记录，按 SOP 第五部分状态流流转。
- 新增 `scripts/normalize_lock.py`（幂等，输出改写行数与 `deps_sha256`）；`04-tech-choice.md` §3.1 写明 Verify 比对锁文件文本哈希、不重跑 `pip freeze`；新增 `specs/12-release-checklist.md`，C-06/C-07 承载该规则，v0.1 专项 10 项。
- `05-modules.md` 目录树补 `scripts/`。
- 订正 wheel 体积：实际 126,626,022 字节 ≈ 120.8 MB，此前「约 220 MB」为进度估算错误；`PROGRESS.md` 与 D-019／D-020 同步改写。
- 步骤 5 Analyze 重跑：9 项核对全部通过（EARS 60/60、config 键、错误码、变更单状态、快照自洽、锁哈希、目录树引用、检查单引用、版本段落）。
- `CHG-004` 状态流转：G3 确认转「已确认」，依 §9 执行记录转「已完成」；`PROGRESS.md` 中原「G3 已确认」与「004 待确认」并存的状态已消除。
- 放行 Implement，按 T-001 → T-004 开工；本批不构成完整小版本，不 push。
- T-001：新增 `src/config.py`、`src/__init__.py`。配置从 `config.yaml` + 环境变量加载并校验范围；`RAG_DB_PATH` 缺失时 `require_db_path()` 抛 `ConfigError`，CLI 自检返回退出码 2。
- T-002：新增 `src/parse/docx_reader.py`、`src/parse/__init__.py`。按 5.3.1 生成基准文本与段落区间，表格/图片不计入，字符守恒自校验；专利法 210 段 11319 字符、代理条例 71 段 3606 字符。
- T-003：新增 `src/parse/anchor.py`。样式 + 正则双判标题、目录副本按「保留最后一次出现」去重、条号索引与区间；专利法 8 标题/82 条（目录丢弃 9），代理条例 5 标题/32 条。
- T-004：新增 `evals/tools/fill_anchors.py` 与 `evals/anchor-review.md`。30/30 条锚点回填成功，独立重解析复核四项全通过；`anchor_status` 保持 `candidate`，等人工确认。
- T-004 口径纠正（D-021）：`anchor_text` 由「该条首句」改为「区间回切的整段文本」，恢复 5.3.4 严格逐字比对；工具默认模式只填区间并校验既有文本、不一致即中止不写，`--reset-anchor-text` 为一次性纠正开关。首句版本下 8 条不一致已全部重置，30/30 逐字一致。
- `evals/cases.csv` 快照更新为 12303 B / `fe2b8eb8d86e8fe7`（依据 T-004 回填；中间态 12004 / `18a09fdaa4d6f326` 作废）。
- T-004 补充：核对表新增「整段文本」列（`anchor_text` 全文，核对对象），「首句（前 60 字）」列保留作扫读；重出后 30 行 9 列结构一致。
- T-004 补充：`fill_anchors.py` 新增 `--check` 只读模式，只校验不写 `cases.csv` 与核对表；实测调用前后两文件 mtime 与大小均未变，退出码 0。Verify 阶段固定用该模式，避免改动快照值。
- 新增 `specs/changes/CHG-005-anchor-text-wording.md`：修订 `01-requirements.md` 5.1 的 `anchor_text` 口径，状态待确认，v0.1 Verify 前完成。
- `CHG-005` 确认并执行：`01-requirements.md` 5.1 该行改为「`[char_start, char_end)` 回切的整段文本 / 逐字取自基准文本，必须与区间回切结果完全一致」；文件 23243 → 23319 字节、`44ea860f…` → `461b49f3…`；单号状态流转至已完成并附执行记录。
- 30 条锚点由用户本人改为 `confirmed`（`cases.csv` 12303 B / `1c162f3a46da238a`）；快照表按「冻结值 + 当前值 + 依据」一次性更新两行，中间态哈希一并留痕。
- `fill_anchors.py --check` 只读复核通过：30 条回切与 `anchor_text` 逐字一致，复核前后三份文件哈希未变。
- `CHG-001/002/003` 状态行补注「规格层已落地，剩余执行/回归随 v0.2/v0.4 任务完成」，各单末节列剩余执行清单；`CHG-004/005` 补状态流转说明（跳过「执行中」的原因为执行先于确认）。
- 修 `src/parse/anchor.py` 直接运行报 `ModuleNotFoundError`：路径注入移到模块顶部，`python src/parse/anchor.py` 与 `-m` 均可运行。
- T-005：新增 `src/split/fixed.py`、`src/store/db.py`、`src/store/dao.py`、`src/cli/ingest.py` 及三个包 `__init__`。入库结果 `documents=2`、`chunks=34`（26 + 8）、`source_format` 唯一值 `docx`、迁移 1/2/3 应用、重复入库仍 2/34。
- `PROGRESS.md` 语料规模段更新为基准文本 14925 字与实测 34 chunk，并标注与 `02-scope.md` §2「约 18」的差异待变更单处理。
- T-005 DoD 补回滚实测：复制库后于事务内写入并注入异常，计数 3/35 → 回滚 2/34、无残留行、原库未改。
- HuggingFace 可达性验证通过（`/api/models` 200）；`bge-small-zh-v1.5` 权重落 `.cache/models/bge-small-zh-v1.5/`：12 文件 96,407,485 字节（91.9 MB），`model.safetensors` 95,827,648 字节 / sha256 `354763b9…` 与官方一致，6 段并行 372.5 s；`HF_HUB_OFFLINE=1` 可加载并编码（维度 512、L2 范数 1.0）。
- 新增 `scripts/download_model.py` 与决策 D-022：`huggingface_hub` 因 CDN 剥离 `X-Repo-Commit`／`X-Linked-Etag` 抛 `FileMetadataError`，改走官方 API 元数据 + Range 并行 + sha256 校验。
- 新增 `specs/changes/CHG-006-scale-figures.md`（语料规模估算口径修正），状态待确认。
- `CHG-006` 确认并执行完毕：`02-scope.md` §2 改 14925 字 / 34 chunk / 基线 14.7%、`03-architecture.md` §5 改实测与口径、`tasks.md` T-010 DoD 预估数字降为参考；`CHG-002` 仅加指针行、正文未覆写；索引体积由 T-006 实测 71,459 字节回填第 5 项；单号转已完成并附执行记录。
- 快照表新增 `03-architecture.md`、`tasks.md` 两行（G2/G3 阶段产出，冻结值记「—」），`02-scope.md` 依据补 CHG-006。
- T-006：新增 `src/index/embedder.py`、`src/index/faiss_index.py`、`src/cli/build_index.py`、`src/index/__init__.py`；`0001_init.sql` 的 `runs` 增 `model_weights_sha256`（本地权重指纹，防权重被替换后 `run_id` 不变）。索引 34 条 512 维向量、归一化偏差 1.19e-07、体积 71,459 字节（69.8 KB），权重 sha256 `354763b9…` 入 `index-meta.json`。
- 订正：`runs` 表不新增权重指纹列（无 Schema 变更单），指纹只写 `data/index/index-meta.json` 的 `weights_sha256`；`0001_init.sql` 已回退，`tasks.md` T-006 DoD 与 `PROGRESS.md` 措辞同步。
- T-007：新增 `src/eval/mapping.py`、`src/eval/metrics.py`、`src/eval/runner.py`、`src/retrieve/dense.py`。映射只按字符区间（不使用 `chunks.article_no`）；多 chunk 命中按「任一命中即 hit、每条只计一次」。实测 `unmapped=0`、6 条多 chunk 映射，Recall@5 0.9667、MRR 0.8317、nDCG@5 0.8647。
- 新增 `evals/badcases.md`：BC-001 = C015 未进 top-5（真失败）、BC-002 = C010 命中 rank 1 但 chunk 混装多条（现象），均指向 v0.3 切分与父子 chunk。
- T-008：新增 `src/cli/eval.py`、`src/store/dao.py` 的 `upsert_run`。`run_id` 只由配置指纹决定（不含日期），产物落 `data/runs/<run_id>/attempt-N/{metrics.json,timing.json,meta.json}`；`attempt-N/meta.json` 记 `weights_sha256`（读 `index-meta.json`）、`deps_sha256`、`config_string` 等，`run_id` 规范串与 `runs` 表结构均未改。实测两次运行 `run_id` 不变、两份 `metrics.json` 逐字节一致（544 字节 / `a83df586…`），`metrics.json` 内注明单 gold 下 Recall@k 与 HitRate@k 同值。
- T-009 全链路排查：`compileall` → `ingest`（2 篇 / 34 chunk）→ `build_index`（34 向量 / 71,459 字节）→ `eval`×2（`run_id` 不变，attempt-1~4 同哈希）→ `fill_anchors --check`（30 条逐字一致），全部退出码 0；DoD 六项逐条成立。
- `12-release-checklist.md` 勾选 v0.1 专项 8 项与 C-06／C-07，均附实测依据。

## v0.2（进行中）

- T-010 全量入库：`--source full` 150 篇、`documents=150`、`chunks=2704`、失败 0、4.3 s；基准文本 1,191,197 字；同名多版本 3 组 6 篇按 `doc_id` 各占一行。
- 修 `docx_reader._table_chars` 的去重 bug：原先用 `str(id(cell._tc))`，元素回收后地址复用导致不同单元格被误判重复，表格字符只统计到 86；改为直接以 `_tc` 元素入集合后实测 2205，与 CHG-002 项五估算一致，`chars_total` 同步由 6951 修正为 9070。
- 全量索引重建：2704×512、体积 5,675,789 字节（5.42 MB）、编码 203 s；参考基线 `run_id=rcc22c5c40628`（30 条 confirmed）Recall@1 0.7333、Recall@5 0.9667、MRR 0.8150、nDCG@5 0.8524。
- 按 CHG-006 回填 `02-scope.md` §2（新增 v0.2 全量实测段）与 `03-architecture.md` §5（chunk 2704 / 1,191,197 字），快照表同步。
- T-012：新增 `src/retrieve/hybrid.py`（`fuse` 纯函数 + `HybridRetriever`，某一路缺失自动退化为单路）与 `tests/test_hybrid.py`（8 例单测，验证 `score = Σ 1/(k+rank)`、排序、截断、降级、同路去重、`k` 非正报错）；`05-modules.md` 目录树补 `tests/`。三条查询两路与融合均非空，前两条两路 top1 一致。
- T-011：新增 `src/index/bm25_index.py`（jieba 分词 + `BM25Okapi`，只持久化分词结果与参数、加载时重建，避免 `python -m` 下 pickle 类路径写成 `__main__` 的跨进程加载失败）；2704 chunk、索引 5,442,894 字节；两路检索均非空，前两条查询两路 top1 一致。
- 依赖：`jieba 0.42.1`、`rank_bm25 0.2.2` 装入 venv（jieba 为源码包，构建耗时约 13 分钟）。
- 标注起草完成：`cases.csv` 达 100 条（30 `confirmed` + 70 `candidate`，C031~C100，dev 80 / holdout 20，覆盖 36 篇文档）；难度分布同义改写 40、否定 25、术语 12、列举 11、数值 10、编号敏感 1、条件 1。
- `anchor-review.md` 说明改为参数化：「当前 100 条，最终 100 条全部 `confirmed` 后再进 T-015 指标」。
- 标注：新增 32 条 `candidate`（C031~C062，dev 26 / holdout 6，覆盖劳动法、医疗保障法、原子能法、反家暴法、反洗钱法、反跨境腐败法、反食品浪费法、商业银行法、商标法两版、国境卫生检疫法、国家赔偿法）；`fill_anchors.py` 增 `--fill-empty`，只填新增空值并回填空 `heading_path`，其余行仍逐字校验。
