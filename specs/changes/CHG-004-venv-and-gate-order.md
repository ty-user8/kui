# 变更单 #004：项目 venv 口径、依赖门禁起点与 G3 后复核顺序

- 日期：2026-11-17
- 发起方：用户（G3 审阅意见）
- 状态：**已完成**（流转记录：2026-11-17 起草为待确认 → 2026-11-18 G3 确认转「已确认」→ 依 §9 执行记录转「已完成」）

## 背景

三项口径问题：

1. **环境错位**：此前的 `faiss-cpu` 与本次 `torch` 都装进了 WorkBuddy 工具自带的解释器（`C:\Users\one\.workbuddy\binaries\python\versions\3.13.12`），项目 `.venv` 根本不存在。工具解释器随工具升级会变，装在那里的包不能作为项目依赖依据，`pip freeze` 出来的锁文件也不可复现。
2. **顺序跳步**：SOP 步骤 5 要求 Analyze 由用户看过结果再进 Implement；本轮已修 5 项，但 `tasks.md` 在 G3 确认前后可能还会变，须在 G3 确认后重跑一次 Analyze。
3. **门禁起点写错**：此前写「T-005 起需要 embedding 模型」，实际 T-005 只做切分与入库，不需要模型；模型门禁在 T-006。

## 变更内容

| # | 变更点 | 落点 |
| --- | --- | --- |
| 1 | 建立项目 venv `.venv`；torch／faiss-cpu／sentence-transformers 一律装进该 venv | 本单执行记录、`PROGRESS.md` |
| 2 | 所有实现命令与 CI 显式使用 `.venv\Scripts\python.exe`；工具自带解释器中的包不作为项目依赖依据 | `constitution.md` 工程约定、`10-security.md` 白名单、`04-tech-choice.md` §3 |
| 3 | 在该 venv 内重做 import 冒烟与 `IndexFlatIP` 自检，并生成 `requirements.lock.txt` 与 `deps_sha256` | `PROGRESS.md`、`04-tech-choice.md` §3.1 |
| 4 | `requirements.txt` 明确「禁止 `pip install -r requirements.txt`」，torch 只能按登记的 `--index-url` 或本地 wheel 安装 | `requirements.txt` |
| 5 | 依赖就绪门禁起点由 T-005 改为 **T-006**；T-001~T-005 不需要模型权重 | `tasks.md` |
| 6 | G3 确认后**先重跑一次 Analyze**（复核未确认的 `tasks.md` 有无改动），结果经用户看过再进 Implement | `PROGRESS.md`、`tasks.md` |

## 影响范围分析

| 面 | 影响 |
| --- | --- |
| 规格文档 | `constitution.md`（工程约定）、`04-tech-choice.md`（§3、§3.1）、`10-security.md`（工具白名单）、`tasks.md`（门禁起点与顺序） |
| 模块与文件 | 无代码影响；新增 `.venv/`（已在 `.gitignore` 排除）、`.cache/wheels/`（同样排除） |
| 接口／Schema | 无 |
| 评测用例 | 无；`deps_sha256` 的取值会因 venv 重建而变化，属预期 |
| 成本／性能／安全 | 磁盘增加一份 venv（约 3GB，含 torch）；隔离后升级工具不再影响项目；`pip freeze` 只含项目依赖，锁文件更短更可读 |

## 执行方案

1. `python -m venv .venv`，确认 `.venv\Scripts\python.exe -V` 为 3.13.14（与 wheel 的 cp313 匹配）。
2. 在 venv 内安装 `faiss-cpu`；torch 待 `.cache/wheels/` 的 wheel 下载完并校验 sha256 后本地安装；随后装 `sentence-transformers`。
3. 在 venv 内跑 `import numpy` / `import faiss` / `import torch` 与 `IndexFlatIP` 自检。
4. `.venv\Scripts\python.exe -m pip freeze > requirements.lock.txt`，计算 `deps_sha256`。
5. 工具解释器里已有的 `faiss-cpu` 保留不动，但不再作为依赖依据，也不写进锁文件。

## 回归验证

- `.venv\Scripts\python.exe -c "import numpy, faiss, torch"` 全部通过且版本可打印。
- `requirements.lock.txt` 中含 `torch==2.15.0+cpu`，不含 CUDA 包（无 `nvidia-*`）。
- `deps_sha256` 与锁文件内容哈希一致。
- 冒烟命令本身即为 Verify 清单中的一条。

## 回滚方式

删除 `.venv/` 与 `requirements.lock.txt`，改回工具解释器；`deps_sha256` 记录作废并重算。无数据依赖。

## 9. 执行记录（2026-11-17）

| # | 事项 | 结果 |
| --- | --- | --- |
| 1 | 建 venv | `.venv`，Python 3.13.14，pip 26.1.2 |
| 2 | venv 内装配 | numpy 2.5.5、faiss-cpu 1.16.0、torch 2.15.0+cpu、sentence-transformers 3.4.1、python-docx 1.2.0、PyYAML 6.0.3、pydantic 2.14.3 |
| 3 | 冒烟 | numpy / faiss / torch / sentence-transformers 同进程 import 通过；`IndexFlatIP` 命中正确；`cuda.is_available()=False` |
| 4 | 锁文件 | `requirements.lock.txt` 40 行；torch 行规范为 `torch==2.15.0+cpu`；`deps_sha256 = ae2cc83b…d6f3` |
| 5 | 依赖门禁 | `tasks.md` 起点改为 T-006；T-001~T-005 不需要模型 |
| 6 | 复核顺序 | `tasks.md` 与 `PROGRESS.md` 写明「G3 确认后先重跑 Analyze」 |

以上为实现层执行结果。状态流转：G3 确认后本单转「已确认」，随执行记录一并落定转「已完成」。

**状态流转说明**：本单在确认前已把各项实施完毕，故流转时跳过「执行中」这一态——2026-11-17 起草为「待确认」，2026-11-18 用户确认后转「已确认」，同日依本节执行记录转「已完成」。跳过「执行中」的原因为实际执行先于确认，如实记录而非补造中间态。
