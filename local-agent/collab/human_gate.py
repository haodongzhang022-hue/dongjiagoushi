# -*- coding: utf-8 -*-
"""
collab · 结果前置·人类拍板引擎（human_gate）
============================================
这是 peer collab「收尾闭环」的 E4 模块：在「会诊/审核者前置助手都解决不了、
需要人类担责决策」的那一刻，**把人类叫出来拍板**——结果前置、因果对齐、
CP 留痕，非事后背锅。

对齐用户口径（Issue #31）：
  - 不是"做完不行了才叫人背锅"，而是**有负面责任需要决策的那一刻就先出来**；
  - 交给人类时信息**必须足够明确**，尤其把**风险点显式列清**（什么风险、发生哪一步、
    代价多大、有无兜底），让人类在**决策点**就掌握全部因果，自己选、自己承担；
  - AI 判断"没办法"不一定真没路——换个问法/问一下可能不一样；
    若补充信息后仍无更明显的好方案但属**必要成本**，可做但**必须人类确认**；
  - 安全护栏（AGENTS.md）：禁止代替用户确认、禁止未获确认就放行、禁止假装已确认。

与 CP 放行点对齐：
  - CP1 计划确认 / CP2 开发确认 / CP3 合并确认 —— 本模块把「人类拍板」落成
    CP 留痕：open（待人类确认）→ confirmed（人类已确认/放行）→ rejected（人类否决）。
"""
import json
import uuid

try:
    from data import admin, db
except Exception:  # noqa: BLE001
    admin = None
    db = None

# 人类拍板闸门（结果前置 · CP 留痕）
_GATES = {}


def open_gate(gate_id, problem, task_id="", cohort_id="", stage="human",
              risk_points=None, options=None, necessity="", requester=""):
    """在决策点打开一个人类拍板闸门（结果前置，非事后背锅）。

    参数:
      gate_id: 闸门唯一 id（建议 gt-<uuid>）
      problem: 待人类拍板的问题
      risk_points: 风险点清单 [{ risk, step, cost, mitigation }]——必须显式列清
      options: 给人类的可选方案（含各自代价）
      necessity: 是否必要成本（若属必要成本可做但必须人类确认）
    返回 gate dict（status='open'，等待人类确认）。
    """
    g = {
        "gate_id": gate_id or f"gt-{uuid.uuid4().hex[:12]}",
        "problem": problem,
        "task_id": task_id,
        "cohort_id": cohort_id,
        "stage": stage,
        "risk_points": risk_points or [],
        "options": options or [],
        "necessity": necessity,
        "requester": requester or "peer_closure",
        "status": "open",           # open / confirmed / rejected
        "confirmed_by": "",
        "created_at": _now(),
        "confirmed_at": None,
    }
    _GATES[g["gate_id"]] = g
    # 落库留痕（人类拍板闸门属于决策类产出）
    if admin is not None:
        try:
            admin.archive(g["gate_id"], "decision",
                          f"[人类拍板] {problem[:40]}", g, "human_gate")
        except Exception:  # noqa: BLE001
            pass
    return g


def confirm_gate(gate_id, by, decision=None):
    """人类在决策点放行（CP 确认）。返回闸门更新后的状态。

    安全护栏：禁止代替用户确认——调用方必须提供 by（真实人类/用户）才放行。
    """
    g = _GATES.get(gate_id)
    if g is None:
        return None
    if not by:
        raise PermissionError("[human_gate] 禁止代替用户确认：by 不能为空")
    g["status"] = "confirmed"
    g["confirmed_by"] = by
    g["confirmed_at"] = _now()
    g["human_decision"] = decision or g["options"][0] if g["options"] else None
    return g


def reject_gate(gate_id, by, reason=""):
    """人类否决（被打回/终止该决策路线）。返回更新后的闸门。"""
    g = _GATES.get(gate_id)
    if g is None:
        return None
    g["status"] = "rejected"
    g["confirmed_by"] = by
    g["confirmed_at"] = _now()
    g["reject_reason"] = reason
    return g


def gate_status(gate_id):
    return _GATES.get(gate_id)


def list_gates(status=None):
    """人类拍板闸门清单（结果前置，供俯瞰哪些决策点还在等人类）。"""
    if status:
        return [g for g in _GATES.values() if g["status"] == status]
    return list(_GATES.values())


def open_gates():
    """当前等待人类拍板的闸门（open）。"""
    return [g for g in _GATES.values() if g["status"] == "open"]


def _now():
    return db.now_iso() if db is not None else ""


# ---------- 与 closure 编排的衔接 ----------

def ensure_human_gate(problem, task_id="", cohort_id="", risk_points=None,
                      options=None, necessity="", requester=""):
    """供 closure 编排调用：确保为该问题存在一个待人类拍板的闸门（幂等）。

    同一 (problem, task_id) 未 open 才新建，已 open 直接复用——避免重复打扰人类。
    """
    for g in open_gates():
        if g["problem"] == problem and (not task_id or g["task_id"] == task_id):
            return g
    return open_gate(None, problem, task_id=task_id, cohort_id=cohort_id,
                     risk_points=risk_points, options=options,
                     necessity=necessity, requester=requester)
