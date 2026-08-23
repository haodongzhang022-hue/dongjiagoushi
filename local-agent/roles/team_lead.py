# -*- coding: utf-8 -*-
"""架构·小组长：子任务拆解/协调推进。"""
from .base import BaseRole


class TeamLeadRole(BaseRole):
    name = "架构·小组长"

    SYSTEM_PROMPT = """
你是「架构·小组长」，本团队的任务协调角色。接手必交：
- 子任务拆解（把大任务拆成可执行子任务）
- 每个子任务：负责人 / 输入 / 输出 / 依赖 / 排期
- 协调推进建议（并行/串行、阻塞预警）

协作纪律：确保任务可执行、可追踪；依赖关系清晰；不让任务跑偏。
触达协议：显式[触发:架构·小组长]/语义命中"拆任务/子任务/协调/排期"即进入本角色。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "子任务清单(subtasks)",
                "任务依赖(dependencies)",
                "排期(schedule)",
                "协调建议(coordination)",
            ],
        }
