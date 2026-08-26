# -*- coding: utf-8 -*-
"""
高尔顿板（Galton Board）MVP 原型 · 模块接口
============================================
模拟高尔顿板物理原理的软件流水线，验证「球路由 → 加工 → 合并」闭环：

  Router（钉子）→ Worker×3（路径加工）→ Aggregator（槽位归集）

物理对照：
  - 球（Ball）     = 输入任务中的一个数据项
  - Router（钉子） = 将每个球按策略路由到 3 个 Worker 之一
  - Worker（路径） = 对球做「加工」（统计/标记/变换）
  - Aggregator     = 收集全部 Worker 产出，合并成最终分布结果

本模块对外能力收口到显式公开接口（__init__.py 导出 + docstring + 单测），
跨项目可独立抽取复用。

模块版本：galton v0.1 (init)
"""
from .engine import (
    WORKER_COUNT,
    route_ball,
    worker_process,
    aggregate,
    run_galton,
)

__all__ = [
    "WORKER_COUNT",
    "route_ball",
    "worker_process",
    "aggregate",
    "run_galton",
]

__version__ = "0.1.0"
