# -*- coding: utf-8 -*-
"""
评审段调度器 · 唯一事实源（spec）
==================================
评审段（review segment）= 一次「评审 → 开发增量 → 测试信号 → 回评审」的调度单位。
本文件集中声明评审段的状态机、节点、触发门控判据，各层（引擎/角色/CLI/测试）
从这里读取，不各自取名（对齐 dev-standard「唯一事实源」纪律）。
"""

MODULE = "review-cycle"
MODULE_VERSION = "v0.3.2"

# 评审段状态机（确定性；不让 LLM 决定"下一步/是否结束"）
# 状态推进由 cycle.advance_state() 依据「本轮的触发门控 + 是否发车」确定性计算，
# 不是硬编码常量（Issue #150 返工 S5：声明即接线，文档与实现一致）。
STATES = (
    "idle",        # 未开始
    "collecting",  # 增量收集中（开发/测试请求已入列，尚未发车）
    "dispatched",  # 已攒批发车（一批跑完）
    "reviewed",    # 已回评审（拿到双轴/处置）
    "done",        # 评审段完成
)

# 状态合法迁移表（确定性；越界迁移即编程错误，advance_state 会拒绝）
STATE_TRANSITIONS = {
    "idle": ("collecting",),
    "collecting": ("dispatched", "reviewed"),
    "dispatched": ("reviewed",),
    "reviewed": ("done",),
    "done": (),
}

# 触发门控 → 状态推进的确定性映射（TRIGGERS 的每项对应一个目标状态）
TRIGGER_STATE = {
    "diff_changed": "collecting",     # 变更指纹变化 → 进入收集
    "batch_ready": "dispatched",      # 攒批就绪且真发车 → 已发车
    "fingerprint_new": "reviewed",    # 指纹未被处理过 → 可做评审处置
}

# 评审段节点（DAG 顺序；每个节点有"触发门控"，满足才真触发，否则复用/跳过）
# 说明：这是**评审段内部**的证据流水线（拿测试信号 → 回评审），不是跨角色阶段链
# （跨角色链条见 `stage_spec.STAGE_ORDER` = 开发→评审→测试）。两者分工不同，勿混。
NODES = (
    {"id": "collect",     "role": "架构·开发", "action": "提交本轮增量（不立即唤醒）"},
    {"id": "coalesce",    "role": "架构·测试", "action": "攒批：变更感知选测 + 入列 Bus"},
    {"id": "dispatch",    "role": "架构·测试", "action": "整批发车：一次构建跑完一批"},
    {"id": "review",      "role": "架构·评审", "action": "增量上下文回评审（冻结骨架+本轮变化）"},
)

# 节点 id 的有序元组（由 NODES 派生，供引擎/CLI/测试读取，不各自再写一遍）
NODE_IDS = tuple(n["id"] for n in NODES)

# 评审段状态 → 承载它的节点 id（状态机与节点表**同源**，不各自取名）
STATE_NODE = {
    "idle": "collect",
    "collecting": "coalesce",
    "dispatched": "dispatch",
    "reviewed": "review",
    "done": "review",
}

# 触发门控（哪个信号满足才真触发，否则判定"复用/跳过"）
TRIGGERS = (
    "diff_changed",     # 变更指纹变化 → 才真触发开发/构建
    "batch_ready",      # 攒批就绪（队列非空且可发车）→ 才发车
    "fingerprint_new",  # 内容指纹未被处理过 → 才做评审处置
)

# 默认攒批窗口（秒）：BusRunner 的"15 分钟一班"由 hybrid.bus 承载，此处仅声明期望
DEFAULT_INTERVAL_SECONDS = 900

__all__ = ["MODULE", "MODULE_VERSION", "STATES", "STATE_TRANSITIONS",
           "TRIGGER_STATE", "NODES", "NODE_IDS", "STATE_NODE", "TRIGGERS",
           "DEFAULT_INTERVAL_SECONDS"]
