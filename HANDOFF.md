# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：v2 收尾（`CHG-013` S5）——规格回填三处：`06-schemas/README.md` 加 `agent_sessions`／`agent_turns` 两表（存储清单、DDL 链到 `0004_agent.sql`、建表要点、对应表）；`09-state.md` §6 由「规划」转「已落地」并按 D1 改写「`stateless_mode` 不进 `run_id`」，新增 §7 会话生命周期与单轮两轮状态机；`01-requirements.md` 新增 §6-I「问答 Agent（v2）」REQ-059~REQ-068。三份均带版本／日期／依据（C.1 留痕，未按规则 #11 删元信息）。另加 1 条测试守 `/ask` 配额独立性。
- 实测：全量 **205 例 OK**（无 env 189 例 OK、6 skip）；评测 `attempt-5` 的 `run_id=r31a95a0e1de6` 与六项 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 逐项不变，本地 `ci_check` 三项 PASS（`attempt-6`／`attempt-7` 逐字节一致 576 B）；真实 `deepseek-flash` 跑一问后 `data/runs` 15 目录、`trace.jsonl` 26695 B、`runs`／`traces` 行数全不变，只 agent 两表各 +1；依赖未动（lock 1379 B / `da26d417…`、73 行）。
- 待确认：按 `D-025` 快进推 `main`（推前 `is-ancestor` 退出码 0、`--ff-only`，不 force／amend／rebase）。两件可选待你定：本地 `agent_*` 两表的 8 条会话／11 轮联调记录是否清空；`CHANGELOG-DECISIONS.md` 缺 v2 的 `D-026`（D1~D5 尚未成条，不在本批授权内）。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：**v2（问答 Agent）已实现并验收**——`CHG-013` 的 S1~S5 全部完成：工具层 4 个、两轮编排与配额、会话记忆 + `0004_agent.sql`、8502 页面、规格回填；v0.5 检索链未改，基线仍 `r31a95a0e1de6`
- 门禁：G1/G2/G3/G4 通过（v0.5 交付时）；v2 属架构与能力边界变更，按 `CHG-013` §6 走变更单、未重过 G2（该单未要求）；CHG-001~013 状态见各单头部
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：全量 2704 条 512 维、5,675,789 字节（v0.1 的 34 条已重建覆盖）
- 指标（v0.2 最终，100 条 / 融合）：R@1 0.5600／@3 0.8600／@5 0.9000、MRR 0.7045、nDCG@5 0.7543，`run_id=r31a95a0e1de6`（基线，`CHG-011` 行尾归一后重测；数值与 `CHG-007` 时代的 `r6c23283f2577` 逐位相同）
- 案例：BC-001 = C015（失败）；BC-002 = C010（现象）；全量语料后待复测
- 规模：已回填实测——v0.1 14925 字/34 chunk；v0.2 150 篇/2704 chunk/1,191,197 字/索引 5.42 MB
- 检查单：`12-release-checklist.md` 通用项 C-01~C-09、v0.1~v0.5 专项已逐条核对，`V05-09`／`V05-11`／`V05-12` 已关闭；v2 的验收证据记在 `CHG-013` §14（S1~S5），未单列检查单条目
- 仓库：`git init -b main`，提交 `a9ee1af`；`dev` 已建并推送
- 远端：`dev` 已含 v2 的 S1~S5 提交；`main` 按 `D-025` 在 v2 验收通过后快进到 `dev` 同点（`merge-base --is-ancestor main dev` 退出码 0、`--ff-only`）
- 未验证：无（v0.5 三项已关闭；v2 的 `V05-11` 降级写法、`V05-09` 真跑、S1~S5 验收均已留痕）

## 待确认（开发方写）

- 基线 `r31a95a0e1de6`（`CHG-011`）；`deps_sha256 = 0d407a49…20ef0`（`CHG-010`）；`llm` 字面值已落 `config.yaml`（`CHG-012`），key 仍只读环境变量
- 快照表随 `CHG-013` 再更新一行：`specs/01-requirements.md` 当前值 26400 / `d7bba05eba2a709b`（新增 §6-I，原 23319 为 v0.5 时点值）；`06-schemas/README.md`（7083 / `dae5b805ebc9e2ff`）与 `09-state.md`（10466 / `5be12436be48216a`）不在快照表内，只在本行留痕
- v2 口径：配额 8 项在 `config.yaml` 的 `agent` 段（三项硬上限只可下调），`ui_port_agent: 8502`；会话两表不被 `/search`／`/eval`／CI 读取；`stateless_mode` 不进 `run_id`（D1）
- v2 已交付（2026-11-22，`D-025`）：`main` 由 `de68f43` 快进到 **`0bb6521`**（推前 `is-ancestor` 退出码 0、`dev` 领先 8 个提交），`git ls-remote` 两分支同点；`dev`@`0bb6521` CI run `45003769470` 49 s 全绿（缓存全命中、回归判定 PASS、14 个业务步骤不变）

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
