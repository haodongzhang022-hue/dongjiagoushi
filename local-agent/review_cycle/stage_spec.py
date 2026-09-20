# -*- coding: utf-8 -*-
"""
评审段「阶段链」唯一事实源（stage spec · Issue #150 打断补齐）
==============================================================
用户痛点（Issue #150 追加）：
  「我们还在处理开发的时候，他就又在跑测试了，然后之后又触发了评审，
   但是这场开发还没完成……中间本该以链条往后运行，他一次触发了。
   开发和测试就乱了，导致重复触发也会导致进度失衡。」

根因：**跨角色的阶段链没有门控**——测试/评审的触发**不校验上游是否已收口**，
于是同一条链被"一次触发"多点并发，且同一件事被重复触发，进度基准被稀释（失衡）。

本文件集中声明阶段链的顺序、节点、放行/驳回判据（各层引擎/角色/CLI/测试都从这里读，
不各自取名——对齐 dev-standard「唯一事实源」纪律）。

> 与 `spec.py`（评审段自己的 collect→coalesce→dispatch→review 状态机）分工：
> `spec.py` 管**评审段内部**的状态；本文件管**跨角色阶段链**的先后门控（谁在跑就别抢跑）。
"""

MODULE = "review-cycle"
MODULE_VERSION = "v0.3.2"

# 跨角色阶段链（source order · 严格有序；编号越大越靠后）
# 顺序依据 = **仓库权威链条**（Issue #150 复评 N1 校正）：
#   `roles/reviewer.py` 首行即「评审通过后**真实转交测试**」（`handoff_to_tester()`），
#   AGENTS.md 双轴/转交规则、`topology/topologies.py` 的 `DEV_ENHANCED_NODES`
#   （`review` depends_on `dev_*`；`test` depends_on `review`）同源。
# 即：**开发 → 评审 → 测试**（评审通过才转测试）。此前误写为 开发→测试→评审，
# 会把评审永久拦在测试之后，与既有转交链路语义颠倒（N1）。
STAGE_ORDER = ("development", "review", "testing")

# 阶段 → 该阶段跑动时**必须活跃**的角色（活跃判定用「阶段活动登记表」，确定性）
STAGE_ACTOR = {
    "development": "架构·开发",
    "review": "架构·评审",
    "testing": "架构·测试",
}

# 角色名 → 阶段（生产路径接线用：编排/角色按角色名登记阶段收口，不各自取名）
ROLE_STAGE = {
    "架构·开发": "development",
    "架构·评审": "review",
    "架构·测试": "testing",
}

# 触发阶段 → 其**唯一上游**（上游未收口即判抢跑）
UPSTREAM = {
    "review": "development",
    "testing": "review",
}

# 门控判据（唯一事实源；引擎不另行取名）
GATE_DECISIONS = (
    "allow",            # 放行：上游已收口 + 本阶段未在跑 + 未回头补上游
    "blocked_active",   # 驳回：本阶段已在跑（重复触发 → 复用，不再起新任务/不冲进度）
    "blocked_upstream", # 驳回：上游阶段未收口（抢跑 → 拒绝，让链条按序推进）
    "blocked_switched", # 驳回：下游阶段已跑过再回头补上游（乱序 → 拒绝，防两条并行链）
)

# 驳回原因的人可读说明（供 tag/俯瞰；不各自取名）
DECISION_REASON = {
    "allow": "链式推进：上游已收口 + 本阶段未在跑 + 未回头补上游",
    "blocked_active": "本阶段已在跑（重复触发）→ 复用进行中的任务，不新起任务、不冲进度",
    "blocked_upstream": "上游阶段未收口 → 拒绝抢跑，先让上游按链条收口",
    "blocked_switched": "下游阶段已跑过、再回头补上游 → 乱序拒绝，防止同一链被并行拆成两条",
}

# 阶段活动登记表的自动静默（秒）：超时即视为该阶段的 agent 已收口（防打标残留卡死链）
# 允许环境变量覆盖：`REVIEW_STAGE_QUIET_SECONDS`（测试隔离用）。
DEFAULT_QUIET_SECONDS = 1800

__all__ = ["MODULE", "MODULE_VERSION", "STAGE_ORDER", "STAGE_ACTOR",
           "ROLE_STAGE", "UPSTREAM", "GATE_DECISIONS", "DECISION_REASON",
           "DEFAULT_QUIET_SECONDS"]
