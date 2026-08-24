# -*- coding: utf-8 -*-
"""
调度中枢 · 驳回迭代表（reject）
================================
用户拍板 #3 的核心落地：**驳回需要触发后续的修改**——不是终点，而是进入
**再次迭代流程**。

机制：
  - `rejections` 表存于数据库（用户拍板：需要一个表，放数据库）；
  - 每条驳回记录带 **gid（唯一确定的负责实体）** + **agent_id（负责 agent）**，
    **监控功能**路由到该 gid 的负责 agent，让其**改进问题重新提交**；
  - **迭代闭环**：`iteration` 计数，驳回 → 回派原 agent 改进重提 → 复评 →
    再驳回则 +1 迭代再回环，**直到通过或哨兵判 2 级上报 blocked**。
  - 命中即派发意图（dispatch 表），走 guard 防无效（同 gid 驳回去重/频限），
    避免同一驳回反复刷。

驳回来源识别（rules 默认规则 rejection_reroute 驱动）：
  - 评论内 `[回转]` / `[打断]` / `🔴必修` / `🔴阻塞` 标记；
  - 测试 `🔴阻塞`；哨兵 2 级上报。
"""
import re
import uuid

from data import db


def _now():
    return db.now_iso()


# 驳回标记（评审必修 / 测试阻塞 / 回转 / 打断）
_REJECT_MARKERS = ("🔴", "[回转]", "[打断]", "必修", "阻塞", "驳回")


def is_reject_text(text):
    """判断一段文本是否含驳回标记。"""
    return any(m in text for m in _REJECT_MARKERS)


def register(task_id, gid, agent_id, reason, level="must", monitor=1):
    """登记一条驳回记录（写入数据库），返回记录 dict。

    - gid：唯一确定的负责实体（精准路由目标）；
    - agent_id：负责该任务的 agent（按 gid 回派改进）；
    - iteration：若同一 task 已有驳回记录则 +1（迭代闭环）。
    """
    prev = latest(task_id)
    iteration = (prev["iteration"] + 1) if prev else 1
    rejection_id = f"rj-{uuid.uuid4().hex[:12]}"
    db.execute(
        """
        INSERT INTO rejections
            (rejection_id, task_id, gid, agent_id, reason, level, iteration,
             status, assigned_to, monitor, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (rejection_id, task_id, gid, agent_id, reason, level, iteration,
         "pending", agent_id, int(monitor), _now(), _now()),
    )
    return {
        "rejection_id": rejection_id, "task_id": task_id, "gid": gid,
        "agent_id": agent_id, "reason": reason, "level": level,
        "iteration": iteration, "status": "pending", "assigned_to": agent_id,
    }


def latest(task_id):
    """某任务最近一条驳回记录（用于迭代计数/续跑）。"""
    row = db.query_one(
        "SELECT * FROM rejections WHERE task_id=? ORDER BY id DESC LIMIT 1",
        (task_id,),
    )
    return dict(row) if row else None


def route_intent(rejection):
    """由驳回记录构造派发意图：按 gid 精准路由到原负责 agent 改进重提。

    用户拍板 #3：驳回不是终点，路由给唯一确定 ID 的负责 agent 尝试改进重新提交。
    """
    return {
        "event_type": "rejection",
        "source": "reject",
        "entity": f"reject:{rejection['task_id']}",
        "gid": rejection["gid"],
        "target_role": "",                       # 目标 = 原负责 agent（按 gid）
        "target_agent": rejection["agent_id"],   # 精准回派唯一 agent
        "action": "reject_reroute",
        "gate": "auto",                          # 驳回回派自动优先（用户拍板 #3）
        "dedup_key": f"{rejection['gid']}:rejection",
        "detail": {
            "rejection_id": rejection["rejection_id"],
            "reason": rejection["reason"],
            "iteration": rejection["iteration"],
            "level": rejection["level"],
        },
    }


def mark_reassigned(rejection_id, assigned_to):
    """标记已回派给指定 agent 改进（status=reassigned）。"""
    db.execute(
        "UPDATE rejections SET status='reassigned', assigned_to=?, updated_at=? "
        "WHERE rejection_id=?",
        (assigned_to, _now(), rejection_id),
    )


def mark_reworked(rejection_id):
    """标记改进已重新提交（status=reworked，进入复评）。"""
    db.execute(
        "UPDATE rejections SET status='reworked', updated_at=? WHERE rejection_id=?",
        (_now(), rejection_id),
    )


def mark_approved(rejection_id):
    """标记通过（status=approved，迭代闭环收尾）。"""
    db.execute(
        "UPDATE rejections SET status='approved', updated_at=? WHERE rejection_id=?",
        (_now(), rejection_id),
    )


def mark_blocked(rejection_id, reason):
    """标记阻塞（status=blocked，哨兵 2 级上报后待人工/总师拍板）。"""
    db.execute(
        "UPDATE rejections SET status='blocked', reason=?, updated_at=? "
        "WHERE rejection_id=?",
        (reason, _now(), rejection_id),
    )


def pending(limit=200):
    """待处理（未通过/未阻塞）的驳回记录，供派发/监控。"""
    rows = db.query(
        "SELECT * FROM rejections WHERE status IN ('pending','reassigned','reworked') "
        "ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def all_rejections(limit=500):
    rows = db.query("SELECT * FROM rejections ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def overview():
    rows = db.query("SELECT status, COUNT(*) AS n FROM rejections GROUP BY status")
    return {r["status"]: r["n"] for r in rows}
