# 安全与权限

无 LLM 参与运行时决策，防注入降级为**外部不可信输入校验**（SOP 7.2）。

## 1. 权限矩阵

| 操作 | 风险等级 | 执行身份 | 允许范围 | 是否需人工确认 |
| --- | --- | --- | --- | --- |
| 读 `corpus/docs/*.docx` | 低 | 本地进程 | 只读，白名单校验 | 否 |
| 读 `corpus/metadata/manifest.json` | 低 | 本地进程 | 只读 | 否 |
| 写 `data/rag.db` | 中 | 本地进程 | 仅本库，事务内 | 否 |
| 写 `data/index/` | 中 | 本地进程 | 仅索引产物 | 否 |
| 写 `data/runs/`、`data/trace.jsonl` | 低 | 本地进程 | 追加/覆盖同名 `run_id` | 否 |
| 写 `.cache/models` | 低 | 模型库 | 仅权重缓存 | 否 |
| 下载模型权重 | 中 | 模型库 | 仅 `HF_HOME` 指向的 `BAAI/*` | 首次运行前告知 |
| 删除任何数据 | **禁止** | — | 不提供删除命令、不提供清库入口（REQ-055） | 不适用 |
| 写 `corpus/**` | **禁止** | — | 语料只读（含 manifest 的 `file_name`） | 不适用 |
| 调用云端 LLM | 中 | 本地进程 | 仅 v0.5 `/ask`，配额上限 50 次 | 演示前确认 |
| `git push` | 高 | 人工 | 仅本地 commit 由 Agent 执行 | **是** |

## 2. 外部不可信输入校验

`/ingest` 与 CLI 的入库入口都要过这四道：

| 校验 | 规则 | 失败响应 |
| --- | --- | --- |
| 扩展名 | 仅 `.docx`（REQ-007） | `ENTRY_UNSUPPORTED_FORMAT` |
| 大小 | 单文件上限取 `config.yaml` 的 `ingest.max_file_mb`（默认 20MB） | `ENTRY_TOO_LARGE` |
| 路径 | 拒绝含 `..`、绝对路径、符号链接（REQ-054） | `ENTRY_UNSAFE_PATH` |
| 包结构 | 头部 `PK\x03\x04`；解压后正文总字节上限（默认 100MB，防 ZIP 炸弹） | `PARSE_FAILED` |

正文内容不做模板求值、不做 `eval`/`exec`、不拼接为 SQL（全部参数化查询）。

## 3. 密钥与环境变量

| 变量 | 用途 | 缺失时行为 |
| --- | --- | --- |
| `RAG_DB_PATH` | SQLite 路径 | 启动报错，不使用默认路径 |
| `HF_HOME` | 模型缓存目录 | 回退到用户默认缓存并给出警告 |
| `RAG_LLM_API_KEY` | `/ask` 调用凭证 | 仅 `/ask` 报 `CONFIG_MISSING_KEY`，检索不受影响（REQ-052） |
| `RAG_LLM_BASE_URL` / `RAG_LLM_MODEL` | 接口地址与模型名 | 同上 |

- 值不写入代码、`config.yaml`、文档、日志、git 历史。
- 日志与 trace 只允许出现变量名，不出现值。

## 4. 工具白名单

Agent 在实施期允许执行的命令类型：

| 允许 | 说明 |
| --- | --- |
| `.venv\Scripts\python.exe -m src.cli.*` | 项目入口；一律用项目 venv，不用工具自带解释器 |
| `.venv\Scripts\python.exe -m compileall` | 语法自检 |
| `.venv\Scripts\python.exe -m unittest` | 单元测试 |
| `pip install <04-tech-choice 已确认的包>` | 装依赖，须在 venv 内执行；装完 `pip freeze` 记锁文件 |
| 从 `download.pytorch.org` / `download-r2.pytorch.org` 下载 wheel | 仅限 `04-tech-choice.md` 登记的文件名与 SHA-256；下载后校验再装 |
| `pip install <本地 wheel 路径>` | 装已校验的本地 wheel，不走索引 |
| `sqlite3` 只读查询 / `python` 读库 | 核对行数 |
| `git add / commit / status / diff / log` | 本地提交 |
| `git push` | **仅用户明确指示时**，且不推 main、不 force |

禁止：`rm -rf`、`del /S`、任何形式的批量删除、`git reset --hard`、`git push --force`、修改 `corpus/**`。

## 5. 日志脱敏

- trace 的 `excerpt` 上限 80 码点（D-009），不写完整原文。
- 路径只记相对项目根的路径，不记用户目录。
- 错误响应只回错误码与字段名，`INTERNAL_ERROR` 不回栈信息（栈写本地日志，含追踪 id）。
- 语料为公开法规、无 PII；即便如此，日志仍按最小必要记录。

## 6. 数据合规

| 项 | 处置 |
| --- | --- |
| 语料来源 | 国家法律法规数据库官方 DOCX，依据著作权法第五条（`corpus/README.md`） |
| 出域 | v0.5 `/ask` 会把命中片段发给云端 LLM，语料为公开法规、无 PII，已获批准 |
| 日志保留 | `data/trace.jsonl` 与 `data/runs/` 本地保留，不入库 |
| 第三方语料 | 不引入（CHG-001） |
