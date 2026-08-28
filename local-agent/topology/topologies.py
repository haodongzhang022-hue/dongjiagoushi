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
# 线路 7：开发增强·双开发小组（dev_enhanced）★ Issue #74
# ------------------------------------------------------------
# 用户核心诉求（Issue #74）：
#   "把一套4个的当一个开发小组……开发才是里面真正持续推进度的，不然进度没多少，
#    辅助很多就浪费了……研究是否调整比例，一套循环里面2个开发，继续研究深化结构的升级。"
#
# 痛点：辅助角色（秘书/产品/总师/经理/评审/测试/对齐/找工具）包围开发，
#       开发才是推进度核心，但占比不足 → 辅助多则浪费、进度慢。
#
# 本拓扑是"开发增强配比（Dev-Ratio）"的落地：
#   - 小组内结构深化：一个开发小组 = 1 小组长(拆解/整合) + N 个开发(并行实现)，
#     默认 N=2（"一套循环 2 个开发"）；
#   - 辅助角色精简：评审/测试作为小组外质量闸门（不挤占小组内开发名额），
#     去掉秘书/经理/对齐/找工具等冗余辅助（前端只留产品+总师把关）；
#   - 开发是实干主力：推进度靠开发，辅助只做必要质量兜底，不堆角色。
# 适用：medium/large 档（中等~高复杂度，需多开发并行推进 + 质量兜底）。
# ------------------------------------------------------------
DEV_ENHANCED_NODES = [
    # ── 前端：产品澄清 + 总师把关（辅助精简到必要）──
    {"id": "product",   "role": "架构·产品", "action": "需求澄清/翻译意图/拆需求", "depends_on": [], "phase": "intake"},
    {"id": "architect", "role": "架构·总师", "action": "架构设计/确认版本/校验", "depends_on": ["product"], "phase": "intake"},
    # ── 开发核心：一套循环 N 个开发（默认 2）＋ 小组长拆解/整合 ──
    {"id": "lead",      "role": "架构·小组长", "action": "任务细化/拆解（小组内 2 开发并行实现）", "depends_on": ["architect"], "phase": "implement"},
    {"id": "dev_1",     "role": "架构·开发", "action": "实现/自测（开发 A，一套循环第 1 个）", "depends_on": ["lead"], "phase": "implement", "share": "ctx"},
    {"id": "dev_2",     "role": "架构·开发", "action": "实现/自测（开发 B，一套循环第 2 个）", "depends_on": ["lead"], "phase": "implement", "share": "ctx"},
    # ── 质量闸门（小组外，不占开发名额）──
    {"id": "review",    "role": "架构·评审", "action": "五维评审/复评", "depends_on": ["dev_1","dev_2"], "phase": "quality"},
    {"id": "test",      "role": "架构·测试", "action": "测试矩阵/信号灯", "depends_on": ["review"], "phase": "quality"},
    # ── 交付 ──
    {"id": "deliver",   "role": "编排引擎",  "action": "汇总交付报告", "depends_on": ["test"], "phase": "deliver"},
]

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


