# -*- coding: utf-8 -*-
"""
memory.backends.sentence_embedding —— 真实 embedding 模型提供方（生产可用）

解决「默认离线哈希向量语义区分度弱」的问题：
  哈希向量对语义只有弱区分度（按字/词哈希叠加），在"智能是否合适"的关键场景（语义触发、记忆检索）里
  区分能力有限。本提供方接入**真实语义 embedding 模型**，让向量真正编码语义。

设计要点（与框架"完整不残次 / 可无缝替换"一致）：
  - 实现统一 EmbeddingProvider 接口（embed / embed_batch）。
  - 输出维度与 schema.EMBEDDING_DIM 保持**一致**（默认 256），
    这样 LanceDB 存储的向量维度不变，替换模型即可无缝切换、无需重建向量库。
  - 采用 **可选依赖 + 优雅降级**：安装 sentence-transformers 则用真实模型；
    未安装时自动回退到 hash 兜底，保证 CI / 离线环境不崩。
  - 支持指定预训练模型名，默认使用多语言小模型（中文友好、体积小、离线可加载）。

关于维度对齐的说明：
  - 真实 embedding 模型原生输出维度各不相同（如 `paraphrase-multilingual-MiniLM-L12-v2` 为 384 维）。
  - 本提供方通过【随机投影 + L2 归一化】把模型输出投影到框架统一维度（EMBEDDING_DIM=256），
    从而与本地 LanceDB 已有向量库 / 云端同格式契约保持维度一致，可无缝替换、无需重建。
  - 随机投影矩阵在首次使用时固定（种子化），保证同一模型同一文本维度与结果可复现。
"""

import os

from ..schema import EMBEDDING_DIM
from .embedding import EmbeddingProvider, HashEmbedding

# 默认多语言句子嵌入模型（中文友好、体积小、~118MB，离线可加载）
DEFAULT_MODEL = os.environ.get(
    "MEMORY_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


class SentenceEmbedding(EmbeddingProvider):
    """基于 sentence-transformers 的真实语义 embedding 提供方。

    未安装 sentence-transformers / 加载失败时，自动回退到 HashEmbedding 兜底，
    保证不阻塞流程。可通过 MEMORY_EMBED_FORCE_HASH=1 强制走哈希。
    """

    name = "sentence"

    def __init__(self, model_name: str = DEFAULT_MODEL, dim: int = EMBEDDING_DIM,
                 use_hash_fallback: bool = True):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._fallback = HashEmbedding()
        self.use_hash_fallback = use_hash_fallback
        # 随机投影矩阵（种子固定，保证可复现）；懒初始化
        self._proj = None

    # ------------------------------------------------------------------
    # 模型懒加载 + 投影矩阵
    # ------------------------------------------------------------------
    def _ensure_model(self):
        if self._model is not None:
            return True
        if os.environ.get("MEMORY_EMBED_FORCE_HASH") == "1":
            return False
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            return True
        except Exception:
            # 未安装依赖 / 模型下载失败 → 优雅降级到哈希
            self._model = False
            return False

    def _ensure_proj(self, src_dim: int):
        """生成/复用固定随机投影矩阵，把模型原生维度投影到统一 EMBEDDING_DIM。"""
        if self._proj is None or self._proj.shape[1] != src_dim:
            import numpy as np
            rng = np.random.default_rng(42)  # 种子固定 → 可复现
            # Gaussian 随机投影，后续按行归一化保持余弦语义近似
            self._proj = rng.standard_normal((self.dim, src_dim)).astype("float32")
            # 行归一化，保持向量长度量纲
            norms = np.linalg.norm(self._proj, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._proj = self._proj / norms
        return self._proj

    def embed(self, text: str) -> list:
        if not self._ensure_model():
            return self._fallback.embed(text)
        try:
            vec = self._model.encode([text or ""], normalize_embeddings=True)[0]
            return self._project(vec)
        except Exception:
            if self.use_hash_fallback:
                return self._fallback.embed(text)
            raise

    def embed_batch(self, texts) -> list:
        if not self._ensure_model():
            return [self._fallback.embed(t) for t in texts]
        try:
            vecs = self._model.encode(list(texts or []), normalize_embeddings=True)
            return [self._project(v) for v in vecs]
        except Exception:
            if self.use_hash_fallback:
                return [self._fallback.embed(t) for t in texts]
            raise

    def _project(self, vec) -> list:
        import numpy as np
        arr = np.asarray(vec, dtype="float32")
        if arr.ndim == 1 and arr.shape[0] != self.dim:
            proj = self._ensure_proj(arr.shape[0])
            arr = proj @ arr
        # 投影后再 L2 归一化，保证向量单位长度（余弦语义稳定）
        norm = float(np.linalg.norm(arr)) or 1.0
        arr = arr / norm
        return [float(x) for x in arr]
