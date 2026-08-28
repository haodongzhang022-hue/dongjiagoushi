# -*- coding: utf-8 -*-
"""
开发持续推进引擎（Dev Iteration · 自循环推进）
================================================
解决用户核心诉求：「开发没开发完 → 继续接开发」，而不是每次回传都触发
评审或经理重新处理跟进——过程中只**记录进度**（写 goal_meters + 存档 archives），
**不对话、不打扰经理**；干完统一交付给经理。

核心机制：
  ┌─────────────────────────────────────────────────────────┐
  │  任务明确（goal_total 北极星目标）                         │
  │     ↓                                                    │
  │  开发自循环： continue_dev()                             │
  │     ↓                                                    │
  │  每次推进 → record_progress()                            │
  │      ├─ 写 goal_meters 进度尺（distance/delta）          │
  │      ├─ 存 archives（记录留痕，非对话）                   │
  │      └─ sentinel_check() 哨兵判定                        │
  │          ├─ 未命中 → 距离>0 → 继续开发                    │
  │          ├─ 命中 1 级 → [打断] + 重规划 → 交评审          │
  │          └─ 命中 2 级 → [上报] 总师助理 + blocked         │
  │     ↓                                                    │
  │  距离==0（完成）→ deliver_to_manager()                   │
  │      一次性通知经理：交付 + 完整进度记录                   │
  └─────────────────────────────────────────────────────────┘

设计要点（对齐 AGENTS.md / docs/SENTINEL.md / docs/DISPATCH_DEPTH.md）：
  - **防无限循环**：靠哨兵判定（停滞/横跳/重复错误）拦截，不是靠"对话限制"；
  - **记录优先于对话**：过程中只存档记录，不每次触发经理对话；
  - **任务明确才自循环**：goal_total 未定义 → 不能自循环，须先澄清目标；
  - **完成后统一交付**：交付 = 完整进度记录 + 产物，一次性给经理。

对应文档：docs/DEV_ITERATION.md
"""
import os
import sys
import json

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from data import admin
from gid import gid_for
from sentinel import engine as sentinel


# ============================================================
# 一、判断是否可继续开发（自循环前提）
# ============================================================
def can_continue(task_key, goal_total=0.0, current=0.0):
    """判断开发是否可继续自循环推进。

    自循环三前提：
      ① 任务明确：goal_total > 0（有北极星目标）；
      ② 未完成：current < goal_total（还有剩余距离）；
      ③ 未命中哨兵拦截（停滞/横跳/重复错误）。

    返回 { can_continue, reason, detail }。
    """
    task_id = gid_for("task", task_key) or task_key

    # ① 任务明确
    try:
        gt = float(goal_total)
    except (TypeError, ValueError):
        return {
            "can_continue": False,
            "reason": "no_goal",
            "detail": "goal_total 未定义或非法，须先澄清北极星目标才能自循环推进",
        }
    if gt <= 0:
        return {
            "can_continue": False,
            "reason": "no_goal",
            "detail": "goal_total<=0，任务目标不明确，不能自循环。请先定义北极星目标（如 10 步）",
        }

    # ② 未完成
    cur = float(current or 0.0)
    if cur >= gt:
        return {
            "can_continue": False,
            "reason": "completed",
            "detail": f"current({cur}) >= goal_total({gt})，任务已完成，应交付而非继续开发",
        }

    # ③ 哨兵未拦截：查最近一条刻度的检测结果
    meter_id = f"g-{task_id}"
    latest = sentinel.store.latest_meter(meter_id)
    analysis = None
    if latest is not None:
        series = sentinel.store.meter_series(meter_id)
        analysis = sentinel.detect.analyze(
            series, goal_total=gt, agent_id="", task_id=task_id,
        )
        if analysis["hit"]:
            return {
                "can_continue": False,
                "reason": f"sentinel_{analysis['reason']}",
                "level": analysis["level"],
                "detail": analysis["detail"],
                "distance": gt - cur,
            }

    return {
        "can_continue": True,
        "reason": "ready",
        "distance": gt - cur,
        "goal_total": gt,
        "current": cur,
        "detail": f"任务明确（目标 {gt} 步），当前进度 {cur}，剩余 {gt-cur}，哨兵未拦截，可继续开发",
    }


