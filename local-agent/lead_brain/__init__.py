# -*- coding: utf-8 -*-
"""
lead_brain · 小组长「脑子」能力包（LeadBrainAbility）
=====================================================
定位（Issue #232 用户诉求）：
  「小组长我还没见到，需要补充上，经理现在智力严重不足，需要小组长当脑子用给他增强，
   看着他别犯傻」

  即：小组长不只做「拆任务/整合产出」的手，要当**经理的脑子 + 监察**——
  经理给的分配方案先过小组长这道脑子（诊断缺口 → 补全方案），
  经理行动前也过这道脑子（看到跑偏/超次/空转就当场拦住）。

三件事：
  1. `diagnose(plan)`    —— 找经理方案的缺口（谁在做/干什么/输入输出/依赖/验收/深度/排期）
  2. `advise(plan)`      —— 把缺口补成可执行方案（补全/改派/拆细/加派/升总师），不让方案带着窟窿往下走
  3. `watch(action)`     —— 看住经理别犯傻（重复派发/跳深度/超次返工/空转/多经理抢单）

用法（任意角色实例上）：
    from lead_brain import LeadBrainAbility
    brain = LeadBrainAbility(owner=role)
    brain.enhance(plan)              # 诊断 + 补全，一次到位
    brain.watch_manager_orders(orders)  # 拦住犯傻的派活
"""
from .ability import LeadBrainAbility

__all__ = ["LeadBrainAbility"]
