# -*- coding: utf-8 -*-
"""
专家级架构评判标准 · 唯一事实源（expertise.spec）
==================================================
本文件是**整个仓库**「专家级架构能力」的唯一规范来源。任何角色（总师/评审/交付）、
任何环节（调研/评审/交付门禁）都从这里读取维度、权重、阈值，**禁止各自取名、
禁止另写第二套判定**（见 AGENTS.md「唯一事实纪律」）。

设计依据（用户 2026-11 明确要求）：
  1. 「不要笼统架构师觉得全能做了」——通用架构师的能力必须建立在
     **行业/岗位专家层**（hanghangchuzhuangyuan）与**AI 发展前沿层**之上。
  2. 判断要从 **高度 / 深度 / 广度 / 资源 / 实现路径 / 帕累托最优 / 外部验证**
     七个维度做，且**外部验证**尤其指**功能性代码验证门禁**（不是"看起来对"）。
  3. 信息**有时效性**：陈旧信息不等于可信信息，必须先做时效性闸门。

七维定义与判据见 `docs/EXPERT_ARCHITECT.md`；本文件只落**机器可执行的规范**。
"""

# ---------------------------------------------------------------------------
# 一、七维证据维度（DIMENSION_SPECS · 唯一事实源）
# ---------------------------------------------------------------------------
# key        : 机器标识（落库/留痕/测试断言都用它，禁止别名）
# name       : 人可读名
# question   : 该维度必须回答的那个问题（判据以「能否回答」为准）
# required   : 是否准入必过（True = 缺失即判 inadmissible，不得放行）
# weight     : 在加权得分中的权重（和为 1.0，由 _check_weights 自检）
# evidence   : 该维度可接受的证据类型 / 形态
DIMENSION_SPECS = [
    {
        "key": "height",
        "name": "高度",
        "question": "这个方案站在什么目标层级？服务的是业务北极星还是局部需求？",
        "required": True,
        "weight": 0.15,
        "evidence": ["目标层级声明", "北极星指标", "与组织战略的对齐关系"],
    },
    {
        "key": "depth",
        "name": "深度",
        "question": "关键决策的技术纵深够不够？边界、失败模式、不变量讲清楚了吗？",
        "required": True,
        "weight": 0.15,
        "evidence": ["模块边界与依赖", "失败模式与降级", "不变量/复杂度上界"],
    },
    {
        "key": "breadth",
        "name": "广度",
        "question": "跨行业/跨岗位/跨模块的覆盖与复用考虑到了吗？",
        "required": True,
        "weight": 0.12,
        "evidence": ["行业/岗位专家层命中", "跨域复用与接口契约", "同类系统横向对照"],
    },
    {
        "key": "resource",
        "name": "资源",
        "question": "成本、人力、时间、算力这些约束被量化了吗？",
        "required": True,
        "weight": 0.12,
        "evidence": ["成本估算", "人力与工期", "算力/存储/预算上限"],
    },
    {
        "key": "path",
        "name": "实现路径",
        "question": "从现状到目标的分步路径明确吗？有里程碑和可回退点吗？",
        "required": True,
        "weight": 0.13,
        "evidence": ["阶段划分", "里程碑与验收", "回退/降级点"],
    },
    {
        "key": "pareto",
        "name": "帕累托最优",
        "question": "有没有做到备选方案的显式比较？前沿上的取舍说清楚了吗？",
        "required": True,
        "weight": 0.13,
        "evidence": ["候选方案集(>=2)", "多目标指标对比", "前沿与支配关系"],
    },
    {
        "key": "external_validation",
        "name": "外部验证",
        "question": "外部独立证据通过了吗？**功能性代码验证门禁**跑通了吗？",
        "required": True,
        "weight": 0.20,
        "evidence": ["真实测试运行结果", "外部/第三方复核", "CI 信号灯红绿"],
    },
]

# 派生索引（供其它模块 import，避免各处硬编码维度名）
DIMENSION_KEYS = tuple(d["key"] for d in DIMENSION_SPECS)
REQUIRED_DIMENSIONS = tuple(d["key"] for d in DIMENSION_SPECS if d["required"])
DIMENSION_BY_KEY = {d["key"]: d for d in DIMENSION_SPECS}

# ---------------------------------------------------------------------------
# 二、判定阈值（JUDGE_THRESHOLDS · 确定性判定，不走主观）
# ---------------------------------------------------------------------------
JUDGE_THRESHOLDS = {
    # 准入：必过维度缺失数 > 0 即 inadmissible（七维是「缺一不可」的准入门）
    "max_missing_required": 0,
    # 证据强度下限：每个维度给出 strength(0~1)，低于此值视为该维度实质缺失
    "min_evidence_strength": 0.5,
    # 加权总分分档：>=expert 判专家级专家；>=competent 合格；否则不合格
    "score_expert": 0.85,
    "score_competent": 0.70,
    # 外部验证特有：必须有**真实执行过**的功能性验证（跑过的命令 + 结果）
    "require_executed_verification": True,
    # 帕累托特有：候选方案少于该数量时，frontier 判定不可信
    "min_alternatives": 2,
}

