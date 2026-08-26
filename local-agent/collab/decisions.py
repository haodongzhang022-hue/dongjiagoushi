# -*- coding: utf-8 -*-
"""
collab · 决策落库与动作消费引擎（decisions）
=============================================
这是 peer collab「收尾闭环」的 E3 模块：把「专家会诊 / 审核者前置助手 /
人类拍板」产生的**决策**持久化为 data 层的**决策实体**，并**驱动后续动作**
（改道 / 补位 / 升级 / 交人）被真正消费——而非一次性返回后无人跟进。

对齐用户口径（Issue #31 已确认）：
  - 「能不能解决」不是决策那一刻判断的，而是**方案实施后拿功能验证是否通过**
    来验收（功能未达成才进本链路）；
  - 决策不是终局，是「当前假设」，执行中可修正；
  - 决策必须可回溯留痕（archives 表，kind='decision'），并驱动动作被消费。

E3 与其他模块协作：
  - expert_consult 未收敛（peer.expert_consult resolved=False）→ 由 closure 编排
    把未收敛结果写入本模块记录 decision（stage='consult_unresolved'）；
  - precursor（审核者前置助手）在各层产出后调用 record_decision 持久化每层结论；
  - human_gate（人类拍板）产出后同样落库，并标记 human_confirmed；
  - 每个 decision 都带 `action`（改道/补位/升级/交人/自决采用），
    供 orchestrator/roles 消费：取走待消费决策并执行对应动作。
"""
import json
import uuid

try:
    from data import admin, db
except Exception:  # noqa: BLE001
    admin = None
    db = None

# 决策实体统一归档到 archives 表，kind='decision'
_DECISION_KIND = "decision"


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False) if isinstance(obj, (dict, list)) else str(obj)


def _now():
    return db.now_iso() if db is not None else ""


# ---------------- 决策落库 ----------------

def record_decision(decision_id, task_id="", cohort_id="", stage="", problem="",
                    chosen=None, action="", agent_id="", human_confirmed=False,
                    detail=None, source=""):
    """持久化一次决策（E3 核心写入）。

    参数:
      decision_id: 决策唯一 id（建议 dt-<uuid>，可复用外部 id）
      stage: 决策阶段（consult / precursor_l1 / precursor_l2 / precursor_l3 / human）
      problem: 被决策的问题
      chosen: 决策采纳的方案（可为 dict）
      action: 驱动的后续动作（改道 reroute / 补位 backup / 升级 escalate / 交人 human / 自决自用 adopt）
      human_confirmed: 是否已经过人类拍板
      detail: 附加详情（会诊意见 / 探索素材 / 折中选项等）
    返回: 决策记录 dict
    """
    archive_id = decision_id or f"dt-{uuid.uuid4().hex[:12]}"
    content = {
        "decision_id": archive_id,
        "task_id": task_id,
        "cohort_id": cohort_id,
        "stage": stage,
        "problem": problem,
        "chosen": chosen,
        "action": action,
        "agent_id": agent_id,
        "human_confirmed": human_confirmed,
        "detail": detail or {},
        "created_at": _now(),
    }
    if admin is not None:
        admin.archive(archive_id, _DECISION_KIND,
                      f"[{stage}] {problem[:40]}", content, source or "peer_closure")
    return content


def get_decision(decision_id):
    """按决策 id 取回已落库的决策实体（可回溯）。"""
    if admin is None:
        return None
    return admin.repo.get_archive(decision_id) if hasattr(admin, "repo") else None


def list_decisions(task_id=None, stage=None, limit=100):
    """列出已落库的决策（按时间倒序，供审计/俯瞰）。"""
    if admin is None:
        return []
    archs = admin.repo.list_archives(kind=_DECISION_KIND, limit=limit)
    out = []
    for a in archs:
        c = a.get("content") or {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except Exception:  # noqa: BLE001
                c = {}
        if task_id and c.get("task_id") != task_id:
            continue
        if stage and c.get("stage") != stage:
            continue
        out.append(c)
    return out


# ---------------- 动作消费（驱动后续动作被真正执行） ----------------

# 待消费动作的进程内队列：decision_id -> 待执行动作描述
_PENDING_ACTIONS = {}


def enqueue_action(decision_id, action, task_id, cohort_id, payload=None):
    """登记一个待消费的决策动作（改道/补位/升级/交人），供调度消费。"""
    _PENDING_ACTIONS[decision_id] = {
        "decision_id": decision_id,
        "action": action,
        "task_id": task_id,
        "cohort_id": cohort_id,
        "payload": payload or {},
        "consumed": False,
    }
    return decision_id


def pending_actions(task_id=None):
    """列出全部待消费动作（未消费）。"""
    return [
        a for a in _PENDING_ACTIONS.values()
        if (task_id is None or a["task_id"] == task_id) and not a["consumed"]
    ]


def consume_action(decision_id):
    """消费一个动作（置为已消费），返回动作描述；不存在/已消费返回 None。"""
    a = _PENDING_ACTIONS.get(decision_id)
    if a is None or a["consumed"]:
        return None
    a["consumed"] = True
    return a


def count_pending(task_id=None):
    """待消费动作数（供看板/哨兵观测闭环是否滞塞）。"""
    return len(pending_actions(task_id))


def actions_overview():
    """决策动作全局俯视图（人类/经理/哨兵可观测）。"""
    return {
        "total_decisions": len(list_decisions()),
        "pending_actions": count_pending(),
        "actions": pending_actions(),
    }


# ---------------- 改道/补位/升级 动作落地辅助 ----------------

def apply_action(action_rec, peer=None, cohort_id="", problem=""):
    """把「动作描述」落地为 peer 引擎的下一步具体动作。

    返回 { action, applied }——applied=True 表示已驱动出下一步。
    """
    if action_rec is None:
        return {"action": None, "applied": False}
    act = action_rec["action"]
    result = {"action": act, "applied": True}
    if act == "reroute":
        # 改道：向 cohort 投递一条"改道"的横向消息，指示换道推进
        if peer is not None and cohort_id:
            peer.peer_message(cohort_id, "closure", "data_admin",
                              f"决策改道：{problem[:40]} → 换道推进", topic="reroute")
            result["note"] = "已向 cohort 投递改道消息"
    elif act == "backup":
        # 补位：记录需补位（专长缺口/卡点），由经理/哨兵按触发时机编排差异 agent
        if peer is not None and cohort_id:
            peer.peer_message(cohort_id, "closure", "data_admin",
                              f"决策补位：{problem[:40]} → 需差异 agent 按专长补位",
                              topic="backup")
            result["note"] = "已投递补位信号，由调度按触发时机编排"
    elif act == "escalate":
        # 升级：上报总师/总师助理评估架构调整
        result["note"] = "已标升级：交由总师/总师助理评估架构调整或折中/取舍"
    elif act == "human":
        # 交人：进入结果前置人类拍板（由 human_gate 承接）
        result["note"] = "已标交人：进入结果前置人类拍板（human_gate）"
    elif act == "adopt":
        result["note"] = "已自决采用：负面小/零成本/零安全风险，直接落地"
    else:
        result["applied"] = False
    return result


def decisions_for_cohort(cohort_id, limit=50):
    """某同岗位编队的全部决策（供 cohort_view 附加收尾闭环状态）。"""
    return list_decisions(limit=limit)  # cohort 过滤在调用方按需再做
