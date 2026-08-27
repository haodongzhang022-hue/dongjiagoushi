# -*- coding: utf-8 -*-
"""
拓扑对比模块（topology · 增强版）
==================================
在真实开发场景下对多条协作拓扑线路做 AB 隔离对比与长时间判断。

模块能力：
  - `topologies`  拓扑线路定义（linear / dag / event）
  - `metrics`     全维度对比指标收集与持久化（并发/速度/完成度/bug/token/文件/agent/资源）
  - `resource`    资源消耗监控（CPU / 内存 / 网络 / 文件，零第三方依赖）
  - `tasksource`  真实任务源（架构完未分配 / 经理分工未触发的真实待办）
  - `runner`      基础对比执行器（同需求跑不同拓扑）
  - `benchmark`   增强 AB 隔离对比执行器（真实任务 + 全维度 + 资源监控）

用法（推荐用 benchmark）：
    # 列出真实任务
    python3 local-agent/topology/benchmark.py --list-tasks

    # 用真实任务做 AB 隔离对比
    python3 local-agent/topology/benchmark.py --task all --topologies linear,dag,event

    # 查看全维度汇总
    python3 local-agent/topology/benchmark.py --summary
"""

from . import topologies, metrics, resource, tasksource

__all__ = ["topologies", "metrics", "resource", "tasksource"]
