# 变更单 #003：复现验证口径、`run_id` 指纹与 trace 读取路径

- 日期：2026-11-16
- 发起方：用户（G2 审阅意见）
- 状态：**已确认**（2026-11-17 用户确认，八处口径修正生效）。规格层已落地，剩余执行/回归随 v0.2/v0.4 对应任务完成后转已完成。

**剩余执行清单**

| 项 | 状态 | 转「已完成」的条件 |
| --- | --- | --- |
| `run_id` 去日期、只由配置指纹决定 | 未开始 | T-008 生成 `run_id` 并验证跨天不变 |
| 复现验证改 `attempt-1/attempt-2` | 未开始 | T-008/T-009 两次运行产物落两个目录且 `metrics.json` 一致 |
| `runs.deps_sha256` | 未开始 | T-008 写库并与 `requirements.lock.txt` 哈希比对 |
| `-2`／`-3` 只作人工并列保留 | 未开始 | 随 T-008 一并验证 |
| trace 读取路径与 `traces` 表 | 未开始 | T-013 写 JSONL、T-024 导入表并核对 `source_run_id`／`imported_at` |
| JSONL 追加写的平台文件锁 | 未开始 | T-013 实现并做并发写用例 |
| `chars_total` 生效前提 | 已落地（T-002 计算、T-005 写库，CHG-002 已确认故允许写非 0 值） | — |

## 背景

G2 审阅指出四处口径不一致，均属契约细化：①`run_id` 含日期，同配置跨天会产生不同指纹，与「可复现」冲突；②复现验证是「连跑两次比对」，但没有规定两次结果各自的落盘位置，实际会互相覆盖；③依赖锁哈希的去处与理由表述与前一条冲突；④trace 的读取路径没写清，明细权威与派生表混在一起。另需明确 `chars_total`／`excluded_chars` 两列的生效前提。

## 变更内容

| # | 变更点 | 落点 |
| --- | --- | --- |
| 1 | `run_id` 去掉日期，只由配置指纹决定：`run_id = "r" + sha256(规范串)[:12]`；跨天同配置必得同一 id | `06-schemas/README.md` §3、§4；`03-architecture.md` §2 第 4 条 |
| 2 | `run_id` 不可反解，五项明细改为「查 `runs` 表反查」 | `01-requirements.md` REQ-031 |
| 3 | 复现验证：同 `run_id` 连跑两次，分别落 `data/runs/<run_id>/attempt-1/` 与 `attempt-2/`，diff 两份 `metrics.json` | REQ-032、REQ-036 第 ① 项；`02-scope.md` §2.2 第 4 条；`09-state.md` §5 |
| 4 | `-2`／`-3` 后缀只用于人工并列保留多份结果，不参与复现判定；重跑不再覆盖旧结果 | `06-schemas/README.md` §4；`09-state.md` §5 |
| 5 | `deps_sha256`（锁文件内容哈希）写入 `runs` 表，与 `config_hash` 并列；理由改为「锁是内容哈希，与配置指纹分开便于独立比对」 | `06-schemas/migrations/0001_init.sql`；`06-schemas/README.md` §3、§6；`04-tech-choice.md` §2 |
| 6 | trace 读取路径：明细权威 `data/trace.jsonl`，`eval.py` 与失败案例归类直接读 JSONL；`traces` 表为派生摘要，记 `source_run_id`／`imported_at`；`/trace` 读 JSONL | `09-state.md` §4.1；`05-modules.md` §3.1 与模块表；`07-api/README.md` `GET /trace`；`0003_runtime.sql` |
| 7 | JSONL 追加写：默认单进程，并发时用标准库平台文件锁（`fcntl.flock`／`msvcrt.locking`），不新增依赖 | `09-state.md` §4.1；`05-modules.md` §3.1 |
| 8 | `documents.chars_total`／`excluded_chars` 以 CHG-002 项五批准为生效前提，未批准前实现不得写入非 0 值 | `0001_init.sql` 注释；`06-schemas/README.md` §2 |

## 影响范围分析

| 面 | 影响 |
| --- | --- |
| 规格文档 | `01-requirements.md`（REQ-031、REQ-032、REQ-036）、`02-scope.md`（§2.2）、`03-architecture.md`（§2）、`04-tech-choice.md`（§2、新增 §3）、`05-modules.md`（模块表、§3.1）、`06-schemas/`（README、2 个迁移脚本）、`07-api/README.md`、`09-state.md`（§4.1、§5） |
| 模块与文件 | `cli.eval`（写 attempt 目录）、`store.dao`（`runs.deps_sha256`）、`trace`（锁与读取）、`cli.import_traces`（`source_run_id`／`imported_at`） |
| 接口／Schema | `runs` 增 `deps_sha256`；`traces` 的 `run_id` 改 `source_run_id`、`created_at` 改 `imported_at`；`/trace` 数据来源改为 JSONL（响应字段不变） |
| 评测用例 | 无新增用例；v0.1 DoD 第 4 项的判定对象由「单文件 diff」改为「两个 attempt 目录 diff」 |
| 成本／性能／安全 | 无 LLM 影响；每次 eval 多写一个小目录；`run_id` 变短不影响索引；trace 直接读 JSONL 省一次导入 |
| 迁移影响 | 三个脚本均未发布（v0.1 未实现），直接改 `0001`／`0003`，不新增 `0004` |

## 执行方案

1. 本单所列 8 处已按 G2 意见改完（规格与 DDL 同步）。
2. 步骤 4 Tasks 中把「attempt 目录写入」写进 `eval` 任务，把「`deps_sha256` 计算与比对」写进 Verify 任务。
3. 步骤 5 Analyze 时核对：`09-state` 的 trace 字段表 ↔ `0003_runtime.sql` 列 ↔ `07-api` 的 `TraceItem`。

## 回归验证

- 同配置连跑两次：`run_id` 相同、产生 `attempt-1/` 与 `attempt-2/`、两份 `metrics.json` diff 为空。
- 跨天模拟：改系统日期或伪造日期参数后重跑，`run_id` 不变。
- `runs` 表可反查五项；`deps_sha256` 与 `requirements.lock.txt` 哈希一致。
- `/trace` 在刚跑完、未导入时即可返回结果。

## 回滚方式

恢复 `run_id` 含日期与「重跑覆盖 `metrics.json`」的旧口径：改 `06-schemas/README.md` §3、`09-state.md` §5、REQ-031／032／036，并把 `0001`／`0003` 的字段改回。已产出的 attempt 目录可直接删除对应行引用，无数据依赖。
