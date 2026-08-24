# -*- coding: utf-8 -*-
"""角色基类：定义统一执行接口。"""


class BaseRole:
    """所有角色继承。子类实现 SYSTEM_PROMPT 与 output_contract()。"""

    name = ""
    SYSTEM_PROMPT = ""

    def system_prompt(self):
        return self.SYSTEM_PROMPT

    def output_contract(self):
        """返回该角色的输出契约（结构化描述），供占位/测试/LLM 统一使用。"""
        return {"role": self.name, "contract": "未定义"}

    def run(self, llm, user_input):
        """执行角色：调用 llm 后端，返回输出。"""
        return llm.call(self.system_prompt(), user_input)
