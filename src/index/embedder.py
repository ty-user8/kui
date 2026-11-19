"""Embedding：加载本地权重、批量编码、L2 归一化，并给出权重指纹。

权重优先用本地目录（`$HF_HOME/<模型名>`，由 `scripts/download_model.py` 落盘），
命中本地即设 `HF_HUB_OFFLINE=1`，保证评测回路不发起网络请求。
`weights_sha256` 取权重文件的 SHA-256，用于 `runs` 表留痕：模型名与 revision 相同
但本地文件被替换时，`run_id` 不变而向量会变，必须能查出来。
"""

from __future__ import annotations

import hashlib
import os
import pathlib

import numpy as np

WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
PATH_MAX_CHARS = 60
MAX_TOKENS = 512


def build_index_text(heading_path: str, text: str, path_max: int = PATH_MAX_CHARS) -> tuple[str, bool]:
    """把标题路径拼在正文前；路径超过 `path_max` 字时截断。返回（索引文本, 是否截断）。"""
    path = (heading_path or "").strip()
    truncated = False
    if len(path) > path_max:
        path = path[:path_max]
        truncated = True
    if not path:
        return text, truncated
    return "%s\n%s" % (path, text), truncated


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Embedder:
    """一次加载、批量编码；编码结果按 L2 归一化，满足 REQ-011。"""

    def __init__(self, conf, model_dir: pathlib.Path | None = None) -> None:
        self.model_name = conf.model.embedding_name
        self.revision = conf.model.embedding_revision or ""
        self.batch_size = conf.model.batch_size
        self.device = conf.model.device
        self.dim = conf.model.embedding_dim

        root = model_dir or self._locate_local(conf)
        self.local_dir = root
        if root is not None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        target = str(root) if root is not None else self.model_name

        from sentence_transformers import SentenceTransformer  # 延迟导入，避免无谓启动开销

        self._model = SentenceTransformer(target, device=self.device)
        self._weights_path = self._pick_weights(root)
        self._weights_sha256: str | None = None

    @staticmethod
    def _locate_local(conf) -> pathlib.Path | None:
        """按 `$HF_HOME/<模型名>` 找本地权重目录；找不到返回 None（走仓库名在线加载）。"""
        base = conf.model_cache_dir() or (conf.resolve(conf.paths.data_dir).parent / ".cache" / "models")
        candidate = pathlib.Path(base) / conf.model.embedding_name.split("/")[-1]
        return candidate if candidate.is_dir() else None

    @staticmethod
    def _pick_weights(root: pathlib.Path | None) -> pathlib.Path | None:
        if root is None:
            return None
        for name in WEIGHT_FILES:
            path = root / name
            if path.is_file():
                return path
        return None

    @property
    def weights_path(self) -> pathlib.Path | None:
        return self._weights_path

    @property
    def weights_sha256(self) -> str:
        if self._weights_sha256 is None:
            if self._weights_path is None:
                raise RuntimeError("找不到本地权重文件，无法计算指纹：%s" % self.model_name)
            self._weights_sha256 = sha256_file(self._weights_path)
        return self._weights_sha256

    def encode(self, texts: list[str]) -> np.ndarray:
        """编码为 float32 且 L2 归一化；空输入返回 (0, dim)。"""
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = np.asarray(vectors, dtype="float32")
        if vectors.shape[1] != self.dim:
            raise RuntimeError("向量维度 %d 与配置 embedding_dim=%d 不一致" % (vectors.shape[1], self.dim))
        return vectors

    def fit(self, text: str, max_tokens: int = MAX_TOKENS) -> tuple[str, bool]:
        """按模型 token 上限截断（超过时截尾部），返回（文本, 是否截断）。"""
        tokenizer = getattr(self._model, "tokenizer", None)
        if tokenizer is None:
            return text, False
        ids = tokenizer.encode(text, add_special_tokens=False)
        if len(ids) <= max_tokens:
            return text, False
        return tokenizer.decode(ids[:max_tokens]), True

    def max_norm_error(self, vectors: np.ndarray) -> float:
        """返回各向量 L2 范数与 1 的最大偏差，用于断言归一化生效。"""
        norms = np.linalg.norm(vectors, axis=1)
        return float(np.max(np.abs(norms - 1.0))) if norms.size else 0.0

    def info(self) -> dict:
        return {
            "model_name": self.model_name,
            "model_revision": self.revision,
            "model_dir": str(self.local_dir) if self.local_dir else None,
            "weights_file": self._weights_path.name if self._weights_path else None,
            "weights_sha256": self.weights_sha256,
            "dim": self.dim,
            "device": self.device,
        }
