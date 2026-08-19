# -*- coding: utf-8 -*-
"""
memory.backends —— 双后端兼容（本地 LanceDB + 云端 CNB 知识库，同格式）

统一接口（各后端实现同一套方法）：
  - add(records)            写入
  - search(vector, top_k)   向量检索，返回 [(MemoryRecord, score)]
  - delete(ids)             删除
  - count()                 记录数
  - close()                 释放资源

两套后端共用同一 MemoryRecord schema（"相同格式"）：
  - lancedb：本地持久化向量库，可离线运行、持续积累经验。
  - cloud   ：适配云端 CNB 知识库（knowledge:update RAG），
              将 MemoryRecord 序列化为同格式 Markdown/JSON 块入库。
"""

from .lancedb_backend import LanceDBBackend
from .cloud_backend import CloudBackend
from .embedding import EmbeddingProvider, HashEmbedding

__all__ = [
    "LanceDBBackend",
    "CloudBackend",
    "EmbeddingProvider",
    "HashEmbedding",
]
