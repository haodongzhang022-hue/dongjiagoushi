# -*- coding: utf-8 -*-
"""
DevTeamAbility · 开发小组闭环能力（通用复用能力）
=================================================
把「一个开发小组」（小组长 + N 个开发）作为一个确定性编排的整体，
深化开发结构升级：一套循环 N 个开发（默认 2），由确定性状态机控制，
全部产出 APPROVED 后小组长整合统一交付。防单 Agent 无限循环。

用法（任意角色实例上）：
    from dev_team_kit import DevTeamAbility
    ability = DevTeamAbility(owner=role)
    team = ability.create_team(goal_total=10.0, devs_per_team=2)
    ability.run_team_round(team, dev_outputs=[("dev0", True, "PASS"), ...])
    ability.team_overview(team)

能力声明：ability.capability() 返回含 dev_team_ability 的声明。
"""
from .ability import DevTeamAbility

__all__ = ["DevTeamAbility"]
