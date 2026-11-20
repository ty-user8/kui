# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：`12-release-checklist.md` 补 v0.5 专项 12 项（V05-09 `/ask` 真跑、V05-11 mermaid、V05-12 真实 runner 如实标未完成）；`.github/workflows/eval.yml` 的 `python-version` 由 `3.11` 改为 `3.13`（bug 修复，根因 `numpy==2.5.5` 要求 ≥3.12）；`CHANGELOG.md` 与 `PROGRESS.md` 记根因与两个失败 run 号。
- 实测：PyPI 元数据确认 `numpy 2.5.5 requires_python = >=3.12`；workflow 仍解析为 12 步、`准备 Python` 步骤值 `3.13`；锁文件与 `evals/baseline.json` 未动（`deps_sha256` 不变）。
- 待确认：已把 3 个提交推 `dev`（只 dev、不 force、不碰 main），等真实 runner 结果；V04-12 待跑通后再改标注。`/ask` 真 key 仍待补。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：v0.4 已发布（`origin/dev` = `fd509a8`）；v0.5 进行中，T-026／T-027 完成（本地待推）
- 门禁：G1/G2/G3 通过；CHG-001~006 已确认，001/002/003 状态行为「规格层已落地 + 剩余执行清单」
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：全量 2704 条 512 维、5,675,789 字节（v0.1 的 34 条已重建覆盖）
- 指标（v0.2 最终，100 条 / 融合）：R@1 0.5600／@3 0.8600／@5 0.9000、MRR 0.7045、nDCG@5 0.7543，`run_id=r5e4a62714526`（基线，CHG-007 已确认）
- 案例：BC-001 = C015（失败）；BC-002 = C010（现象）；全量语料后待复测
- 规模：已回填实测——v0.1 14925 字/34 chunk；v0.2 150 篇/2704 chunk/1,191,197 字/索引 5.42 MB
- 检查单：`12-release-checklist.md` v0.1 专项 8 项 + C-06/C-07 已勾选；v0.2 段待补
- 仓库：`git init -b main`，提交 `a9ee1af`；`dev` 已建并推送
- 远端：`origin` = `https://github.com/ty-user8/kui.git`；已推送 `origin/dev`（v0.1 内容提交 `a9ee1af`，其后为记录类提交；远端仅此一个分支，记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准），`main` 交付前不推、未 force（CHG-009：v0.5 交付时快进推一次）

## 待确认（开发方写）

- 基线 `r5e4a62714526`（CHG-007）；v0.3 T-016 已推送，T-017／T-018 本地待推

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
