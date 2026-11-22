"""读取 config.yaml 与环境变量，产出只读配置对象。

约定：本模块不读取、不缓存任何凭据值；数据库路径与模型缓存目录只从环境变量取，
变量名本身来自配置（`db.path_env`）。
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

STRATEGIES = ("fixed", "recursive", "sliding")


class ConfigError(RuntimeError):
    """配置缺失或取值非法。"""


@dataclass(frozen=True)
class Paths:
    data_dir: pathlib.Path
    index_dir: pathlib.Path
    runs_dir: pathlib.Path
    trace_file: pathlib.Path
    pdf_refs_dir: pathlib.Path
    migrations_dir: pathlib.Path


@dataclass(frozen=True)
class CorpusConfig:
    docs_dir: pathlib.Path
    manifest: pathlib.Path
    v01_subset: tuple[str, ...]
    full_dir: pathlib.Path


@dataclass(frozen=True)
class IngestConfig:
    max_file_mb: int
    max_unpacked_mb: int
    max_failure_rate: float


@dataclass(frozen=True)
class SplitConfig:
    strategy: str
    chunk_size: int
    overlap: int


@dataclass(frozen=True)
class ModelConfig:
    embedding_name: str
    embedding_dim: int
    embedding_revision: str
    batch_size: int
    device: str
    rerank_name: str


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int
    candidate_k: int
    rrf_k: int
    rerank_top_n: int
    rerank_timeout_ms: int
    use_bm25: bool
    use_rerank: bool


@dataclass(frozen=True)
class EvalConfig:
    cases_file: pathlib.Path
    bootstrap_rounds: int
    metrics: tuple[str, ...]


@dataclass(frozen=True)
class RunConfig:
    seed: int
    normalizer_version: int


@dataclass(frozen=True)
class ServerConfig:
    api_host: str
    api_port: int
    ui_port: int
    ui_port_agent: int = 8502


# Agent 的 8 项默认值（`CHG-013` §7）。与 `src.agent.quota.AgentSettings` 的字段默认值逐项一致，
# 两边由 tests/test_agent_memory.py 的断言绑定：改一边漏一边会直接红。
AGENT_DEFAULTS = {
    "max_turns": 2,
    "timeout_seconds": 30.0,
    "max_calls_per_question": 2,
    "max_calls_per_session": 20,
    "max_tool_calls_per_turn": 3,
    "max_context_turns": 3,
    "max_tool_chars": 2000,
    "session_ttl_hours": 24.0,
}

# 这三项直接决定一轮问答最多烧多少调用/上下文，配置只能下调
AGENT_HARD_CAPS = {"max_turns": 2, "max_tool_calls_per_turn": 3, "max_context_turns": 3}

_AGENT_FLOAT_KEYS = ("timeout_seconds", "session_ttl_hours")


@dataclass(frozen=True)
class AgentConfig:
    """`config.yaml` 的 `agent` 段；默认值即 §7 口径，硬上限在 `_parse_agent` 里拦。"""

    max_turns: int
    timeout_seconds: float
    max_calls_per_question: int
    max_calls_per_session: int
    max_tool_calls_per_turn: int
    max_context_turns: int
    max_tool_chars: int
    session_ttl_hours: float


@dataclass(frozen=True)
class LlmConfig:
    api_key_env: str
    base_url_env: str
    model_env: str
    timeout_seconds: int
    max_calls: int
    # 非密钥字面值（CHG-012）：配置里给默认模型名与接口地址，环境变量作覆盖。
    # 缺省为空串，老配置文件不带这两个键也能加载。
    model_name: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class Config:
    """项目运行参数。字段为只读，构造后不再变更。"""

    source: pathlib.Path
    corpus: CorpusConfig
    ingest: IngestConfig
    split: SplitConfig
    model: ModelConfig
    retrieval: RetrievalConfig
    eval: EvalConfig
    run: RunConfig
    server: ServerConfig
    agent: AgentConfig
    llm: LlmConfig
    paths: Paths
    db_path_env: str
    model_cache_env: str
    excerpt_max_chars: int
    raw: Mapping[str, Any]

    def resolve(self, value: str | pathlib.Path) -> pathlib.Path:
        """把配置里的相对路径解析到项目根；绝对路径原样返回。"""
        path = pathlib.Path(value)
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    def require_db_path(self) -> pathlib.Path:
        """取数据库路径；变量缺失或为空时立刻报错，不使用默认值。"""
        raw = os.environ.get(self.db_path_env, "").strip()
        if not raw:
            raise ConfigError("环境变量 %s 未设置或为空，数据库路径必须由它注入" % self.db_path_env)
        return pathlib.Path(raw)

    def model_cache_dir(self) -> pathlib.Path | None:
        """模型缓存目录；未设置环境变量时返回 None，由调用方决定是否告警。"""
        raw = os.environ.get(self.model_cache_env, "").strip()
        return pathlib.Path(raw) if raw else None


def _need(section: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in section:
        raise ConfigError("配置缺少 %s.%s" % (where, key))
    return section[key]


def _as_dir(cfg: Mapping[str, Any], dotted: str) -> pathlib.Path:
    node: Any = cfg
    for part in dotted.split("."):
        node = _need(node, part, dotted)
    return (PROJECT_ROOT / str(node)).resolve()


def _parse_agent(raw: Mapping[str, Any] | None) -> AgentConfig:
    """读 `agent` 段：缺键取默认值；三项硬上限与正数校验在这里拦（与 `AgentSettings` 同一条口径）。"""
    section = raw or {}
    if not isinstance(section, Mapping):
        raise ConfigError("agent 段必须是映射")

    values: dict[str, Any] = {}
    for name, default in AGENT_DEFAULTS.items():
        raw_value = section.get(name, default)
        try:
            values[name] = float(raw_value) if name in _AGENT_FLOAT_KEYS else int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("agent.%s 取值非法：%r" % (name, raw_value)) from exc

    for name, cap in AGENT_HARD_CAPS.items():
        if values[name] < 1:
            raise ConfigError("agent.%s 必须为正整数（当前 %r）" % (name, values[name]))
        if values[name] > cap:
            raise ConfigError(
                "agent.%s 只能下调，不得大于默认上限 %d（当前 %d）：见 CHG-013 §7" % (name, cap, values[name])
            )
    if values["timeout_seconds"] <= 0:
        raise ConfigError("agent.timeout_seconds 必须为正数")
    if values["session_ttl_hours"] <= 0:
        raise ConfigError("agent.session_ttl_hours 必须为正数")
    for name in ("max_calls_per_question", "max_calls_per_session", "max_tool_chars"):
        if values[name] < 1:
            raise ConfigError("agent.%s 必须为正整数" % name)
    if values["max_calls_per_question"] > values["max_calls_per_session"]:
        raise ConfigError("agent.max_calls_per_question 不得大于 max_calls_per_session")
    return AgentConfig(**values)


def load(path: str | pathlib.Path | None = None, require_db: bool = False) -> Config:
    """加载配置并校验取值范围。

    `require_db=True` 时额外要求 `RAG_DB_PATH` 已设置；解析类任务不需要数据库，
    默认不检该项，但任何真正取用数据库路径的调用都会由 `require_db_path()` 报错。
    """
    config_path = pathlib.Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError("找不到配置文件 %s" % config_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("配置文件格式错误：顶层应为映射")

    corpus = _need(raw, "corpus", "root")
    docs_dir = PROJECT_ROOT / str(_need(corpus, "docs_dir", "corpus"))
    manifest = PROJECT_ROOT / str(_need(corpus, "manifest", "corpus"))
    subset = tuple(str(x) for x in (_need(corpus, "v01_subset", "corpus") or []))
    full = corpus.get("full") or {}
    full_dir = PROJECT_ROOT / str(full.get("dir", corpus["docs_dir"]))

    ingest = _need(raw, "ingest", "root")
    max_file_mb = int(_need(ingest, "max_file_mb", "ingest"))
    max_unpacked_mb = int(_need(ingest, "max_unpacked_mb", "ingest"))
    max_failure_rate = float(_need(ingest, "max_failure_rate", "ingest"))
    if max_file_mb <= 0 or max_unpacked_mb <= 0:
        raise ConfigError("ingest.max_file_mb 与 ingest.max_unpacked_mb 必须为正数")
    if not 0.0 <= max_failure_rate <= 1.0:
        raise ConfigError("ingest.max_failure_rate 应在 [0, 1] 内")

    split = _need(raw, "split", "root")
    strategy = str(_need(split, "strategy", "split"))
    chunk_size = int(_need(split, "chunk_size", "split"))
    overlap = int(_need(split, "overlap", "split"))
    if strategy not in STRATEGIES:
        raise ConfigError("split.strategy 只允许 %s" % (STRATEGIES,))
    if chunk_size < 32:
        raise ConfigError("split.chunk_size 不得小于 32")
    if not 0 <= overlap < chunk_size:
        raise ConfigError("split.overlap 应满足 0 <= overlap < chunk_size")

    model = _need(raw, "model", "root")
    embedding_dim = int(_need(model, "embedding_dim", "model"))
    if embedding_dim <= 0:
        raise ConfigError("model.embedding_dim 必须为正数")

    retrieval = _need(raw, "retrieval", "root")
    top_k = int(_need(retrieval, "top_k", "retrieval"))
    candidate_k = int(_need(retrieval, "candidate_k", "retrieval"))
    rerank_top_n = int(_need(retrieval, "rerank_top_n", "retrieval"))
    if not 1 <= top_k <= 50:
        raise ConfigError("retrieval.top_k 应在 [1, 50] 内")
    if candidate_k < top_k:
        raise ConfigError("retrieval.candidate_k 不得小于 top_k")
    if rerank_top_n < top_k:
        raise ConfigError("retrieval.rerank_top_n 不得小于 top_k")

    eval_cfg = _need(raw, "eval", "root")
    metrics = tuple(str(x) for x in (_need(eval_cfg, "metrics", "eval") or []))
    if not metrics:
        raise ConfigError("eval.metrics 不得为空")

    run = _need(raw, "run", "root")
    normalizer_version = int(_need(run, "normalizer_version", "run"))
    if normalizer_version < 0:
        raise ConfigError("run.normalizer_version 不得为负")

    server = _need(raw, "server", "root")
    api_port = int(_need(server, "api_port", "server"))
    ui_port = int(_need(server, "ui_port", "server"))
    ui_port_agent = int(server.get("ui_port_agent", 8502))
    for name, port in (
        ("server.api_port", api_port),
        ("server.ui_port", ui_port),
        ("server.ui_port_agent", ui_port_agent),
    ):
        if not 1 <= port <= 65535:
            raise ConfigError("%s 应在 [1, 65535] 内" % name)

    llm = _need(raw, "llm", "root")
    timeout_seconds = int(_need(llm, "timeout_seconds", "llm"))
    max_calls = int(_need(llm, "max_calls", "llm"))
    if timeout_seconds <= 0 or max_calls <= 0:
        raise ConfigError("llm.timeout_seconds 与 llm.max_calls 必须为正数")

    db = _need(raw, "db", "root")
    paths_raw = _need(raw, "paths", "root")
    logging_raw = _need(raw, "logging", "root")
    excerpt_max_chars = int(_need(logging_raw, "excerpt_max_chars", "logging"))
    if not 1 <= excerpt_max_chars <= 1000:
        raise ConfigError("logging.excerpt_max_chars 应在 [1, 1000] 内")

    conf = Config(
        source=config_path,
        corpus=CorpusConfig(
            docs_dir=docs_dir,
            manifest=manifest,
            v01_subset=subset,
            full_dir=full_dir,
        ),
        ingest=IngestConfig(
            max_file_mb=max_file_mb,
            max_unpacked_mb=max_unpacked_mb,
            max_failure_rate=max_failure_rate,
        ),
        split=SplitConfig(strategy=strategy, chunk_size=chunk_size, overlap=overlap),
        model=ModelConfig(
            embedding_name=str(_need(model, "embedding_name", "model")),
            embedding_dim=embedding_dim,
            embedding_revision=str(model.get("embedding_revision", "")),
            batch_size=int(model.get("batch_size", 16)),
            device=str(model.get("device", "cpu")),
            rerank_name=str(model.get("rerank_name", "")),
        ),
        retrieval=RetrievalConfig(
            top_k=top_k,
            candidate_k=candidate_k,
            rrf_k=int(retrieval.get("rrf_k", 60)),
            rerank_top_n=rerank_top_n,
            rerank_timeout_ms=int(retrieval.get("rerank_timeout_ms", 3000)),
            use_bm25=bool(retrieval.get("use_bm25", False)),
            use_rerank=bool(retrieval.get("use_rerank", False)),
        ),
        eval=EvalConfig(
            cases_file=PROJECT_ROOT / str(_need(eval_cfg, "cases_file", "eval")),
            bootstrap_rounds=int(eval_cfg.get("bootstrap_rounds", 1000)),
            metrics=metrics,
        ),
        run=RunConfig(seed=int(_need(run, "seed", "run")), normalizer_version=normalizer_version),
        server=ServerConfig(
            api_host=str(server.get("api_host", "127.0.0.1")),
            api_port=api_port,
            ui_port=ui_port,
            ui_port_agent=ui_port_agent,
        ),
        agent=_parse_agent(raw.get("agent")),
        llm=LlmConfig(
            api_key_env=str(_need(llm, "api_key_env", "llm")),
            base_url_env=str(_need(llm, "base_url_env", "llm")),
            model_env=str(_need(llm, "model_env", "llm")),
            timeout_seconds=timeout_seconds,
            max_calls=max_calls,
            model_name=str(llm.get("model_name", "") or "").strip(),
            base_url=str(llm.get("base_url", "") or "").strip(),
        ),
        paths=Paths(
            data_dir=_as_dir(paths_raw, "data_dir"),
            index_dir=_as_dir(paths_raw, "index_dir"),
            runs_dir=_as_dir(paths_raw, "runs_dir"),
            trace_file=_as_dir(paths_raw, "trace_file"),
            pdf_refs_dir=_as_dir(paths_raw, "pdf_refs_dir"),
            migrations_dir=(PROJECT_ROOT / str(_need(db, "migrations_dir", "db"))).resolve(),
        ),
        db_path_env=str(_need(db, "path_env", "db")),
        model_cache_env=str(model.get("cache_env", "HF_HOME")),
        excerpt_max_chars=excerpt_max_chars,
        raw=raw,
    )

    for label, target in (("corpus.docs_dir", conf.corpus.docs_dir), ("corpus.manifest", conf.corpus.manifest)):
        if not target.exists():
            raise ConfigError("%s 指向的路径不存在：%s" % (label, target))

    if require_db:
        conf.require_db_path()
    return conf


def main() -> int:
    """命令行自检：打印关键参数，缺数据库变量时以非零码退出。"""
    try:
        conf = load(require_db=True)
        db_path = conf.require_db_path()
    except ConfigError as exc:
        print("配置错误: %s" % exc)
        return 2
    cache = conf.model_cache_dir()
    print("配置文件: %s" % conf.source)
    print("语料目录: %s（v0.1 子集 %d 篇）" % (conf.corpus.docs_dir, len(conf.corpus.v01_subset)))
    print("数据库: %s" % db_path)
    print("模型缓存: %s" % (cache if cache else "未设置 %s" % conf.model_cache_env))
    print("切分: %s / %d / overlap %d" % (conf.split.strategy, conf.split.chunk_size, conf.split.overlap))
    print("检索 top_k=%d candidate_k=%d" % (conf.retrieval.top_k, conf.retrieval.candidate_k))
    print("端口: api %d / ui %d" % (conf.server.api_port, conf.server.ui_port))
    print("LLM 配额: 超时 %d 秒 / 上限 %d 次" % (conf.llm.timeout_seconds, conf.llm.max_calls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
