# 变更单 #010：依赖锁重新生成（补 v0.2~v0.5 依赖）

- 日期 / 发起方：2026-11-20 / 用户
- 状态：**已完成**（用户 2026-11-20「按 A 修锁」授权，含重跑基线留痕 → 执行完毕转「已完成」）

## 背景

`requirements.lock.txt` 为 v0.1（2026-11-17）一次性生成，仅 40 个包，此后未随依赖增长更新。v0.2 的 `jieba`／`rank_bm25`、v0.4 的 `fastapi`／`uvicorn`、v0.5 的 `streamlit`／`openai` 及其传递依赖均不在锁内，导致 CI 装完依赖后必然失败：

- run `44707436948`（5m50s，失败）annotation 指向第 12 步「构建 BM25 索引」——`src/index/bm25_index.py` 顶部 `import jieba`，缺包即失败；
- 即使补 `jieba`，「单元测试」会因缺 `fastapi` 失败，「回归判定」会因 BM25 索引缺失失败。

锁文件与真实 venv 长期不一致，本身也违反「锁 = 环境内容哈希」的定义。两种修法：A 重新生成锁并追认（本单）；B 只在 CI 补装六个包（锁继续与真实环境脱节）。用户 2026-11-20 选 A。

## 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| `requirements.lock.txt` | 40 行（v0.1 环境） | **73 行**（当前 venv 全量 `pip freeze`，torch 行经 `normalize_lock.py` 规范） |
| `deps_sha256` | `ae2cc83b6ae374acfc373bd8fdd19c1454ae62a045d58019f2e1377c1790d6f3` | `0d407a4951804399336a14e46184bad98d0ad84b53e98d0e62329ee109a20ef0` |
| torch 行格式 | `torch==2.15.0+cpu  # wheel sha256=086f79c7…c619` | 不变（CI 用 `grep -v '^torch'` 剔除，改由 PyTorch CPU 索引安装同名版本） |
| 补齐的六个直接依赖 | 无 | `jieba==0.42.1`、`rank-bm25==0.2.2`、`fastapi==0.165.0`、`uvicorn==0.54.0`、`streamlit==1.67.0`、`openai==3.57.0`（另有 pandas／pyarrow／altair／httpcore2／httpx2／annotated-doc 等传递依赖） |
| 基线 `evals/baseline.json` | `run_id=r6c23283f2577`，六项 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 | **不变**（`deps_sha256` 不进 `run_id` 规范串，属独立比对项） |
| CI `eval.yml` | 安装步只用 PyPI 主索引 | **不改**（见下方举证：新锁全部包在 PyPI 主索引可取，不需要补 `--index-url`） |

## 影响范围分析

- 波及规格：`04-tech-choice.md` §3 实测表「锁文件」行（行数与 `deps_sha256`）、`12-release-checklist.md` C-06 与 V01-09、`PROGRESS.md`「环境现状」。
- 波及模块与文件：无源码改动；`requirements.lock.txt`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md`（如需）、`HANDOFF.md`。
- 波及接口／Schema：无。`runs.deps_sha256` 取值变化，字段与语义不变。
- 评测用例：无。`run_id` 不含锁哈希，故不触发 REQ-037 的「有意变更重定基线」，仅按 REQ-037 重跑一次留痕。
- 成本／性能／安全：CI 的 venv 缓存键为 `hashFiles('requirements.lock.txt')`，锁变更后首次运行为冷缓存，需全量装依赖（torch ≈ 120.8 MB）一次；安全性不变，未引入新来源。

## 执行方案

1. 项目根目录，`.venv\Scripts\python.exe -m pip freeze > requirements.lock.txt`。
2. 同目录，`.venv\Scripts\python.exe scripts/normalize_lock.py`——把 `torch @ file:///…` 改写为 `torch==2.15.0+cpu  # wheel sha256=…` 并打印 `deps_sha256`；再跑一次确认幂等。
3. 按 REQ-037 在新锁上重跑基线：`RAG_DB_PATH=data\rag.db`、`HF_HOME=.cache/models`，`.venv\Scripts\python.exe -m src.cli.eval`，落新 `attempt-N`。
4. 回填四处旧哈希（`PROGRESS.md`、`04-tech-choice.md` §3、`12-release-checklist.md` C-06／V01-09），历史记录类条目（`CHANGELOG.md` 2026-11-17 段、`CHG-004` 执行记录）保持原值不动。
5. 与本地积压提交一并推 `dev`，用真实 runner 验证 14 步走完。

