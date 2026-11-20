# 变更单 #009：交付时推送 main 一次

- 日期 / 发起方：2026-11-20 / 用户
- 状态：**已完成**（用户 2026-11-20 口头批准「可以改」→ 出单转「已确认」→ 改毕转「已完成」）

## 背景

远端仓库 `ty-user8/kui` 为 public、默认分支是 `main`，但 main 从未推送，远端只有 `dev`。clone 者默认落在空 main，须手动 checkout dev 才见代码。对公开作品集项目不利。

## 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| push 规则 | 只推 dev、永不推 main | 日常只推 dev；**v0.5 全部完成并交付时，dev 快进合并到 main 推一次**；全程不 force |
| 技术方案 2.1「代码仓库」行 | 「不 push main」未写明，仅约定 push 需明确指定 | 明写交付时推 main 一次、平时只推 dev、不 force |
| HANDOFF.md 当前状态 | 「main 未 push、未 force」 | 加注「交付前不推，v0.5 交付时快进推一次」 |

`use_bm25` 等其他规则不变；v0.3 三处否决保持不启用。

## 影响范围分析

- 波及规格：`RAG检索项目技术方案_2026-11-14.md` §2.1、`HANDOFF.md` 当前状态段。
- 波及模块与文件：无代码改动；仅两份文档与 `CHANGELOG.md`、`CHANGELOG-DECISIONS.md`。
- 波及接口/Schema：无。
- 评测用例：无。
- 成本/性能/安全：无。git 操作仅交付时一次快进 push，不重写历史。

## 执行方案

1. 本单确认后改上述两份文档的 push 规则文字。
2. v0.5 全部任务完成、交付确认后：本地 `git checkout main`、`git merge --ff-only dev`、`git push origin main`，再报远端头部给用户确认。
3. 日常开发和各小版本 push 仍只推 dev，不 force。

## 回归验证

- 执行前实测 `git merge-base --is-ancestor main dev` 退出码 0：main 是 dev 祖先，可快进；main 停在 `a9ee1af`，dev 领先 25 提交。
- 快进合并用 `--ff-only`，若失败则不推、报告冲突。
- 交付 push 后核对 `git ls-remote --heads origin` 含 main 且与本地一致。

## 回滚方式

文档改回原表述即可；git 层面若已推 main 且需撤回，用 `git push origin --delete main` 会删远端分支（破坏性，须用户单独确认），不在本单默认回滚范围内。

## 执行记录（2026-11-20）

- 技术方案 2.1 代码仓库行、HANDOFF.md 当前状态段已改；CHANGELOG.md 记流水。
- 未执行任何 git push；本单只改规则，实际推 main 留到 v0.5 交付时。
