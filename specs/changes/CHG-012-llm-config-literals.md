# 变更单 #012：LLM 模型名与接口地址可写 `config.yaml`（密钥仍只走环境变量）

- 日期 / 发起方：2026-11-20 / 用户
- 状态：**已完成**（用户 2026-11-20 授权「改走 A」→ 执行完毕转「已完成」）

## 背景与原因

`/ask` 目前要跑起来必须设三个环境变量：`RAG_LLM_API_KEY`、`RAG_LLM_BASE_URL`、`RAG_LLM_MODEL`。但其中只有 key 是密钥——模型名与接口地址是公开信息（`DeepSeek-V4.1-Flash-1017`、`https://api.deepseek.com`），每次演示都要额外设两个变量，容易漏设、也不利于「换模型」被看见。

而三处已冻结口径把三者并列禁止入库：

| 位置 | 原文（摘） |
| --- | --- |
| `specs/constitution.md` 第 2 条 | 「`RAG_LLM_API_KEY`、`RAG_LLM_BASE_URL`、`RAG_LLM_MODEL` 只从环境变量读取，**禁止写入代码、`config.yaml`、文档、日志与 git 历史**」 |
| `specs/10-security.md` | 变量表把 `RAG_LLM_BASE_URL` / `RAG_LLM_MODEL` 与 key 并列；下方「值不写入代码、`config.yaml`、文档、日志、git 历史」 |
| `specs/00-source/RAG检索项目技术方案_2026-11-14.md` 第 102 行 | 「只记变量名，**值不写入代码、文档与仓库**」 |

本轮实现前提出时，代码侧尚未改动、`config.yaml` 未写入任何字面值——先把口径分歧报出，再按本单落地。

## 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| 口径 | key／base_url／model 三者并列，一律只读环境变量、值不入库 | **密钥值**（`RAG_LLM_API_KEY`）只走环境变量、禁止入库；**模型名与接口地址**属非密钥，可写 `config.yaml` 并注明非密钥 |
| `config.yaml` 的 `llm` 段 | 只有三个 `*_env` 名 | 新增 `model_name: DeepSeek-V4.1-Flash-1017`、`base_url: https://api.deepseek.com`；**三个 `*_env` 名保留**（向后兼容，且作为覆盖入口） |
| 取值优先级 | 环境变量唯一来源 | 环境变量**覆盖**配置字面值：`RAG_LLM_MODEL` 有值则用它，否则用 `llm.model_name`；`RAG_LLM_BASE_URL` 同理；`RAG_LLM_API_KEY` 仍只从环境变量取 |
| 缺值行为 | 缺 `RAG_LLM_MODEL` 即报 `CONFIG_MISSING_KEY` | 配置字面值与 `RAG_LLM_MODEL` **都为空**时报 `CONFIG_MISSING_KEY`，错误信息同时点出两者 |
| `run_id` 指纹 | 不含 `llm` 字段 | **不变**（规范串仍为 seed／embedding／chunk／topk／cases／corpus／docs／nv） |
| 基线、容差、锁文件 | — | **不变** |

## 技术方案差异追溯（按 `CHG-001` 先例）

`specs/00-source/RAG检索项目技术方案_2026-11-14.md` 属只读归档（C-01 保护），**正文不改**；第 102 行「值不写入代码、文档与仓库」与本单的差异，按 `CHG-001` 的处置方式以「本单 + `CHANGELOG-DECISIONS.md` D-024」作为追溯依据：

- 差异点：技术方案把 base_url／model 与 key 一起归入「值不入库」；本单将二者排除在「密钥值」之外，允许写入 `config.yaml`。
- 不变点：key 值仍严格不入库；日志与 trace 仍只记变量名，不记值（含模型名与地址也不进日志，避免把演示环境写死进日志）。
- 追溯：归档副本的字节与 SHA-256 不变，C-01 结论不受影响。

## 影响范围分析

- 波及规格：`specs/constitution.md` 第 2 条、`specs/10-security.md`（变量表与两条 note）按新口径改写；`specs/07-api/README.md` 中「`RAG_LLM_MODEL` 缺失返回 500」的表述改为「配置与变量都缺」。
- 波及模块与文件：`config.yaml`（`llm` 增两字段）、`src/config.py`（`LlmConfig` 增 `model_name`／`base_url`）、`src/generate/ask.py`（取值优先级与环境变量覆盖）、`tests/test_ask.py`（缺模型名用例改为「字面值与变量都空」）。
- 波及接口／Schema：`/ask` 请求与响应字段不变；错误码不变（`CONFIG_MISSING_KEY`）。
- 评测用例：`evals/cases.csv` 不变；`run_id` 不变；基线六项与容差不动。
- 成本／性能／安全：`config.yaml` 变更会让 CI 的 `data` 缓存键（按 `corpus/manifest.json`＋`cases.csv`＋`config.yaml` 计算）失效，下次冷跑重建索引，多约 2~3 分钟；不引入新依赖，不改变密钥存储方式。
- 快照：`specs/constitution.md` 的「当前值」随本条改写更新，依据列标 `CHG-012`。

## 执行方案

1. 改 `specs/constitution.md` 第 2 条、`specs/10-security.md` 相关表述、`specs/07-api/README.md` 一行。
2. `config.yaml` 的 `llm` 段加 `model_name`／`base_url`；`src/config.py` 的 `LlmConfig` 增同名字段（默认空串，老配置缺字段不报错）。
3. `src/generate/ask.py`：新增 `resolve_model`／`resolve_base_url`，先看环境变量、再落配置字面值；两者都空才报 `CONFIG_MISSING_KEY`。
4. `tests/test_ask.py` 的 `test_missing_model_name_raises_config_error` 改成「配置字面值为空且 `RAG_LLM_MODEL` 未设时」才报错，并补一条「配置字面值生效」的用例。
5. 全量单测 + 本地 `/ask` 走假客户端；有 key 时再跑一次真实调用（记录模型名、耗时、引用校验）。

## 回归验证

| 检查 | 结果 |
| --- | --- |
| 单测 | 122 例 OK（原 121 + 新增 1 条字面值用例；改写的缺值用例按新口径断言） |
| 取值优先级 | 只配字面值 → 用 `DeepSeek-V4.1-Flash-1017`／`https://api.deepseek.com`；设 `RAG_LLM_MODEL` 后覆盖为环境变量值；两者都空 → `CONFIG_MISSING_KEY` |
| 密钥 | 仓库内 `grep -R "sk-"` 零命中；`config.yaml` 只有非密钥字面值 |
| `run_id` / 基线 | 不变（`llm` 不进规范串），`evals/baseline.json` 未改 |
| 待补 | 真实模型一次完整调用（本机环境暂无 `RAG_LLM_API_KEY`），故 `V05-09` 保持「未验证」 |

## 回滚方式

删 `config.yaml` 的两个字面值字段、`LlmConfig` 的两字段与 `resolve_*` 两函数，恢复三处规格措辞与那条用例；`run_id`、基线、锁文件均不涉及，回滚不改数值。

## 执行记录（2026-11-20）

- 已完成：三处规格改写、`config.yaml` 增两字段、`LlmConfig`／`ask.py` 取值优先级、单测调整与新增。
- CI 缓存：`config.yaml` 变更后 `data` 缓存键失效，下一次运行为冷跑。
- 未完成：真实模型调用（环境无 `RAG_LLM_API_KEY`），`V05-09` 保持「未验证」。
