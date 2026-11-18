# 会话交接

项目根：`D:\02-Projects\python\python project\rag`。双方启动先读本文件。各自只写自己的区段，覆盖自己上一条即可，不改对方区段。

## 开发方写（每轮三行）

- 改动：`src/cli/eval.py`、`src/store/dao.py`（`upsert_run`）、`specs/12-release-checklist.md`、`PROGRESS.md`、`CHANGELOG.md`——`eval` 入口与 `run_id`／attempt 落盘、全链路排查、检查单勾选。
- 实测：`compileall` 0；`ingest` 0（2 篇 / 34 chunk）；`build_index` 0（34 向量 / 71,459 字节）；`eval` ×2 均 0（`run_id=r98aa795a93cf`，attempt-1~4 的 `metrics.json` 均 544 字节 / sha `a83df586…`）；`fill_anchors.py --check` 0（30 条逐字一致）；DoD 六项逐条成立，指标 0.7667／0.8333／0.9667／0.8317／0.8647／0.9667。
- 待确认：v0.1 是否 push（九项任务与 DoD 六项已完成，迄今未建 git 仓、未 push）。

自检脚本（`compileall`、`fill_anchors.py --check`、`src.eval.runner`）由开发方自己跑，输出贴进「实测」。状态、哈希、变更流转写 `PROGRESS.md` / `CHANGELOG.md`，不在对话里复述。

## 核验方写（每轮）

只写结论：放行 / 暂缓 + 必须随行订正 + 一句话理由。抽验 1~2 个关键数字，不复述核查过程。

## 暂停等我确认的四种情况

1. G 门禁（G1~G4）
2. 小版本 push 前（附该版生效依据逐条结果、`eval.py` 输出、回归对比、自检与说明文本检查）
3. 新变更单
4. 规格口径分歧

其余轮次自行推进，不转发。

## 当前状态（开发方维护，每轮更新）

- 版本：v0.1；T-001~T-009 全部完成，DoD 六项逐条成立，等 push 决策
- 门禁：G1/G2/G3 通过；CHG-001~006 已确认，001/002/003 状态行为「规格层已落地 + 剩余执行清单」
- 权重：`.cache/models/bge-small-zh-v1.5`，指纹写入 `data/index/index-meta.json` 的 `weights_sha256`
- 索引：34 条 512 维、71,459 字节；30 条 gold 全映射、`unmapped=0`；`run_id=r98aa795a93cf`，attempt-1~4 的 `metrics.json` 同哈希
- 指标：Recall@1/3/5 = 0.7667/0.8333/0.9667，MRR 0.8317，nDCG@5 0.8647，HitRate@5 0.9667
- 案例：BC-001 = C015 未进 top-5（失败）；BC-002 = C010 命中 rank 1 但 chunk 混装（现象，v0.3 处理）
- 规模：02-scope 已改实测值（基准文本 14925 字 / 34 chunk / 基线 14.7%），全量估算待 T-010 回填
- 检查单：`12-release-checklist.md` v0.1 专项 8 项 + C-06/C-07 已勾选
- push：本批不 push，未建 git 仓

## 待确认（开发方写）

- v0.1 是否 push（附 `eval` 输出与检查单，等确认后才按 push 规则执行）

## 结论（核验方写）

- 2026-11-18：T-008 放行；`attempt-N/meta.json` 增加 `weights_sha256`（从 `data/index/index-meta.json` 读），`run_id` 规范串与 `runs` 表不动。只做 T-008，不改 `corpus/**`，本批不 push。

本文件只做交接，正式决策与流水仍以 `PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG-DECISIONS.md` 为准。
