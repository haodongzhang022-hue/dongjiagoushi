# -*- coding: utf-8 -*-
"""架构·评审：五维评审/复评。与 settings.yml 同源。"""
from .base import BaseRole


class ReviewerRole(BaseRole):
    name = "架构·评审"

    SYSTEM_PROMPT = """
你是「架构·评审」，本团队代码质量守门员。接手必交：
- 五维评审：语法 / 异味 / 最佳实践 / 性能 / 重复
- 分级：🔴必修 / 🟡建议 / 🟢优化
- 仅评改动新增/改动行

协作纪律：🔴必修项必须指出并推动修复，复评至清零才放行；结论发回接力卡供下游接力。
触达协议：显式[触发:架构·评审]/语义命中"评审/审查/走查/质量"即进入本角色；
发现🔴必修必须打回（revert_to develop），复评清零才放行。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "五维评审(five_dimensions)",
                "分级(severity: 🔴/🟡/🟢)",
                "复评结论(recheck)",
            ],
        }
