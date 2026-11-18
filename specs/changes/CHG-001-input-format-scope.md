# 变更单 #001：A1 输入格式范围由「PDF/DOCX/MD」收窄为「DOCX + 官方同源 PDF（仅解析对照）」

- 日期：2026-11-16
- 发起方：用户（P0#4 决策，Agent 起草）
- 状态：**已确认**（2026-11-16 用户批准，含配套决策：PDF 对照样本落 `data/pdf-refs/`，`corpus/` 保持只读原样）。规格层已落地，剩余执行/回归随 v0.2/v0.4 对应任务完成后转已完成。

**剩余执行清单**

| 项 | 状态 | 转「已完成」的条件 |
| --- | --- | --- |
| 规格收窄（7 份文档口径） | 已落地 | — |
| 索引只含 `docx` 的断言 | 已落地（T-005 入库后校验 `source_format` 唯一值为 `docx`） | — |
| PDF 对照样本采集与解析对照实验 | 未开始 | v0.4 执行，样本落 `data/pdf-refs/`，且不进索引 |
| PDF 进索引（如需） | 未启动 | 另出变更单并经 G2 |

## 背景与原因

技术方案 A1 写「PDF/DOCX/MD → 统一结构」，第 2 节技术栈并列 PyMuPDF／pdfplumber、python-docx、markdown-it-py、BeautifulSoup，含义是三种输入格式都要解析。实际语料 `corpus/docs/` 为 150 篇 `.docx`，全库无 PDF、无 MD：

| 实测项 | 结果 |
| --- | --- |
| 文件总数 | 150，扩展名全部为 `.docx` |
| 官方是否提供 MD | 否，官方仅提供 DOCX／PDF 等文件格式 |
| 官方是否提供 PDF | 是，同一 `doc_id` 可经 `/law-search/download/pc?format=pdf` 取同源原件 |

若按原文实现，必须从语料子树之外引入 PDF／MD 文档，会破坏两条既有边界：元数据口径统一（`manifest.json` 逐篇记录 `sha256`／`file_name`，外部文档无对应条目）、许可证与来源可追溯（`corpus/README.md` 已按著作权法第五条声明来源）。

## 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| A1 输入格式 | PDF／DOCX／MD | DOCX（v1 唯一进索引格式）；PDF 仅作解析层对照样本 |
| 索引与 gold 锚点基准 | 混合格式解析文本 | **DOCX 解析文本为唯一基准**，锚点字符区间据此定义 |
| PDF 用途 | 与 DOCX 同级输入 | 按同一批 `doc_id` 从官方接口取同源原件，只作解析层对照，**不进检索索引、不参与任何指标** |
| PDF 升级为进索引的路径 | 未定义 | 须另出变更单并重新过 G2，不在本单授权内 |
| MD | 输入格式之一 | 不引入。官方不提供；第三方 MD 语料一律不引入（授权与元数据口径不同） |
| 解析库 | PyMuPDF／pdfplumber、python-docx、markdown-it-py、BeautifulSoup 并列 | v0.1 只引入 python-docx；PDF 解析器仅在对照实验启用时由 PyMuPDF 承担；markdown-it-py、BeautifulSoup **不引入** |

技术方案原文属 `specs/00-source/` 只读归档，本单不改其正文；差异以本单 + `CHANGELOG-DECISIONS.md` 为追溯依据。

## 影响范围分析

### 波及的规格文档

| 文档 | 受影响的章节 |
| --- | --- |
| `01-requirements.md` | A1 相关验收条款；需新增一条「PDF 对照样本不得出现在检索结果中」 |
| `02-scope.md` | 输入格式边界、明确不做清单（加「v1 不做 MD 输入」「v1 不做 PDF 进索引」） |
| `03-architecture.md` | 解析层数据流（DOCX 主链路与 PDF 对照支路分离） |
| `04-tech-choice.md` | 解析库选型表，记录 pdfplumber／markdown-it-py／BeautifulSoup 的放弃理由 |
| `05-modules.md` | `parser` 模块职责与依赖方向；对照支路为旁路，不进入 `ingest` 主链 |
| `06-schemas/` | `Document.source_format` 枚举取值 |
| `11-errors.md` | 解析失败分支（DOCX 损坏／空正文） |

### 波及的模块与文件

- `src/` 解析器：v0.1 只实现 DOCX 解析；PDF 对照脚本独立，不进入检索主链。
- `ingest` 命令行：`--format` 参数取值由 `{pdf,docx,md}` 收窄为 `{docx}`，保留解析器注册接口以便 v2 扩展。
- `config.yaml`：`parser.formats` 只列 `docx`；PDF 对照开关默认关闭。

### 波及的接口／数据结构／Schema

- `Document.source_format`：v1 取值域 `{"docx"}`；`"pdf"` 作为预留值写入 Schema 枚举但不产生实例，避免后续加值造成契约破坏。
- chunk 表、锚点结构（`doc_id` + 标题路径 + 字符区间）、评测 CSV 列名均不变。

### 需要更新的评测用例

- 现有 `evals/cases.csv` 行结构不变，gold 锚点基准不变（DOCX 文本），**无需重标**。
- 新增 1 条断言类用例：文档集合中不存在 `source_format == "pdf"` 的 chunk，用于防止对照样本误入索引。

### 对成本／性能／安全的影响

- 成本：无 LLM 影响。依赖面收窄，少装 markdown-it-py／BeautifulSoup。
- 性能：索引规模不变。PDF 对照为离线一次性实验，不进每次评测回路。
- 安全：外部不可信输入面不变（本就只读 `corpus/docs/`）。PDF 对照样本若落盘，需与语料目录隔离，避免被误扫描。

## 配套决策（已确认：方案 A）

PDF 对照样本的存放位置：

| 方案 | 路径 | 说明 |
| --- | --- | --- |
| A（建议） | `data/pdf-refs/` | `corpus/` 保持只读原样，PDF 属项目中间产物，进 `.gitignore`；对照结论以表格形式写入 `evals/` 或规格 |
| B | `corpus/pdf-refs/` | 与语料同处，便于溯源；但会改动语料子树目录结构，与「corpus 只读」约束冲突，且需同步维护校验口径 |

## 执行方案

1. 本单批准后，按新口径产出 `02-scope.md` 与 `01-requirements.md`，`00-source/` 归档时附本单编号。
2. 步骤 3 在 `04-tech-choice.md` 记录解析库降级理由与放弃备选。
3. PDF 对照实验推迟到 v0.4，执行前单独确认样本位置与数量；若结论要求 PDF 进索引，另出变更单。

## 回归验证

- v0.1 生效依据：同一 `run_id` 连跑两次 `eval.py` 输出完全一致。
- 锚点可映射率 100%：30 条 gold 锚点全部落在 DOCX 解析文本内。
- 新增断言：索引内 `source_format` 取值集合等于 `{"docx"}`。

## 回滚方式

恢复 A1 原文口径：`source_format` 枚举放开 `pdf`／`md`，补充对应解析器实现，并重跑锚点映射校验。回滚不影响已产出的 DOCX 侧数据。
