# -*- coding: utf-8 -*-
"""
collab · 同岗协作收尾闭环编排（closure）
=========================================
这是 peer collab「收尾闭环」的统一编排入口：把 G1~G4 四个缺漏模块
（会诊升级链 precursor / 哨兵同岗收敛监控 peer_guard / 决策落库 decisions /
结果前置人类拍板 human_gate）**串成一个自动闭环**，让"会诊解决不了"自动
进入审核者前置助手 → 人类拍板，能多自动一环就多自动一环，直到功能验证通过。

触发硬约束（缺前置直接触发 = 错误）：
  - 本闭环**只在功能实现不了时才接入**；前置（单兵 → 补位 → 专家会诊）一个都不能丢。

主流程（对齐用户口径「以事能不能解决为准，不以做了判断当终局」）：
```
peer.expert_consult(cohort, problem) 
   ├─ resolved=True（会诊收敛，功能验证通过）→ 放行 ✅
   └─ resolved=False（未收敛）→ 进入本 closure.run()
         ├─ E1 precursor：L1 内部分支 → L2 外部探索
         │     ├─ L2 命中且自决（负面小/零成本/零安全风险）→ adopt ✅（功能验证）
         │     └─ L2 命中但需担责 / 未命中 → E4 human_gate 结果前置交人类拍板
         ├─ E3 decisions：每一层结论落库 + enqueue 待消费动作
         └─ E2 peer_guard：对 cohort 写收敛刻度 + 命中按协议打断/上报
```
"""
import json
import uuid

try:
    from data import admin, db
    from collab import peer, decisions, precursor, human_gate
    from sentinel import peer_guard
except Exception:  # noqa: BLE001
    admin = db = peer = decisions = precursor = human_gate = peer_guard = None


def _now():
    return db.now_iso() if db is not None else ""


def _new_dt(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def run(problem, cohort_id, task_id="", option_a="", option_b="",
        keyword="", known_patterns=None, consult_result=None,
        scenario_hint="", defects_a="", defects_b="", alt="", blank=""):
    """同岗协作收尾闭环：从"会诊未收敛"自动走到"人类拍板"或"自决采用"。

    参数:
      consult_result: peer.expert_consult 的返回（resolved=False 才应进本函数）
      known_patterns: L2 外部探索命中方案（含 negative/cost/risk 标记）
    返回一个分阶段结果 dict，供调用方（roles/manager/哨兵）消费。
    """
    # ---- 前置硬约束校验：缺前置（无会诊结果）直接触发 = 错误 ----
    if consult_result is None:
        return {
            "status": "error",
            "error": "缺前置：必须由 peer.expert_consult 产生未收敛结果才能进入收尾闭环",
            "trace": [],
        }
    if consult_result.get("resolved"):
        return {
            "status": "resolved_at_consult",
            "trace": [{"stage": "consult", "result": "会诊已收敛，功能验证通过，放行"}],
        }

    trace = [{"stage": "consult", "result": "会诊未收敛，进入审核者前置助手"}]
    dt_consult = _new_dt("dt")
    decisions.record_decision(
        dt_consult, task_id=task_id, cohort_id=cohort_id, stage="consult",
        problem=problem, action="escalate", source="closure",
        detail={"opinions": consult_result.get("opinions", []),
                "summary": consult_result.get("summary", "")},
    )
    decisions.enqueue_action(dt_consult, "escalate", task_id, cohort_id,
                             {"problem": problem})

    # ---- E1 审核者前置助手：L1 → L2 → L3 ----
    pr = precursor.run(problem, option_a=option_a, option_b=option_b,
                       scenario_hint=scenario_hint, keyword=keyword,
                       known_patterns=known_patterns,
                       defects_a=defects_a, defects_b=defects_b,
                       alt=alt, blank=blank)
    outcome = pr["outcome"]

    # 记录每一层结论落库
    for layer in pr["layers"]:
        dt = _new_dt("dt")
        decisions.record_decision(
            dt, task_id=task_id, cohort_id=cohort_id, stage=layer["layer"],
            problem=problem, action=outcome, source="precursor",
            detail={"branch": layer.get("branches") if layer.get("branches") else layer},
        )

    if outcome == "l2_adopt":
        # L2 命中且自决：负面小/零成本/零安全风险 → 直接采用
        adopt = pr["decision"]["adopt"]
        dt = _new_dt("dt")
        decisions.record_decision(
            dt, task_id=task_id, cohort_id=cohort_id, stage="precursor_l2",
            problem=problem, chosen=adopt, action="adopt", source="closure",
            detail={"principle": "负面足够小/零成本/零安全风险，自决采用"},
        )
        decisions.enqueue_action(dt, "adopt", task_id, cohort_id, {"adopt": adopt})
        # 哨兵记录：自决采用视为该问题功能验证通过（距离归零）
        if peer_guard is not None:
            peer_guard.guard_track(cohort_id, task_id, problem, goal_total=1.0,
                                   current=1.0, note="自决采用，收敛")
        return {
            "status": "adopted",
            "outcome": outcome,
            "decision": pr["decision"],
            "trace": trace + [{"stage": "precursor_l2", "result": "自决采用"}],
        }

    # ---- L3 结果前置·人类拍板（含"命中但需担责"与"未命中"两情形） ----
    gate = human_gate.ensure_human_gate(
        problem, task_id=task_id, cohort_id=cohort_id,
        risk_points=pr["layers"][-1].get("pack", {}).get("l2", {}).get("hits", [])
        if pr["layers"][-1].get("pack") else [],
        options=pr["decision"].get("pack", {}).get("options", []),
        necessity="L2 命中但需担责，或未命中外部方案，属必要成本则须人类确认",
        requester="closure",
    )
    dt = _new_dt("dt")
    decisions.record_decision(
        dt, task_id=task_id, cohort_id=cohort_id, stage="precursor_l3",
        problem=problem, chosen=pr["decision"], action="human", source="closure",
        detail={"gate_id": gate["gate_id"], "reason": pr["decision"].get("reason", "")},
    )
    decisions.enqueue_action(dt, "human", task_id, cohort_id,
                             {"gate_id": gate["gate_id"]})
    # 哨兵记录：未收敛但已交人（距离未归零，标记等待人类）
    if peer_guard is not None:
        peer_guard.guard_track(cohort_id, task_id, problem, goal_total=1.0,
                               current=0.0, note="已交人类拍板，等待确认")
    return {
        "status": "awaiting_human",
        "outcome": outcome,
        "gate": gate,
        "decision": pr["decision"],
        "trace": trace + [{"stage": "precursor_l3", "result": "结果前置交人类拍板"}],
    }


def run_consult_chain(cohort_id, problem, task_id="", **kwargs):
    """便捷入口：给定 cohort 与问题，内部先做 expert_consult，未收敛再走闭环。

    适合"调用方只关心最终能否自动闭环"的场景（自动化优先）。
    """
    if peer is None:
        return {"status": "error", "error": "peer 引擎不可用"}
    res = peer.expert_consult(cohort_id, problem)
    if res["resolved"]:
        return {"status": "resolved_at_consult", "consult": res}
    return run(problem, cohort_id, task_id=task_id, consult_result=res, **kwargs)


def closure_overview():
    """收尾闭环全局俯视图（二级信息，供人类/经理/哨兵俯瞰）。"""
    return {
        "decisions": decisions.actions_overview() if decisions is not None else {},
        "gates": human_gate.list_gates() if human_gate is not None else [],
        "peer_guard": peer_guard.peer_guard_overview() if peer_guard is not None else {},
    }
