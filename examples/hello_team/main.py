# -*- coding: utf-8 -*-
"""
hello_team · 统一交付入口 — main.py
=====================================
端到端验证：两个分形小组（A/B）各自交付后，由「架构·小组长」整合、
统一向上交付；本入口把小组A的 greet 与小组B的 meta 拼成最终结果，
证明跨小组数据互通、协作链路完整。
"""
import sys
import os

# 便于直接以脚本运行：把 team_a / team_b 加入模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_a"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_b"))

from team_a.greet import greet
from team_b.meta import load_team_meta


def deliver() -> dict:
    """整合两个小组的交付，返回最终结果。"""
    meta = load_team_meta()
    greeting = greet("CNB团队")
    return {
        "framework_version": meta["framework_version"],
        "team_count": meta["team_count"],
        "greeting": greeting,
        "status": "delivered",
    }


if __name__ == "__main__":
    print(deliver())