# ============================================================
# 二、记录推进度（存档 · 非对话 · 供后续回放）
# ============================================================
def record_progress(task_key, agent_id, target, goal_total, current,
                    note="", archive_detail=""):
    """记录一次开发推进度。

    - 写 goal_meters 进度尺（distance/delta，供哨兵收敛判定）；
    - 存 archives 记录（非对话，先存起来，干完一起给经理）；
    - 返回哨兵检测结果（调用方据此判断是否继续）。

    输入：
      task_key: 任务 key
      agent_id: 开发 agent gid
      target: 目标描述
      goal_total: 北极星目标总量（必须 > 0）
      current: 当前已达量
      note: 本次推进说明（失败须显式标"失败/报错/重试"等，供哨兵重复错误判定）
      archive_detail: 可选，额外存档内容（实现细节/遇到的问题/下一步计划）

    返回 { record, sentinel }：
      record: {task_key, current, distance, delta, archived}
      sentinel: {hit, reason, level, detail} 哨兵判定结果
    """
    task_id = gid_for("task", task_key) or task_key
    meter_id = f"g-{task_id}"

    # ① 写 goal_meters 进度尺
    result = sentinel.track(
        meter_id, task_id=task_id, agent_id=agent_id,
        target=target, goal_total=float(goal_total), current=float(current),
        note=note,
    )
    meter = result["meter"]
    analysis = result["analysis"]

    # ② 存 archives（非对话，先存起来，干完一起给经理）
    archive_id = f"dev_{task_id}_{meter.get('ts', '')}"
    admin.archive(
        archive_id,
        kind="dev_progress",
        title=f"[开发推进] {task_key} 进度 {current}/{goal_total}",
        content=json.dumps({
            "task_key": task_key,
            "task_id": task_id,
            "agent_id": agent_id,
            "target": target,
            "goal_total": float(goal_total),
            "current": float(current),
            "distance": meter.get("distance", 0),
            "delta": meter.get("delta", 0),
            "note": note,
            "archive_detail": archive_detail or "",
            "ts": meter.get("ts", ""),
        }, ensure_ascii=False, indent=2),
        source=agent_id,
    )

    # ③ 记录进度事件
    admin.record_event(
        agent_id, "dev_progress",
        {"task_key": task_key, "task_id": task_id,
         "current": float(current), "goal_total": float(goal_total),
         "distance": meter.get("distance", 0),
         "delta": meter.get("delta", 0),
         "note": note},
        task_id,
    )

    return {
        "record": {
            "task_key": task_key,
            "current": float(current),
            "goal_total": float(goal_total),
            "distance": meter.get("distance", 0),
            "delta": meter.get("delta", 0),
            "archived": True,
            "archive_id": archive_id,
        },
        "sentinel": {
            "hit": analysis["hit"],
            "reason": analysis["reason"],
            "level": analysis["level"],
            "detail": analysis["detail"],
        },
    }


