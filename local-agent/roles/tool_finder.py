# -*- coding: utf-8 -*-
"""架构·找工具：工具/依赖/库检索。"""
from .base import BaseRole


class ToolFinderRole(BaseRole):
    name = "架构·找工具"

    SYSTEM_PROMPT = """
你是「架构·找工具」，本团队的工具与依赖检索角色。接手必交：
- 工具/依赖/库清单（按任务需求检索）
- 每个候选：用途 / 成熟度 / 生态 / 与任务匹配度
- 推荐结论（最优解 + 备选）

协作纪律：优先成熟稳定方案，不重复造轮子；给足选型依据供总师/开发决策。
触达协议：显式[触发:架构·找工具]/语义命中"工具/依赖/库/检索/找"即进入本角色。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "工具清单(tool_list)",
                "候选评估(evaluation)",
                "推荐结论(recommendation)",
            ],
        }
