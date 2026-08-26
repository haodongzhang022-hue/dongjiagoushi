# -*- coding: utf-8 -*-
"""架构·评审：五维评审/复评 + 统一处置标签。与 settings.yml 同源。"""
from .base import BaseRole

try:
    from collab import disposition
except Exception:  # noqa: BLE001
    disposition = None


class ReviewerRole(BaseRole):
    name = "架构·评审"

    SYSTEM_PROMPT = """
你是「架构·评审」，本团队代码质量守门员。接手必交：
- 五维评审：语法 / 异味 / 最佳实践 / 性能 / 重复
- 分级：🔴必修 / 🟡建议 / 🟢优化
- 统一处置标签：**每次评审必须给出一个规范处置标签**（不能漏、不能自定义），
  从规范集合中取：merge(适合合并)/proceed(适合推进)/fix_bug(适合改bug)/
  research(适合调研)/human(适合移交人类判断)/consult(适合专家会诊)/vote(适合投票)
- 仅评改动新增/改动行

协作纪律：🔴必修项必须指出并推动修复，复评至清零才放行；结论发回接力卡供下游接力。
触达协议：显式[触发:架构·评审]/语义命中"评审/审查/走查/质量"即进入本角色；
发现🔴必修必须打回（[回转]退回开发），复评清零才放行。
统一处置标签：处置标签是评审输出契约的**必填字段**，缺标签即评审未完成。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "五维评审(five_dimensions)",
                "分级(severity: 🔴/🟡/🟢)",
                "统一处置标签(disposition: merge/proceed/fix_bug/research/human/consult/vote)",
                "复评结论(recheck)",
            ],
        }

    def dispose(self, problem="", severity=None, signals=None, scenario_hint=""):
        """评审结论 → 规范处置标签 + 自动化流程（强制必有标签）。"""
        if disposition is None:
            # 引擎不可用时兜底：按严重级给一个稳定标签，仍保证必有
            sev = str(severity or "")
            if "🔴" in sev or "red" in sev.lower():
                return {"disposition": "fix_bug"}
            if "🟢" in sev or "green" in sev.lower():
                return {"disposition": "merge"}
            return {"disposition": "proceed"}
        return disposition.route_for_review(problem=problem, severity=severity,
                                            signals=signals, scenario_hint=scenario_hint)
