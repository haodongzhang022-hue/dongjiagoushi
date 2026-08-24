# -*- coding: utf-8 -*-
"""
sentinel · 监控哨兵引擎（engine）
=================================
「防无效努力 / 目标收敛监控」的统一入口：把 数据刻度(store) + 判定(detect)
串成可执行的**哨兵处置协议**。由「架构·监控哨兵」角色统一执行（见 roles/sentinel.py）。

处置协议（docs/SENTINEL.md，与 AGENTS.md「防无效努力」固定规则对齐）：

  ⏹ 每次推进动作必须先在目标进度尺记录刻度（record_meter）；
  ⏹ 记录后即跑 detect.analyze：若未命中 → 放行，继续推进；
  ⏹ 命中 1 级 → 触发 [打断] + 依据「剩余距离」重新规划再分配，留痕 sentinel_actions；
  ⏹ 命中 2 级（该任务此前已 1 级打断过 / 或检测引擎直接判 2 级）→ 上报
     「架构·总师助理」讨论**局部架构调整**，留痕并标 blocked 待人工/总师介入。

绝不假装执行：每一步真实落库（goal_meters / sentinel_actions）、可回放、可审计。
"""
from sentinel import store, detect

# 便捷再导出：engine.analyze / engine.store / engine.detect
analyze = detect.analyze


def init():
    """哨兵初始化：确保表存在（幂等）。"""
    from data import schema
    tables = schema.init_schema()
    return {"tables": tables}


def track(meter_id, task_id="", agent_id="", target="",
          goal_total=0.0, current=0.0, note="", params=None):
    """记录一次到目标的进度刻度并立即做收敛检测。

    返回：{ meter, analysis } —— meter 为落库刻度，analysis 为检测结果（见 detect.analyze）。
    若 analysis.hit 命中，调用方（哨兵角色）应据此按协议处置（interrupt/escalate）。
    """
    meter = store.record_meter(
        meter_id, task_id=task_id, agent_id=agent_id, target=target,
        goal_total=goal_total, current=current, note=note,
    )
    series = store.meter_series(meter_id)
    analysis = detect.analyze(
        series, goal_total=goal_total, agent_id=agent_id, task_id=task_id, params=params,
    )
    return {"meter": meter, "analysis": analysis}


def interrupt(meter_id, task_id, agent_id, reason, detail, params=None):
    """1 级处置：打断 + 重新规划（依据剩余距离），留痕。

    返回 action_id；同时把「重新规划」的要求固化到 detail（供接收方重规划）。
    """
    analysis = detect.analyze(
        store.meter_series(meter_id), goal_total=0.0,  # goal_total 由调用方在 detail 说明
        agent_id=agent_id, task_id=task_id, params=params,
    )
    action = (
        f"[打断] 目标 {task_id} 角色 {agent_id} 触发无效努力({reason})："
        f"打断当前推进，依据剩余距离重新规划再分配，禁止在同类失败上反复尝试。"
    )
    action_id = store.record_action(
        agent_id, task_id, 1, reason, detail, action=action,
    )
    # 同步留痕进度事件，供总师/人类俯瞰
    from data import admin
    admin.record_event(agent_id, "sentinel_interrupt",
                       {"task_id": task_id, "reason": reason}, task_id)
    return action_id


def escalate(task_id, agent_id, reason, detail):
    """2 级处置：上报「架构·总师助理」讨论局部架构调整，留痕并标 blocked。

    返回 action_id。
    """
    action = (
        f"[上报] 目标 {task_id} 角色 {agent_id} 二度触发无效努力({reason})："
        f"交由「架构·总师助理」评估是否对架构做局部调整（含目标定义/分配/流程）。"
    )
    action_id = store.record_action(
        agent_id, task_id, 2, reason, detail, action=action,
    )
    from data import admin
    admin.record_event(agent_id, "sentinel_escalate",
                       {"task_id": task_id, "reason": reason}, task_id)
    # 标任务 blocked，待人工/总师介入（不自行放行）
    try:
        admin.update_task(task_id, "blocked")
    except Exception:  # noqa: BLE001 任务可能不存在，忽略
        pass
    return action_id


def handle(meter_id, task_id="", agent_id="", target="",
           goal_total=0.0, current=0.0, note="", params=None):
    """哨兵统一处置入口：track + 按命中级别执行中断/上报协议。

    返回 { meter, analysis, action_id, handled }。
    """
    result = track(meter_id, task_id, agent_id, target, goal_total, current, note, params)
    analysis = result["analysis"]
    action_id = None
    handled = False
    if analysis["hit"]:
        if analysis["level"] >= 2:
            action_id = escalate(task_id, agent_id, analysis["reason"], analysis)
        else:
            action_id = interrupt(meter_id, task_id, agent_id, analysis["reason"], analysis)
        handled = True
    result["action_id"] = action_id
    result["handled"] = handled
    return result


# ---------------- 二级信息（供人类/总师俯瞰） ----------------

def health_report():
    """哨兵运行健康报告（二级信息）：刻度总数 / 各级触发次数。"""
    return {
        "meters": store.count_meters(),
        "interrupts": store.count_actions(level=1),
        "escalations": store.count_actions(level=2),
    }
