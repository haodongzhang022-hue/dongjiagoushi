# -*- coding: utf-8 -*-
"""
任务调度与交付编排（ops）
=========================
把「任务驱动的并发扩展 + 全局唯一 ID + 任务拆分/加派 + 任务 1-3 PR（各按独立
Issue）」整合为可执行的高层编排，供 架构·经理 / 架构·小组长 / 架构·开发 等角色使用。

覆盖用户本轮四项关键诉求：
  ① 任务驱动并发：任务进功能域池子，按负载扩容 agent（非直接 2500）→ pool 模块；
  ② 全局唯一 ID：agent/任务/PR/Issue 全部全局唯一、稳定寻址、二次触发同一实体 → gid 模块；
  ③ 任务拆分/加派：任务过大初始拆分，或开发中发现过大申报小组长加派 agent 负责分支，
     分支产出汇总回小组长整合 → admin.add_split / aggregate_split；
  ④ 每个角色任务 1-3 PR：每个 PR 按独立 Issue 处理；对已有 PR 的修改再提交不新增 Issue
     （kind=amend）→ admin.add_task_pr / amend_task_pr。
"""
from data import admin
from gid import register


MAX_PR_PER_TASK = 3   # 每个任务最多 1-3 个 PR


# ---------- ① 任务驱动的并发扩展（功能域任务池） ----------
def enqueue_task(domain, task_id, title="", weight=1):
    """把任务投入某功能域任务池，并派一个全局唯一 agent 负责。

    返回 { pool_id, agent_id, task_id, capacity, action }。
    """
    from pool import assign_to_pool
    res = assign_to_pool(domain, task_id, weight)
    # 任务标题登记（gid 稳定）
    admin.assign_task(task_id, title=title or f"[{domain}] {task_id}",
                      assignee=res["agent_id"], status="in_progress",
                      detail={"domain": domain})
    return res


def task_concurrency_status():
    """功能域任务池的并发负载全貌（二级信息）：各池容量/负载/是否按需扩容。"""
    from pool import pool_overview
    return pool_overview()


# ---------- ② 全局唯一 ID 精准定位（二次触发同一实体） ----------
def register_task(task_key, title=""):
    """为一个任务登记/取回同一个全局唯一 gid（同 key 二次触发拿同一 ID，不漂移）。"""
    gid, is_new = admin.register_gid("task", task_key)
    return {"task_id": gid, "is_new": is_new, "title": title}


def register_agent_for(task_key, role="架构·开发"):
    """为一个任务派/取回同一个全局唯一 agent（同一任务二次触发仍同一负责人）。"""
    gid, is_new = admin.register_gid("agent", task_key)
    admin.register_agent(gid, role=role, status="in_progress", spec={"task": task_key})
    return {"agent_id": gid, "is_new": is_new}


def locate(gid):
    """按全局唯一 gid 精准定位某实体（类型 + 业务 key），供二次触发用。"""
    return admin.registry_lookup(gid)


# ---------- ③ 任务拆分 / 加派（小组长整合） ----------
def split_task(parent_task, reason, branch_name="", submitter="架构·开发"):
    """把一个（过大的）父任务拆出一个分支，派独立 agent 负责。

    reason 说明：'initial'=初始拆分（一开始任务太大）/'found_too_big'=开发中发现过大申报。
    返回 { split_id, parent_task, branch_task, agent_id, reason }。
    """
    branch_task, _ = admin.register_gid("task", f"{parent_task}::branch::{branch_name}")
    agent_id, _ = admin.register_gid("agent", f"branch:{branch_task}")
    admin.register_agent(agent_id, role="架构·开发", status="in_progress",
                         spec={"parent_task": parent_task, "branch": branch_task})
    split_id = admin.add_split(parent_task, branch_task, agent_id,
                               reason=reason, submitter=submitter)
    return {"split_id": split_id, "parent_task": parent_task,
            "branch_task": branch_task, "agent_id": agent_id, "reason": reason}


def apply_more_agents(parent_task, reason, branch_name, submitter="架构·开发"):
    """开发中途发现任务过大：开发申报小组长 → 加派 agent 负责分支内容。"""
    return split_task(parent_task, reason="found_too_big:" + reason,
                      branch_name=branch_name, submitter=submitter)


def team_lead_aggregate(split_id):
    """小组长把某拆分分支的产出汇总整合（标记已聚合）。"""
    admin.aggregate_split(split_id)
    return split_id


def split_overview(status="open"):
    """任务拆分/加派全貌（二级信息）。"""
    return admin.split_overview(status)


# ---------- ④ 任务 1-3 PR（各按独立 Issue） ----------
def submit_pr(task_id, agent_id, title=""):
    """为一个任务提交一个 PR（每个任务最多 1-3 个，各按独立 Issue 处理）。

    若该任务已达 3 个新 PR，抛异常（除非对已有 PR 的修改再提交走 amend_pr）。
    返回 { pr_id, issue_id, seq, kind }。
    """
    prs = admin.prs_for_task(task_id, status="open")
    new_count = sum(1 for p in prs if p["kind"] == "new")
    if new_count >= MAX_PR_PER_TASK:
        raise ValueError(
            f"任务 {task_id} 已提交 {new_count} 个新 PR（上限 {MAX_PR_PER_TASK}）。"
            f"若为对已有 PR 的修改，请用 amend_pr（不新增独立 Issue）。"
        )
    seq = new_count + 1
    pr_id, issue_id = admin.add_task_pr(task_id, agent_id, seq=seq, kind="new")
    return {"pr_id": pr_id, "issue_id": issue_id, "seq": seq, "kind": "new"}


def amend_pr(task_id, agent_id, seq):
    """对某任务第 seq 个已有 PR 的修改再提交（不新增独立 Issue，复用原 Issue）。"""
    target = admin.amend_task_pr(task_id, agent_id, seq)
    return {"pr_id": target["pr_id"], "issue_id": target["issue_id"],
            "seq": seq, "kind": "amend"}


def task_prs(task_id, status=None):
    """某任务的全部 PR 记录（含每个 PR 的独立 Issue id）。"""
    return admin.prs_for_task(task_id, status)


def agent_prs(agent_id, status=None):
    """某 agent（按全局唯一 id）提交的全部 PR（精准定位该 agent 工作）。"""
    return admin.prs_for_agent(agent_id, status)
