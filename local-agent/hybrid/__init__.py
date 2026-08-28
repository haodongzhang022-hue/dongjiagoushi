# -*- coding: utf-8 -*-
"""
Hybrid 资源路由模块（Issue #57）+ 测试智能优化层（Issue #65）
=============================================================
把云端 CI 的 CPU 密集纯逻辑本地化，云端只保留 LLM 强相关操作。

v1.0（Issue #57）核心路由能力：
  - hybrid.router.HybridResourceRouter  核心路由（local/cloud 判定）
  - hybrid.worker.LocalWorker           本地批量测试执行器
  - hybrid.sync.ResultSync              结果同步留痕
  - hybrid.cost.CostMonitor             成本监测与报表

v2.0（Issue #65）测试智能优化层：
  - hybrid.cache.FingerprintCache       源码指纹缓存（缓存命中跳过）
  - hybrid.parallel.ParallelExecutor    并行测试执行器（多进程 + 超时 + 隔离）

显式公开接口（跨项目可复用参考）：
  - FingerprintCache / default_cache    源码指纹 + 缓存命中判定
  - ParallelExecutor / default_executor 并行执行 + 超时聚合 + 失败隔离
"""
from hybrid.router import HybridResourceRouter, RouteDecision, default_router
from hybrid.worker import LocalWorker, default_worker
from hybrid.sync import ResultSync, default_sync
from hybrid.cost import CostMonitor, default_monitor
from hybrid.cache import FingerprintCache, default_cache
from hybrid.parallel import ParallelExecutor, default_executor

__all__ = [
    # v1.0 路由
    "HybridResourceRouter",
    "RouteDecision",
    "default_router",
    "LocalWorker",
    "default_worker",
    "ResultSync",
    "default_sync",
    "CostMonitor",
    "default_monitor",
    # v2.0 测试智能优化层
    "FingerprintCache",
    "default_cache",
    "ParallelExecutor",
    "default_executor",
]
