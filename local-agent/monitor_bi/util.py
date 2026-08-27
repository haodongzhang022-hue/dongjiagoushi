# -*- coding: utf-8 -*-
"""
monitor_bi · 公共辅助工具（util.py）
=====================================
存放模块内各子模块共享的辅助函数，避免在 stats/code/token 中重复定义。
"""
from data import db


def query(sql, args=None):
    """统一查询入口：执行 SQL 并返回 dict 列表。

    供 stats/code/token 等子模块共用，消除重复定义。
    """
    rows = db.query(sql, args) if args else db.query(sql)
    return [dict(r) for r in rows]
