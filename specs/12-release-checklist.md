# 上线检查单

本清单自 v0.1 起逐版增补；未到 Verify 阶段的条目状态记为「待执行」，不预先勾选。每版完成后按本版段落逐条核对，结果与 `eval.py` 输出、回归对比一起提交。

## 通用项（每版都查）

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| C-01 | 输入材料未改：SOP、技术方案、`corpus/**`（含 `manifest.json` 的 `file_name`）、`collect.py` | 与 `specs/00-source/README.md` 记录的大小与 SHA-256 比对 | 待执行 |
| C-02 | 规格快照与 `PROGRESS.md` 的「当前值」一致 | 逐文件 `sha256sum` | 待执行 |
| C-03 | 变更单状态无「已执行」等非模板状态 | 读 `specs/changes/` 各单头部 | 待执行 |
| C-04 | 交付说明文本按附录 C 扫描，扫描范围仅限 C.1 适用对象 | 关键词扫描 `src/**`、`README.md`、脚本用法文本 | 待执行 |
| C-05 | 密钥未进入任何文件与 git 历史 | `git grep -iE "sk-\|api_key="` 无命中；只出现变量名 | 待执行 |
| C-06 | 环境一致性：`deps_sha256` 等于 `runs` 表记录值 | 读 `requirements.lock.txt` 文本哈希，**不重跑 `pip freeze`** | 通过：`ae2cc83b…d6f3` 与 `runs`／`meta.json` 一致 |
| C-07 | `requirements.lock.txt` 已规范化（torch 行为 `torch==2.15.0+cpu`） | 跑 `scripts/normalize_lock.py`，输出「改写行数: 0」 | 通过：改写行数 0，幂等 |
| C-08 | 无删除类命令入口 | 检查 CLI 参数与接口清单 | 待执行 |
| C-09 | 默认账号表写「无」 | `README.md` 存在该节且值为「无」 | 待执行 |

## v0.1 专项

| # | 检查项 | 判定方式 | 状态 |
| --- | --- | --- | --- |
| V01-01 | 30 条锚点全部 `anchor_status=confirmed`，未确认数 0 | 读 `evals/cases.csv` 计数 | 通过：30/30，未确认 0（2026-11-18） |
| V01-02 | 30 条 `char_start`/`char_end` 非空，回切文本与 `anchor_text` 逐字一致 | 回填工具日志 | 通过：`fill_anchors.py --check` 30 条逐字一致，区间无空值 |
| V01-03 | 锚点可映射率 100%，`unmapped=0` | `eval.py` 输出 | 通过：`unmapped=0`、`unconfirmed=0`、多 chunk 映射 6 条 |
| V01-04 | 同一 `run_id` 连跑两次，`attempt-1/` 与 `attempt-2/` 的 `metrics.json` 逐字节一致 | `diff` 两文件 | 通过：attempt-1~4 均 544 字节、sha `a83df586…` |
| V01-05 | 两次运行 `run_id` 相同（不含日期） | 对比两次输出 | 通过：四次均为 `r98aa795a93cf` |
| V01-06 | 评测回路 LLM 调用 0 次 | 清空 `RAG_LLM_API_KEY` 后完整跑通 | 通过：key 未设置跑通，`src/` 无 openai 引用 |
| V01-07 | 指标齐全：Recall@1/3/5、MRR、nDCG@5、HitRate@5 | `eval.py` 输出 | 通过：0.7667／0.8333／0.9667／0.8317／0.8647／0.9667 |
| V01-08 | v0.1 语料仍为 2 篇 DOCX（未被 v0.2 的全量配置污染） | `documents` 行数 = 2 | 通过：`doc_count=2`，`chunks=34`，`source_format` 仅 docx |
| V01-09 | `requirements.lock.txt` 与 `deps_sha256` 已记录 | 读文件与 `PROGRESS.md` | 已就绪（2026-11-17） |
| V01-10 | 四件套 import 冒烟通过（numpy / faiss / torch / sentence-transformers） | `.venv\Scripts\python.exe -c "import numpy, faiss, torch, sentence_transformers"` | 已就绪（2026-11-17） |
