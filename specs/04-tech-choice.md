# 技术选型

选型原则：能解释机制的实现优先，不引入隐藏边界行为的高层封装；依赖数量与体积受「单机 CPU、内存 < 4GB」约束（D-010）。

## 1. 选型表

| 组件 | 候选 | 选择 | 理由 | 放弃理由 / 成本 |
| --- | --- | --- | --- | --- |
| 语言与运行时 | Python 3.10+ / 3.13 | Python 3.13.14（现环境） | 生态齐全，模型库与 FAISS 均支持 | — |
| DOCX 解析 | python-docx、PyMuPDF、docx2txt | `python-docx` | 保留段落结构与样式，能按段取文本与偏移；无子进程 | docx2txt 丢结构；PyMuPDF 面向 PDF，仅用于 PDF 对照样本 |
| PDF 解析 | PyMuPDF、pdfplumber | `PyMuPDF`（仅对照） | 与 python-docx 同为本地库，无需额外运行时 | PDF 不进索引（CHG-001），plumber 解析慢且表格还原不稳 |
| MD 解析 | markdown-it-py | **不引入** | 语料无 MD，官方也不提供 | 无使用场景（CHG-001） |
| HTML 解析 | BeautifulSoup | **不引入** | 语料无 HTML | 同上 |
| 切分 | 自实现、LangChain RecursiveCharacterTextSplitter | **自实现三种** | 切分策略是核心考点，需要能解释重叠、边界与锚点关系 | LangChain 封装隐藏边界行为，且引入额外依赖树 |
| Embedding | `BAAI/bge-small-zh-v1.5`、`text2vec-base-chinese`、`m3e-base`、`bge-base-zh` | **bge-small-zh-v1.5**（D-016） | 约 95MB、512 维、中文语料表现稳定；体积与「内存 <4GB」相容 | 三候选各约 400MB~1GB，且换模型使全部历史基线失效（D-016）；bge-base 精度更高但推理慢约 3 倍 |
| 向量索引 | faiss-cpu、numpy 暴力、Chroma、Qdrant | **faiss-cpu `IndexFlatIP` + `IDMap2`**（D-018） | 万级向量精确检索足够；`IDMap2` 保留自定义 id 便于回溯 | numpy 需自写持久化；Chroma/Qdrant 引入服务依赖，超出规模边界 |
| 相似度 | 内积、L2 | **归一化后内积（等价余弦）** | 归一化后内积排序与余弦一致，FAISS 的 `IndexFlatIP` 直接可用 | 未归一化时 L2 排序 ≠ 余弦排序，属常见错用 |
| 中文分词 | jieba、pkuseg、按字切 | **jieba**（v0.2） | 纯 Python、无需训练、词典可扩展 | 按字切会让 BM25 退化为字符匹配；pkuseg 依赖重、加载慢 |
| 稀疏检索 | rank_bm25、BM25S | **rank_bm25**（v0.2） | 实现短、可读，适合讲清 BM25 公式 | BM25S 更快但为稀疏矩阵实现，可读性差；当前语料规模无需 |
| 融合 | RRF、加权分数、学习排序 | **RRF**（v0.2） | 只用排名，免去两路量纲归一化 | 加权分数需两路分数分布稳定可比；学习排序需标注训练集 |
| Rerank | `BAAI/bge-reranker-base`、`ms-marco-MiniLM-L-6-v2`、FlashRank | **bge-reranker-base**（v0.3） | XLM-R 多语言，中文可用 | MiniLM/FlashRank 为纯英文模型，对中文给出「自信但无意义」的分数且不报错；base 版约 1.04GB，CPU 30 候选约 0.7~12 秒 |
| 存储 | SQLite、DuckDB、Postgres | **SQLite** | 单文件、零服务、事务可用，符合单机边界 | 其余需服务或额外运行时 |
| 服务框架 | FastAPI + Uvicorn、Flask | **FastAPI**（v0.4） | Pydantic 直接产出请求/响应 Schema，契约与代码同源 | Flask 需手写校验 |
| 展示 | Streamlit、Gradio、React | **Streamlit**（v0.5） | 单文件页面，不引入前端工程 | React 成本过高 |
| 配置 | YAML + 环境变量、.env 文件、纯代码常量 | **YAML + 环境变量** | 密钥只走环境变量，代码不写死 | .env 文件易被误提交；纯常量无法切换配置 |
| 测试 | unittest（标准库）、pytest | **unittest + compileall** | 环境无 pytest，标准库足够覆盖确定性逻辑 | pytest 体验更好，但需新增依赖（走依赖确认） |
| 生成层（v0.5） | 云端 LLM API、本地 Ollama | **云端 API（低配额）** | 调用量约 20~30 次，单次即可；不引入本地推理运行时 | Ollama 需额外进程与 1.5B 权重，演示环境不确定 |

