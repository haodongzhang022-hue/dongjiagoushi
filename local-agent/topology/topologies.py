# -*- coding: utf-8 -*-
"""
拓扑线路定义（Topology Definitions）
====================================
定义可对比的不同协作拓扑线路，供 comparative runner 在真实开发场景下
执行同一任务、收集指标、做长期对比判断。

当前对比线路（3 条）：
  - `linear`:  直线串行拓扑（基线，最早版本）
  - `dag`:     有向无环图拓扑（并行波次，当前生产拓扑）
  - `event`:   事件驱动拓扑（新增线路，弹性路由）

每条线路的核心差异在于「节点依赖关系 + 调度策略」不同，
同一需求跑完各条线路后，收集指标进行对比。
"""

# ------------------------------------------------------------
# 线路 1：直线串行（linear）
# 特点：所有步骤严格串行，前一步完成才能进入下一步。
# 适用：小任务、依赖极其明确的场景。
# ------------------------------------------------------------
LINEAR_NODES = [
    {"id": "secretary",  "role": "架构·秘书",   "action": "默认入口/诉求接收/路由",          "depends_on": []},
    {"id": "clarify",    "role": "架构·产品",   "action": "需求澄清/翻译意图/拆需求",        "depends_on": ["secretary"]},
    {"id": "architect",  "role": "架构·总师",   "action": "架构设计/确认版本/校验",          "depends_on": ["clarify"]},
    {"id": "plan",       "role": "架构·经理",   "action": "任务拆解/角色分配/排期",          "depends_on": ["architect"]},
    {"id": "lead",       "role": "架构·小组长", "action": "子任务细化/协调推进",             "depends_on": ["plan"]},
    {"id": "find_tools", "role": "架构·找工具", "action": "检索工具/依赖清单",               "depends_on": ["lead"]},
    {"id": "develop",    "role": "架构·开发",   "action": "实现/自测",                       "depends_on": ["lead"]},
    {"id": "review",     "role": "架构·评审",   "action": "五维评审/复评",                   "depends_on": ["develop"]},
    {"id": "align",      "role": "架构·对齐",   "action": "版本对齐/一致性校验",             "depends_on": ["review"]},
    {"id": "test",       "role": "架构·测试",   "action": "测试矩阵/信号灯",                 "depends_on": ["align"]},
    {"id": "deliver",    "role": "编排引擎",    "action": "汇总交付报告",                    "depends_on": ["test"]},
]

# ------------------------------------------------------------
# 线路 2：DAG 并行（dag）
# 特点：依赖满足即并行，plan 只依赖 architect 可提前分工。
# 当前生产拓扑。支持分形扩展。
# ------------------------------------------------------------
DAG_NODES = [
    {"id": "secretary",  "role": "架构·秘书",   "action": "默认入口/诉求接收/路由",              "depends_on": []},
    {"id": "clarify",    "role": "架构·产品",   "action": "需求澄清/翻译意图/拆需求",            "depends_on": ["secretary"]},
    {"id": "architect",  "role": "架构·总师",   "action": "架构设计/确认版本/校验",              "depends_on": ["clarify"]},
    # plan 只依赖 architect，提前分工
    {"id": "plan",       "role": "架构·经理",   "action": "任务拆解/角色分配/排期",              "depends_on": ["architect"]},
    # plan 之后三个环节可并行
    {"id": "lead",       "role": "架构·小组长", "action": "子任务细化/协调推进/分形整合",         "depends_on": ["plan"]},
    {"id": "find_tools", "role": "架构·找工具", "action": "检索工具/依赖清单",                    "depends_on": ["plan"]},
    {"id": "align",      "role": "架构·对齐",   "action": "版本对齐/一致性校验",                 "depends_on": ["plan"]},
    # 实现
    {"id": "develop",    "role": "架构·开发",   "action": "实现/自测（可分形多小组）",            "depends_on": ["lead"], "fractal": {"enabled": True, "max_per_team": 4}},
    # 质量
    {"id": "review",     "role": "架构·评审",   "action": "五维评审/复评",                       "depends_on": ["develop"]},
    {"id": "test",       "role": "架构·测试",   "action": "测试矩阵/信号灯",                     "depends_on": ["review", "align"]},
    # 交付
    {"id": "deliver",    "role": "编排引擎",    "action": "汇总交付报告",                        "depends_on": ["test"]},
]

