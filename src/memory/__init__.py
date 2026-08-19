# -*- coding: utf-8 -*-
"""
架构师 Agent · 经验记忆库（memory）模块

本模块为「语义向量触发」提供专业可靠的落库与检索能力，并对接两种后端：

  - 本地 LanceDB 向量库（可持久化、离线可用、持续积累经验）
  - 云端 CNB 知识库（RAG，`knowledge:update` 原生能力，同格式适配）

核心理念：
  1. 统一向量格式 —— 本地与云端共用同一套 schema / 文档契约（"相同格式"）。
  2. 双后端兼容 —— MemoryStore 提供统一接口，按 backend 路由到 LanceDB 或云端。
  3. 持续积累经验 —— 每次协作交互（接力/回转/触发）写入记忆库，语义触发随积累增强。
  4. 专业可靠 —— 具备真实向量检索与角色语义触发，而非纯关键词/prompt 层面。

用法示例：
    from memory import MemoryStore
    store = MemoryStore(backend="lancedb", path="./.memory")   # 本地 LanceDB
    store.add(role="架构·开发", text="用户要求实现 auth 登录接口...")
    hit = store.match("写一个登录接口", top_k=1)               # 语义向量命中 → 触发角色
"""

from .store import MemoryStore
from .schema import (
    MemoryRecord,
    ROLE_PROTOTYPES,
    UnifiedSchema,
    COLLECTION_NAME,
)
from .triggers import SemanticTriggerEngine

__all__ = [
    "MemoryStore",
    "SemanticTriggerEngine",
    "MemoryRecord",
    "ROLE_PROTOTYPES",
    "UnifiedSchema",
    "COLLECTION_NAME",
]

__version__ = "0.1.0"
