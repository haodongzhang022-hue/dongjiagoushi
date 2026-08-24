# -*- coding: utf-8 -*-
"""
上位机 · 工程能力引擎包（engine）
=================================
将「定时器」+「状态机」组合为上位机对机器角色的统一管理内核：
  - state_machine: 机器角色任务的状态流转（合法转移强制校验 + 留痕）
  - timer: 周期心跳巡检 / 超时检测 / 定时触发
  - host: 上位机运行内核（把两者挂到编排 / 角色上，统一入口）

详见 docs/HOST_ENGINE.md。
"""
from .state_machine import StateMachine, is_valid_transition, STATES
from .timer import TimerEngine
from .host import HostEngine

__all__ = [
    "StateMachine", "is_valid_transition", "STATES",
    "TimerEngine", "HostEngine",
]
