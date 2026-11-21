# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：跑 `V05-09`——真实 key（用户级环境变量，只在进程内用，未落盘）走 `POST /ask`；模型名按接口实际值把 `config.yaml` 的 `llm.model_name` 由 `DeepSeek-V4.1-Flash-1017` 改为 **`deepseek-flash`**（首次调用返回 400「supported API model names are deepseek-flash, deepseek-v4-pro」）；检查单 `V05-09` 转「通过」，`README` 已知限制第 4 条改为如实描述。未动代码。
- 实测：两条 query 均 HTTP 200——「发明专利权的期限是几年」3152.4 ms、「假冒专利要承担什么法律责任」7008.7 ms（< 30 s 阈值）；两次 `citation_valid=true`、`invalid_citations=null`（无越界），引用均在本次 top-5 内，`prompt_version=ask.system.v1`、`reason=null`；`base_url` 仍是 `https://api.deepseek.com`。
- 待确认：`V05-11`（mermaid 渲染）是最后一项未验证，需 GitHub 页面确认；`RAG_LLM_MODEL`／`RAG_LLM_BASE_URL` 保持不设（模型名与地址从 `config.yaml` 读）；CI 因 `config.yaml` 再变又要冷跑一次索引。

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
- 快照表 3 行已按实测回填（`02-scope`／`03-architecture` 归因行尾，`tasks` 归因 `CHG-006`），`constitution` 随 `CHG-012` 更新为 10844 / `72663e47c75dfd11`；`V05-09` 已通过（`deepseek-flash`，3152.4／7008.7 ms，无越界），仅 `V05-11`（mermaid）未验证

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
