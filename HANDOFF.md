# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：`CHG-012` 改口径——`constitution` 第 2 条与 `10-security` 改为「密钥值只走环境变量，模型名与接口地址可写 `config.yaml`（非密钥）」；技术方案第 102 行原文未动，差异按 `CHG-001` 先例由本单 + `D-024` 追溯；`config.yaml` 的 `llm` 加 `model_name: DeepSeek-V4.1-Flash-1017`／`base_url: https://api.deepseek.com`，三个 `*_env` 保留作覆盖；`config.py`／`ask.py` 按「环境变量覆盖配置字面值」取值，key 仍只读 `RAG_LLM_API_KEY`。
- 实测：单测 **124 例 OK**（121 + 3 条新增：字面值生效／env 覆盖 model／env 覆盖 base_url）；配置加载读出 `model_name=DeepSeek-V4.1-Flash-1017`、`base_url=https://api.deepseek.com`；改 `config.yaml` 后复跑评测 `run_id` 仍 `r31a95a0e1de6`、六项 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 逐位不变；`constitution.md` 新指纹 10844 / `72663e47c75dfd11` 已回填快照表；CI 冷跑 run `44764582340`（5m41s）14 步全绿（索引重建 4m35s，其余缓存命中）。
- 待确认：`RAG_LLM_API_KEY` 仍不在本机环境里，**`V05-09` 保持「未验证」**——key 到位后我跑一次完整 200 路径，记录模型名／耗时／引用校验结果再转「通过」；`config.yaml` 变更使 CI 的 `data` 缓存键失效，下一次运行为冷跑（多 2~3 分钟）。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：**v0.5 可交付**——T-026~T-029 完成，`CHG-010`（锁 73 行）与 `CHG-011`（行尾 LF、基线 `r31a95a0e1de6`）已落地，真实 runner 14 步全绿（`44729212536` 及两次缓存命中复跑）；按 `CHG-009` 交付时 `dev` 快进 `main` 推一次
- 门禁：G1/G2/G3 通过；**G4 通过**（v0.4 段 2026-11-20、v0.5 段同日按 V04-12／V05-12 勾选）；CHG-001~011 状态见各单头部
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：全量 2704 条 512 维、5,675,789 字节（v0.1 的 34 条已重建覆盖）
- 指标（v0.2 最终，100 条 / 融合）：R@1 0.5600／@3 0.8600／@5 0.9000、MRR 0.7045、nDCG@5 0.7543，`run_id=r31a95a0e1de6`（基线，`CHG-011` 行尾归一后重测；数值与 `CHG-007` 时代的 `r6c23283f2577` 逐位相同）
- 案例：BC-001 = C015（失败）；BC-002 = C010（现象）；全量语料后待复测
- 规模：已回填实测——v0.1 14925 字/34 chunk；v0.2 150 篇/2704 chunk/1,191,197 字/索引 5.42 MB
- 检查单：`12-release-checklist.md` 通用项 C-01~C-09、v0.1~v0.5 专项已逐条核对；`V05-09`（`/ask` 真实模型）与 `V05-11`（mermaid 渲染）如实保留「未验证」
- 仓库：`git init -b main`，提交 `a9ee1af`；`dev` 已建并推送
- 远端：`origin` = `https://github.com/ty-user8/kui.git`；`origin/dev` 与 `origin/main` 均停在 `138d1d3`（v0.5 交付点，`main` 由 `a9ee1af` 快进而来，未 force／amend／rebase）

## 待确认（开发方写）

- 基线 `r31a95a0e1de6`（`CHG-011`）；`deps_sha256 = 0d407a49…20ef0`（`CHG-010`）；`llm` 字面值已落 `config.yaml`（`CHG-012`），key 仍只读环境变量
- 快照表 3 行已按实测回填（`02-scope`／`03-architecture` 归因行尾，`tasks` 归因 `CHG-006`），`constitution` 随 `CHG-012` 更新为 10844 / `72663e47c75dfd11`；`V05-09`（缺 key）／`V05-11`（mermaid）仍「未验证」

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
