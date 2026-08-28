# -*- coding: utf-8 -*-
"""
DevTeamAbility · 开发小组闭环能力（通用复用能力）
=================================================
把「一个开发小组」作为一个确定性编排的整体来驱动，深化结构升级：
- 一套循环 N 个开发（默认 2），开发是持续推进度的核心，辅助不挤占名额；
- 确定性状态机：全部 dev 产出 APPROVED 后小组长才整合统一交付；
- 硬性熔断 + 进度北极星监督贯穿每一层，防单 Agent 无限循环。
"""
import os
import sys

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DevTeamAbility:
    """通用开发小组闭环能力：任何 agent 挂载即得小组级确定性编排。"""

    RULES = {
        "何时用": (
            "开发任务较大、需按小组并行推进且目标明确(goal>0)时："
            "把小组作为一个整体，用确定性闭环控制 N 个开发的执行-验证-整合，"
            "防单 Agent 无限循环/防辅助挤占开发推进度。"
        ),
        "不越权": (
            "小组闭环是确定性 Orchestrator，不替代 Leader 决策；"
            "超过 max_attempts 后必须上报 Leader，禁止自行无限重试；"
            "跨岗位派发须经经理统一协调。"
        ),
        "防无效": (
            "验证必须用客观结果(测试/lint)，不用主观判断；"
            "进度推进走哨兵 goal_meters，停滞/横跳/重复错误由哨兵拦截；"
            "记录优先于对话，干完统一交付给经理。"
        ),
    }

    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)

    @staticmethod
    def _resolve_owner_name(owner):
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        return getattr(owner, "name", "") or getattr(owner, "__class__", object).__name__

    def _engine(self):
        import dev_team
        return dev_team

    def create_team(self, goal_total=0.0, devs_per_team=2, **kwargs):
        """创建一次开发小组闭环（Planner 门控：goal>0 才允许）。返回 DevTeamEngine。"""
        team = self._engine().DevTeamEngine(
            goal_total=goal_total, devs_per_team=devs_per_team,
            owner=self._owner_name, **kwargs)
        return team

    def run_team_round(self, team, dev_outputs, task_id="", max_attempts=None):
        """确定性编排一轮小组循环：小组长发起 + 各开发上报客观验证结果 + 决策。"""
        team.start_round(task_id=task_id or team.team_id)
        for dev_id, ok, evidence in dev_outputs:
            team.developer_output(dev_id, task_id or team.team_id,
                                  ok, evidence=evidence)
        return team.decide(task_id=task_id or team.team_id, agent_id=team.lead_id)

    def advance_team(self, team, delta):
        """推进小组进度（目标北极星），写 goal_meters。"""
        return team.advance(delta)

    def team_overview(self, team):
        """小组闭环俯瞰（二级信息）。"""
        return team.overview()

    def capability(self):
        """返回能力声明（供 BaseRole.capability() 汇总，扁平结构同其他能力）。"""
        return {
            "name": "DevTeamAbility",
            "desc": "开发小组闭环（DevTeamEngine）——把小组作为一个整体，"
                    "N 个开发确定性编排，全部 APPROVED 后小组长整合统一交付",
            "methods": ["create_team", "run_team_round", "advance_team", "team_overview"],
            "devs_per_team": "默认 2，可配置（3/4）",
            "rules": self.RULES,
        }