## 2. 依赖清单

安装状态须逐条确认（D-010）。`requirements.txt` 只登记，不代表已安装；实际版本以安装后 `pip freeze` 结果回写本节。

| 包 | 版本约束 | 用途 | 体积量级 | 安装阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `python-docx` | ≥1.2 | DOCX 解析 | <1MB | v0.1 | 已装 1.2.0 |
| `numpy` | ≥2.0 | 向量运算、归一化 | 20MB | v0.1 | 已装 2.5.5 |
| `PyYAML` | ≥6.0 | 读 `config.yaml` | <1MB | v0.1 | 已装 6.0.3 |
| `pydantic` | ≥2.0 | 数据结构校验 | 5MB | v0.1 | 已装 2.14.3 |
| `torch` | 2.15.0+cpu | 模型运行时 | 约 121MB（CPU 轮子） | v0.1 | **已装（本地 wheel）** |
| `sentence-transformers` | ≥3.0 | 加载 bge 系列模型 | 20MB | v0.1 | 已装 3.4.1 |
| `faiss-cpu` | ≥1.8 | 向量索引 | 30MB | v0.1 | 已装 1.16.0 |
| `jieba` | ≥0.42 | 中文分词 | 20MB | v0.2 | 已装 0.42.1（源码包构建） |
| `rank_bm25` | ≥0.2 | 稀疏检索 | <1MB | v0.2 | 已装 0.2.2 |
| `fastapi` + `uvicorn` | ≥0.110 / ≥0.30 | HTTP 接口 | 30MB | v0.4 | 待装 |
| `streamlit` | ≥1.35 | 演示页 | 200MB | v0.5 | 已装 1.67.0（连带 pandas 3.1.1 / pyarrow 26.0.1 / altair 6.3.0） |
| `openai` | ≥1.0 | 云端 LLM 客户端 | 5MB | v0.5 | 待装（venv 内；工具解释器已有的不计） |

模型权重不通过 pip 安装，由 `HF_HOME=.cache/models` 首次加载时下载并缓存：

| 权重 | 体积 | 阶段 |
| --- | --- | --- |
| `BAAI/bge-small-zh-v1.5` | 约 95MB | v0.1 |
| `BAAI/bge-reranker-base` | 约 1.04GB | v0.3 |

**锁文件**：安装完成后 `pip freeze > requirements.lock.txt`，其内容 SHA-256 记为 `runs.deps_sha256`——**不进 `config_hash`**：锁是内容哈希，与配置指纹分开才能独立比对「环境变了」还是「配置变了」。Python 3.13 下 `torch` 与 `faiss-cpu` 的轮子可用性需实测，装不上时按 D-018 回退方案处理并记决策。

## 3. 安装环境与 CI 约束

| 项 | 值 |
| --- | --- |
| 解释器 | 项目 venv `.venv\Scripts\python.exe`（Python 3.13.14，与 cp313 轮子匹配）；工具自带解释器只用于创建 venv 与运行工具本身，其中已装的包不作依赖依据 |
| 源 | PyTorch 官方 CPU 索引 `https://download.pytorch.org/whl/cpu/torch/`；**不使用镜像** |
| 获取方式 | 从索引页解析 `download-r2` 直链与 `#sha256=`，断点续传（支持 Range）到 `.cache/wheels/`，按官方 SHA-256 校验后本地安装（D-019） |
| 直链 | `https://download-r2.pytorch.org/whl/cpu/torch-2.15.0%2Bcpu-cp313-cp313-win_amd64.whl` |
| wheel | `torch-2.15.0+cpu-cp313-cp313-win_amd64.whl` |
| 官方 SHA-256 | `086f79c78c941b428410dc15f898ce2420a4580ae6983ea314692d71ce76c619` |
| 实测速率 | 索引直连约 32 KB/s（26 分钟 54 MB 未完成）；`download-r2` 单连接 34~133 KB/s 波动，重连可恢复速率 |
| 其余包 | `sentence-transformers`、`faiss-cpu` 走默认 PyPI（实测 3.5 MB/s，无瓶颈） |
| 锁文件 | `.venv\Scripts\python.exe -m pip freeze > requirements.lock.txt`，固定 `torch==2.15.0+cpu`；哈希记 `runs.deps_sha256`，Verify 时比对 |
| 模型权重 | `scripts/download_model.py`：读官方 API `blobs=true` 元数据，直连 GET（≥16MB 按 Range 6 段并行），逐文件按官方 SHA-256 校验后落 `$HF_HOME/<模型名>/`（D-022） |
| 防回退 | `requirements.txt` 顶部注明**禁止 `pip install -r requirements.txt`**——该命令会把 torch 解析成 CUDA 版；torch 只能按本节登记的 `--index-url` 或本地 wheel 安装 |
| 冒烟 | 在 venv 内依次 `import numpy`、`import faiss`、`import torch`，版本与兼容性记入 `PROGRESS.md` |
| CI（v0.4） | 只跑**已缓存向量**的纯计算评测：模型权重与 FAISS 索引走 CI cache，workflow 不重装 torch；解释器统一 `.venv\Scripts\python.exe` |

