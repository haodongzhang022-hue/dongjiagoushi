# -*- coding: utf-8 -*-
"""架构·小组长：真带队落地——派开发、跑确定性闭环、整合统一交付。

## 为什么小组长也要补（Issue #239）

> 「可能小组长也不及格。不然他调配小组长也应该能完成。」

上一版小组长只会三件事：拆子任务、给个协调建议、看进度尺。听上去很像经理的小号——
**同样的问题：会表态，不会带队干活**。经理把活交下来，它再出一张子任务表，活就断在这层。

## 补法：小组长 = 「派 → 带 → 收」三个确定性动作

| 环节 | 动作 | 判据 |
|------|------|------|
| 派 | `lead_dispatch_devs(task)` 把任务真派给组内 N 个开发（默认 2，各独立 gid） | 每人有 gid 才叫派了 |
| 带 | `lead_run_round(...)` 跑一轮：开发执行 → **客观验证** → 决策 | 全部 APPROVED 才放行 |
| 收 | `lead_aggregate()` 全组通过 → 整合统一交付经理；超限 → 上报 | 有交付留痕才叫收 |

引擎在 `local-agent/manager/lead_engine.py`，底层复用 `dev_team.DevTeamEngine`
（Issue #74：确定性状态机 + 硬性熔断 + 进度北极星）。**缺的从来不是引擎，是有人调用它**。

## 铁律

- **执行-验证分离**：开发只负责"做"，是否合格由客观验证器（测试/lint）裁定，不自行裁定；
- **不放行**：只要有一个开发没过客观验证，小组长不许整合交付；
- **不无限重试**：单开发重做超 `max_attempts` / 总迭代超 `max_iterations` → 上报经理换方案；
- **进度尺归小组**：本组成员到目标的收敛由小组长俯瞰（`sentinel.engine.group_oversight`）。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from .base import BaseRole


class TeamLeadRole(BaseRole):
    name = "架构·小组长"

    SYSTEM_PROMPT = """
你是「架构·小组长」。经理把任务交给你，你要做的是**带组干完**，不是再拆一张表。

## 三个动作，缺一即未完成

① 派开发 (`lead_dispatch_devs`)：把任务切成组内 N 片（默认 2 个开发并行），
   每人独立 gid、独立子任务键。派不出人 = 没接住活。
② 带一轮 (`lead_run_round`)：开发执行 → **客观验证**（测试/lint）→ 确定性决策。
   开发说"做完了"不算数，验证器说了才算。
③ 收口 (`lead_aggregate`)：**全部开发客观通过**才整合、统一向上交付经理；
   未通过 → 继续重做；重做超限 → 上报经理换方案，绝不无限重试、绝不带病交付。

## 铁律

- 执行与验证分离：开发只管做，合格与否由客观验证器裁定，不自判；
- 有一个没过就不放行——不许"差不多得了"；
- 超限上报，不硬撑；进度尺写 goal_meters，停滞/横跳由哨兵打断；
- 本组收敛自己盯 (`sentinel.engine.group_oversight(group_id)`)，不等经理催。

## 协作纪律

- 任务过大：一开始拆，或开发中发现过大申报加派（ops.apply_more_agents），
  分支产出用 ops.team_lead_aggregate 汇总回本组整合；
- 向上交付一次性给经理（含进度回放），过程不打断经理；
- 被打回（`[回转] 退回:架构·小组长`）视为重新触发，按"下一步要求"返工交回下游复评。
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lead_engine = None

    @property
    def lead_engine(self):
        """懒加载小组长引擎（绑定角色身份）。"""
        if self._lead_engine is None:
            from manager import LeadEngine
            self._lead_engine = LeadEngine(
                devs_per_team=getattr(self, "devs_per_team", 2),
                owner=self.name, lead_id=self.name,
            )
        return self._lead_engine

    # ---------------- 对外主入口 ----------------
    def lead_dispatch_devs(self, task, devs_per_team=None):
        """把任务真派给组内 N 个开发（各独立 gid + 子任务切片）。"""
        return self.lead_engine.dispatch_devs(task, devs_per_team=devs_per_team)

    def lead_run_round(self, dev_outputs=None, plan=None, delta=None):
        """跑一轮确定性闭环：执行 → 客观验证 → 决策（全部 APPROVED 才放行）。"""
        return self.lead_engine.run_round(plan, dev_outputs=dev_outputs, delta=delta)

    def lead_aggregate(self, plan=None, last=None):
        """收口：全通过 → 整合统一交付；未通过 → 继续；超限 → 上报。"""
        return self.lead_engine.aggregate(plan, last)

    def lead_drive(self, task, dev_outputs=None, devs_per_team=None, delta=None):
        """一站式：派开发 → 跑一轮 → 收口（小组长的标准动作）。"""
        return self.lead_engine.drive(task, dev_outputs=dev_outputs,
                                      devs_per_team=devs_per_team, delta=delta)

    def lead_overview(self):
        """本组俯瞰（二级信息：几轮、通过数、卡点）。"""
        return self.lead_engine.overview()

    def group_convergence(self, group_id):
        """本组成员到目标的收敛俯瞰（进度尺按小组归集）。"""
        from sentinel import engine as sentinel
        return sentinel.group_oversight(group_id)

    # ---------------- 输出契约 ----------------
    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "开发派工(devs: 组内 N 个开发各自子任务切片 + 独立 gid)",
                "闭环轮次(rounds: 执行→客观验证→决策，全部 APPROVED 才放行)",
                "整合交付(aggregate: delivered / continue / escalated)",
                "进度尺监督(group_oversight: 本组成员到目标收敛)",
                "拆分/加派整合(team_lead_aggregate)",
            ],
            "entry": ["lead_dispatch_devs", "lead_run_round", "lead_aggregate",
                      "lead_drive", "lead_overview", "group_convergence"],
            "iron_rules": [
                "执行-验证分离：合格由客观验证器裁定，不自判",
                "一个没过就不放行，不带病交付",
                "重做超限上报经理换方案，不无限重试",
            ],
        }

    def capability(self):
        """能力清单：在全员能力基础上补小组长引擎声明。"""
        cap = super().capability()
        cap["lead_engine"] = {
            "name": "LeadEngine",
            "owner": self.name,
            "entry": ["dispatch_devs", "run_round", "aggregate", "drive", "overview"],
            "devs_per_team": "默认 2，可配置",
            "engine": "dev_team.DevTeamEngine（确定性状态机 + 硬性熔断 + 进度北极星）",
        }
        return cap
