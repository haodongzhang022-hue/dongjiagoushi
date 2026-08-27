# -*- coding: utf-8 -*-
"""
monitor_bi · 代码变化统计（M3 · code.py）
==========================================
「代码变化统计」：按项目/agent 归集代码增删（+/- 行），呈现贡献分布。

数据源：code_changes 表（按 commit 归集），复用 data 层 repository，不重造 git 解析。
"""
from data import repository as repo
from data import db


def code_changes(by=("project", "agent")):
    """按指定维度归集代码变化总量。

    by: tuple 或 list，∈ {project, agent}，支持单个或多个维度组合。
    返回 list[Row]，含 {key1, key2, added, deleted, net, commits}。
    """
    if isinstance(by, str):
        by = (by,)
    by = list(by)
    assert all(b in ("project", "agent") for b in by), "by 仅支持 project / agent"

    # 维度映射到表字段
    field_map = {"project": "project", "agent": "agent_id"}

    if len(by) == 1:
        field = field_map[by[0]]
        q = (f"SELECT {field} AS key, SUM(added) AS added, SUM(deleted) AS deleted, "
             f"COUNT(*) AS commits FROM code_changes GROUP BY {field} "
             f"ORDER BY (SUM(added)+SUM(deleted)) DESC")
    else:
        f0 = field_map[by[0]]
        f1 = field_map[by[1]]
        q = (f"SELECT {f0} AS k0, {f1} AS k1, SUM(added) AS added, SUM(deleted) AS deleted, "
             f"COUNT(*) AS commits FROM code_changes GROUP BY {f0}, {f1} "
             f"ORDER BY (SUM(added)+SUM(deleted)) DESC")
    rows = _query(q)
    result = []
    for r in rows:
        entry = dict(r)
        entry["added"] = entry["added"] or 0
        entry["deleted"] = entry["deleted"] or 0
        entry["net"] = entry["added"] - entry["deleted"]
        entry["commits"] = entry["commits"] or 0
        result.append(entry)
    return result


def code_total():
    """总代码变化量。"""
    return repo.code_total()


def code_by_project():
    """按项目归集代码变化（便捷封装）。"""
    return code_changes(("project",))


def code_by_agent():
    """按 agent 归集代码变化（便捷封装）。"""
    return code_changes(("agent",))


def _query(sql, args=None):
    rows = db.query(sql, args) if args else db.query(sql)
    return [dict(r) for r in rows]
