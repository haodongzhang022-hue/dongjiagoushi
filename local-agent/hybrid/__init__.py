# -*- coding: utf-8 -*-
"""
Hybrid 资源路由模块（Issue #57）
================================
把云端 CI 的 CPU 密集纯逻辑本地化，云端只保留 LLM 强相关操作。

显式公开接口（跨项目可复用参考）：
  - hybrid.router.HybridResourceRouter  核心路由（local/cloud 判定）
  - hybrid.worker.LocalWorker           本地批量测试执行器
  - hybrid.sync.ResultSync              结果同步留痕
  - hybrid.cost.CostMonitor             成本监测与报表（含 T6 三合一节省报表）
"""
from hybrid.router import HybridResourceRouter, RouteDecision, default_router
from hybrid.worker import LocalWorker, default_worker
from hybrid.sync import ResultSync, default_sync
from hybrid.cost import CostMonitor, default_monitor

__all__ = [
    "HybridResourceRouter",
    "RouteDecision",
    "default_router",
    "LocalWorker",
    "default_worker",
    "ResultSync",
    "default_sync",
    "CostMonitor",
    "default_monitor",
]
