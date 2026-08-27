# -*- coding: utf-8 -*-
"""
真实任务源（Real Task Source）
==============================
用户诉求：用**现成未完成的任务**做对比测试——尤其是
  - 「架构师架构完了但还没完成分配」的任务
  - 「经理分工了但还没给到对应 Issue 和触发工作」的任务

本模块从数据层任务池 / 路由队列读取这些真实待办任务，
把它们作为对比 runner 的输入（而不仅是虚拟需求"做一个登录系统"），
让「真实开发效果对比」建立在真实未完成工作之上。

任务来源（按优先级）：
  1. 数据层 tasks 表（admin.task_overview / dispatch 表）——经理已分工但未触发/未完成的；
  2. 路由队列（dispatcher.queue）——已入队未派发/未触发的任务；
  3. 内置样例真实任务（架构完未分配、经理分工未触发两类）——数据层空时兜底。

每个任务带 `stage` 标记：
  - `architected_unassigned`  架构完、未分配（经理还没分）
  - `assigned_untriggered`    经理已分工、未触发 / 未给 Issue / 未开工
"""
import os
import sys
import json

# 允许独立 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------
# 数据层任务读取
# ------------------------------------------------------------
def _try_load_data_tasks():
    """尝试从数据层加载真实任务。数据层未初始化/无库时返回空列表。"""
    tasks = []
    try:
        from data import admin
        overview = admin.task_overview()
        # overview 结构形如 {"todo": [...], "in_progress": [...], "done": [...], ...}
        for status in ("todo", "in_progress", "blocked"):
            items = overview.get(status, []) if isinstance(overview, dict) else []
            if isinstance(items, list):
                for t in items:
                    if isinstance(t, dict):
                        tasks.append({
                            "title": t.get("title") or t.get("task_id", ""),
                            "task_id": t.get("task_id", ""),
                            "status": status,
                            "assignee": t.get("assignee", ""),
                            "stage": _infer_stage(t),
                            "source": "data",
                        })
    except Exception:
        pass
    return tasks


def _infer_stage(t):
    """推断任务阶段：有 assignee 未 done = 已分工未触发；无 assignee 未 done = 架构完未分配。"""
    status = (t.get("status") or "").lower()
    if status in ("done", "closed"):
        return "done"
    if t.get("assignee"):
        return "assigned_untriggered"
    return "architected_unassigned"


# ------------------------------------------------------------
# 内置样例真实任务（数据层空时兜底）
# ------------------------------------------------------------
# 这些任务取自本项目 AGENTS.md / ROADMAP 中已定义但尚未派发触发的工作，
# 是"真实未完成的任务"的样例，供沙盒/数据层为空时也能跑对比。
SAMPLE_TASKS = [
    {
        "title": "分形引擎按项目规模递归细分多小组开发",
        "task_id": "tpl-dispatch-fractal",
        "stage": "assigned_untriggered",
        "source": "sample",
        "status": "todo",
        "assignee": "架构·经理",
        "detail": "经理已按 DAG 分工（plan→lead→develop 分形），但未触发小组长细化与开发开工，"
                  "未生成对应小组 Issue 与接力卡。",
        "suit": "architected",
    },
    {
        "title": "市场获客分层通用基建落地（工具/数据/渠道/客服/销售 五层）",
        "task_id": "tpl-market-layer",
        "stage": "architected_unassigned",
        "source": "sample",
        "status": "todo",
        "assignee": "",
        "detail": "架构·总师已给出市场分层方案，但尚未分配对应角色执行，任务停在架构完未分配阶段。",
        "suit": "architected",
    },
    {
        "title": "审核者前置助手 3 层时点接入总师决策链路",
        "task_id": "tpl-reviewer-precursor",
        "stage": "assigned_untriggered",
        "source": "sample",
        "status": "todo",
        "assignee": "架构·审核前置助手",
        "detail": "已分工给审核者前置助手，但未触发其 L1/L2/L3 决策补全工作。",
        "suit": "architected",
    },
    {
        "title": "2500 并发池弹性伸缩（按积压任务数扩容/缩容 agent）",
        "task_id": "tpl-concurrency-pool",
        "stage": "architected_unassigned",
        "source": "sample",
        "status": "todo",
        "assignee": "",
        "detail": "架构已明确功能域任务池+按负载伸缩方案，未分配数据管理员/引擎角色落地。",
        "suit": "architected",
    },
    {
        "title": "文案/示例/文档链接补全（零散常规补全）",
        "task_id": "tpl-scattered-tidbits",
        "stage": "assigned_untriggered",
        "source": "sample",
        "status": "todo",
        "assignee": "",
        "detail": "零散常规任务：补全示例、修复笔误、完善文档链接等，无复杂架构，适合架构师确认后直接一窝蜂瓜分解决。",
        "suit": "scattered",
    },
]


def list_real_tasks(include_done=False, stage_filter=None, suit_filter=None):
    """返回真实未完成任务列表。可只取某阶段。"""
    tasks = _try_load_data_tasks()
    if not tasks:
        tasks = SAMPLE_TASKS
    if not include_done:
        tasks = [t for t in tasks if t.get("stage") != "done"]
    if stage_filter:
        tasks = [t for t in tasks if t.get("stage") == stage_filter]
    if suit_filter:
        tasks = [t for t in tasks if t.get("suit") == suit_filter]
    return tasks


def task_to_req(task):
    """把任务转换为 runner 用的需求文本（保持调度内容真实）。"""
    title = task.get("title", "")
    detail = task.get("detail", "")
    stage = task.get("stage", "")
    stage_label = {
        "architected_unassigned": "【架构完·未分配】",
        "assigned_untriggered": "【经理已分工·未触发】",
        "done": "【已完成】",
    }.get(stage, "")
    return f"{stage_label}{title}。{detail}".strip("。")


def show_tasks(stage_filter=None):
    """列出可用的真实任务（二级信息）。"""
    tasks = list_real_tasks(stage_filter=stage_filter)
    lines = []
    lines.append("📋 可用真实任务（对比测试输入）")
    lines.append(f"  共 {len(tasks)} 项")
    lines.append("")
    for i, t in enumerate(tasks, 1):
        lines.append(f"  {i}. [{t.get('stage')}] {t.get('title')} "
                     f"(task_id={t.get('task_id')}, suit={t.get('suit') or '-'}, "
                     f"assignee={t.get('assignee') or '未分配'})")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="列出真实未完成任务")
    parser.add_argument("--stage", default=None,
                        help="过滤：architected_unassigned / assigned_untriggered")
    args = parser.parse_args()
    print(show_tasks(args.stage))
