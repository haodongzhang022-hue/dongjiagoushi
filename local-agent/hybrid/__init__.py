# -*- coding: utf-8 -*-
"""
Hybrid 资源路由模块（Issue #57）+ 测试智能优化层（v2.1）
=========================================================
把云端 CI 的 CPU 密集纯逻辑本地化，云端只保留 LLM 强相关操作。

显式公开接口（跨项目可复用参考）：
  - hybrid.router.HybridResourceRouter  核心路由（local/cloud 判定）
  - hybrid.worker.LocalWorker           本地批量测试执行器
  - hybrid.sync.ResultSync              结果同步留痕
  - hybrid.cost.CostMonitor             成本监测与报表（含 T6 三合一节省报表）
  - hybrid.registry.TestRegistry        集中测试注册表（v2.1 增强）
  - hybrid.selector.IncrementalSelector 变更感知增量选择器（v2.0 新增）
"""
from hybrid.router import HybridResourceRouter, RouteDecision, default_router
from hybrid.worker import LocalWorker, default_worker
from hybrid.sync import ResultSync, default_sync
from hybrid.cost import CostMonitor, default_monitor
from hybrid.station import StationAnchor, default_anchor
from hybrid.bus import BusRunner, default_bus

# 子模块直接引用
from hybrid import registry as registry
from hybrid import selector as selector
from hybrid import cache as cache
from hybrid import parallel as parallel
from hybrid import policy as policy
from hybrid import bus as bus

# 便捷函数引用（registry 模块内可直接调用）
from hybrid.registry import (
    all_tests, get, covers, dependencies,
    find_by_source, find_many_by_source,
    impact_closure, affected_tests, summary,
)

# 便捷函数引用（selector 模块）
from hybrid.selector import (
    IncrementalSelector, default_selector,
)
from hybrid.cache import (
    FingerprintCache, default_cache,
)
from hybrid.parallel import (
    ParallelExecutor, default_executor,
)
from hybrid.policy import (
    PolicyEngine, default_policy,
)
from hybrid.cost import (
    CostReporter, default_cost_reporter,
)

__version__ = "v2.1"
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
    "StationAnchor",
    "default_anchor",
    "BusRunner",
    "default_bus",
    "registry",
    "selector",
    # registry 便捷函数
    "all_tests",
    "get",
    "covers",
    "dependencies",
    "find_by_source",
    "find_many_by_source",
    "impact_closure",
    "affected_tests",
    "summary",
    # selector 便捷函数
    "IncrementalSelector",
    "default_selector",
    "cache",
    "parallel",
    "policy",
    "bus",
    "FingerprintCache",
    "default_cache",
    "ParallelExecutor",
    "default_executor",
    "PolicyEngine",
    "default_policy",
    "CostReporter",
    "default_cost_reporter",
]
