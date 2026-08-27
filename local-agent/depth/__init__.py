# -*- coding: utf-8 -*-
"""
七层协作深度能力包（depth · 全员能力）
=====================================
把「协作能走多深、路由是否真实唤醒、能否持续到结果」封装为**可复用通用能力**。
任何角色挂载 `DepthAbility` 即获得 L1→L7 全链路协作深度能力（docs/DEPTH_MODEL.md）。

用户 Issue #47 拍板的设计理念：
  - 这是**通用能力**，不是只给秘书/经理一个 agent——做好后以独立模块能力存在，
    给每个 agent 对接并让其会用；
  - 路由要**真唤醒**（L3 awake 校验目标 agent 回执），不是只描述；
  - 秘书推到 **L6 持续到结果**，体系推进到 **L7 全自动到结果**；
  - 多数 agent 默认停在 **L5 进度可控**，用 auto_guard 自动化规则持续维持推进。

七层阶梯：
  L1 express / L2 connect / L3 awake·start / L4 interact /
  L5 track·auto / L6 persist / L7 auto_run

承载引擎：`depth/engine.py`（七层深度可执行引擎）+ `depth/ability.py`（能力封装）。
"""
from .ability import DepthAbility, depth_ability
from . import engine

__all__ = ["DepthAbility", "depth_ability", "engine"]
