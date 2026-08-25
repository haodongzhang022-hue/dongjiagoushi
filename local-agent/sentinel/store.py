# -*- coding: utf-8 -*-
"""
sentinel · 监控哨兵数据访问（store）
====================================
「防无效努力 / 目标收敛监控」的数据访问层：读写目标进度尺（goal_meters）与
监控动作留痕（sentinel_actions）。由「架构·监控哨兵」角色统一使用，
复用 data 层后端抽象（sqlite 默认 / postgresql 可选），统一口径。

设计原则：
  - 目标进度尺记录的是「**到目标的量化距离**」，而非模糊的"进展百分比"，
    让"是否真的在收敛"可被机器判定（distance 单调下降才算推进）。
  - 每个推进动作写一条刻度：`goal_total/current` 归一化为 `distance=goal_total-current`，
    `delta = 本次 distance - 上次 distance`（负=在靠近，正=在远离/回退，0=停滞）。
"""
import json
import uuid

from data import db


def _dumps(obj):
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False)
    return "" if obj is None else str(obj)


# ---------------- 目标进度尺（goal_meters） ----------------

def record_meter(meter_id, task_id="", agent_id="", target="",
                 goal_total=0.0, current=0.0, note="", ts=""):
    """记录一次到目标的进度刻度。

    距离 = goal_total - current；delta = 本次距离 - 上次距离（该任务同 agent 最近一次）。
    """
    distance = float(goal_total) - float(current)
    last = latest_meter(meter_id)
    delta = 0.0
    if last is not None:
        delta = distance - float(last["distance"])
    db.execute(
        """
        INSERT INTO goal_meters
            (meter_id, task_id, agent_id, target, goal_total, current,
             distance, delta, note, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (meter_id, task_id, agent_id, target,
         float(goal_total), float(current), distance, delta, note,
         ts or db.now_iso()),
    )
    return {"meter_id": meter_id, "distance": distance, "delta": delta, "ts": db.now_iso()}


def latest_meter(meter_id):
    """某目标刻度最近一次记录。"""
    row = db.query_one(
        "SELECT * FROM goal_meters WHERE meter_id=? ORDER BY id DESC LIMIT 1",
        (meter_id,),
    )
    return dict(row) if row else None


def meter_series(meter_id, limit=100):
    """某目标刻度的距离序列（按时间升序），供检测引擎分析。"""
    rows = db.query(
        "SELECT * FROM goal_meters WHERE meter_id=? ORDER BY id ASC LIMIT ?",
        (meter_id, limit),
    )
    return [dict(r) for r in rows]


def meters_for_task(task_id, limit=100):
    """某任务的全部目标刻度（跨 agent 汇总，按时间升序）。"""
    rows = db.query(
        "SELECT * FROM goal_meters WHERE task_id=? ORDER BY id ASC LIMIT ?",
        (task_id, limit),
    )
    return [dict(r) for r in rows]


def meters_for_group(group_id, limit=100):
    """某小组（group_id）下全部成员的目标刻度（供小组长监督本组收敛）。"""
    rows = db.query(
        """
        SELECT m.* FROM goal_meters m
        JOIN agents a ON a.agent_id = m.agent_id
        WHERE a.group_id = ? ORDER BY m.id ASC LIMIT ?
        """,
        (group_id, limit),
    )
    return [dict(r) for r in rows]


def group_meter_summary(group_id):
    """小组进度尺监督视图（二级信息，供小组长俯瞰）：本组成员每个任务的最近刻度/距离/增量。"""
    rows = db.query(
        """
        SELECT m.task_id, m.agent_id, m.target, m.goal_total, m.current,
               m.distance, m.delta, m.note, m.ts
        FROM goal_meters m
        JOIN agents a ON a.agent_id = m.agent_id
        WHERE a.group_id = ?
        ORDER BY m.task_id, m.id
        """,
        (group_id,),
    )
    # 每个任务取最近一条刻度
    latest = {}
    for r in rows:
        d = dict(r)
        latest.setdefault((d["task_id"], d["agent_id"]), d)
    out = []
    for key in sorted(latest):
        m = latest[key]
        dist = float(m["distance"])
        out.append({
            "task_id": m["task_id"],
            "agent_id": m["agent_id"],
            "target": m["target"],
            "goal_total": float(m["goal_total"]),
            "current": float(m["current"]),
            "distance": dist,
            "progress_ratio": round((1 - dist / float(m["goal_total"])) if m["goal_total"] else 0.0, 4),
            "delta": float(m["delta"]),
            "note": m["note"],
            "ts": m["ts"],
        })
    return {"group_id": group_id, "meters": out, "count": len(out)}


def count_meters():
    row = db.query_one("SELECT COUNT(*) AS n FROM goal_meters")
    return row["n"] if row else 0


# ---------------- 监控动作留痕（sentinel_actions） ----------------

def record_action(agent_id, task_id, level, reason, detail=None, action="", ts=""):
    """记录一次监控哨兵动作（打断 / 重规划 / 上报 / 局部调整）。"""
    action_id = f"{'escalate' if level >= 2 else 'interrupt'}-{uuid.uuid4().hex[:8]}"
    db.execute(
        """
        INSERT INTO sentinel_actions
            (action_id, task_id, agent_id, level, reason, detail, action, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (action_id, task_id, agent_id, int(level), reason,
         _dumps(detail or {}), action, ts or db.now_iso()),
    )
    return action_id


def actions_for_task(task_id, limit=50):
    """某任务的监控动作历史（按时间升序）。"""
    rows = db.query(
        "SELECT * FROM sentinel_actions WHERE task_id=? ORDER BY id ASC LIMIT ?",
        (task_id, limit),
    )
    return [dict(r) for r in rows]


def level2_count_for_task(task_id):
    """某任务已触发的 2 级（上报架构师助理）次数。"""
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM sentinel_actions WHERE task_id=? AND level>=2",
        (task_id,),
    )
    return row["n"] if row else 0


def count_actions(level=None):
    if level is None:
        row = db.query_one("SELECT COUNT(*) AS n FROM sentinel_actions")
    else:
        row = db.query_one(
            "SELECT COUNT(*) AS n FROM sentinel_actions WHERE level=?", (int(level),)
        )
    return row["n"] if row else 0
