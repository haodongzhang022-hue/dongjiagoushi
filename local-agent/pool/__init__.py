# -*- coding: utf-8 -*-
"""
功能域任务池（pool · 任务驱动的并发扩展）
===========================================
用户核心诉求：
  "允许 2500 并发，不是直接 2500 并发，还是要根据任务情况，有任务了就到
   某个功能域的任务池子，然后每个池子有根据任务扩展 agent 去负责的功能。"

本模块把「并发」从「直接开满 N 个 agent」改为**任务驱动**的弹性扩缩容：

  - **功能域任务池**：每个功能域（登录/结算/报表/搜索/...）一个池子（task_pools），
    任务按功能域投递到对应池子；
  - **按负载动态扩展 agent**：池子容量随「积压任务数」伸缩——有任务就扩容
    agent，任务少了就缩容，不预先空占 2500 个并发；
  - **每个池子内的 agent** 由任务决定：一个任务派一个 agent（可多任务并行），
    全部走**全局唯一 gid**，二次触发仍命中同一 agent/任务（见 gid.py）；
  - 支持**父池 → 子池**拆分（大功能域拆子池），池子可关闭（draining/closed）。

对外统一入口：
  - `assign_to_pool(domain, task_id, weight=1)`：把任务投入某功能域池子，自动扩容；
  - `scale_pools()`：扫描全部池子，按负载自动扩容/缩容（有任务就扩，没任务就缩）；
  - `pool_overview()`：池子负载/容量全貌（二级信息）。
"""
import math

from data import admin, db
from gid import gen


# 每个池子的「任务 → 并发 agent」映射参数（可按环境覆盖）
# 一个 agent 处理多个任务时共享，积压越多并行度越高
BASE_AGENT_PER_POOL = 1          # 每个池子至少 1 个 agent（池子存在即有 1 个常驻）
TASKS_PER_AGENT = 2              # 每个 agent 默认同时负责 2 个任务（超出则扩容）
MAX_AGENT_PER_POOL = 512         # 单池上限（防失控）；2500 全局上限靠多池 + 全局总控


def _pool_id(domain):
    """某功能域池子的稳定全局唯一 id（同一域同一池，不漂移）。"""
    from data import admin as a
    gid, _ = a.register_gid("pool", f"domain:{domain}")
    return gid


def _agent_id_for_task(domain, task_id):
    """为某任务派一个全局唯一 agent（同一任务二次触发拿同一 agent，不漂移）。"""
    from data import admin as a
    gid, _ = a.register_gid("agent", f"task:{task_id}")
    return gid


def _current_pool_capacity(pool_id):
    p = admin.get_pool(pool_id)
    return p["capacity"] if p else 0


def assign_to_pool(domain, task_id, weight=1):
    """把一个任务投入某功能域任务池，并按负载自动扩容。

    返回 { pool_id, domain, task_id, agent_id, capacity, action }。
    """
    pool_id = _pool_id(domain)
    # 确保池存在
    existing = admin.get_pool(pool_id)
    if existing is None:
        admin.upsert_pool(pool_id, domain, capacity=BASE_AGENT_PER_POOL, load=0)
    # 为任务派全局唯一 agent
    agent_id = _agent_id_for_task(domain, task_id)
    # 登记 agent 档案（挂到该池）
    admin.register_agent(agent_id, role="架构·开发", group_id=pool_id,
                         status="in_progress",
                         spec={"domain": domain, "task": task_id})
    # 登记任务（assignee=该 agent，stable gid）
    admin.assign_task(task_id, title=f"[{domain}] {task_id}", assignee=agent_id,
                      status="in_progress", detail={"domain": domain})
    # 按负载扩容
    action = _autoscale(pool_id)
    return {
        "pool_id": pool_id,
        "domain": domain,
        "task_id": task_id,
        "agent_id": agent_id,
        "capacity": _current_pool_capacity(pool_id),
        "action": action,
    }


def _autoscale(pool_id):
    """根据池内未完成任务量自动扩容/缩容并发 agent 数（有任务就扩，没任务就缩）。"""
    p = admin.get_pool(pool_id)
    if p is None:
        return "no_pool"
    # 负载 = 任务表里 assignee 属于该池 agent 的未完成任务数
    from data import repository as repo
    agents = repo.active_agents("in_progress")
    pool_agents = [a for a in agents if a["group_id"] == pool_id]
    pending = 0
    for a in pool_agents:
        pending += len([t for t in repo.list_tasks(status="in_progress")
                        if t["assignee"] == a["agent_id"]])
    # 期望容量：每个 agent 处理 TASKS_PER_AGENT 个任务
    need = max(BASE_AGENT_PER_POOL, int(math.ceil(pending / TASKS_PER_AGENT)))
    need = min(need, MAX_AGENT_PER_POOL)
    cur = _current_pool_capacity(pool_id)
    if need != cur:
        admin.resize_pool(pool_id, need)
        return f"resized:{cur}->{need}"
    return "no_change"


def scale_pools():
    """扫描全部池子，按当前负载自动扩容/缩容。返回各池动作。"""
    out = []
    for p in admin.list_pools(status="active"):
        action = _autoscale(p["pool_id"])
        out.append({"pool_id": p["pool_id"], "domain": p["domain"], "action": action})
    return out


def pool_overview():
    """功能域任务池全貌（二级信息）。"""
    return admin.pool_overview()
