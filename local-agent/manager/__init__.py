# -*- coding: utf-8 -*-
"""
经理模块（Manager · Issue #239）
================================
把「架构·经理」与「架构·小组长」从**会表态**补成**会干活**。

- `ManagerEngine`：计划 → 真激活（建 Issue 派发）→ 督促进度 → 监督结果
  （揪出「回执 [接单] 却没下文」的假装分工，转小组长 + 哨兵打断 + 升级）。
- `LeadEngine`：小组长真带队——派开发 → 确定性闭环（客观验证）→ 整合统一交付。

两者都是**确定性引擎**（不是靠 LLM 自觉），每次动作落库留痕、可核验。
详见 docs/MANAGER.md。
"""
from .engine import (
    ManagerEngine, DUTIES, NOT_MANAGER,
    parse_plan, resolve_choice,
)
from .lead_engine import LeadEngine

__all__ = [
    "ManagerEngine", "LeadEngine",
    "DUTIES", "NOT_MANAGER",
    "parse_plan", "resolve_choice",
]
