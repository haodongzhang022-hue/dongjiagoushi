# -*- coding: utf-8 -*-
"""
sentinel · 同岗位协作组收敛监控（peer_guard）
==============================================
「监控哨兵」对**同岗位协作组（cohort）**的收敛监控——复用目标进度尺
（goal_meters）与判定引擎（detect），把「同岗多 agent 面对同一问题」的
收敛情况纳入哨兵机器判定（停滞/横跳/重复错误），命中即按既有协议打断/上报。

背景（对齐 AGENTS.md「防无效努力」+「同岗位多角色交互」固定规则）：
  - 同岗位多 agent 协作时，同样需要"量化到目标的收敛监控"——不能因为分工了
    就放任每个成员自己横跳/停滞/重复错误；
  - 按组（cohort）记录收敛刻度：以「到问题解决的量化距离」为统一口径；
  - 命中 1 级 → [打断] + 按剩余距离重规划；命中 2 级 → 上报总师助理评估局部调整，
    标 blocked 待人工/总师拍板后才放行。

E2 与其他模块协作：
  - closure 编排在每次 peer 决策/会诊推进后调用本模块 guard_track 记录收敛刻度；
  - 复用 sentinel.detect.analyze 判定（stagnation/oscillation/repeated_error）；
  - 命中处置复用 sentinel.engine.interrupt / escalate 留痕协议。
"""
import uuid

try:
    from data import admin
    from sentinel import store as sstore, detect, engine as sengine
except Exception:  # noqa: BLE001
    admin = None
    sstore = None
    detect = None
    sengine = None


def guard_track(cohort_id, task_id, problem, goal_total, current,
                agent_id="", note="", params=None):
    """对同岗位协作组记录一次到目标的收敛刻度并立即判定。

    参数（与 sentinel.store.record_meter 对齐）：
      goal_total: 该问题解决的量化总量（北极星）
      current: 当前已达量（向解决收敛）
    返回 { meter, analysis }——analysis.hit 命中时调用方按协议处置。
    """
    meter_id = f"cg-{cohort_id}"
    if sstore is None:
        return None
    meter = sstore.record_meter(
        meter_id, task_id=task_id, agent_id=agent_id or cohort_id,
        target=f"[同岗协作组 {cohort_id}] {problem}", goal_total=goal_total,
        current=current, note=note,
    )
    series = sstore.meter_series(meter_id)
    analysis = detect.analyze(
        series, goal_total=goal_total, agent_id=agent_id or cohort_id,
        task_id=task_id, params=params,
    )
    return {"meter": meter, "analysis": analysis}


def guard_handle(cohort_id, task_id, problem, goal_total, current,
                 agent_id="", note="", params=None):
    """哨兵统一处置入口（同岗协作组）：track + 按命中级别执行中断/上报协议。

    返回 { meter, analysis, action_id, handled }。
    """
    r = guard_track(cohort_id, task_id, problem, goal_total, current,
                    agent_id=agent_id, note=note, params=params)
    if r is None:
        return {"handled": False}
    analysis = r["analysis"]
    action_id = None
    handled = False
    if analysis["hit"]:
        if analysis["level"] >= 2:
            action_id = sengine.escalate(task_id, agent_id or cohort_id,
                                         analysis["reason"], analysis)
        else:
            action_id = sengine.interrupt(
                f"cg-{cohort_id}", task_id, agent_id or cohort_id,
                analysis["reason"], analysis)
        handled = True
    r["action_id"] = action_id
    r["handled"] = handled
    return r


def cohort_meter_summary(cohort_id):
    """同岗协作组收敛俯视图（二级信息，供人类/经理/哨兵监控）。"""
    if sstore is None:
        return {"cohort_id": cohort_id, "meters": [], "count": 0}
    series = sstore.meter_series(f"cg-{cohort_id}")
    latest = series[-1] if series else None
    return {
        "cohort_id": cohort_id,
        "meters": series,
        "count": len(series),
        "latest": latest,
        "distance": float(latest["distance"]) if latest else None,
        "converging": bool(latest and float(latest["distance"]) == 0.0),
    }


def peer_guard_overview():
    """同岗协作收敛监控全局俯视图（二级信息）。"""
    return {
        "cohort_meters": sstore.count_meters() if sstore else 0,
        "interrupts": sstore.count_actions(level=1) if sstore else 0,
        "escalations": sstore.count_actions(level=2) if sstore else 0,
    }