## 回归验证

**① 锁文件内容**

| 检查 | 结果 |
| --- | --- |
| 行数 | 73（原 40） |
| 规范化幂等 | 第二次运行「改写行数: 0」 |
| torch 行 | `torch==2.15.0+cpu  # wheel sha256=086f79c78c941b428410dc15f898ce2420a4580ae6983ea314692d71ce76c619` |
| 六个直接依赖在锁内 | `jieba==0.42.1`(21)／`rank-bm25==0.2.2`(47)／`fastapi==0.165.0`(12)／`uvicorn==0.54.0`(71)／`streamlit==1.67.0`(59)／`openai==3.57.0`(33)（括号为行号） |

**② CI 可安装性举证（对应「风险先举证」）**

- 逐个向 PyPI 查询 72 个非 torch 包的「版本是否存在 + 是否有 Linux 轮子」：71 个存在 `manylinux_*_x86_64` 或 `py3-none-any` 轮子；仅 `jieba==0.42.1` 为 sdist-only（`jieba-0.42.1.tar.gz`），属纯 Python 包（`setup.py` 无 `ext_modules`），本地 py3.13 下 `pip wheel --no-build-isolation` 成功产出 `jieba-0.42.1-py3-none-any.whl`，CI 的构建隔离安装路径同样可行。
- 交叉平台干跑（Windows 本机模拟 ubuntu + cp313）：`pip install --dry-run --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --python-version 3.13 --implementation cp --abi cp313 -r <去 torch 锁>` 解析通过。注意 `faiss-cpu==1.16.0` 只发布 `manylinux_2_28` 标签，只给 `manylinux2014` 单标签会误报「无匹配版本」——这是干跑参数问题，不是包缺失。
- 结论：`httpcore2`／`httpx2`／`annotated-doc` 均为 PyPI 主索引上的正式包（pydantic 组织维护的 httpx 后继分支），**不需要在 `eval.yml` 安装步补 `--index-url`**，CI 无需改动。

**③ 基线重跑留痕**

- `run_id=r6c23283f2577`（不变），`attempt-4`，split all，100 条（unmapped 0、unconfirmed 0）。
- 六项：R@1 0.5600／R@3 0.8600／R@5 0.9000、MRR 0.7045、nDCG@5 0.7543、HitRate@5 0.9000 —— 与 `evals/baseline.json` 完全一致。
- `attempt-4/metrics.json` 576 字节、sha256 前 12 位 `ca2d0c8a316f`，与 `attempt-1~3` 逐字节相同（`metrics.json` 不含时间戳，锁变更不触碰指标）。
- `attempt-4/meta.json` 的 `deps_sha256 = 0d407a495180…20ef0`；`runs` 表 `r6c23283f2577` 行同步更新为新值。既有实验行（`-dev-head`／`-dev-hybrid` 等）保留旧哈希，属历史记录，不改。

**④ 待补**：真实 runner 上的 14 步结果（V04-12／V05-12 仍标「未验证」，待 CI 全绿后改）。

## 回滚方式

`git revert` 本单涉及的锁文件与文档提交，在 venv 内还原旧锁并重跑一次 `src.cli.eval` 使 `runs` 表 `r6c23283f2577.deps_sha256` 回到 `ae2cc83b…d6f3`；基线数值不受影响，无需改 `evals/baseline.json`。CI 的 venv 缓存键随锁哈希自动回到旧值，无需清缓存。

## 执行记录（2026-11-20）

- 锁重新生成：40 → 73 行；`deps_sha256` `ae2cc83b…d6f3` → `0d407a49…20ef0`；`normalize_lock.py` 首次「改写行数: 1」（torch 行）、二次「改写行数: 0」。
- 基线重跑落 `data/runs/r6c23283f2577/attempt-4`，指标与基准逐位相同，`metrics.json` 与前三次逐字节一致。
- 四处旧哈希回填；`eval.yml` 未改（举证见上）。
- 未 force、未碰 `main`。
