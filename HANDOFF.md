# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：`src/index/embedder.py` 增 `build_index_text`／`fit`；`src/cli/build_index.py` 增 `--inject-heading`／`--out` 并回写 `index_text_sha256`；`src/cli/eval.py` 增 `--index-dir`；新增 `evals/experiments-v0.3.md`。
- 实测：`.venv\Scripts\python.exe -m src.cli.build_index --inject-heading --out data/index-head` 0（2704 条、5,675,789 字节、路径截断 0、token 截断 255、193.7 s）；dev 对比 `.venv\Scripts\python.exe -m src.cli.eval --split dev --retriever dense --index-dir {data/index,data/index-head}` 均 0：R@1 0.4750→0.4375、R@3 0.7125→0.7750、R@5 0.8375→0.8250、MRR 0.6121→0.5958 → 不启用。
- 待确认：无阻塞项；T-017／T-018 共 2 个提交本地攒着，等 paused 点一并 push。下一步 T-019。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：v0.2 已发布；v0.3 进行中，T-016~T-018 完成（`origin/dev` = `407fe62`，本地待推）
- 门禁：G1/G2/G3 通过；CHG-001~006 已确认，001/002/003 状态行为「规格层已落地 + 剩余执行清单」
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：全量 2704 条 512 维、5,675,789 字节（v0.1 的 34 条已重建覆盖）
- 指标（v0.2 最终，100 条 / 融合）：R@1 0.5600／@3 0.8600／@5 0.9000、MRR 0.7045、nDCG@5 0.7543，`run_id=r5e4a62714526`（基线，CHG-007 已确认）
- 案例：BC-001 = C015（失败）；BC-002 = C010（现象）；全量语料后待复测
- 规模：已回填实测——v0.1 14925 字/34 chunk；v0.2 150 篇/2704 chunk/1,191,197 字/索引 5.42 MB
- 检查单：`12-release-checklist.md` v0.1 专项 8 项 + C-06/C-07 已勾选；v0.2 段待补
- 仓库：`git init -b main`，提交 `a9ee1af`；`dev` 已建并推送
- 远端：`origin` = `https://github.com/ty-user8/kui.git`；已推送 `origin/dev`（v0.1 内容提交 `a9ee1af`，其后为记录类提交；远端仅此一个分支，记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准），`main` 未 push、未 force

## 待确认（开发方写）

- 基线 `r5e4a62714526`（CHG-007）；v0.3 T-016 已推送，T-017／T-018 本地待推

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

- （开发方补记 2026-11-18）v0.1 推送完成：`origin/dev`，v0.1 内容提交 `a9ee1afce1f9696581e7051cca11103676fad46e`，`main` 未推送；记录类提交会让头部前移，远端实际头部以 `git log origin/dev` 为准。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