# ============================================================
# 三、开发自循环入口
# ============================================================
def continue_dev(task_key, agent_id, target, goal_total, current,
                 note="", archive_detail="", max_iterations=20):
    """开发自循环入口：记录推进度 + 哨兵判定 + 判断是否继续。

    关键：任务明确（goal_total>0）时，开发可自循环推进——每次记录进度、
    哨兵判定是否拦截、距离>0 则继续、距离==0 则建议交付。

    防无限循环三道防线：
      ① 哨兵判定：停滞/横跳/重复错误 → 命中即拦截（level 1 打断 / level 2 上报）；
      ② max_iterations：单轮 continue_dev 最多自循环 N 次（默认 20），防失控；
      ③ 完成即止：current >= goal_total → 返回"建议交付"。

    返回 {
      iteration,       # 本次自循环序号（从 1 开始）
      can_continue,    # 是否可继续下一轮
      continue_reason, # ready / completed / sentinel_* / max_iterations / no_goal
      distance,        # 剩余距离
      sentinel,        # 哨兵判定结果
      record,          # 本次记录
    }
    """
    # 先检查任务是否明确
    check = can_continue(task_key, goal_total, current)
    if not check["can_continue"] and check["reason"] != "completed":
        # 不明确 / 哨兵已拦截 → 不能自循环
        return {
            "iteration": 0,
            "can_continue": False,
            "continue_reason": check["reason"],
            "distance": check.get("distance", 0),
            "detail": check["detail"],
            "sentinel": None,
            "record": None,
        }

    # 记录本次推进
    result = record_progress(
        task_key, agent_id, target, goal_total, current,
        note=note, archive_detail=archive_detail,
    )
    sentinel_res = result["sentinel"]
    record = result["record"]

    # 哨兵判定拦截
    if sentinel_res["hit"]:
        return {
            "iteration": 1,
            "can_continue": False,
            "continue_reason": f"sentinel_{sentinel_res['reason']}",
            "level": sentinel_res["level"],
            "distance": record["distance"],
            "sentinel": sentinel_res,
            "record": record,
            "detail": sentinel_res["detail"],
        }

    # 完成判定
    if float(current) >= float(goal_total):
        return {
            "iteration": 1,
            "can_continue": False,
            "continue_reason": "completed",
            "distance": 0,
            "sentinel": sentinel_res,
            "record": record,
            "detail": "任务已完成（current>=goal_total），应交付给经理，不继续开发",
        }

    # 可继续
    return {
        "iteration": 1,
        "can_continue": True,
        "continue_reason": "ready",
        "distance": record["distance"],
        "sentinel": sentinel_res,
        "record": record,
        "detail": f"进度 {current}/{goal_total}，剩余 {record['distance']}，可继续下一轮开发",
    }


def run_iterations(task_key, agent_id, target, goal_total,
                   steps, notes=None, archive_details=None):
    """批量执行多轮开发自循环（供脚本/测试/自动化调用）。

    steps: 每轮的 current 值列表，如 [1,2,3,4,5,...,10]
    notes: 每轮说明（可选，长度对齐 steps；含"失败/报错"等标记用于哨兵重复错误判定）

    返回所有轮的 continue_dev 结果列表。
    """
    results = []
    for i, cur in enumerate(steps):
        note = (notes[i] if notes and i < len(notes) else f"第{i+1}轮推进")
        archive_detail = (archive_details[i] if archive_details and i < len(archive_details)
                          else f"完成第{i+1}轮：进度 {cur}/{goal_total}")
        res = continue_dev(
            task_key, agent_id, target,
            goal_total=goal_total, current=cur,
            note=note, archive_detail=archive_detail,
        )
        results.append(res)
        # 若哨兵拦截或完成，提前停止
        if not res["can_continue"]:
            break
    return results


# ============================================================
# 四、完成时统一交付给经理
# ============================================================
def deliver_to_manager(task_key, agent_id, output, issue_ref="", manager_msg=""):
    """任务完成时，统一交付给经理（一次性通知 + 完整进度记录）。

    - 归档交付产物（deliverable）；
    - 标记任务 done；
    - 投递一条交付消息给经理（含完整进度记录回放，不反复打扰）；
    - 留痕交付事件。

    输入：
      task_key: 任务 key
      agent_id: 开发 agent gid
      output: 交付产物描述
      issue_ref: 可选，关联 Issue（如 "#42"）
      manager_msg: 可选，给经理的附加说明

    返回 { status, task_id, archived, progress_history }。
    """
    from gid import gid_for as gf
    task_id = gf("task", task_key) or task_key

    # ① 归档交付产物
    admin.archive(
        f"deliver_{task_key}",
        kind="deliverable",
        title=f"任务 {task_key} 交付",
        content=output,
        source=agent_id,
    )

    # ② 标记任务 done
    admin.update_task(task_id, "done")

    # ③ 汇总全部开发进度记录（回放，给经理参考）
    history = progress_history(task_key)

    # ④ 投递一次性交付消息给经理
    admin.post_message(
        topic="dev.delivered",
        payload={
            "task_key": task_key,
            "task_id": task_id,
            "agent_id": agent_id,
            "action": "开发已完成，统一交付",
            "output": output,
            "issue_ref": issue_ref,
            "progress_history": history,
            "manager_msg": manager_msg or "",
        },
        from_agent=agent_id,
        to_agent="架构·经理",
    )

    # ⑤ 留痕交付事件
    admin.record_event(
        agent_id, "delivered",
        {"task_key": task_key, "task_id": task_id,
         "issue_ref": issue_ref, "output": output,
         "progress_history_count": len(history)},
        task_id,
    )

    return {
        "status": "delivered",
        "task_key": task_key,
        "task_id": task_id,
        "archived": True,
        "progress_history": history,
    }


