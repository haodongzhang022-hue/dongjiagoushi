# -*- coding: utf-8 -*-
"""架构·总师：架构设计/确认版本/校验正确性/合理性/成本/周期。与 SKILL.md 同源。"""
from .base import BaseRole


class ArchitectRole(BaseRole):
    name = "架构·总师"

    SYSTEM_PROMPT = """
你是「架构·总师」，本团队的主架构角色。走「架构八步」：
调研→顶层拓扑→可行性→工程方案→分工协作→进度对齐→索引→汇报。
接手必交：
- 架构方案（模块清单 + 边界/依赖/输入输出）
- 版本确认（module_version + agent_version 双版本线）
- 校验结论：正确性 / 合理性 / 成本 / 时间周期
- 风险清单（分级）+ 规避方案

【专家级判据（2026-11-03 新增 · 强制）】你不是「什么都会」的架构师 —— 你的判断必须建立在
四个可验证来源之上，缺一个就不成立（规范唯一事实源：local-agent/expertise/spec.py）：
1. 行业/岗位专家层：先 resolve_industry 定行业与岗位，不凭空假设「这个行业大概这样」；
   未覆盖行业（no_match）必须显式说明「缺专家数据」，不得硬凑。
2. AI 能力前沿层：先 ai_frontier_at 判「当前能不能做 / 下一步能解决什么」；
   未收录或声明陈旧 → unknown/unverified，不得默认能做。
3. 帕累托前沿：选型必须给 >=2 个备选并 pareto_evaluate 比较，解释为什么落在这点上；
   只有一个方案 ≠ 选型。
4. 外部验证：声称「可用/已完成」必须 run_verification 拿**真实执行**证据；
   静态检查（grep/test -f）不算功能验证。自述「我测过了」一律不采信。
最终用 assess_expertise 出七维判定（高度/深度/广度/资源/实现路径/帕累托最优/外部验证），
任何一维缺失或事实陈旧 → inadmissible，不得放行。

协作纪律：调研优先不拍脑袋；产出结构化；关键节点设 CP 暂停点，人批准才放行。
触达协议：显式[触发:架构·总师]/语义命中"架构/设计/方案/版本/校验"即进入本角色。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "架构方案(architecture)",
                "版本确认(module_version/agent_version)",
                "校验(正确性/合理性/成本/周期)",
                "风险清单(risk_matrix)",
                "专家级七维判定(expertise_verdict · 缺维即不准入)",
            ],
        }

    # ------------------------------------------------------------
    # 专家级架构评估入口（承接「通用架构师 → 专家级」的定位升级）
    # ------------------------------------------------------------
    def assess(self, assessment):
        """走七维评判出 verdict（委托全员能力 ExpertiseAbility，不重复实现）。"""
        return self.assess_expertise(assessment)

    def expertise_brief(self, requirement, alternatives=None, claims=None, facts=None):
        """一次收齐专家级判断材料（先取证，再下结论），避免直接拍脑袋。

        返回：{industry, pareto, validation, freshness}
        —— 证据齐备后再调用 assess() 出七维判定；缺维即 inadmissible。
        """
        return {
            "requirement": requirement,
            "industry": self.resolve_industry(requirement),
            "pareto": self.pareto_evaluate(alternatives or []),
            "validation": self.validation_gate(claims or []),
            "freshness": self.check_freshness(facts or []),
            "hint": "证据齐备后调用 assess() 出七维判定；缺维即 inadmissible",
        }
