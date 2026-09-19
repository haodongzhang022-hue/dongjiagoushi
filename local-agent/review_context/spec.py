# -*- coding: utf-8 -*-
"""
评审上下文增量复用 · 唯一事实源（spec）
========================================
稳定骨架的**分段规范**集中在此：哪些来源算「稳定骨架」（构建后冻结、按摘要引用），
哪些算「变化片段」（每轮只传增量）。各层（引擎/角色/CLI/测试）都从这里读取，
不各自取名，避免口径漂移（对齐 dev-standard「唯一事实源」纪律）。
"""

# 模块版本线（独立升版，不与整体版本联动）
MODULE = "review-context"
MODULE_VERSION = "v0.2.0"

# 稳定骨架分段（构建一次 → 冻结 → 评审每轮只引用摘要，不再复述）
STABLE_SEGMENTS = (
    "goal",        # 项目/任务北极星目标
    "boundary",    # 做 · 不做 边界
    "acceptance",  # 验收标准
    "contract",    # 模块接口契约 / 数据结构
    "decisions",   # 既有架构决策（ADR 摘要）
)

# 变化片段分段（每轮评审只传这部分增量）
VOLATILE_SEGMENTS = (
    "diff_summary",   # 本轮变更摘要（diff）
    "test_signals",   # 本轮客观测试信号灯（以测试为准）
    "findings",       # 本轮新增发现 / 必修项
    "round_note",     # 本轮说明
)

# 复用判据阈值：稳定骨架摘要占全量上下文的**目标压缩比**（信息密度）
# 摘要按 SEGMENT_REF_CHARS 截断成「引用」，避免把骨架原文再复述一遍。
SEGMENT_REF_CHARS = 120

# 摘要口径：把稳定骨架压成"引用行"所需的最小信息（只保关键，不保全文）
REF_FORMAT = "[{segment}] {summary}"

__all__ = [
    "MODULE", "MODULE_VERSION",
    "STABLE_SEGMENTS", "VOLATILE_SEGMENTS",
    "SEGMENT_REF_CHARS", "REF_FORMAT",
]