### 3.1 实测记录

| 项 | 实测值 |
| --- | --- |
| venv | `.venv`，Python 3.13.14，pip 26.1.2 |
| numpy | 2.5.5 |
| faiss-cpu | 1.16.0；`IndexFlatIP` + `normalize_L2` 自检通过（查询 `[0,1,0]` → 命中下标 1，分数 1.0） |
| torch | **2.15.0+cpu**；`torch.cuda.is_available() = False`（符合 CPU 版预期）；张量前向自检通过 |
| sentence-transformers | 3.4.1（附 transformers 4.57.6、tokenizers 0.22.2、huggingface-hub 0.36.2） |
| python-docx / PyYAML / pydantic | 1.2.0 / 6.0.3 / 2.14.3 |
| import 冒烟 | numpy ✅ / faiss ✅ / torch ✅ / sentence-transformers ✅（同进程一次跑通） |
| 模型权重 | `bge-small-zh-v1.5` 12 个文件、**96,407,485 字节（91.9 MB）**；`model.safetensors` 95,827,648 字节、sha256 `354763b9b1357bc9…` 与官方 LFS 元数据一致；6 段并行下载 **372.5 s**（聚合约 258 KB/s）；落 `.cache/models/bge-small-zh-v1.5/` |
| 权重可用性 | `HF_HUB_OFFLINE=1` 下 `SentenceTransformer(本地目录)` 加载 0.2 s，编码 2 条 0.09 s，维度 512，向量 L2 范数 1.0 |
| 已知偏差 | 本机 CDN 剥离 `X-Repo-Commit`／`X-Linked-Etag`，`huggingface_hub` 抛 `FileMetadataError` 拒绝下载 LFS 文件；改用 `scripts/download_model.py`（D-022） |
| wheel 校验 | 126,626,022 字节；sha256 `086f79c7…c619` 与官方索引一致 |
| 下载方式 | 6 段并行 Range + 尾段补传，实测聚合约 215 KB/s；单连接仅 23~34 KB/s（D-020） |
| 锁文件 | `requirements.lock.txt` 40 行；`deps_sha256 = ae2cc83b6ae374acfc373bd8fdd19c1454ae62a045d58019f2e1377c1790d6f3` |

**锁文件的 torch 行需手工规范化**：`pip freeze` 会把本地安装的 wheel 写成 `torch @ file:///…` 绝对路径，跨机器不可用。规范化由脚本执行，不手改：

```
.venv\Scripts\python.exe scripts/normalize_lock.py
```

脚本把该行改写为 `torch==2.15.0+cpu` 并保留官方 sha256 作为行尾注释，同时打印 `deps_sha256`。脚本幂等，重复运行不改变结果。

**Verify 口径**：比对对象是 `requirements.lock.txt` 的**文件文本哈希**，Verify 阶段**不重跑 `pip freeze`**——重跑会把本机路径重新写回、并因环境差异产生新哈希，导致「环境一致」与「锁文件一致」两个判断混淆。判断环境是否漂移看 `deps_sha256` 是否等于 `runs` 表记录值；判断锁文件是否被改看工作区 diff。

**已就绪**：三者 import 与版本兼容全部通过（2026-11-17），T-006 可开工。

## 4. 明确不引入

`LangChain` 作为唯一实现、`markdown-it-py`、`BeautifulSoup`、`Chroma`、`Qdrant`、`BM25S`、`pkuseg`、`ms-marco-MiniLM` / `FlashRank`、`pytest`（暂）、`ruff`（暂）、任何云端向量或检索引擎。
