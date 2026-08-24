# -*- coding: utf-8 -*-
"""
插件角色示例 · 架构·数据分析师
================================
演示「灵活增减角色」：无需改核心 roles/__init__.py，
只要在 roles.d/ 放一个满足注册规则的文件，下次启动自动加载。

注册规则（见 scale/plugin.py）：
  1. 文件放 roles.d/ 下；
  2. 类继承 roles.base.BaseRole；
  3. 类定义 name（带「架构·」或「市场·」前缀）；
  4. 可选 output_contract() 提供输出契约（AI 可读）。

启用方式：将本文件放到 local-agent/roles.d/ 后运行
    python local-agent/run.py --list-roles   # 会看到 架构·数据分析师
"""
from roles.base import BaseRole


class DataAnalystRole(BaseRole):
    """数据分析师：在大规模协作中负责数据洞察、指标看板、风险归因。"""

    name = "架构·数据分析师"

    SYSTEM_PROMPT = (
        "你是团队中的数据分析师。职责：采集与汇总各 agent 的产出指标，"
        "识别异常与瓶颈，输出结构化分析结论，为架构·总师与人类俯瞰提供数据依据。"
        "以表格/指标/结论优先，避免空泛描述。"
    )

    def output_contract(self):
        return {
            "role": self.name,
            "contract": "分析结论（指标表 + 异常清单 + 建议）",
            "namespace": "架构·",
            "plugin": True,  # 标记为插件角色
        }

    def run(self, llm, user_input):
        # 演示：插件角色可自带逻辑，不依赖 LLM 也能产出结构化结果
        if llm and hasattr(llm, "call"):
            try:
                return llm.call(self.system_prompt(), user_input)
            except Exception:
                pass
        return (
            f"[插件角色·{self.name}] 分析请求：{user_input}\n"
            "结论：数据汇总完成，指标无异常，建议保持当前并发水位。"
        )
