# -*- coding: utf-8 -*-
"""
memory.backends.lancedb_backend —— 本地 LanceDB 向量库后端（持久化）

功能：
  - 连接本地 LanceDB，创建/打开统一集合（arch_memory）。
  - 写入 MemoryRecord（含统一向量）。
  - 按向量做余弦检索（top_k），返回 [(MemoryRecord, score)]。
  - 按 id 删除、统计记录数、关闭连接。

依赖：lancedb（本地运行 / CI 需安装）。
"""

import json

from ..schema import MemoryRecord, COLLECTION_NAME


class LanceDBBackend:
    """LanceDB 本地向量库后端。"""

    backend = "lancedb"

    def __init__(self, path: str = "./.memory", table: str = COLLECTION_NAME):
        self.path = path
        self.table = table
        self._db = None
        self._tbl = None

    def _connect(self):
        if self._db is None:
            import lancedb
            self._db = lancedb.connect(self.path)
        return self._db

    def _table(self):
        if self._tbl is None:
            db = self._connect()
            try:
                self._tbl = db.open_table(self.table)
            except Exception:
                # 空表无法用 data=[] 直接建，需给 schema 样板行
                sample = {
                    "id": "__init__", "role": "", "category": "context",
                    "text": "",
                    "vector": [0.0] * 256,
                    "meta": "{}", "created_at": "",
                }
                self._tbl = db.create_table(self.table, data=[sample])
                self._tbl.delete("id = '__init__'")
        return self._tbl

    # ------------------------------------------------------------------
    # 统一接口
    # ------------------------------------------------------------------
    def add(self, records) -> int:
        """写入多条记录，返回成功条数。同 id 覆盖（upsert）。"""
        if not records:
            return 0
        rows = []
        for rec in records:
            r = rec if isinstance(rec, MemoryRecord) else MemoryRecord(**rec)
            if not r.vector:
                from .embedding import HashEmbedding
                r.vector = HashEmbedding().embed(r.text)
            d = r.to_dict()
            if isinstance(d.get("meta"), dict):
                d["meta"] = json.dumps(d["meta"], ensure_ascii=False)
            rows.append(d)
        tbl = self._table()
        for row in rows:
            # 简单 upsert：先按 id 删除旧行再插入
            try:
                tbl.delete(f"id = '{row['id']}'")
            except Exception:
                pass
        tbl.add(rows)
        return len(rows)

    def search(self, vector, top_k: int = 3) -> list:
        """按向量余弦检索，返回 [(MemoryRecord, score)]。"""
        if not vector:
            return []
        tbl = self._table()
        try:
            result = tbl.search(vector).metric("cosine").limit(top_k).to_list()
        except Exception:
            return []
        out = []
        for row in result:
            rec = MemoryRecord(
                id=row.get("id", ""),
                role=row.get("role", ""),
                category=row.get("category", "context"),
                text=row.get("text", ""),
                vector=list(row.get("vector", [])),
                meta=json.loads(row["meta"]) if isinstance(row.get("meta"), str) else (row.get("meta") or {}),
                created_at=row.get("created_at", ""),
            )
            # LanceDB cosine 返回 _distance（越小越相似）；转为相似度分
            score = 1.0 - row.get("_distance", 0.0)
            out.append((rec, score))
        return out

    def delete(self, ids) -> int:
        """按 id 删除，返回删除条数。"""
        if not ids:
            return 0
        tbl = self._table()
        n = 0
        for rid in ids:
            try:
                tbl.delete(f"id = '{rid}'")
                n += 1
            except Exception:
                pass
        return n

    def count(self) -> int:
        tbl = self._table()
        try:
            return tbl.count_rows()
        except Exception:
            return 0

    def close(self):
        self._db = None
        self._tbl = None
