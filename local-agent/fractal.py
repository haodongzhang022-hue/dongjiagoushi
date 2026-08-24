# -*- coding: utf-8 -*-
"""
本地 Agent · 分形团队扩展引擎（fractal）
===========================================
核心目标：让「开发」环节可按项目规模**分形扩展**为多个小组并行，
并统一「小组长整合 → 向上交付」的汇聚规则。

设计背景（对齐用户诉求）：
  - 项目可大可小，开发不应永远只有单点串行；
  - 大规模项目可拆分为多个**小组（team）**，每个小组内部：
        小组长拆子任务 → 多个「架构·开发」并行实现 → 小组长测试/整合 → 小组向上交付；
  - 每个小组是**可递归**的：小组内若仍过大，可再次分形出子小组（分形扩展）；
  - 分形后各小组可并行，最终统一汇聚到「架构·小组长」整合、测试、统一向上交付。

引擎职责：
  1. 根据项目规模（任务数/复杂度/估算）计算需要分形出的小组数；
  2. 对每个小组递归构建子 DAG（小组长 + 多开发 + 整合）；
  3. 把分形结果注入主 DAG 的对应节点，供 DAG 引擎并行调度。

规模启发式（默认，可被显式覆盖）：
  - 任务数 < 阈值（如 3）    → 1 个小组（不分形）；
  - 任务数中（3~8）          → 2 个小组；
  - 任务数大（>8）           → 按每小组最多 n 个任务切分。
"""

# 分形默认参数
DEFAULT_MAX_PER_TEAM = 4   # 每个小组最多承载的子任务数
DEFAULT_MIN_TASKS_FOR_FORK = 3  # 达到该任务数才允许分形


def estimate_team_count(n_tasks, max_per_team=DEFAULT_MAX_PER_TEAM,
                        min_tasks=DEFAULT_MIN_TASKS_FOR_FORK):
    """根据任务数估算小组数（≥1）。

    返回 (team_count, tasks_per_team)。
    """
    if n_tasks < min_tasks or max_per_team <= 0:
        return 1, n_tasks
    team_count = (n_tasks + max_per_team - 1) // max_per_team
    tasks_per_team = (n_tasks + team_count - 1) // team_count
    return team_count, tasks_per_team


def partition_tasks(task_ids, team_count):
    """把任务 id 列表均分到 team_count 个小组，返回 list[list[id]]。"""
    teams = [[] for _ in range(team_count)]
    for i, tid in enumerate(task_ids):
        teams[i % team_count].append(tid)
    return teams


def build_fractal_plan(task_ids, max_per_team=DEFAULT_MAX_PER_TEAM,
                       min_tasks=DEFAULT_MIN_TASKS_FOR_FORK):
    """生成一个分形计划。

    参数：
      task_ids: 待实现的子任务 id 列表（来自架构·经理的任务拆解）。
    返回：
      {
        "team_count": 小组数,
        "tasks_per_team": 每小组任务数（估算）,
        "teams": [ { "team_id": "team0", "tasks": [id,...] }, ... ],
        "scaled": True/False,     # 是否发生了分形
        "recurse": [ ... ]        # 预留：小组内仍过大时递归的分形计划
      }
    """
    n = len(task_ids)
    team_count, tasks_per_team = estimate_team_count(
        n, max_per_team=max_per_team, min_tasks=min_tasks
    )
    scaled = team_count > 1
    teams = partition_tasks(list(task_ids), team_count)
    plan = {
        "team_count": team_count,
        "tasks_per_team": tasks_per_team,
        "scaled": scaled,
        "teams": [
            {"team_id": f"team{i}", "tasks": t} for i, t in enumerate(teams)
        ],
        "recurse": [],
    }
    # 递归分形：若单小组任务仍过多，进一步拆（预留，避免无限递归用深度控制）
    plan["recurse"] = [
        build_fractal_plan(t["tasks"], max_per_team, min_tasks)
        for t in plan["teams"]
        if len(t["tasks"]) > max_per_team * 2
    ]
    return plan


def describe_plan(plan):
    """把分形计划渲染为人类/AI 可读的结构化文本（用于接力卡输出）。"""
    lines = [f"分形计划：{plan['team_count']} 个小组（{'已分形' if plan['scaled'] else '单组不分形'}）"]
    for t in plan["teams"]:
        lines.append(f"  - {t['team_id']}: 任务 {t['tasks']}")
    return "\n".join(lines)
