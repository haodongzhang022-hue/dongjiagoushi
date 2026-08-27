# -*- coding: utf-8 -*-
"""
monitor_bi · 四维统计引擎（M1 · stats.py）
==========================================
「工作过程监控 + 可视化 BI 大屏」模块的第一核心：**四维口径统计体系工作量**。

四维口径（与 Issue #55 需求一致）：
  - **agent**   ：每个 agent 的工作量/产出/状态
  - **role**    ：每个岗位（秘书/产品/开发/评审/测试/哨兵）汇总
  - **conversation**（topic）：每轮对话/会话的文字量/参与方
  - **project** ：每个项目(Issue/PR/任务)产出/参与度

工作量口径：`progress` 事件数 + `messages` 数 + `archives` 产出数，按四维 GROUP BY。
状态汇总：读 `tasks` 表各 agent 任务状态（in_progress/done/blocked）计数。
下钻：`progress.detail` / `messages.payload` / `archives.content` 支持明细行。

复用现有 data 层（repository），不重造引擎；只做**聚合查询**，不改任何角色业务逻辑。
"""
from data import repository as repo


# ---- 四维常量 ----
DIMS = ("agent", "role", "conversation", "project")


def workload_4d(dim="agent"):
    """四维口径统计工作量。

    口径 = 每个维度的 progress 事件数 + messages 数 + archives 产出数。
    dim  ∈ {agent, role, conversation, project}。
    返回 list[Row]，每行含 {key, progress_count, message_count, archive_count, total}。
    """
    assert dim in DIMS, f"dim 必须 ∈ {DIMS}，当前={dim}"
    # 映射维度到对应字段
    counts = {}

    # 从各数据源按维度聚合
    # 1) progress 事件（按 agent/role 从 progress 聚合）
    if dim in ("agent", "role"):
        if dim == "agent":
            q = "SELECT agent_id AS key, COUNT(*) AS n FROM progress GROUP BY agent_id"
        else:
            q = """
                SELECT COALESCE(a.role, p.agent_id) AS key, COUNT(p.id) AS n
                FROM progress p LEFT JOIN agents a ON a.agent_id=p.agent_id
                GROUP BY COALESCE(a.role, p.agent_id)
                """
        rows_q = _query(q)
        for r in rows_q:
            key = r["key"] or "(unknown)"
            c = counts.setdefault(key, {"key": key, "progress_count": 0, "message_count": 0, "archive_count": 0})
            c["progress_count"] = r["n"] or 0
    elif dim == "conversation":
        rows_q = _query("SELECT topic AS key, COUNT(*) AS n FROM messages GROUP BY topic")
        for r in rows_q:
            key = r["key"] or "(unknown)"
            c = counts.setdefault(key, {"key": key, "progress_count": 0, "message_count": 0, "archive_count": 0})
            c["progress_count"] = r["n"] or 0
    elif dim == "project":
        # 项目维度：从 messages.topic 归集（topic 通常即项目标识，如 ISSUE-55）
        rows_q = _query("SELECT topic AS key, COUNT(*) AS n FROM messages WHERE topic != '' GROUP BY topic")
        for r in rows_q:
            key = r["key"] or "(unknown)"
            c = counts.setdefault(key, {"key": key, "progress_count": 0, "message_count": 0, "archive_count": 0})
            c["progress_count"] = r["n"] or 0

    # 2) messages 消息数
    if dim == "agent":
        q2 = _query("SELECT from_agent AS key, COUNT(*) AS n FROM messages WHERE from_agent != '' GROUP BY from_agent")
    elif dim == "role":
        q2 = _query("""
            SELECT COALESCE(a.role, m.from_agent) AS key, COUNT(m.id) AS n
            FROM messages m LEFT JOIN agents a ON a.agent_id=m.from_agent
            WHERE m.from_agent != '' GROUP BY COALESCE(a.role, m.from_agent)
            """)
    elif dim == "conversation":
        q2 = _query("SELECT topic AS key, COUNT(*) AS n FROM messages WHERE topic != '' GROUP BY topic")
    elif dim == "project":
        # 项目维度 message_count：从 messages.topic 归集
        q2 = _query("SELECT topic AS key, COUNT(*) AS n FROM messages WHERE topic != '' GROUP BY topic")
    for r in q2:
        key = r["key"] or "(unknown)"
        c = counts.setdefault(key, {"key": key, "progress_count": 0, "message_count": 0, "archive_count": 0})
        c["message_count"] = r["n"] or 0

    # 3) archives 产出数
    if dim == "project":
        # 项目维度 archive_count：从 token_usage.project 归集（项目参与的 token 记录数）
        q3 = _query("SELECT project AS key, COUNT(*) AS n FROM token_usage WHERE project != '' GROUP BY project")
    else:
        q3 = _query("SELECT source AS key, COUNT(*) AS n FROM archives GROUP BY source")
    for r in q3:
        key = r["key"] or "(unknown)"
        c = counts.setdefault(key, {"key": key, "progress_count": 0, "message_count": 0, "archive_count": 0})
        c["archive_count"] = r["n"] or 0

    # 计算 total
    result = []
    for c in counts.values():
        c["total"] = c["progress_count"] + c["message_count"] + c["archive_count"]
        result.append(c)
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def status_summary(dim="agent"):
    """按维度统计各实体的任务状态分布（in_progress/done/blocked）。"""
    q = """
        SELECT assignee AS key, status, COUNT(*) AS n
        FROM tasks GROUP BY assignee, status
        """
    rows_q = _query(q)
    result = {}
    for r in rows_q:
        key = r["key"] or "(unknown)"
        entry = result.setdefault(key, {"key": key, "todo": 0, "in_progress": 0, "done": 0, "blocked": 0})
        status = r["status"] or "todo"
        if status in entry:
            entry[status] += r["n"] or 0
    return list(result.values())


