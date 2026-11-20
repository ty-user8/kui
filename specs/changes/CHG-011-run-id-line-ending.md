# 变更单 #011：行尾统一 LF，`run_id` 指纹跨平台一致（基线 run_id 变更）

- 日期 / 发起方：2026-11-20 / 用户
- 状态：**已完成**（用户 2026-11-20 授权「按 A 的行尾根治方案修复」→ 执行完毕转「已完成」）

## 背景

CI 第 14 步「回归判定」报 `FAIL ①：data/runs/r6c23283f2577 下只有 0 个 attempt`（run `44727235979`）。根因不在复现性，也不在指标：

- `run_id` 由 `build_run_id` 按配置指纹算出，指纹里含 `cases_sha256`（`evals/cases.csv`）与 `corpus_sha256`（`corpus/metadata/manifest.json`），算的是**文件字节**。
- 这两个文件（以及另外 52 个文本文件）在仓库索引里是 LF，在本机工作区是 CRLF：`git ls-files --eol` 显示 `i/lf w/crlf`，本机 `core.autocrlf=true`，仓库此前没有 `.gitattributes`。
- CI 检出 LF，于是两个哈希与基线不同：本机 `7f94fe58…`／`c861678a…` → CI `27fc0a88…`／`010e011f…`，`run_id` 由 `r6c23283f2577` 变成 `r31a95a0e1de6`。CI 把 attempt 写进新目录，`ci_check` 按基线 id 找不到目录，报 ①。

即：指纹与检出配置耦合，同一份内容在两台机器上算出两个 id。三种处置中（A 解耦、B 只在 CI 对齐 CRLF、C 在 Linux 重测基线）用户选 A 的根治路线。

## 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| 行尾策略 | 无 `.gitattributes`；本机 `core.autocrlf=true` 导致工作区 CRLF | 新增 `.gitattributes`：`* text=auto eol=lf`；工作区 54 个文本文件逐字节 `CRLF→LF` 归一 |
| `git ls-files --eol` | 53 个 `i/lf w/crlf` + 1 个 `i/lf w/mixed` + 68 个 `i/lf w/lf` | 122 个文本文件全部 `i/lf w/lf`；150 个 DOCX 仍 `i/-text w/-text`（未触碰） |
| 基线 `run_id` | `r6c23283f2577` | **`r31a95a0e1de6`**（`evals/baseline.json` 的 `run_id` 与 `effective_from` 已改） |
| 六项指标数值 | 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 | **不变**（重测逐位相同，未调任何数值与容差） |
| 仓库内容（git blob） | — | **不变**：归一的是工作区字节，索引 blob 本来就是 LF，`git diff --cached` 为空 |

## 影响范围分析

- 波及规格：`evals/baseline.json`（`run_id`、`effective_from`）、`specs/12-release-checklist.md`（C-06/C-07 证据行随新 run）、`PROGRESS.md`（环境现状、基线、推送记录）、`HANDOFF.md`、`CHANGELOG.md`。
- 波及模块与文件：`.gitattributes`（新增）；54 个文本文件的工作区字节（源码、规格、脚本、`evals/cases.csv`、`corpus/metadata/*.json|csv`）；`tests/test_ci_check.py`、`tests/test_ui_view.py` 里钉住基线 id 的两处断言随本单改为 `r31a95a0e1de6`（断言强度不变，仍钉具体 id）；无源码逻辑改动。
- 波及接口／Schema：无。
- 评测用例：内容未改，`evals/cases.csv` 的字节变了（去掉 101 个 CR），故 `cases_sha256` 变；这是本次变更的预期结果，也是 `run_id` 变化的原因。
- 已知副作用：**工作区字节指纹全部变了**。`PROGRESS.md` 的冻结快照表与 `specs/00-source/README.md` 里记录的「文件大小 + SHA-256」是 CRLF 时点的值，现已与工作区不符（git blob 哈希未变，可用于溯源）。是否按「LF 口径」重新登记一次，待用户定，本单不擅自改冻结记录。
- 成本／性能／安全：无。git 层面仅新增一个属性文件；CI 缓存键不含这些文件的字节，无需清缓存。

## 执行方案

1. 新增 `.gitattributes`：`* text=auto eol=lf`（仓库 blob 已是 LF，此条覆盖 Windows 上 `core.autocrlf=true` 的检出转换）。
2. 用脚本按 `git ls-files --eol` 列出 `w/crlf`／`w/mixed` 的文本文件，逐字节把 `b"\r\n"` 替换为 `b"\n"` 写回（不使用 `git reset --hard`／`git checkout --`）。
3. `git add --renormalize .` 刷新索引里的 stat 记录（内容无变化，`git diff --cached` 为空），使 `git status` 干净。
4. 按 REQ-037 重跑一次基线：`RAG_DB_PATH=data\rag.db`、`HF_HOME=.cache/models`，`.venv\Scripts\python.exe -m src.cli.eval`。
5. 六项指标与旧基线逐位一致后，把 `evals/baseline.json` 的 `run_id` 改为新 id，`effective_from` 注明本单；数值一个不动。
6. 本地 `scripts/ci_check.py` 三项全绿后推 `dev`，用真实 runner 验证 14 步。

## 回归验证

| 检查 | 结果 |
| --- | --- |
| 行尾归一 | `git ls-files --eol`：122 个 `i/lf w/lf`、150 个 `i/-text w/-text`；改写 54 个文件，逐个 `CRLF` 计数为 0 |
| 工作区干净 | `git add --renormalize .` 后 `git status` 无 `M`（仅 `.gitattributes` 未跟踪）；`git diff --cached --stat` 为空，说明 blob 未变 |
| 指纹 | `cases_sha256` `27fc0a88…`、`corpus_sha256` `010e011f…`，与 CI 检出值一致 |
| `run_id` | `build_run_id` 预测 `r31a95a0e1de6`，实跑一致（`attempt-1`） |
| 六项指标 | R@1 0.5600／R@3 0.8600／R@5 0.9000、MRR 0.7045、nDCG@5 0.7543、HitRate@5 0.9000——与 `r6c23283f2577` 逐位相同 |
| `metrics.json` | 576 字节、sha256 前 12 位 `d07e63d7c525`（与旧 attempt 的差异仅在 `run_id` 字段本身） |
| 待补 | 真实 runner 14 步结果；`V04-12`／`V05-12` 待 CI 全绿后才改标注 |

## 回滚方式

删除 `.gitattributes`，用脚本按相反方向把工作区文本文件改回 CRLF（或在 Windows 上 `git config core.autocrlf true` 后重新检出），再把 `evals/baseline.json` 的 `run_id` 改回 `r6c23283f2577`、重跑一次 `src.cli.eval` 让 `runs` 表恢复旧记录。指标数值两边一致，回滚不涉及数值改动。

## 执行记录（2026-11-20）

- `.gitattributes` 已加；54 个文本文件已归一（`git ls-files --eol` 从 53×`w/crlf` + 1×`w/mixed` 变为 0 个非 LF）。
- 重跑基线落 `data/runs/r31a95a0e1de6/attempt-1`，六项与旧基线逐位一致；`evals/baseline.json` 只改 `run_id` 与 `effective_from`。
- `runs` 表新增 `r31a95a0e1de6` 一行；`r6c23283f2577` 及其实验行保留为历史，不改。
- 未 force、未碰 `main`。
