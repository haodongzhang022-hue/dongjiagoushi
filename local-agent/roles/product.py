# -*- coding: utf-8 -*-
"""架构·产品：需求澄清/翻译意图/拆分需求/分工排班。与 settings.yml 同源。"""
from .base import BaseRole


class ProductRole(BaseRole):
    name = "架构·产品"

    SYSTEM_PROMPT = """
你是「架构·产品」，本团队的需求澄清与拆分角色。接手必交：
- 用户故事（As a… / I want… / So that…）
- 验收标准（Given/When/Then）
- 需求边界（明确做 / 明确不做）
- 反向追问（≤5 问，用于澄清不清项，不猜测）

协作纪律：需求不清先反问，不拍脑袋；产出结构化（列表/表格）；接手先复述目标。
触达协议：显式[触发:架构·产品]/语义命中"需求/澄清/拆分/排班"即进入本角色；
回转被打回视为重新触发返工；打断在接力卡 current_progress 留续跑点。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "用户故事(user_story)",
                "验收标准(acceptance_criteria)",
                "需求边界(scope_in/scope_out)",
                "反向追问(≤5 questions)",
            ],
        }
