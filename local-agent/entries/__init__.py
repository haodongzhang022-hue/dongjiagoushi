# -*- coding: utf-8 -*-
"""
多宿主入口适配层（entries · Issue #105 三入口归一化）
======================================================
用户诉求（Issue #105）：把三个执行入口（网页对话 / cnb.cool 云端 NPC / 本地
harness-AI）统一在一套仓库内、用「多层适配 + 配置管差异」，避免拆 3 个仓库
导致的开发对齐地狱，实现「一套核心规则、多宿主稳定运行」。

模块定位：
  - 主入口锁死「架构·秘书」：三入口都是「把话送到秘书面前」的通道，主入口
    永远一个（秘书→路由），其余只是触达方式。`guard_entry` 为强制护栏。
  - 差异收口到「适配层 + 执行地」两维度，做配置不做硬编码：入口适配
    （web / cnb / local）各实现最小宿主接口 `trigger / read_card / run_dag /
    scale_swarm`；本地 vs 云端执行走 `CLOUD_LOCAL_COOP.md` 分工边界。
  - 核心编排仅一份、无入口 if 分支污染：本模块只做「入口 → 适配器 → 单份核心」
    的路由，不把 if (entry==网页) 塞进 core。

注：目录取名 `entries`（复数）而非 `platform`，规避 Python 标准库同名
`platform` 模块遮蔽风险，保证第三方库 `import platform` 正常。

模块能力：
  - `adapter`  宿主无关的适配器抽象基类 + 三入口具体适配器 + 配置驱动的注册路由
  - `route`    入口归一化路由（把任意入口的一句话收敛到秘书主入口并落位适配器）
"""
from . import adapter, route, bridge, dashboard

__all__ = ["adapter", "route", "bridge", "dashboard"]
