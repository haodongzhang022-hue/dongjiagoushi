# -*- coding: utf-8 -*-
"""
规模伸缩层 · 并发执行池（pool）
================================
当前 orchestrator.py 的 DAG 波次虽标记「可并行」，但实际用 `for nid in wave`
逐个串行执行——**并发是纸面上的，不是真并发**。2500 个 agent 无法被如此调度。

本模块提供 **并发执行池**：

  - 线程池：默认，适合 IO 密集的 LLM 调用（天然契合 agent 团队）；
  - 异步：预留（asyncio，后续事件循环模式）；
  - 并发度：通过 `--concurrency` / `POOL_SIZE` 环境变量控制（模拟 2500 并发规模）；
  - 与 broker 消息总线 + store 分片状态配合，实现真正的并行协作。

用法：
    from scale.pool import run_concurrent

    results = run_concurrent(
        [("agentA", fn_a), ("agentB", fn_b), ...],
        max_workers=2500,
    )
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_POOL_SIZE = int(os.environ.get("POOL_SIZE", "4"))
_pool_lock = threading.Lock()


def set_pool_size(n):
    """动态调整默认并发池大小。"""
    global _POOL_SIZE
    _POOL_SIZE = max(1, int(n))


def get_pool_size():
    return _POOL_SIZE


def run_concurrent(tasks, max_workers=None):
    """并发执行一批任务。

    参数:
      tasks: list[(agent_id, fn)]，fn 为可调用对象（无参或接受 ctx）
      max_workers: 并发度；默认取 POOL_SIZE 或 env
    返回:
      dict {agent_id: result}
    """
    workers = max_workers or _POOL_SIZE
    results = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for agent_id, fn in tasks:
            futures[ex.submit(fn)] = agent_id
        for fut in as_completed(futures):
            aid = futures[fut]
            try:
                results[aid] = fut.result()
            except Exception as e:  # noqa: BLE001
                errors[aid] = str(e)
    return {"results": results, "errors": errors, "concurrency": workers}


def run_wave(wave_items, max_workers=None):
    """并发执行一个 DAG 波次。

    参数:
      wave_items: list[(node_id, fn)]
    返回:
      dict {node_id: result}
    """
    return run_concurrent(wave_items, max_workers)
