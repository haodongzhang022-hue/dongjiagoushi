# -*- coding: utf-8 -*-
"""
memory.triggers —— 语义向量触发引擎（语义向量触发真正落地）

作用：
  将"语义向量触发"从 prompt/关键词层面，升级为**真实向量检索**触发：
  输入文本 → 向量化 → 与角色语义原型（及已积累经验）做余弦相似度 → 命中最高者即触发角色。

这对应协作触发三层机制中的「② 语义向量触发」的工程化实现。
显式 [触发:角色] 标记优先级最高；无显式标记时，走本引擎做语义命中。

触发判定：
  - 输入含 [触发:<角色>] → 显式触发（最高优先，直接返回）。
  - 否则 → 语义向量检索，返回 top 命中角色 + 相似度；
          若最高相似度低于 threshold，判为"未命中"（不猜测角色，请求澄清）。
"""

import re

from .schema import (
    role_prototype_vector,
    cosine,
    ROLE_PROTOTYPES,
)


# 显式触发标记：如 [触发:架构·开发]
EXPLICIT_RE = re.compile(r"\[触发[:：]\s*(架构·[^\]]+?)\]")


class SemanticTriggerEngine:
    """语义向量触发引擎。"""

    def __init__(self, embedder=None, threshold: float = 0.10, embed_kind: str = "hash"):
        from .backends.embedding import get_embedder
        self.embedder = embedder or get_embedder(embed_kind)
        # 阈值：离线哈希向量相似度整体偏低，采用较低阈值并支持显式触发兜底
        self.threshold = threshold

    def classify(self, text: str, top_k: int = 1) -> list:
        """对输入做语义向量分类，返回 [(role, score)] 按相似度降序。"""
        vec = self.embedder.embed(text or "")
        scored = []
        for role in ROLE_PROTOTYPES:
            proto = role_prototype_vector(role)
            scored.append((role, cosine(vec, proto)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def trigger(self, text: str) -> dict:
        """判定应触发的角色。

        返回：
          {
            "method": "explicit" | "semantic" | "none",
            "role": <角色名> 或 None,
            "score": <相似度> 或 0,
            "confidence": "high" | "medium" | "low",
          }
        """
        if not text:
            return {"method": "none", "role": None, "score": 0.0, "confidence": "low"}

        # ① 显式触发：最高优先
        m = EXPLICIT_RE.search(text)
        if m:
            role = m.group(1).strip()
            return {"method": "explicit", "role": role, "score": 1.0, "confidence": "high"}

        # ② 语义向量触发
        top = self.classify(text, top_k=1)
        if not top:
            return {"method": "none", "role": None, "score": 0.0, "confidence": "low"}
        role, score = top[0]
        if score >= self.threshold:
            conf = "high" if score >= self.threshold * 1.5 else "medium"
            return {"method": "semantic", "role": role, "score": round(score, 4),
                    "confidence": conf}
        return {"method": "none", "role": None, "score": round(score, 4), "confidence": "low"}

    def trigger_with_memory(self, text: str, store, top_k: int = 3) -> dict:
        """结合已积累经验的语义触发：先显式/原型判定，再用记忆库经验做二次确认。

        若记忆库中积累了该角色/语义的历史记录，返回时附带来源，体现"持续积累经验"。
        """
        result = self.trigger(text)
        if result["role"] and store is not None:
            vec = self.embedder.embed(text)
            hits = store.search(vec, top_k=top_k)
            # 仅保留与命中角色相关的经验
            related = [h for h in hits if h[0].role == result["role"] or not h[0].role]
            if related:
                result["memory_hits"] = [
                    {"text": r.text, "score": round(s, 4), "id": r.id}
                    for r, s in related
                ]
        return result
