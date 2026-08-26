# -*- coding: utf-8 -*-
"""
调度中枢 · 路由派发器（router）
================================
把「已放行的意图」真正派发给对应 agent。**按 gid 精准定位**（用户拍板 #3）：
同一任务/实体二次触发命中同一个 gid、同一负责 agent，绝不因重跑导致责任人漂移。

派发通道（复用现有零件，不另起炉灶）：
  - `gid`：全局唯一寻址（ops.register_agent_for / pool 的 agent 稳定寻址）；
  - `pool`：功能域任务池（assign_to_pool，按负载弹性扩展 agent）；
  - `broker`：消息总线（deliver 定向投递 → 对应 agent 队列）；
  - `relay`：接力卡（生成/续跑）。

`dispatch(intent)` 返回派发结果 dict；护栏在调用方（engine）已先行判定。
"""
from data import db
from gid import register as gid_register

try:
    from pool import assign_to_pool
    from scale import broker
except ImportError:  # 兼容 local-agent 作为 sys.path 根目录
    from local_agent.pool import assign_to_pool  # pragma: no cover
    from scale import broker  # pragma: no cover


def resolve_agent(intent):
    """由意图解析目标 agent 的全局唯一 gid。

    规则：
      - 驳回回派 / 哨兵打断：意图已带 target_agent（原负责 agent 的 gid），直接用；
      - 其余派发：按 角色+实体key 用 gid.register 稳定取同一个 agent gid
        （同一业务 key 二次触发拿同一 agent，不漂移）。
    """
    if intent.get("target_agent"):
        return intent["target_agent"]
    role = intent.get("target_role", "架构·开发")
    entity = intent.get("entity", "")
    key = f"{role}:{entity}"
    gid, _ = gid_register("agent", key)
    return gid


def dispatch(intent, event_id=""):
    """把一个已放行的意图派发给对应 agent。返回派发结果 dict。"""
    agent_gid = resolve_agent(intent)
    gid_val = intent.get("gid", "")
    payload = {
        "action": intent.get("action", "dispatch"),
        "rule": intent.get("rule", ""),
        "entity": intent.get("entity", ""),
        "gid": gid_val,
        "detail": intent.get("detail", {}),
        "source": intent.get("source", "repo"),
    }

    # ① 尝试投递功能域任务池（任务驱动，弹性扩展）
    dispatched_pool = None
    try:
        if intent.get("target_role"):
            assigned = assign_to_pool(intent.get("target_role", "general"), gid_val or f"task-{intent.get('entity','')}")
            dispatched_pool = assigned.get("pool_id")
    except Exception:
        dispatched_pool = None

    # ② 经 broker 定向投递给对应 agent（消息管线，可追踪可回放）
    broker.deliver(agent_gid, topic="dispatch", payload=payload, from_agent="dispatcher")

    return {
        "dispatched": True,
        "target_agent": agent_gid,
        "pool": dispatched_pool,
        "gid": gid_val,
        "event_id": event_id or intent.get("event_id", ""),
        "action": intent.get("action", "dispatch"),
    }


def reroute_rejection(rejection):
    """驳回回派：把驳回记录路由给原负责 agent（改进重提，迭代闭环）。"""
    intent = {
        "event_type": "rejection",
        "source": "reject",
        "entity": f"reject:{rejection['task_id']}",
        "gid": rejection["gid"],
        "target_role": "",
        "target_agent": rejection["agent_id"],   # 精准回派唯一 agent（gid）
        "action": "reject_reroute",
        "gate": "auto",
        "dedup_key": f"{rejection['gid']}:rejection",
        "detail": {
            "rejection_id": rejection["rejection_id"],
            "reason": rejection["reason"],
            "iteration": rejection["iteration"],
        },
    }
    return dispatch(intent)
