# -*- coding: utf-8 -*-
"""
memory.store —— MemoryStore 门面（统一后端路由）

按 backend 参数路由到：
  - lancedb：本地 LanceDB 向量库（持久化、离线、持续积累）
  - cloud  ：云端 CNB 知识库（同格式适配）
  - memory / dual：双写（本地 + 云端同格式对齐），满足"双兼容"诉求。

统一方法（add / search / delete / count / close）对调用方透明，
调用方无需关心底层是 LanceDB 还是云端。
"""

from .backends.lancedb_backend import LanceDBBackend
from .backends.cloud_backend import CloudBackend
from .schema import MemoryRecord


class MemoryStore:
    """经验记忆库门面，负责双后端统一路由。"""

    def __init__(self, backend: str = "lancedb", **kwargs):
        self.backend = backend
        self._store = self._build(backend, kwargs)

    def _build(self, backend, kwargs):
        backend = (backend or "lancedb").lower()
        if backend in ("lancedb", "local"):
            return LanceDBBackend(path=kwargs.get("path", "./.memory"),
                                  table=kwargs.get("table", "arch_memory"))
        if backend in ("cloud", "cnb"):
            return CloudBackend(export_dir=kwargs.get("export_dir", "./.memory-cloud"))
        if backend in ("dual", "memory", "both"):
            # 双兼容：本地 LanceDB + 云端同格式，写入时双写
            local = LanceDBBackend(path=kwargs.get("path", "./.memory"),
                                   table=kwargs.get("table", "arch_memory"))
            cloud = CloudBackend(export_dir=kwargs.get("export_dir", "./.memory-cloud"))
            return _DualBackend(local, cloud)
        raise ValueError(f"未知后端: {backend}。支持 lancedb/cloud/dual")

    # ------------------------------------------------------------------
    # 统一接口（转发到具体后端）
    # ------------------------------------------------------------------
    def add(self, records) -> int:
        if not isinstance(records, (list, tuple)):
            records = [records]
        return self._store.add(records)

    def search(self, vector, top_k: int = 3) -> list:
        return self._store.search(vector, top_k=top_k)

    def delete(self, ids) -> int:
        return self._store.delete(ids)

    def count(self) -> int:
        return self._store.count()

    def close(self):
        self._store.close()


class _DualBackend:
    """双写后端：本地 + 云端同格式同时写入，保证双兼容。"""

    backend = "dual"

    def __init__(self, local: LanceDBBackend, cloud: CloudBackend):
        self.local = local
        self.cloud = cloud

    def add(self, records) -> int:
        n = self.local.add(records)
        self.cloud.add(records)
        return n

    def search(self, vector, top_k: int = 3) -> list:
        return self.local.search(vector, top_k=top_k)

    def delete(self, ids) -> int:
        n = self.local.delete(ids)
        self.cloud.delete(ids)
        return n

    def count(self) -> int:
        return self.local.count()

    def close(self):
        self.local.close()
        self.cloud.close()
