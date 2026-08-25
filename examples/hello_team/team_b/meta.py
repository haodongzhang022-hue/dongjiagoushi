# -*- coding: utf-8 -*-
"""
hello_team · 小组B 交付模块 — meta.py
=========================================
由「分形小组B」开发：
  角色分工：架构·开发（实现）→ 架构·测试（单组自测）
职责：输出团队调度元数据（小组划分 / 角色 / 版本）。
本模块的元数据会被小组A的 greet.py 消费，验证跨小组数据互通。
"""
TEAM_META = {
    "team_count": 2,
    "teams": [
        {"team_id": "team_a", "role": "架构·开发", "module": "greet.py"},
        {"team_id": "team_b", "role": "架构·开发", "module": "meta.py"},
    ],
    "framework_version": "v2.dag-fractal",
}


def load_team_meta():
    """返回团队调度元数据 dict（小组A通过它读取 team_id）。"""
    return dict(TEAM_META)


def team_id() -> str:
    """便捷取当前（小组B视角）的 team_id。"""
    return "team_b"