# ------------------------------------------------------------
# 线路 3：事件驱动（event）
# 特点：没有固定的前置依赖链，每个节点按"触发事件"独立响应。
#      核心差异在于**部分产出即启动下游**——不需要等待上游完全完成，
#      只要上游发出"有进展了"的事件即可触发下游。
# 优势：
#   - 架构师只需产品给出需求草案即可开始（不用等完全澄清）；
#   - 经理只需架构师给出方案草案即可分工（不用等完整方案）；
#   - 开发只需小组长给出任务细化即可开工（不用等全部细化完）。
# 风险：部分信息可能导致返工（用回转指标捕捉）。
# ------------------------------------------------------------
EVENT_NODES = [
    # 入口：收到用户请求即触发
    {"id": "secretary",  "role": "架构·秘书",   "action": "入口事件接收/意图翻译/路由",
     "depends_on": [], "trigger": "user_request"},

    # 产品：收到 secretary 路由事件后开始澄清
    {"id": "clarify",    "role": "架构·产品",   "action": "需求澄清/翻译意图/拆需求",
     "depends_on": [], "trigger": "secretary:routed"},

    # 架构：产品给出"初步需求"事件即可开始（不用等完全澄清完）
    #   —— 比 DAG 更快：DAG 要等 clarify 完全完成
    {"id": "architect",  "role": "架构·总师",   "action": "架构设计/确认版本/校验",
     "depends_on": [], "trigger": "clarify:initial"},

    # 经理：架构给出"初步方案"事件即可分工
    #   —— 比 DAG 更快：DAG 要等 architect 完全完成
    {"id": "plan",       "role": "架构·经理",   "action": "任务拆解/角色分配/排期",
     "depends_on": [], "trigger": "architect:initial"},

    # 小组长/找工具/对齐：经理分工后并行启动
    {"id": "lead",       "role": "架构·小组长", "action": "子任务细化/协调推进",
     "depends_on": [], "trigger": "plan:assigned"},
    {"id": "find_tools", "role": "架构·找工具", "action": "检索工具/依赖清单",
     "depends_on": [], "trigger": "plan:assigned"},
    {"id": "align",      "role": "架构·对齐",   "action": "版本对齐/一致性校验",
     "depends_on": [], "trigger": "plan:assigned"},

    # 开发：小组长给出初步任务分解即可开工（不用等细化完全完成）
    {"id": "develop",    "role": "架构·开发",   "action": "实现/自测",
     "depends_on": [], "trigger": "lead:initial"},

    # 评审：开发有初步产出即可评审
    {"id": "review",     "role": "架构·评审",   "action": "五维评审/复评",
     "depends_on": [], "trigger": "develop:output_ready"},

    # 测试：评审通过 + 版本对齐后触发
    {"id": "test",       "role": "架构·测试",   "action": "测试矩阵/信号灯",
     "depends_on": [], "trigger": "review:passed + align:done"},

    # 交付：测试通过后交付
    {"id": "deliver",    "role": "编排引擎",    "action": "汇总交付报告",
     "depends_on": [], "trigger": "test:passed"},
]


# ------------------------------------------------------------
# 拓扑注册表
# ------------------------------------------------------------
TOPOLOGIES = {
    "linear": {
        "name": "直线串行",
        "description": "严格串行，前一步完成才能进入下一步。基线拓扑。",
        "nodes": LINEAR_NODES,
        "strategy": "linear",
    },
    "dag": {
        "name": "DAG 并行",
        "description": "依赖满足即并行，提前分工。当前生产拓扑。",
        "nodes": DAG_NODES,
        "strategy": "dag",
    },
    "event": {
        "name": "事件驱动",
        "description": "事件触发，部分产出即启动下游，最大化并行。",
        "nodes": EVENT_NODES,
        "strategy": "event",
    },
}


def list_topologies():
    """列出全部可对比拓扑。"""
    result = []
    for tid, t in TOPOLOGIES.items():
        result.append({
            "id": tid,
            "name": t["name"],
            "description": t["description"],
            "node_count": len(t["nodes"]),
            "strategy": t["strategy"],
        })
    return result


def get_topology(tid):
    """获取指定拓扑。"""
    if tid not in TOPOLOGIES:
        raise ValueError(f"未知拓扑：{tid}，可选：{list(TOPOLOGIES.keys())}")
    return TOPOLOGIES[tid]
