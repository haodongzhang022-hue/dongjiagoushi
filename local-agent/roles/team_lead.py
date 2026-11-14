# -*- coding: utf-8 -*-
"""架构·小组长：真带队落地（派→带→收）+ **当经理的脑子**（补全方案/看住犯傻）。

## 一、真带队（Issue #239 · main 已有）
> 「可能小组长也不及格。不然他调配小组长也应该能完成。」

上一版小组长只会三件事：拆子任务、给个协调建议、看进度尺——**会表态，不会带队干活**。
补法：小组长 = 「派 → 带 → 收」三个确定性动作：

| 环节 | 动作 | 判据 |
|------|------|------|
| 派 | `lead_dispatch_devs(task)` 把任务真派给组内 N 个开发（默认 2，各独立 gid） | 每人有 gid 才叫派了 |
| 带 | `lead_run_round(...)` 跑一轮：开发执行 → **客观验证** → 决策 | 全部 APPROVED 才放行 |
| 收 | `lead_aggregate()` 全组通过 → 整合统一交付经理；超限 → 上报 | 有交付留痕才叫收 |

## 二、当经理的脑子（Issue #232）
> 「小组长我还没见到，需要补充上，经理现在智力严重不足，需要小组长当脑子用给他增强，
>   看着他别犯傻」

经理方案常有窟窿、行动常跑偏：空任务、无主派发、跳深度（以为派完就完事，其实下游
没接单没开工）、同一个错误重复派、进度零推进还继续往前推。小组长要：
  ① 补全方案（`enhance`/`advise`）：诊断缺口 → 补字段/拆细/改派/加派/升总师，
     给 `ready` 判定，**缺口不齐不许往下派**；
  ② 看住经理（`watch`/`watch_manager_orders`）：六类犯傻逐条判定 +
     **替代动作**，二度命中 `blocked_escalate` 上报总师。

脑子是**确定性实现**（`lead_brain/`），不是再叫一个 LLM 自由发挥；判定可核验、可留痕。
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
你是「架构·小组长」。经理把任务交给你，你要做两件事：**带组干完** + **当经理的脑子看住他**。

## 一、带组干完：三个动作，缺一即未完成（Issue #239）

① 派开发 (`lead_dispatch_devs`)：把任务切成组内 N 片（默认 2 个开发并行），
   每人独立 gid、独立子任务键。派不出人 = 没接住活。
② 带一轮 (`lead_run_round`)：开发执行 → **客观验证**（测试/lint）→ 确定性决策。
   开发说"做完了"不算数，验证器说了才算。
③ 收口 (`lead_aggregate`)：**全部开发客观通过**才整合、统一向上交付经理；
   未通过 → 继续重做；重做超限 → 上报经理换方案，绝不无限重试、绝不带病交付。

## 二、当经理的脑子：补全 + 看住（Issue #232）

经理管「谁来做/何时做完/怎么分配」，但经理方案常有窟窿、行动常跑偏。
你要替他补全、盯住他别犯傻：

- **补全方案**（`enhance`/`advise`）：逐项诊断 目标 / 负责人 / 干什么（不许是"开发"这种
  空词）/ 输入 / 输出 / 验收标准 / 派活深度 / 编号唯一，缺口逐条点名 →
  给修正动作（补字段 / 拆细 / 改派 / 加派 / 修正方案 / 升总师）。
  **缺口不齐不许往下派**（`ready=False` 即拦），不带窟窿往下走。
- **看住经理**（`watch`/`watch_manager_orders`）：确定性拦住六类犯傻并给替代动作——
  跳深度（不到 L4）、重复派发（同一实体 >2 次）、超次返工（打回 >3 次）、
  空转（进度零推进）、抢单、无主派发。
  **二度命中** → `blocked_escalate` 标 blocked 上报总师，不让经理自己硬扛；
  较大的改框架交「总师助理」，保总师上下文纯净。

## 铁律

- **执行-验证分离**：开发只管做，合格与否由客观验证器裁定，不自判；
- **一个没过就不放行**：不许"差不多得了"，不带病交付；
- **超限上报，不硬撑**：重做超 `max_attempts` / 总迭代超 `max_iterations` → 上报经理换方案；
- **只补窟窿不碰边界**：你补方案的可执行性，做什么/为何做仍归总师与经理；判不了的标
  `escalate` 显式暴露，不猜；
- **进度尺归小组**：本组收敛自己盯 (`sentinel.engine.group_oversight(group_id)`)，不等经理催。

## 接单不是终点（Issue #239 二轮 · 承上启下的下半段）

经理把活交给你，回 `[接单]` 只是开始，你要**使命必达**：

- 组内开发派不出去 → **换承接方式**（拆小 / 换人 / 自己先顶上不越界部分），
  不是发一句「无人承接」就交回；
- 卡点确实超出本组能力 → **带证据交回经理**（`lead_escalate`：试过什么、缺什么、
  要谁来帮），让经理去跨岗借人。交回不是甩锅，是给经理能继续决策的输入；
- 组内收敛自己盯到 0，不 poke 一下动一下。

## 协作纪律

- 任务过大：一开始拆，或开发中发现过大申报加派（ops.apply_more_agents），
  分支产出用 ops.team_lead_aggregate 汇总回本组整合；
- 向上交付一次性给经理（含进度回放），过程不打断经理；
- 验收标准必须可客观验证（测试/lint/信号灯），不接受「我觉得完成了」；
- 判定是确定性的，不靠感觉：宁可拦住一次，也不让团队在同一个错误上打转。

## 触发与回转协议

- 显式触发：收到带 `[触发:架构·小组长]` 的接力卡即进入本角色执行。
- 语义触发：命中「拆任务/子任务/协调/排期/整合/进度尺/经理方案/看住经理/别犯傻」即切本角色。
- 回转：被打回（`[回转] 退回:架构·小组长`）视为重新触发，按"下一步要求"返工并交回下游复评；
  最多 3 次，超次标 blocked 上报总师。
- 打断：中断须在接力卡 `当前进度` 留续跑点，续跑凭进度无缝接续，不重做已完成部分。
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lead_engine = None
        try:
            from lead_brain import LeadBrainAbility
            self.lead_brain_ability = LeadBrainAbility(owner=self)
        except Exception:
            self.lead_brain_ability = None

    # ---------------- 带队引擎（Issue #239）----------------
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

    def lead_escalate(self, task, tried=None, need=""):
        """卡点超出本组能力 → **带证据**交回经理（不是只发一句"无人承接"）。"""
        rec = {
            "task_key": (task or {}).get("task_key", ""),
            "tried": list(tried or []),
            "need": need or "本组承接不到，请经理跨岗借角色或重新分派",
            "shift": "向上移交（经理继续找通路，不把活掉地上）",
        }
        try:
            from data import admin
            admin.record_event(self.name, "lead_escalate", rec,
                               rec["task_key"] or "")
        except Exception:  # noqa: BLE001 留痕失败不改判定
            pass
        return rec

    def lead_borrow(self, task_key, role="", reason="", task=""):
        """组内没有能承接的人 → 申请**跨岗借角色**，并且**把结果记下来**。

        借谁不写死（`role` 留空时按任务语义 + 名册派生）；借不到也落台账，
        下次自动跳过这个人换下一个——否则同一批人会被反复借、反复失败
        （Issue #239 收尾轮用户点名：缺这一步结果的记录）。
        """
        from manager import borrow as borrow_mod
        target = role or (borrow_mod.need_roles(task or task_key) or
                          [("架构·评审")])[0]
        failed = borrow_mod.failed_roles(task_key)
        if role and role in failed:  # 指定的人借败过：直接说清，别再重复
            return {"task_key": task_key, "borrow_role": role, "handle": None,
                    "ok": False, "reason": "该角色在这条任务上已借败过（台账在案）",
                    "next": "换下一个候选或换手段", "failed_roles": failed}
        try:
            handle = self.resolve(role=target)
        except Exception:  # noqa: BLE001 解析失败如实暴露
            handle = {"handle": "", "note": "HandleAbility 未解析出，须经理协调"}
        ok = bool(isinstance(handle, dict) and handle.get("handle"))
        borrow_mod.record(task_key, target, ok,
                          handle=(handle or {}).get("handle", "") if isinstance(handle, dict) else "",
                          lane="resolve", reason="" if ok else "handle 未解析出",
                          owner=self.name)
        return {
            "task_key": task_key,
            "borrow_role": target,
            "handle": handle,
            "ok": ok,
            "reason": reason or "组内无人可承接，申请跨岗借角色",
            "recorded": True,
            "failed_roles": failed,
        }

    def lead_overview(self):
        """本组俯瞰（二级信息：几轮、通过数、卡点）。"""
        return self.lead_engine.overview()

    def group_convergence(self, group_id):
        """本组成员到目标的收敛俯瞰（进度尺按小组归集）。"""
        from sentinel import engine as sentinel
        return sentinel.group_oversight(group_id)

    # ---------------- 脑子能力透传（Issue #232）----------------
    def diagnose(self, plan):
        """诊断经理方案缺口（缺口清单 + 可执行评分）。"""
        return self.lead_brain_ability.diagnose(plan)

    def enhance(self, plan):
        """补全经理方案：诊断 + 给修正动作，一次到位。"""
        return self.lead_brain_ability.enhance(plan)

    def advise(self, plan):
        """给出补全建议（改派/拆细/加派/升总师）。"""
        return self.lead_brain_ability.advise(plan)

    def watch(self, action, history=None):
        """看住经理的一次行动（跳深度/重复派发/超次返工/空转/抢单/无主派发）。"""
        return self.lead_brain_ability.watch(action, history=history)

    def watch_manager_orders(self, orders, history=None):
        """批量看住经理的一串派活。"""
        return self.lead_brain_ability.watch_manager_orders(orders, history=history)

    # ---------------- 输出契约 / 能力 ----------------
    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "开发派工(devs: 组内 N 个开发各自子任务切片 + 独立 gid)",
                "闭环轮次(rounds: 执行→客观验证→决策，全部 APPROVED 才放行)",
                "整合交付(aggregate: delivered / continue / escalated)",
                "脑子·补全经理方案(enhance: 诊断缺口→补字段/拆细/改派/加派/升总师, ready 判定)",
                "脑子·看住经理(watch: 跳深度/重复派发/超次返工/空转/抢单/无主派发 → pass|block|blocked_escalate)",
                "进度尺监督(group_oversight: 本组成员到目标收敛)",
                "拆分/加派整合(team_lead_aggregate)",
            ],
            "entry": ["lead_dispatch_devs", "lead_run_round", "lead_aggregate",
                      "lead_drive", "lead_overview", "group_convergence",
                      "lead_escalate", "lead_borrow",
                      "enhance", "advise", "diagnose", "watch", "watch_manager_orders"],
            "iron_rules": [
                "执行-验证分离：合格由客观验证器裁定，不自判",
                "一个没过就不放行，不带病交付",
                "重做超限上报经理换方案，不无限重试",
                "缺口不齐不许往下派（当经理的脑子补全方案）",
            ],
        }

    def capability(self):
        """能力清单：全员能力 + 小组长引擎 + 脑子。"""
        cap = super().capability()
        cap["lead_engine"] = {
            "name": "LeadEngine",
            "owner": self.name,
            "entry": ["dispatch_devs", "run_round", "aggregate", "drive", "overview"],
            "devs_per_team": "默认 2，可配置",
            "engine": "dev_team.DevTeamEngine（确定性状态机 + 硬性熔断 + 进度北极星）",
        }
        if getattr(self, "lead_brain_ability", None) is not None:
            cap["lead_brain_ability"] = self.lead_brain_ability.capability()
        return cap
