# -*- coding: utf-8 -*-
"""
ParallelExecutor · 并行测试执行器（Issue #65 · T4）
===================================================
在 LocalWorker 顺序执行的基础上，提供**并行执行**能力：

能力：
  - `run(scripts, max_workers)`：并行批量执行测试脚本（多进程）；
  - `-P/--parallel`：CLI 层开关（`-P N` 指定并行度）；
  - **超时聚合**：单个脚本超时统一记录为 `timeout`，不阻塞其他脚本；
  - **失败隔离**：单个脚本失败（非零退出/超时）不影响其他脚本继续执行；
  - **结果聚合**：汇总 pass/fail/timeout，与 LocalWorker 结果格式兼容。

设计原则：
  - 基于 `concurrent.futures.ProcessPoolExecutor`，天然支持并行 + 超时；
  - 与 LocalWorker 结果结构兼容：`{results, summary}`；
  - 纯逻辑 + 子进程执行，不依赖数据层。
"""
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed


def _run_one(script_path, root_dir, timeout):
    """子进程执行单个脚本（供 ProcessPoolExecutor 调用）。"""
    import subprocess
    start = time.time()
    try:
        proc = subprocess.run(
            ["bash", script_path],
            capture_output=True, text=True,
            timeout=timeout,
            cwd=root_dir,
        )
        duration = round(time.time() - start, 3)
        return {
            "script": script_path,
            "exit_code": proc.returncode,
            "duration": duration,
            "output": (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:],
            "status": "pass" if proc.returncode == 0 else "fail",
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start, 3)
        return {
            "script": script_path,
            "exit_code": 124,
            "duration": duration,
            "output": "[timeout %ss]" % timeout,
            "status": "timeout",
        }
    except Exception as e:  # noqa
        duration = round(time.time() - start, 3)
        return {
            "script": script_path,
            "exit_code": -1,
            "duration": duration,
            "output": "[error] %s" % e,
            "status": "error",
        }


class ParallelExecutor(object):
    """并行批量测试执行器。

    用法：
        from hybrid.parallel import ParallelExecutor
        ex = ParallelExecutor(max_workers=4, timeout=120)
        result = ex.run(["local-agent/tests/test_a.sh", "local-agent/tests/test_b.sh"])
    """

    def __init__(self, max_workers=4, timeout=120, root_dir=None, dry_run=False):
        self.max_workers = max(1, int(max_workers))
        self.timeout = timeout
        self.root_dir = root_dir or os.getcwd()
        self.dry_run = dry_run

    # ---------- 核心执行 ----------
    def run(self, scripts):
        """并行批量执行，返回 {results, summary}。

        - 单个脚本失败/超时不影响其他脚本（**失败隔离**）；
        - 超时统一记录 exit_code=124 + status=timeout（**超时聚合**）。
        """
        if self.dry_run:
            return self._dry_run(scripts)

        resolved = []
        for s in scripts:
            if os.path.isabs(s):
                resolved.append(s)
            else:
                resolved.append(os.path.join(self.root_dir, s))

        if not resolved:
            return {"results": [], "summary": self._summary([], [])}

        results = []
        # ProcessPoolExecutor 并行执行，收集所有结果
        with ProcessPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(_run_one, path, self.root_dir, self.timeout): path
                for path in resolved
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:  # noqa
                    results.append({
                        "script": futures[future],
                        "exit_code": -1,
                        "duration": 0,
                        "output": "[pool error] %s" % e,
                        "status": "error",
                    })

        # 按输入顺序排序（结果稳定，便于聚合）
        order = {p: i for i, p in enumerate(resolved)}
        results.sort(key=lambda r: order.get(r["script"], 0))

        summary = self._summary(results, [])
        return {"results": results, "summary": summary}

    # ---------- 批量执行（带超时聚合） ----------
    def run_many(self, scripts, per_script_timeout=None):
        """批量执行，支持 per_script_timeout 统一覆盖。

        兼容 LocalWorker.run() 接口签名，方便替换。
        """
        if per_script_timeout is not None:
            old_timeout = self.timeout
            self.timeout = per_script_timeout
            result = self.run(scripts)
            self.timeout = old_timeout
            return result
        return self.run(scripts)

    # ---------- 结果聚合 ----------
    def _summary(self, results, _ignored):
        """汇总结果：pass / fail / timeout / error 计数 + 总耗时。"""
        pass_count = sum(1 for r in results if r.get("status") == "pass")
        fail_count = sum(1 for r in results
                         if r.get("status") in ("fail", "error"))
        timeout_count = sum(1 for r in results if r.get("status") == "timeout")
        total_dur = round(sum(r.get("duration", 0) for r in results), 3)
        return {
            "total": len(results),
            "pass": pass_count,
            "fail": fail_count,
            "timeout": timeout_count,
            "total_duration": total_dur,
        }

    # ---------- 演练模式 ----------
    def _dry_run(self, scripts):
        """dry_run 模式：不真执行，直接生成假结果（CI 演练用）。"""
        results = []
        for s in scripts:
            results.append({
                "script": s,
                "exit_code": 0,
                "duration": 0.001,
                "output": "[dry-run] would run: %s" % s,
                "status": "pass",
            })
        return {"results": results, "summary": self._summary(results, [])}


# 便捷单例
default_executor = ParallelExecutor(max_workers=4)
