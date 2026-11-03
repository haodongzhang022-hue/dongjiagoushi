# -*- coding: utf-8 -*-
"""
专家级架构能力包（ExpertiseAbility · 全员挂载）
================================================
把 `local-agent/expertise/` 的四支柱 + 时效闸门封装成一个**通用能力**，挂载到
`BaseRole`，与 DispatchAbility / DepthAbility / LabelAbility 同构 ——
各角色**不各自实现、不各自声明用法**，直接调用透传方法（单一规范来源）。

为什么全员挂载而不是只给总师：
  - 评审需要"外部验证门禁"判断对方**真的跑过了吗**；
  - 产品/经理需要"行业岗位专家"判断需求边界与人力配置；
  - 交付需要"时效性闸门"确认引用的事实没过期；
  - 任一角色的结论都应能被同一把尺子量。

使用（任意角色实例上）：
    role.assess_expertise(assessment)        # 七维 verdict
    role.explain_expertise(verdict)          # 人可读报告
    role.resolve_industry("给律所做合同审查") # 行业/岗位专家判定
    role.ai_frontier_at("多智能体协作编排")   # 能力前沿状态
    role.run_verification("pytest -q")       # 真实执行验证（返回证据）
    role.verify_validation(claim)            # 反造假核验
    role.check_freshness([{...}])            # 时效性闸门
    role.pareto_evaluate(candidates)         # 前沿判定
    role.capability()                        # 能力声明（含使用规则与时机）
"""
from __future__ import annotations

import os
import sys

_LOCAL_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT)


class ExpertiseAbility:
    """专家级架构能力（懒加载 border 依赖，失败不阻断角色可用）。"""

    def __init__(self, owner=None):
        self.owner = owner
        self._layer = None
        self._frontier = None
        # 延迟到首次使用再加载（避免 import 期读盘影响其它角色初始化）
        try:
            from expertise import (  # noqa: F401
                IndustryExpertLayer, AIFrontier, pareto,
                freshness, external_validation, evaluate, explain,
            )
            self._mods = {
                "IndustryExpertLayer": IndustryExpertLayer,
                "AIFrontier": AIFrontier,
                "pareto": pareto,
                "freshness": freshness,
                "external_validation": external_validation,
                "evaluate": evaluate,
                "explain": explain,
            }
        except Exception as exc:  # noqa: BLE001
            self._mods = None
            self._error = f"{type(exc).__name__}: {exc}"

    # -- 内部 ---------------------------------------------------------------
    def _require(self):
        if self._mods is None:
            raise RuntimeError(f"专家级架构能力未加载：{getattr(self, '_error', '未知原因')}")
        return self._mods

    def expert_layer(self):
        """行业/岗位专家层句柄（复用同一实例，避免重复读注册表）。"""
        mods = self._require()
        if self._layer is None:
            self._layer = mods["IndustryExpertLayer"]()
        return self._layer

    def ai_frontier(self):
        """AI 能力前沿句柄。"""
        mods = self._require()
        if self._frontier is None:
            self._frontier = mods["AIFrontier"]()
        return self._frontier

    # -- 七维评估 -----------------------------------------------------------
    def assess_expertise(self, assessment):
        """七维专家级评估（规范见 docs/EXPERT_ARCHITECT.md）。"""
        return self._require()["evaluate"](assessment)

    def explain_expertise(self, verdict):
        """把 verdict 渲染成人可读报告。"""
        return self._require()["explain"](verdict)

    # -- 专家层 -------------------------------------------------------------
    def resolve_industry(self, text):
        """需求 → (行业单元, 岗位列表)；专家层不可用时显式 unverified。"""
        return self.expert_layer().resolve(text)

    def industries(self):
        """已注册行业清单。"""
        return self.expert_layer().industries()

    # -- AI 前沿 ------------------------------------------------------------
    def ai_frontier_at(self, name):
        """某能力在当前时点的状态（陈旧即 unverified）。"""
        return self.ai_frontier().capability_at(name)

    def ai_solve_candidates(self):
        """下一步可利用的前沿能力清单。"""
        return self.ai_frontier().solve_candidates()

    # -- 外部验证 -----------------------------------------------------------
    def run_verification(self, command, cwd=None, timeout=120, expectation="exit0"):
        """**真实执行**一条验证命令，返回可留痕证据。"""
        return self._require()["external_validation"].run_check(
            command, cwd=cwd, timeout=timeout, expectation=expectation
        )

    def verify_validation(self, claim):
        """反造假核验：静态冒充/失败/超时/未来时间戳/自述 一律不可信。"""
        return self._require()["external_validation"].verify_claim(claim)

    def validation_gate(self, claims):
        """功能性代码验证门禁（一组证据全过才算过）。"""
        return self._require()["external_validation"].gate(claims)

    # -- 时效性 -------------------------------------------------------------
    def check_freshness(self, items):
        """信息时效性闸门。"""
        return self._require()["freshness"].gate(items)

    # -- 帕累托 -------------------------------------------------------------
    def pareto_evaluate(self, candidates, preferred=None):
        """多目标备选的前沿判定与可解释取舍。"""
        return self._require()["pareto"].evaluate(candidates, preferred=preferred)

    # -- 能力声明（供 CAPABILITY_INDEX / 自述对齐）--------------------------
    def capability(self):
        available = self._mods is not None
        return {
            "name": "expertise_ability",
            "version": "0.1.0",
            "available": available,
            "error": None if available else getattr(self, "_error", None),
            "source_of_truth": "local-agent/expertise/spec.py",
            "doc": "docs/EXPERT_ARCHITECT.md",
            "pillars": [
                "行业/岗位专家层（消费 hanghangchuzhuangyuan）",
                "AI 能力前沿层（data/ai-frontier.yaml，带时效）",
                "帕累托前沿（多目标支配与取舍解释）",
                "外部验证门禁（只认真实执行的功能性验证）",
                "时效性闸门（陈旧/无日期/无来源一律不可用）",
            ],
            "when_to_use": [
                "做架构设计/技术选型前：先 resolve_industry 定行业岗位，再 pareto_evaluate 比较备选",
                "声称'已完成/已测试'时：必须先 run_verification 拿真实证据，不接受自述",
                "引用任何外部事实时：先 check_freshness，陈旧信息不得作为依据",
                "判断'能不能做'时：先 ai_frontier_at，未收录/陈旧一律按 unverified 处理",
            ],
            "rules": [
                "判不出来 → unknown/unverified，不得默认通过",
                "七维缺一即 inadmissible，不论其它维度多高",
                "静态检查（grep/test -f）不算功能验证",
                "候选<2 时前沿判定不可信，不得据此选型",
            ],
        }
