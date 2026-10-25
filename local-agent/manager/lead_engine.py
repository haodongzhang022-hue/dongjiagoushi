# -*- coding: utf-8 -*-
"""
小组长引擎（LeadEngine · Issue #239）
====================================
「不然他调配小组长也应该能完成」——经理把活交给小组长后，小组长必须**真带组干活**，
而不是再出一张分工表。

## 病灶（用户原话）

> 「可能小组长也不及格。不然他调配小组长也应该能完成。」

经理把所有事都自己扛或都不扛，本质是**承接口缺失**：中间层（小组长）只会拆任务、
不会带队落地，于是活要么掉地上、要么全堆回经理。

## 机制：三件事，全部确定性

| 环节 | 动作 | 判据 |
|------|------|------|
| **dispatch_devs** | 把任务真派给组内 N 个开发（默认 2），每人独立子键/gid | 每人有 gid 且投池 |
| **run_round** | 跑一轮 DevTeam 闭环：执行→**客观验证**→决策 | 全部 dev APPROVED 才放行 |
| **aggregate** | 全组通过 → 小组长整合、统一向上交付经理 | 有交付留痕 + 进度尺 |

## 为什么抄 DevTeamEngine 而不是另造

`dev_team.py` 已经把「一个小组=1 小组长 + N 开发」的确定性状态机、硬性熔断、
进度北极星做好了（Issue #74）。缺的不是引擎，是**没人调用它**。
所以 LeadEngine 是**接线层**：把任务变成 dev 输出、把 dev 输出喂给引擎、
把引擎结论变成"继续/整合/上报"，一步都不让小组长自由发挥。

## 用法

```python
from manager import LeadEngine
lead = LeadEngine(devs_per_team=2)
plan = lead.dispatch_devs({"task_key": "登录模块", "goal_total": 3})
r    = lead.run_round(plan, dev_outputs=[("dev0", True, "pytest 通过")])
final = lead.aggregate(plan, r)     # 全通过 → 整合交付；否则 REWORK/ESCALATED
```
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


def closing_stage_round(rounds):
    """整合补齐轮次的轮号（接在最后一轮之后）。"""
    return (rounds[-1].get("round") or len(rounds)) + 1 if rounds else 1


class LeadEngine:
    """小组长引擎：派开发 → 跑确定性闭环 → 整合统一交付。"""

    name = "架构·小组长"

    def __init__(self, devs_per_team=2, owner="架构·小组长", lead_id="架构·小组长",
                 max_attempts=None, max_iterations=None):
        self.devs_per_team = max(1, int(devs_per_team))
        self.owner = owner
        self.lead_id = lead_id
        self._team = None
        self._max_attempts = max_attempts
        self._max_iterations = max_iterations
        self.plan = None
        self.rounds = []

    # ---------------- ① 派开发：把任务真分下去 ----------------
    def dispatch_devs(self, task, devs_per_team=None):
        """把一条任务派给组内 N 个开发（每人独立 gid + 独立子任务切片）。

        task: {task_key, title?/goal_total?/detail?/issue?}
        返回 plan：{task_key, goal_total, devs:[{dev_id, agent_id, slice}], team}
        """
        task = dict(task or {})
        task_key = task.get("task_key") or task.get("title") or "未命名任务"
        n = max(1, int(devs_per_team or self.devs_per_team))
        # 目标量默认按「一条任务=1 个单位」计：一轮全员通过即可收口，
        # 不再要求调用方猜 goal_total —— 目标明确（>0）才进闭环是 DevTeam 的门控。
        goal_total = float(task.get("goal_total") or 1.0)

        devs = []
        for i in range(n):
            sub_key = f"{task_key}::dev{i}"
            # dev_id 必须是组引擎的键（dev0/dev1…）：DevTeamEngine.devs 就按这个索引，
            # 拿子任务键当 dev_id 会在 run_round 里报「未知开发」——那等于小组根本没跑起来。
            dev_id = f"dev{i}"
            agent_id = sub_key
            try:
                import ops
                dev = ops.register_agent_for(sub_key, role="架构·开发")
                agent_id = dev["agent_id"]
            except Exception:  # noqa: BLE001 登记失败不影响小组编排，但留原始 key
                pass
            devs.append({
                "dev_id": dev_id,
                "agent_id": agent_id,
                "slice": f"第 {i + 1} 片 / 共 {n} 片：{task_key}",
                "task_key": sub_key,
            })

        from dev_team import DevTeamEngine
        team = DevTeamEngine(
            goal_total=goal_total, devs_per_team=n,
            lead_id=self.lead_id, owner=self.owner,
            max_attempts=self._max_attempts, max_iterations=self._max_iterations,
        )
        self._team = team
        self.plan = {
            "task_key": task_key, "goal_total": goal_total,
            "issue": task.get("issue"),
            "devs": devs, "devs_per_team": n, "team": team,
            "stage": "dispatched",
        }
        return self.plan

    # ---------------- ② 跑一轮闭环（执行-验证-决策） ----------------
    def run_round(self, plan=None, dev_outputs=None, delta=None):
        """跑一轮：小组长发起 → 各开发上报客观验证结果 → 确定性决策。

        dev_outputs: [(dev_id, ok, evidence)]，ok 由**客观验证器**（测试/lint）给出，
                     不是"开发说自己做完了"。缺省视为未通过（不乱放行）。
        delta:       本轮实际推进量（有才写进度尺）。
        返回 {round, verdict, stage, reason, approved_devs, total_devs, progress}
        """
        plan = plan or self.plan
        if not plan or not plan.get("team"):
            raise RuntimeError("小组长未派开发（先 dispatch_devs），不空跑")
        team = plan["team"]

        if dev_outputs is None:
            dev_outputs = [(d["dev_id"], False, "无客观验证结果 → 默认未通过")
                           for d in plan["devs"]]

        start = team.start_round(task_id=plan["task_key"])
        results = []
        for dev_id, ok, evidence in dev_outputs:
            results.append(team.developer_output(
                dev_id, plan["task_key"], ok, evidence=evidence))
        decision = team.decide(task_id=plan["task_key"], agent_id=self.lead_id)

        if delta:
            team.advance(delta)

        rec = {
            "round": start.get("round"),
            "verdict": decision["verdict"],
            "stage": decision["stage"],
            "reason": decision["reason"],
            "approved_devs": decision["approved_devs"],
            "total_devs": decision["total_devs"],
            "remaining": decision.get("remaining"),
            "dev_results": results,
            "progress_pct": round(team.current / team.goal_total * 100, 1)
                            if team.goal_total else 0.0,
        }
        self.rounds.append(rec)
        plan["stage"] = decision["stage"]
        return rec

    # ---------------- ③ 整合 / 上报 ----------------
    def aggregate(self, plan=None, last=None):
        """按最后一轮裁决收口：DONE→整合统一交付；REWORK→继续；ESCALATED→上报。

        **小组长绝不自行放行**：只有 DONE（全部 dev 客观通过且目标达成）才交付。
        """
        plan = plan or self.plan
        last = last or (self.rounds[-1] if self.rounds else None)
        if not plan or not last:
            raise RuntimeError("没有可整合的轮次（先 run_round）")
        team = plan["team"]
        verdict = last["verdict"]

        if verdict == "DONE":
            record = team.deliver_to_manager(
                task_id=plan["task_key"],
                summary=f"小组整合交付：{plan['task_key']}（{plan['devs_per_team']} 开发，"
                        f"{len(self.rounds)} 轮）")
            plan["stage"] = "delivered"
            return {"status": "delivered", "record": record,
                    "next": "向上交付经理 → 经理转评审/测试"}
        if verdict == "ESCALATED":
            self._escalate(plan, last)
            return {"status": "escalated", "reason": last["reason"],
                    "next": "上报经理（换方案/重新规划），不无限重试"}
        # INTEGRATE：全员通过但目标未满 → 按剩余量记一次推进刻度，再裁决
        if verdict == "INTEGRATE":
            remaining = last.get("remaining")
            if remaining is None:
                remaining = team._remaining()
            team.advance(remaining)
            closing = team.decide(task_id=plan["task_key"], agent_id=self.lead_id)
            self.rounds.append({
                "round": closing_stage_round(self.rounds),
                "verdict": closing["verdict"], "stage": closing["stage"],
                "reason": closing["reason"],
                "approved_devs": closing["approved_devs"],
                "total_devs": closing["total_devs"],
                "remaining": closing.get("remaining"),
                "progress_pct": round(team.current / team.goal_total * 100, 1)
                                if team.goal_total else 0.0,
                "note": "整合阶段补齐剩余进度后重新裁决",
            })
            if closing["verdict"] == "DONE":
                record = team.deliver_to_manager(
                    task_id=plan["task_key"],
                    summary=f"小组整合交付：{plan['task_key']}（{plan['devs_per_team']} 开发，"
                            f"{len(self.rounds)} 轮）")
                plan["stage"] = "delivered"
                return {"status": "delivered", "record": record,
                        "verdict": "DONE", "next": "向上交付经理 → 经理转评审/测试"}
            return {"status": "continue", "verdict": closing["verdict"],
                    "reason": closing["reason"], "next": "继续小组循环"}
        # REWORK：未通过客观验证 → 继续跑，不放行
        return {"status": "continue", "verdict": verdict,
                "reason": last["reason"],
                "next": "未通过客观验证者重做；全员通过才整合"}

    def _escalate(self, plan, last):
        """上报经理：小组超限（单 dev 重试超限 / 总迭代超限）。"""
        try:
            from data import admin
            admin.record_event(self.owner, "lead_escalate",
                               {"task_key": plan["task_key"],
                                "reason": last["reason"]}, plan["task_key"])
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 一站式 ----------------
    def drive(self, task, dev_outputs=None, devs_per_team=None, delta=None):
        """派开发 → 跑一轮 → 收口，一次做完（小组长的标准动作）。"""
        plan = self.dispatch_devs(task, devs_per_team=devs_per_team)
        rd = self.run_round(plan, dev_outputs=dev_outputs, delta=delta)
        agg = self.aggregate(plan, rd)
        return {"plan": {k: v for k, v in plan.items() if k != "team"},
                "round": rd, "aggregate": agg}

    # ---------------- 二级信息 ----------------
    def overview(self):
        """小组俯瞰：几轮、几轮通过、卡在哪。"""
        if not self._team:
            return {"devs_per_team": self.devs_per_team, "rounds": 0,
                    "stage": "idle", "note": "尚未派开发"}
        return self._team.overview()
