# -*- coding: utf-8 -*-
"""
拓扑对比模块（topology）
========================
在真实开发场景下对多条协作拓扑线路做对比测试与长时间判断。

模块能力：
  - `topologies`  拓扑线路定义（linear / dag / event）
  - `metrics`     对比指标收集与持久化
  - `runner`      对比执行器（同一需求跑不同拓扑，收集指标）

用法：
    # 列出拓扑
    python3 local-agent/topology/runner.py --list

    # 跑对比
    python3 local-agent/topology/runner.py --req "XX" --topologies linear,dag,event

    # 查看历史汇总
    python3 local-agent/topology/runner.py --summary
"""

# 不在此处 import runner，避免 -m 运行时的双重加载 warning
from . import topologies, metrics

__all__ = ["topologies", "metrics"]
