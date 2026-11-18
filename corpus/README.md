# 法律法规语料

## 内容

- `docs/`：国家法律法规数据库发布的 DOCX 原件，正文未改动；文件名由标题、公布日期与文档标识组成。
- `metadata/manifest.json`、`metadata/manifest.csv`：每篇的标识、名称、类别、制定机关、公布日期、生效日期、状态字段、详情页链接、官方下载接口、文件名、字节数、SHA-256 与获取时间。
- `metadata/failures.json`：官方接口未提供 DOCX 或下载失败的条目及原因。
- `tools/collect.py`：按官方接口重新检索、下载并校验；重复执行会跳过 `manifest.json` 中已有的条目。

## 资料来源与依据

来源：国家法律法规数据库 https://flk.npc.gov.cn ，通过官方检索接口 `/law-search/search/list` 与下载接口 `/law-search/download/pc` 获取。每篇的详情页链接见 `manifest.json` 的 `source_url`。

依据：《中华人民共和国著作权法》第五条规定，法律、法规，国家机关的决议、决定、命令和其他具有立法、行政、司法性质的文件及其官方正式译文不适用该法。本目录仅保存官方发布的原始文件，未改写内容；使用与再分发以国家法律法规数据库的服务条款为准。语料不含个人信息、内部资料或企业机密。

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `doc_id` | 官方详情页使用的文档标识 |
| `title` | 法规名称，已去除检索结果中的高亮标记 |
| `category` | 官网返回的法规类别 |
| `authority` | 制定机关 |
| `publish_date` / `effective_date` | 公布日期、施行日期 |
| `status_code` | 官网返回的原始状态值，含义以对应详情页为准 |
| `source_url` | 官方详情页 |
| `official_download_api` | 获取该文件下载地址的官方接口 |
| `file_name` / `bytes` / `sha256` | 本地文件名、字节数、内容校验值 |
| `retrieved_at` | 文件获取时间（UTC） |

## 使用与校验

依赖：Python 3.10+ 标准库，不需要第三方包。

在 PowerShell 或 Git Bash，`D:\02-Projects\python\python project\rag\corpus` 目录下执行：`python tools/collect.py .` —— 重新检索并下载，跳过已记录的条目，刷新元数据。

每个 DOCX 应以 `PK\x03\x04` 开头（OOXML 包），字节数应与 `manifest.json` 一致；内容完整性可比对 `sha256`。官方接口未提供 DOCX 的条目记录在 `failures.json`，可稍后重试。

## 与检索链路的衔接

`category`、`publish_date`、`effective_date`、`status_code` 可作为元数据过滤维度；法规正文的条款编号适合检验精确匹配与归一化；同一名称、不同公布日期的文件可用于版本识别与相似文档区分。检索评测集需人工标注 `doc_id`、章节路径与原文字符区间，标注不要依赖切分后的块编号。