# ------------------------------------------------------------
# 线路 4：混合调度·中央调控（hybrid）
# 特点：用户方案核心——不再依赖"提前开工+返工"，
#      而是「前段中央调控 + 后段外部抢单」两段式：
#   - 前段（中央调控）：架构化任务仍走既有方式——秘书→产品澄清→架构设计→经理预先分工。
#     企业"内部"先吃核心/高价值部分，不提前开工、不靠返工。
#   - 后段（一窝蜂抢单）：架构确定 + 预先分工后，**余下的子任务像"外部抢单"一样
#     一窝蜂并行解决和补全**——没有先后依赖，全部同时开工、各自完成。
# 优势：既保留架构的质量兜底（前段可控），又最大化末段并行度（后段瓜分补全），
#      任务规模越大、子任务越多，抢单并行优势越明显。
# 适用：架构化任务（有复杂架构 / 需中央统一调控的项目）。
# ------------------------------------------------------------
HYBRID_NODES = [
    # ── 前段：中央调控（保持既有方式，不提前开工）──
    {"id": "secretary",  "role": "架构·秘书", "action": "入口/诉求接收/路由", "depends_on": [], "phase": "central"},
    {"id": "clarify",    "role": "架构·产品", "action": "需求澄清/翻译意图/拆需求", "depends_on": ["secretary"], "phase": "central"},
    {"id": "architect",  "role": "架构·总师", "action": "架构设计/确认版本/校验", "depends_on": ["clarify"], "phase": "central"},
    {"id": "plan",       "role": "架构·经理", "action": "任务拆解/预先分工/定核心vs余量", "depends_on": ["architect"], "phase": "central"},
    # 企业"内部"先吃核心/高价值部分（内部消化，不走抢单）
    {"id": "core_lead",  "role": "架构·小组长", "action": "核心部分细化/内部消化", "depends_on": ["plan"], "phase": "central"},
    {"id": "core_dev",   "role": "架构·开发",  "action": "核心模块实现/自测（内部）", "depends_on": ["core_lead"], "phase": "central"},

    # ── 后段：一窝蜂抢单（余下子任务瓜分补全，全部并行）──
    # 预先分工后，余下子任务像"外部抢单"一样同时丢出去，全部并行开工、各自补全
    {"id": "scramble_1", "role": "架构·开发", "action": "【抢单】余量子任务 A 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_2", "role": "架构·开发", "action": "【抢单】余量子任务 B 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_3", "role": "架构·开发", "action": "【抢单】余量子任务 C 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_4", "role": "架构·开发", "action": "【抢单】余量子任务 D 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_5", "role": "架构·开发", "action": "【抢单】余量子任务 E 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_6", "role": "架构·开发", "action": "【抢单】余量子任务 F 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_7", "role": "架构·开发", "action": "【抢单】余量子任务 G 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},
    {"id": "scramble_8", "role": "架构·开发", "action": "【抢单】余量子任务 H 一窝蜂解决", "depends_on": ["plan"], "phase": "scramble"},

    # 质量与交付：抢单全部完成后统一收口
    {"id": "review",  "role": "架构·评审", "action": "五维评审/复评", "depends_on": ["core_dev", "scramble_1", "scramble_2", "scramble_3", "scramble_4", "scramble_5", "scramble_6", "scramble_7", "scramble_8"], "phase": "quality"},
    {"id": "test",    "role": "架构·测试", "action": "测试矩阵/信号灯", "depends_on": ["review"], "phase": "quality"},
    {"id": "deliver", "role": "编排引擎",  "action": "汇总交付报告", "depends_on": ["test"], "phase": "quality"},
]

# ------------------------------------------------------------
# 线路 5：零散·一窝蜂（scatter）
# 特点：**无复杂架构**的常规零散任务专用——架构师快速确认"没什么复杂架构，适合一窝蜂解决"，
#      就直接往下丢，所有子任务一窝蜂并行解决和补全。
# 无前段中央调控（不设 architect/plan 深度设计），仅保留轻量确认 + 全量并行瓜分。
# 适用：零散任务（无架构依赖 / 常规补全 / 小修小补）。
# ------------------------------------------------------------
SCATTER_NODES = [
    # 轻量入口 + 架构师确认"无复杂架构"
    {"id": "secretary",  "role": "架构·秘书", "action": "入口/诉求接收/路由", "depends_on": [], "phase": "confirm"},
    {"id": "architect",  "role": "架构·总师", "action": "快速确认无复杂架构→直接丢", "depends_on": ["secretary"], "phase": "confirm"},
    # 一窝蜂：全部子任务并行解决和补全（无依赖）
    {"id": "scatter_1", "role": "架构·开发", "action": "零散子任务 1 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_2", "role": "架构·开发", "action": "零散子任务 2 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_3", "role": "架构·开发", "action": "零散子任务 3 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_4", "role": "架构·开发", "action": "零散子任务 4 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_5", "role": "架构·开发", "action": "零散子任务 5 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_6", "role": "架构·开发", "action": "零散子任务 6 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_7", "role": "架构·开发", "action": "零散子任务 7 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_8", "role": "架构·开发", "action": "零散子任务 8 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_9", "role": "架构·开发", "action": "零散子任务 9 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    {"id": "scatter_10","role": "架构·开发", "action": "零散子任务 10 一窝蜂解决", "depends_on": ["architect"], "phase": "swarm"},
    # 统一收口
    {"id": "review",  "role": "架构·评审", "action": "五维评审/复评", "depends_on": ["scatter_1","scatter_2","scatter_3","scatter_4","scatter_5","scatter_6","scatter_7","scatter_8","scatter_9","scatter_10"], "phase": "quality"},
    {"id": "test",    "role": "架构·测试", "action": "测试矩阵/信号灯", "depends_on": ["review"], "phase": "quality"},
    {"id": "deliver", "role": "编排引擎",  "action": "汇总交付报告", "depends_on": ["test"], "phase": "quality"},
]


# ------------------------------------------------------------

# ------------------------------------------------------------
# 线路 5.5：敏捷承接·极简体系（agile）★ 最高频任务专用
# ------------------------------------------------------------
# 用户 Issue #41 纠偏核心："小任务其实占比最高，这个才最适合体系承接，但需要
#   简化的体系，类似于只剩下产品和开发，审查了，复杂度低的基本就是敏捷开发。"
#   最小任务（单任务修改 / 单个开发即可完成）占所有任务比例最高，最该精雕细琢。
#
# 本拓扑就是"简化体系（敏捷开发）"的落地：**只保留 产品→开发→审查 三个最小角色**，
#   去掉秘书/架构/经理/小组长/找工具/对齐/测试等重型角色 —— 不为高频小任务
#   背载完整公司流程（防过度设计）。流程：
#     product  需求澄清/翻译意图/确认修改点（单点，微任务仅此一步接手）
#     develop  实现/自测（单开发即可完成的修改）
#     review   轻量审查（质量兜底，不引入重型五维/测试矩阵）
#   缓存命中为主线：product→develop→review 共享需求前缀，前缀只构造一次，
#   后续节点命中缓存只付增量 token —— 小任务虽小，也要复用共享上下文（cache-first）。
# 适用：micro / small 档（单任务修改、低复杂度敏捷开发）。
# ------------------------------------------------------------
AGILE_NODES = [
    # ① 产品（接手 + 澄清 + 确认修改点）——单开发任务的极简接手层
    {"id": "product",   "role": "架构·产品", "action": "需求澄清/翻译意图/确认修改点", "depends_on": [], "phase": "intake", "share": "ctx"},
    # ② 开发（单开发即可完成的修改/实现 + 自测）——占比最高的最小执行单元
    {"id": "develop",   "role": "架构·开发", "action": "实现/自测（单开发完成的修改）", "depends_on": ["product"], "phase": "implement", "share": "ctx"},
    # ③ 审查（轻量质量兜底，不引入重型五维/测试矩阵）
    {"id": "review",    "role": "架构·评审", "action": "轻量审查/复评（小任务快速验收）", "depends_on": ["develop"], "phase": "review", "share": "ctx"},
    # 交付（编排引擎收口）
    {"id": "deliver",   "role": "编排引擎",  "action": "汇总交付报告", "depends_on": ["review"], "phase": "deliver"},
]

# 线路 6：前缀缓存·水龙头蔓延（prefix）
# 特点：用户 Issue #41 优化核心——把「一盘散沙争抢」改造成「有序快领」。
#      共享提示词前缀聚合为集群，以**缓存命中为索引**：
#        - 同一集群内节点共享前缀，前缀只构造一次（首节点付全量），
#          后续节点命中缓存只付增量差异 token —— 形成"水龙头持续往下蔓延"；
#        - 不同集群间无共享前缀，天然并行。
#      对比对象：scramble（散沙·全并行·每节点独立携带完整前缀）的**优化版**。
# 适用：架构化任务的余下一窝蜂抢单 / 零散一窝蜂 —— 用缓存前缀复用替代各自重构造。
# ------------------------------------------------------------
PREFIX_NODES = [
    # ── 前段中央调控（与 hybrid 相同：架构→分工，企业内先吃核心）──
    {"id": "secretary",  "role": "架构·秘书", "action": "入口/诉求接收/路由", "depends_on": [], "phase": "central"},
    {"id": "clarify",    "role": "架构·产品", "action": "需求澄清/翻译意图/拆需求", "depends_on": ["secretary"], "phase": "central"},
    {"id": "architect",  "role": "架构·总师", "action": "架构设计/确认版本/校验", "depends_on": ["clarify"], "phase": "central"},
    {"id": "plan",       "role": "架构·经理", "action": "任务拆解/预先分工/定核心vs余量", "depends_on": ["architect"], "phase": "central"},
    {"id": "core_lead",  "role": "架构·小组长", "action": "核心部分细化/内部消化", "depends_on": ["plan"], "phase": "central"},
    {"id": "core_dev",   "role": "架构·开发",  "action": "核心模块实现/自测（内部）", "depends_on": ["core_lead"], "phase": "central"},

    # ── 后段：前缀缓存·水龙头蔓延（替代散沙抢单）──
    # 同一 role 的抢单节点共享同一前缀，前缀只构造一次，后续节点命中缓存增量蔓延
    {"id": "prefix_1", "role": "架构·开发", "action": "【水龙头】余量子任务 A 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_2", "role": "架构·开发", "action": "【水龙头】余量子任务 B 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_3", "role": "架构·开发", "action": "【水龙头】余量子任务 C 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_4", "role": "架构·开发", "action": "【水龙头】余量子任务 D 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_5", "role": "架构·开发", "action": "【水龙头】余量子任务 E 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_6", "role": "架构·开发", "action": "【水龙头】余量子任务 F 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_7", "role": "架构·开发", "action": "【水龙头】余量子任务 G 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},
    {"id": "prefix_8", "role": "架构·开发", "action": "【水龙头】余量子任务 H 增量蔓延", "depends_on": ["plan"], "phase": "faucet", "share": "dev"},

    # ── 质量与交付：统一收口（与 hybrid 相同）──
    {"id": "review",  "role": "架构·评审", "action": "五维评审/复评", "depends_on": ["core_dev","prefix_1","prefix_2","prefix_3","prefix_4","prefix_5","prefix_6","prefix_7","prefix_8"], "phase": "quality"},
    {"id": "test",    "role": "架构·测试", "action": "测试矩阵/信号灯", "depends_on": ["review"], "phase": "quality"},
    {"id": "deliver", "role": "编排引擎",  "action": "汇总交付报告", "depends_on": ["test"], "phase": "quality"},
]

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
    "hybrid": {
        "name": "混合调度·中央调控",
        "description": "架构化任务：前段中央调控（架构→分工，内部先吃核心）＋后段余下一窝蜂抢单补全。",
        "nodes": HYBRID_NODES,
        "strategy": "hybrid",
        "suitable": "architected",
    },
    "scatter": {
        "name": "零散·一窝蜂",
        "description": "零散任务：架构师确认无复杂架构后，直接往下丢，全部子任务一窝蜂并行解决补全。",
        "nodes": SCATTER_NODES,
        "strategy": "scatter",
        "suitable": "scattered",
    },
    "agile": {
        "name": "敏捷承接·极简体系",
        "description": "简化体系（敏捷开发）：只保留产品→开发→审查三最小角色，去掉重型公司流程。占比最高的最小任务（单开发可完成）专用，cache-first 共享需求前缀。",
        "nodes": AGILE_NODES,
        "strategy": "agile",
        "suitable": "agile",
        "cache_first": True,
    },
    "prefix": {
        "name": "前缀缓存·水龙头蔓延",
        "description": "共享提示词前缀聚合为集群，以缓存命中为索引，前缀只构造一次、后续节点增量蔓延（替代散沙争抢，降token降bug）。",
        "nodes": PREFIX_NODES,
        "strategy": "prefix",
        "suitable": "architected",
        "optimizes": "hybrid",
    },
    "dev_enhanced": {
        "name": "开发增强·双开发小组",
        "description": "★Issue #74 开发增强配比：一个开发小组=小组长+N开发(默认2,一套循环2个开发)，开发是推进度实干主力，评审/测试作小组外质量闸门，辅助精简。",
        "nodes": DEV_ENHANCED_NODES,
        "strategy": "dev_enhanced",
        "suitable": "architected",
        "dev_ratio": 2,   # ★ 一套循环 2 个开发
        "dev_enhanced": True,
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
            "suitable": t.get("suitable", "all"),
        })
    return result


def get_topology(tid):
    """获取指定拓扑。"""
    if tid not in TOPOLOGIES:
        raise ValueError(f"未知拓扑：{tid}，可选：{list(TOPOLOGIES.keys())}")
    return TOPOLOGIES[tid]

