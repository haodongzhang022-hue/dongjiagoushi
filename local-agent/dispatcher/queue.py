# -*- coding: utf-8 -*-
"""
调度中枢 · Action 队列（queue）
================================
用户拍板 #2 的核心落地：**到队列，不卡进程**。

设计：
  - 派发意图先进 Action 队列（dispatch 表，status=queued），消费方异步拉取；
  - **自动优先 / 规则优先**：gate=auto 的意图直接放行（released → dispatched），
    不经过人工；
  - 只有 gate=hold（需人工判断）的意图才进**人工审核闸门**（status=hold），
    等人类放行后才派发——常规不人力，仅"规则拦截后人工需要判断"才审；
  - 队列解耦：**任务允许追加内容、允许重新分配**，因此即使派发后也能重新入队/
    追加，不会因单点阻塞卡住整条进程。

状态机：
  queued → released（自动放行）→ dispatched
  queued → hold（人工审核闸门）→ released → dispatched
  queued → skipped/rejected（护栏拦截/规则不命中）
  dispatched → requeued（可追加内容/重新分配，不卡进程）
"""
import uuid

from data import db
from . import source as _src


def _now():
    return db.now_iso()


def enqueue(intent, note=""):
    """把一个派发意图写入 Action 队列（dispatch 表，status=queued）。

    返回 dispatch 记录 dict。若为需人工判断（gate=hold）则直接进人工闸门。
    """
    event_id = intent.get("event_id") or f"ev-{uuid.uuid4().hex}"
    status = "hold" if intent.get("gate") == "hold" else "queued"
    db.execute(
        """
        INSERT INTO dispatch
            (event_id, event_type, source, entity, gid, matched_rule, target_role,
             target_agent, status, gate, dedup_key, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, intent.get("event_type", ""), intent.get("source", ""),
         intent.get("entity", ""), intent.get("gid", ""),
         intent.get("rule", ""), intent.get("target_role", ""),
         intent.get("target_agent", ""), status, intent.get("gate", "auto"),
         intent.get("dedup_key", ""), note, _now(), _now()),
    )
    return {
        "event_id": event_id,
        "status": status,
        "gate": intent.get("gate", "auto"),
        "intent": intent,
    }


def queued(limit=200, gate=None):
    """拉取待处理队列（未派发）。gate 可选过滤 auto/hold。"""
    sql = "SELECT * FROM dispatch WHERE status IN ('queued','hold')"
    params = []
    if gate:
        sql += " AND gate=?"
        params.append(gate)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.query(sql, params)]


def auto_release(limit=100):
    """把 gate=auto 且 queued 的意图批量放行（自动优先，不卡进程）。"""
    rows = db.query(
        "SELECT * FROM dispatch WHERE status='queued' AND gate='auto' ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    released = []
    for r in rows:
        db.execute(
            "UPDATE dispatch SET status='released', updated_at=? WHERE id=?",
            (_now(), r["id"]),
        )
        released.append(dict(r))
    return released


def hold_entries(limit=200):
    """待人工审核闸门的意图（人类俯瞰 / 放行）。"""
    return [dict(r) for r in db.query(
        "SELECT * FROM dispatch WHERE status='hold' ORDER BY id ASC LIMIT ?", (limit,))]


def human_release(event_id):
    """人工审核闸门放行：把 hold 的意图释放为 released（供后续派发）。"""
    db.execute(
        "UPDATE dispatch SET status='released', gate='auto', updated_at=? WHERE event_id=?",
        (_now(), event_id),
    )
    return True


def mark_dispatched(event_id, target_agent="", note=""):
    """标记一条意图已派发（status=dispatched），记录目标 agent。"""
    db.execute(
        "UPDATE dispatch SET status='dispatched', target_agent=?, note=?, updated_at=? "
        "WHERE event_id=?",
        (target_agent, note, _now(), event_id),
    )


def mark_rejected(event_id, reason):
    """护栏拦截：status=rejected，留痕 reason（面板可见）。"""
    db.execute(
        "UPDATE dispatch SET status='rejected', note=?, updated_at=? WHERE event_id=?",
        (reason, _now(), event_id),
    )


def mark_skipped(event_id, reason):
    """规则不命中：status=skipped，留痕。"""
    db.execute(
        "UPDATE dispatch SET status='skipped', note=?, updated_at=? WHERE event_id=?",
        (reason, _now(), event_id),
    )


def requeue(event_id, note="追加/重分配，重新入队"):
    """派发后追加内容/重新分配（不卡进程）：dispatched → queued。"""
    db.execute(
        "UPDATE dispatch SET status='queued', note=?, updated_at=? WHERE event_id=?",
        (note, _now(), event_id),
    )


def overview():
    """Action 队列全貌（二级信息，供面板/俯瞰）。"""
    rows = db.query(
        "SELECT status, COUNT(*) AS n FROM dispatch GROUP BY status"
    )
    return {r["status"]: r["n"] for r in rows}
