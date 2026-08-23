# -*- coding: utf-8 -*-
"""
memory.backends.embedding —— 向量化提供方（可插拔）

专业可靠要求：
  - 提供统一的向量化入口，本地/云端行为一致。
  - 默认 HashEmbedding（零依赖、可复现，适合 CI 与原型验证）。
  - 预留真实模型接入点（Hunyuan / sentence-transformers 等），
    实现 EmbeddingProvider 接口并保持 EMBEDDING_DIM 维度即可无缝替换。
"""

from ..schema import hash_embedding, EMBEDDING_DIM


class EmbeddingProvider:
    """向量化提供方接口。子类实现 embed 即可接入真实模型。"""

    name = "base"

    def embed(self, text: str) -> list:
        raise NotImplementedError

    def embed_batch(self, texts) -> list:
        return [self.embed(t) for t in texts]


class HashEmbedding(EmbeddingProvider):
    """离线确定性哈希向量（默认）。"""

    name = "hash"

    def embed(self, text: str) -> list:
        return hash_embedding(text, EMBEDDING_DIM)


def get_embedder(kind: str = "hash") -> EmbeddingProvider:
    """按名称返回向量化提供方。

    支持：
      - hash / offline / default  离线哈希向量（零依赖、CI 可复现）
      - sentence / real / model   真实语义 embedding（sentence-transformers，
                                  未安装时自动回退哈希兜底，维度与哈希一致可无缝替换）
    """
    kind = (kind or "hash").lower()
    if kind in ("hash", "offline", "default"):
        return HashEmbedding()
    if kind in ("sentence", "real", "model", "auto"):
        # 真实语义模型：自动选 sentence-transformers，未安装则回退 hash
        from .sentence_embedding import SentenceEmbedding
        return SentenceEmbedding()
    raise ValueError(
        f"未知 embedding 提供方: {kind}。支持 'hash' / 'sentence'(真实模型，自动回退)。"
    )
