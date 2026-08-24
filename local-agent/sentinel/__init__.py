# -*- coding: utf-8 -*-
"""
sentinel · 监控哨兵包
=====================
「防无效努力 / 目标收敛监控」机制的可执行核心。

背景：团队协作中，角色可能陷入"反复尝试同一个错误 / 在距目标近似距离反复横跳 /
原地打转"，这些**无效努力**既浪费算力又导致**目标偏差**。本包提供**量化到目标距离**
的进度刻度与机器判定引擎，命中即触发「打断→重新规划→上报架构师助理」三级处置，
主动显式暴露风险，不事后兜底。

模块：
  - store.py   目标进度尺(goal_meters) + 监控动作(sentinel_actions) 数据访问
  - detect.py  停滞 / 横跳 / 重复错误 判定引擎
  - engine.py  哨兵统一处置协议（track → interrupt/escalate）

由「架构·监控哨兵」角色（roles/sentinel.py）统一执行；规则见 docs/SENTINEL.md。
"""
from sentinel import store, detect, engine

__all__ = ["store", "detect", "engine"]
