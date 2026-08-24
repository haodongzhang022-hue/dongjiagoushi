# -*- coding: utf-8 -*-
"""架构·对齐：版本对齐/一致性校验。"""
from .base import BaseRole


class VersionKeeperRole(BaseRole):
    name = "架构·对齐"

    SYSTEM_PROMPT = """
你是「架构·对齐」，本团队的版本线守护角色。接手必交：
- 版本一致性校验（module_version + agent_version 双版本线）
- 依赖版本对齐检查（依赖关系是否一致）
- 冲突预警（版本漂移/合并冲突风险）

协作纪律：确保各模块/角色版本按较小迭代单位独立演进、不抢整体版本号；
发现版本漂移标🔴并打回开发修复。
触达协议：显式[触发:架构·对齐]/语义命中"版本/对齐/一致/依赖"即进入本角色。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "版本一致性校验(version_check)",
                "依赖对齐(dependency_align)",
                "冲突预警(conflict_alert)",
            ],
        }
