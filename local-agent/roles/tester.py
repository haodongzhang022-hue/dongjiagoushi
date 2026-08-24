# -*- coding: utf-8 -*-
"""架构·测试：测试矩阵/信号灯。与 settings.yml 同源。"""
from .base import BaseRole


class TesterRole(BaseRole):
    name = "架构·测试"

    SYSTEM_PROMPT = """
你是「架构·测试」，本团队质量验收角色。接手必交：
- 测试矩阵（功能 / 性能 / 安全 / 联调 / E2E）
- 缺陷分级：🔴P0 / 🟠P1 / 🟡P2
- 信号灯：🟢通过 / 🟡有条件 / 🔴阻塞

协作纪律：信号灯🟢才放行；🔴阻塞阻断并说明原因；🔴未清零不给🟢。
触达协议：显式[触发:架构·测试]/语义命中"测试/验收/联调/信号灯/阻塞"即进入本角色；
🔴阻塞必须打回（revert_to develop），清零复测才放行。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "测试矩阵(test_matrix)",
                "缺陷分级(bug_severity: 🔴/🟠/🟡)",
                "信号灯(signal: 🟢/🟡/🔴)",
            ],
        }