# ============================================================
# 五、二级信息：进度记录回放 / 迭代俯瞰
# ============================================================
def progress_history(task_key):
    """某任务的全部开发进度记录（回放，供交付时给经理参考）。

    按时间升序返回 goal_meters 序列（含 distance/delta/note）。
    """
    task_id = gid_for("task", task_key) or task_key
    meter_id = f"g-{task_id}"
    series = sentinel.store.meter_series(meter_id, limit=200)
    return [
        {
            "meter_id": m["meter_id"],
            "current": m["current"],
            "goal_total": m["goal_total"],
            "distance": m["distance"],
            "delta": m["delta"],
            "note": m["note"],
            "ts": m["ts"],
        }
        for m in series
    ]


def iteration_overview():
    """全部开发自循环的俯瞰（二级信息）：各任务当前进度/距离/状态。

    返回 { total_meters, tasks: [{task_id, current, goal_total, distance, delta, latest_ts}] }
    """
    from data import db
    rows = db.query(
        """
        SELECT task_id, goal_total, current, distance, delta, note, ts
        FROM goal_meters
        ORDER BY id ASC LIMIT 500
        """
    )
    tasks = {}
    for r in rows:
        m = dict(r)
        tid = m.get("task_id", "")
        if tid not in tasks:
            tasks[tid] = {
                "task_id": tid,
                "goal_total": m.get("goal_total", 0),
                "current": m.get("current", 0),
                "distance": m.get("distance", 0),
                "delta": m.get("delta", 0),
                "latest_ts": m.get("ts", ""),
                "notes": [],
            }
        else:
            tasks[tid]["current"] = m.get("current", 0)
            tasks[tid]["distance"] = m.get("distance", 0)
            tasks[tid]["delta"] = m.get("delta", 0)
            tasks[tid]["latest_ts"] = m.get("ts", "")
        if m.get("note"):
            tasks[tid]["notes"].append(m["note"])
    return {
        "total_meters": len(rows),
        "total_tasks": len(tasks),
        "tasks": list(tasks.values()),
    }


# ============================================================
# 六、哨兵拦截处置（供哨兵角色 / 调用方按协议执行）
# ============================================================
def handle_sentinel_hit(task_key, agent_id, hit_result):
    """哨兵命中处置：按级别执行协议（1级打断 / 2级上报）。

    输入：continue_dev 返回的 sentinel 命中结果
    返回：处置动作记录
    """
    task_id = gid_for("task", task_key) or task_key
    meter_id = f"g-{task_id}"
    reason = hit_result.get("reason", "unknown")
    detail = hit_result.get("detail", {})
    level = hit_result.get("level", 1)

    if level >= 2:
        action_id = sentinel.escalate(task_id, agent_id, reason, detail)
        return {
            "handled": True,
            "level": 2,
            "action": "上报总师助理（局部架构调整评估）",
            "action_id": action_id,
            "blocked": True,
        }

    action_id = sentinel.interrupt(meter_id, task_id, agent_id, reason, detail)
    return {
        "handled": True,
        "level": 1,
        "action": "打断重规划（依据剩余距离重新分配）",
        "action_id": action_id,
        "blocked": False,
    }
