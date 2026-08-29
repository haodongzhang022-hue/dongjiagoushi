# -*- coding: utf-8 -*-
"""
ParallelExecutor · 并行执行器（测试智能优化层 T4）
==================================================
改造现有 LocalWorker 支持并行：`-P` 并行度、超时聚合、失败隔离。

核心能力：
  - `run(scripts, parallel=1)`   并行批量执行测试脚本
  - 超时聚合：单脚本超时（timeout）不阻塞其他并行脚本
  - 失败隔离：单脚本失败不影响其他脚本执行（互不中断）
  - 与 LocalWorker 兼容：parallel=1 退化为串行

与 LocalWorker（v1.0）的关系：
  - 复用 LocalWorker.run_one() 的单脚本执行能力（含超时/失败兜底）；
  - 仅把「顺序 for」升级为「线程池并行」，产出结构一致（results + summary），
    向后兼容 `hybrid/worker.py` 的调用方。
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from hybrid.worker import LocalWorker


class ParallelExecutor(LocalWorker):
    """并行测试执行器（继承 LocalWorker，扩展 -P 并行）。"""

    def __init__(self, root_dir=None, timeout=300, dry_run=False, parallel=4):
        super(ParallelExecutor, self).__init__(
            root_dir=root_dir, timeout=timeout, dry_run=dry_run,
        )
        self.parallel = parallel   # 并行度（默认 4）

    # ---------- 并行执行 ----------
    def run_parallel(self, local_scripts, parallel=None):
        """并行批量执行测试脚本。

        parallel: 并行度；None 用实例默认（self.parallel）。
        返回结构与 LocalWorker.run() 一致：{results, summary}。
        """
        n = parallel or self.parallel
        n = max(1, int(n))
        scripts = list(local_scripts)
        if n == 1 or len(scripts) <= 1:
            # 串行退化（与 LocalWorker.run 结构一致 + 补 wall_seconds/parallel 字段）
            start = time.time()
            base = super(ParallelExecutor, self).run(scripts)
            base["summary"]["wall_seconds"] = round(time.time() - start, 3)
            base["summary"]["parallel"] = n
            return base

        results = []
        start = time.time()
        with ThreadPoolExecutor(max_workers=n) as ex:
            futs = {ex.submit(self.run_one, s): s for s in scripts}
            # as_completed：谁先完成先收谁（失败隔离，不互相阻塞）
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
        # 按脚本原始顺序排（稳定性）
        order = {s: i for i, s in enumerate(scripts)}
        results.sort(key=lambda r: order.get(r.get("script", ""), 0))
        wall = round(time.time() - start, 3)

        ok = sum(1 for r in results if r["exit_code"] == 0)
        return {
            "results": results,
            "summary": {
                "total": len(results),
                "pass": ok,
                "fail": len(results) - ok,
                "total_duration": round(sum(r["duration"] for r in results), 3),
                "wall_seconds": wall,          # 并行墙钟耗时（关键指标）
                "parallel": n,                 # 本次实际并行度
            },
        }

    # 兼容：run() 默认走并行（parallel=self.parallel）
    def run(self, local_scripts):
        return self.run_parallel(local_scripts, parallel=self.parallel)


# 便捷单例（默认 4 路并行）
default_executor = ParallelExecutor()
