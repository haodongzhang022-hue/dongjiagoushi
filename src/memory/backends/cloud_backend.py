# -*- coding: utf-8 -*-
"""
memory.backends.cloud_backend —— 云端 CNB 知识库后端（同格式适配）

云端 CNB 知识库（knowledge:update）以"文档切片 + embedding"入库，靠 RAG 检索，
与本地 LanceDB 是"不同引擎、同一套 MemoryRecord 格式"。本后端做格式适配：

  - 把 MemoryRecord 序列化为同格式的 Markdown/JSON 文档块（见 schema.to_markdown）。
  - 提供云端入库文件清单（memory_records.md / memory_records.jsonl），
    交由 .cnb.yml 的 knowledge:update（include 覆盖 src/memory/**）自动入库。
  - search/count 等做"格式对齐 / 占位"实现，真实云端检索走 CNB 原生 RAG
    （知识库已入库后由 @CodeBuddy 对话检索）；本类保证格式与接口一致。
"""

import json
import os

from ..schema import MemoryRecord, COLLECTION_NAME, now_iso


class CloudBackend:
    """云端 CNB 知识库后端（格式适配 + 导出对齐文件）。"""

    backend = "cloud"

    def __init__(self, export_dir: str = "./.memory-cloud", table: str = COLLECTION_NAME):
        self.export_dir = export_dir
        self.table = table
        self._records = {}
        self._manifest = []

    # ------------------------------------------------------------------
    # 统一接口
    # ------------------------------------------------------------------
    def add(self, records) -> int:
        """写入记录（内存暂存），并导出同格式对齐文件供云端入库。"""
        if not records:
            return 0
        for rec in records:
            r = rec if isinstance(rec, MemoryRecord) else MemoryRecord(**rec)
            self._records[r.id or str(len(self._records))] = r
            self._manifest.append(r.id or str(len(self._records)))
        self._export()
        return len(records)

    def search(self, vector, top_k: int = 3) -> list:
        """本地对齐检索：用余弦相似度在已入库记录中比对（同格式）。"""
        if not vector or not self._records:
            return []
        from ..schema import cosine
        scored = []
        for r in self._records.values():
            rv = r.vector or []
            scored.append((r, cosine(vector, rv)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def delete(self, ids) -> int:
        n = 0
        for rid in ids:
            if rid in self._records:
                del self._records[rid]
                n += 1
        self._export()
        return n

    def count(self) -> int:
        return len(self._records)

    def close(self):
        self._export()

    # ------------------------------------------------------------------
    # 云端格式导出（同格式：Markdown + JSONL 两种视图）
    # ------------------------------------------------------------------
    def _export(self):
        os.makedirs(self.export_dir, exist_ok=True)
        # Markdown 视图（可直接被 CNB knowledge:update 以 md 入库）
        md_path = os.path.join(self.export_dir, "memory_records.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# 架构师经验记忆库（云端视图）\n\n")
            f.write(f"> 统一格式：MemoryRecord（与本地 LanceDB 一致）\n")
            f.write(f"> 集合：{self.table} | 导出时间：{now_iso()}\n\n")
            f.write("---\n\n")
            for r in self._records.values():
                f.write(r.to_markdown())
                f.write("\n---\n\n")
        # JSONL 视图（结构化，便于下游程序读取）
        jl_path = os.path.join(self.export_dir, "memory_records.jsonl")
        with open(jl_path, "w", encoding="utf-8") as f:
            for r in self._records.values():
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        return md_path, jl_path