def drill_down(dim, key, limit=50):
    """下钻到明细（AC-1「可下钻到明细」）：按维度实体拉取关联的进度/消息/产出明细。"""
    items = []
    # 消息明细（messages 表字段：from_agent/topic，无 agent_id/project 列）
    if dim == "agent":
        q = _query(
            "SELECT msg_id, from_agent, to_agent, topic, payload, ts FROM messages "
            "WHERE from_agent=? ORDER BY ts DESC LIMIT ?",
            (key, limit),
        )
        for r in q:
            items.append({"kind": "message", **dict(r)})
    elif dim == "conversation":
        q = _query(
            "SELECT msg_id, from_agent, to_agent, topic, payload, ts FROM messages "
            "WHERE topic=? ORDER BY ts DESC LIMIT ?",
            (key, limit),
        )
        for r in q:
            items.append({"kind": "message", **dict(r)})
    elif dim == "role":
        # role 需要 join agents 表
        q = _query(
            "SELECT m.msg_id, m.from_agent, m.to_agent, m.topic, m.payload, m.ts "
            "FROM messages m LEFT JOIN agents a ON a.agent_id=m.from_agent "
            "WHERE COALESCE(a.role, m.from_agent)=? ORDER BY m.ts DESC LIMIT ?",
            (key, limit),
        )
        for r in q:
            items.append({"kind": "message", **dict(r)})
    elif dim == "project":
        # project 归集到 task 维度（从 progress 表）
        q = _query(
            "SELECT task_id, agent_id, event, detail, ts FROM progress "
            "WHERE task_id=? ORDER BY ts DESC LIMIT ?",
            (key, limit),
        )
        for r in q:
            items.append({"kind": "progress", **dict(r)})
    return items


# ---- 内部辅助 ----
from data import db


def _query(sql, args=None):
    """统一查询入口，返回 dict 列表。"""
    rows = db.query(sql, args) if args else db.query(sql)
    return [dict(r) for r in rows]
