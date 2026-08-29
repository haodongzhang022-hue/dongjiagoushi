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

开发增强配比（Issue #74 · Dev-Ratio，本版新增）：
  - 用户痛点：辅助角色（秘书/产品/总师/经理/评审/测试/对齐/找工具）过多，
    开发才是真正持续推进度的，辅助多则浪费、进度慢。
  - 核心机制：给每个分形小组可配置的「开发实例数」`devs_per_team`，
    让一套小组内配 N 个开发并行实现（默认 2，即"一套循环 2 个开发"），
    小组长只做拆解/整合，不占开发名额；评审/测试/对齐抽到小组外作质量闸门。
  - 量化俯瞰：`dev_ratio()` 计算小组内开发密度，辅助角色过多时直观暴露浪费。

规模启发式（默认，可被显式覆盖）：
  - 任务数 < 阈值（如 3）    → 1 个小组（不分形）；
  - 任务数中（3~8）          → 2 个小组；
  - 任务数大（>8）           → 按每小组最多 n 个任务切分。
"""

# 分形默认参数
DEFAULT_MAX_PER_TEAM = 4   # 每个小组最多承载的子任务数
DEFAULT_MIN_TASKS_FOR_FORK = 3  # 达到该任务数才允许分形
DEFAULT_DEVS_PER_TEAM = 2  # ★ Issue #74：每个小组默认配 2 个开发（"一套循环 2 个开发"）


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
                       min_tasks=DEFAULT_MIN_TASKS_FOR_FORK,
                       devs_per_team=DEFAULT_DEVS_PER_TEAM):
    """生成一个分形计划。

    参数：
      task_ids: 待实现的子任务 id 列表（来自架构·经理的任务拆解）。
      devs_per_team: ★ Issue #74 每个小组配的开发实例数（默认 2）。
        小组结构深化：一个小组 = 小组长(拆解/整合) + devs_per_team 个开发(并行实现)，
        辅助质量闸门(评审/测试/对齐)在小组外，不占小组内开发名额。
    返回：
      {
        "team_count": 小组数,
        "tasks_per_team": 每小组任务数（估算）,
        "devs_per_team": 每小组开发实例数,
        "teams": [ { "team_id": "team0", "tasks": [...], "devs": [dev0,dev1,...] }, ... ],
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
    # ★ Issue #74：每个小组携带开发实例列表（"一套循环 devs_per_team 个开发"）
    devs_per_team = max(1, int(devs_per_team))
    plan = {
        "team_count": team_count,
        "tasks_per_team": tasks_per_team,
        "devs_per_team": devs_per_team,
        "scaled": scaled,
        "teams": [
            {
                "team_id": f"team{i}",
                "tasks": t,
                "devs": [f"dev{i}_{j}" for j in range(devs_per_team)],
            }
            for i, t in enumerate(teams)
        ],
        "recurse": [],
    }
    # 递归分形：若单小组任务仍过多，进一步拆（预留，避免无限递归用深度控制）
    plan["recurse"] = [
        build_fractal_plan(t["tasks"], max_per_team, min_tasks, devs_per_team)
        for t in plan["teams"]
        if len(t["tasks"]) > max_per_team * 2
    ]
    return plan


def dev_ratio(plan, include_lead=True):
    """★ Issue #74：量化开发密度（开发占小组内实干角色的比例）。

    小组内实干角色 = 开发实例 + 小组长（拆解/整合也算推进实干的辅助）；
    dev_ratio = devs_per_team / (devs_per_team + 小组长数)
    用于俯瞰"开发到底占多少"——辅助(评审/测试/对齐)在小组外时天然不算进来。

    返回 { "devs": 总开发数, "leads": 小组长数, "ratio": 开发密度(0~1) }
    """
    n_teams = max(1, plan.get("team_count", 1))
    devs = plan.get("devs_per_team", DEFAULT_DEVS_PER_TEAM) * n_teams
    leads = n_teams if include_lead else 0
    total = devs + leads
    return {
        "devs": devs,
        "leads": leads,
        "ratio": round(devs / total, 2) if total > 0 else 0.0,
    }


def describe_plan(plan):
    """把分形计划渲染为人类/AI 可读的结构化文本（用于接力卡输出）。"""
    devs_per_team = plan.get("devs_per_team", DEFAULT_DEVS_PER_TEAM)
    lines = [
        f"分形计划：{plan['team_count']} 个小组（{'已分形' if plan['scaled'] else '单组不分形'}）"
        f" · 每小组 {devs_per_team} 个开发（一套循环 {devs_per_team} 个开发）"
    ]
    for t in plan["teams"]:
        devs = " + ".join(t["devs"]) if t.get("devs") else f"dev×{devs_per_team}"
        lines.append(f"  - {t['team_id']}: 任务 {t['tasks']} | 开发 {devs} | 小组长整合")
    d = dev_ratio(plan)
    lines.append(f"  · 开发密度（Dev-Ratio）：{d['devs']} 开发 / {d['devs'] + d['leads']} 实干角色 = {d['ratio']:.0%}")
    return "\n".join(lines)
