# -*- coding: utf-8 -*-
"""
全局唯一编号（gid）—— 全局唯一、不重复、可稳定寻址的 ID 生成与注册
====================================================================
用户核心诉求：
  "每个负责的 agent 和任务 全都是全局唯一 不重复的有 ID 编号，能精准针对
   某个 agent 和任务进行调整、二次触发，而不是二次触发的责任人和任务都变了。"

本模块为「agent / 任务 / PR / 小组 / 池子」提供**全局唯一、稳定、可持久化**的 ID：

  - **全局唯一**：UUID 命名空间 + 时间戳 + 随机，碰撞概率可忽略，库内 UNIQUE 兜底；
  - **稳定寻址**：同一实体的 gid 一经生成即落库（gid_registry 表），**二次触发时
    按 gid 取回同一实体**（责任人/任务不漂移），不再"每次重新生成导致第二次变了"；
  - **类型前缀**：`agent-` / `task-` / `pr-` / `group-` / `pool-`，一眼可辨类型。

设计：
  - `gen(etype)`：生成一个带类型前缀的全局唯一 ID（不落库，供调用方组合使用）；
  - `register(etype, key)`：为某业务 key（如稳定名/任务标题）登记/取回**同一个** gid；
    若该 key 已登记过，则返回既有 gid（保证"同一实体二次触发拿到同一个 ID"）；
  - `gid_for(etype, key)`：查某 key 已登记的 gid（未登记返回 None）。
  - 使用 data 层 gid_registry 表持久化（sqlite/pg 通吃）。
"""
import uuid

# 类型前缀（一眼可辨 + 隔离命名空间）
_PREFIX = {
    "agent": "ag",
    "task": "tk",
    "pr": "pr",
    "issue": "is",
    "group": "gp",
    "pool": "pl",
    "meter": "mt",
    "split": "sp",
}


def gen(etype):
    """生成一个全局唯一、带类型前缀的 ID（不落库）。

    例：gen('agent') → 'ag-2f4c9a1b-3e5d-4f8a-9b1c-d2e3f4a5b6c7'
    """
    prefix = _PREFIX.get(etype, "id")
    return f"{prefix}-{uuid.uuid4().hex}"


def _reg_table():
    """确保 gid_registry 表存在并返回 store 访问接口。"""
    from data import schema
    schema.init_schema()
    return None  # 实际读写走下方 data.admin / repository 封装


def register(etype, key):
    """为业务 key 登记并返回**同一个**全局唯一 gid。

    幂等：同一 key 二次调用返回既有的 gid，确保"同一实体二次触发仍是同一个 ID"。
    返回 (gid, is_new)。is_new=True 表示本次新登记；False 表示命中既有 gid。
    """
    from data import admin
    gid = admin.registry_get(etype, key)
    if gid:
        return gid, False
    gid = gen(etype)
    admin.registry_set(etype, key, gid)
    return gid, True


def gid_for(etype, key):
    """查询某 key 已登记的 gid；未登记返回 None。"""
    from data import admin
    return admin.registry_get(etype, key)
