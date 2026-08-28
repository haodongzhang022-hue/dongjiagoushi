# -*- coding: utf-8 -*-
"""
Hybrid 资源路由模块 · 模块接口
================================
本地/云端混合协同调度——把纯 CPU 密集操作本地化，云端只保留 LLM 强相关操作。

核心组件：
  - Router（HybridResourceRouter）  : 判断任务路由到本地还是云端
  - Worker（LocalWorker）           : 本地批量执行器（跑测试/脚本/管线）
  - Sync（ResultSyncer）            : 结果同步回云端留痕
  - Cost（CostMonitor）             : 成本监测与节省量化报表
  - CLI                            : 统一命令行入口

模块版本：hybrid v0.1 (init)
"""
from .router import (
    HybridResourceRouter,
    RESOURCE_LOCAL,
    RESOURCE_CLOUD,
    RESOURCE_AUTO,
    classify_task,
)
from .worker import LocalWorker, run_tests_local
from .sync import ResultSyncer, sync_results
from .cost import CostMonitor, estimate_savings

__all__ = [
    "HybridResourceRouter",
    "RESOURCE_LOCAL",
    "RESOURCE_CLOUD",
    "RESOURCE_AUTO",
    "classify_task",
    "LocalWorker",
    "run_tests_local",
    "ResultSyncer",
    "sync_results",
    "CostMonitor",
    "estimate_savings",
]

__version__ = "0.1.0"
