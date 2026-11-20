# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：按 `CHG-011` 根治行尾——新增 `.gitattributes`（`* text=auto eol=lf`），脚本把 54 个文本文件的 `CRLF` 逐字节改 `LF`（不改仓库 blob）；按 REQ-037 重跑基线，`evals/baseline.json` 的 `run_id` 改 `r31a95a0e1de6`、六项数值未动；`ci_check.py` 的 `FAIL` 行已加 `::error::` 前缀（上批）。
- 实测：`git ls-files --eol` 122×`i/lf w/lf` + 150×`i/-text w/-text`，`git status` 无残留 modified、`git diff --cached` 为空；新 `run_id=r31a95a0e1de6`（`attempt-1`），六项 0.5600／0.8600／0.9000／0.7045／0.7543／0.9000 与旧基线逐位相同，`metrics.json` 576 字节 sha `d07e63d7…`；本地 `ci_check.py` 三项 PASS。
- 待确认：真实 runner 14 步是否全绿（推后看 annotation）；另发现 `12-release-checklist.md` C-01 的技术方案尺寸/哈希自 `fd509a8`（CHG-009）起就没同步，以及行尾归一使所有文本文件的工作区字节指纹变化（blob 未变），是否按 LF 口径重登快照待你定。V04-12／V05-12 仍「未验证」，G4 不过门。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：v0.4 已发布（`origin/dev` = `fd509a8`）；v0.5 全部任务 T-026~T-029 完成；`CHG-010` 换锁与基线重跑已完成，等真实 runner 结果
- 门禁：G1/G2/G3 通过；CHG-001~006 已确认，001/002/003 状态行为「规格层已落地 + 剩余执行清单」
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：全量 2704 条 512 维、5,675,789 字节（v0.1 的 34 条已重建覆盖）
- 指标（v0.2 最终，100 条 / 融合）：R@1 0.5600／@3 0.8600／@5 0.9000、MRR 0.7045、nDCG@5 0.7543，`run_id=r31a95a0e1de6`（基线，`CHG-011` 行尾归一后重测；数值与 `CHG-007` 时代的 `r6c23283f2577` 逐位相同）
- 案例：BC-001 = C015（失败）；BC-002 = C010（现象）；全量语料后待复测
- 规模：已回填实测——v0.1 14925 字/34 chunk；v0.2 150 篇/2704 chunk/1,191,197 字/索引 5.42 MB
- 检查单：`12-release-checklist.md` v0.1 专项 8 项 + C-06/C-07 已勾选；v0.2 段待补
- 仓库：`git init -b main`，提交 `a9ee1af`；`dev` 已建并推送
- 远端：`origin` = `https://github.com/ty-user8/kui.git`；已推送 `origin/dev`（v0.1 内容提交 `a9ee1af`，其后为记录类提交；远端仅此一个分支，记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准），`main` 交付前不推、未 force（CHG-009：v0.5 交付时快进推一次）

## 待确认（开发方写）

- 基线 `r31a95a0e1de6`（`CHG-011`）；`deps_sha256 = 0d407a49…20ef0`（`CHG-010`）；等真实 runner 14 步全绿

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
