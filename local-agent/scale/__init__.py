# -*- coding: utf-8 -*-
"""
规模伸缩层（scale）—— 本次架构升级核心
========================================
把体系从「单进程串行 + 单文件接力卡 + 硬编码角色表」升级为
「可伸缩蜂群协作平台」的四件套：

  - broker   agent 间消息总线（发布/订阅/定向投递/广播）
  - store    按 agent 分片的状态存储（替代单文件接力卡）
  - pool     并发执行池（真并行波次，支持 2500 级并发模拟）
  - spec     团队规模/分工层级/并发度声明（与 AI 交互的入口）
  - profile  前置流程区分（不同位置的流程模板）
  - plugin   角色插件化注册（灵活增减角色的规则支撑）

对外统一入口：`run_scaled_pipeline()`（见 scale/engine.py）。
"""
from . import broker, store, pool, spec, profile, plugin

__all__ = ["broker", "store", "pool", "spec", "profile", "plugin"]