# 质量档位（与 review_metrics 的 low/mid/high/full 口径保持正交、不冲突）
QUALITY_TIERS = ("expert", "competent", "insufficient", "inadmissible")

# ---------------------------------------------------------------------------
# 三、时效性规范（FRESHNESS_SPECS · 信息不是陈旧就一定可信）
# ---------------------------------------------------------------------------
# 按信息类型给出「可接受的最大陈旧天数」与「必须复核的证据形态」。
# 依据：AI 能力/模型价格/框架 API 变化极快（周级），行业规范/法规相对稳定（年级）。
FRESHNESS_SPECS = {
    # kind: (max_age_days, must_recheck_note)
    "ai_model": (30, "模型能力/价格/上下文窗口变化快，超过 30 天必须重新核实"),
    "ai_framework": (60, "框架 API 版本（如 DSH/Cordis/MCP 契约）半年内常破坏性变更"),
    "ai_research": (180, "论文/技术路线结论超半年需看是否被新结果推翻"),
    "industry_practice": (365, "行业做法/岗位流程相对稳定，但需样本来源与年份"),
    "regulation": (365, "法规政策须注明生效日期与地域，过期即不可用"),
    "price_cost": (30, "价格/成本极易变动，不得用缓存价做决策"),
    "benchmark": (90, "榜单/基准结果会被新模型刷新，必须注明采样日期"),
    "internal_decision": (None, "内部决策以 ADR 版本为准，不按天数失效，按是否被 Superseded 判定"),
}
DEFAULT_MAX_AGE_DAYS = 180

# 时效性判定档位
FRESHNESS_TIERS = (
    "fresh",       # 在有效期内且来源可核验
    "ageing",      # 超过建议复核期但未到硬上限（可用，须标注）
    "stale",       # 超过硬上限，作为决策依据不可信
    "undated",     # 无日期 —— 视同 stale（无法证明时效 = 不可信）
    "unknown",     # 判不出来（读不到来源）——显式 unknown，不得当通过
)

# ---------------------------------------------------------------------------
# 四、专家层来源（EXPERT_SOURCES · 借鉴行行出状元，不重造轮子）
# ---------------------------------------------------------------------------
# 通用架构师不得凭空"我懂所有行业"：行业/岗位专家的判定必须来自专家层，
# 本仓只消费其接口，不复制其数据（唯一事实源在 hanghangchuzhuangyuan）。
EXPERT_SOURCES = {
    "industry": {
        "repo": "dongdongxiaozu/hanghangchuzhuangyuan",
        "purpose": "行业/岗位专家层：行业划分、岗位关键词、能力标签、覆盖缺口",
        "interface": "Registry(unit-index.yaml) → all_units / get_unit / search_capability",
        "fallback": "专家层不可用时显式降级为 unverified，不假装命中",    },
    "ai_frontier": {
        "repo": "dongdongxiaozu/dongjiagoushi",
        "purpose": "AI 发展与下一步可解问题的能力前沿（本仓自维护 registry）",
        "interface": "expertise.ai_frontier.AIFrontier → load / capability_at / solve_candidates",
        "fallback": "注册表缺失时判 unknown，不得默认「全能可做」",
    },
}

# ---------------------------------------------------------------------------
# 五、自检（唯一事实源被人改坏时，必须有确定性红灯）
# ---------------------------------------------------------------------------
def validate_specs():
    """校验规范自身的一致性；返回 (ok, errors)。供测试与 CI 使用。"""
    errors = []
    keys = [d["key"] for d in DIMENSION_SPECS]
    if len(keys) != len(set(keys)):
        errors.append("维度 key 重复")
    total = round(sum(d["weight"] for d in DIMENSION_SPECS), 6)
    if abs(total - 1.0) > 1e-6:
        errors.append(f"维度权重之和应为 1.0，实际 {total}")
    for d in DIMENSION_SPECS:
        for field in ("key", "name", "question", "required", "weight", "evidence"):
            if field not in d:
                errors.append(f"维度 {d.get('key')} 缺字段 {field}")
        if not d.get("evidence"):
            errors.append(f"维度 {d.get('key')} 证据类型为空")
    if len(REQUIRED_DIMENSIONS) != len(DIMENSION_SPECS):
        # 当前设计为七维全部必过；若未来放宽须同步改文档与测试
        errors.append("当前设计要求七维全部必过")
    if not (JUDGE_THRESHOLDS["score_competent"] <= JUDGE_THRESHOLDS["score_expert"]):
        errors.append("分档阈值顺序错误：competent 不得高于 expert")
    for tier in QUALITY_TIERS:
        if not tier:
            errors.append("质量档位存在空值")
    return (not errors), errors
