# -*- coding: utf-8 -*-
"""
LocalWorker · 本地执行器
=========================
在本地批量执行被 HybridResourceRouter 判定为「纯 CPU 逻辑」的测试脚本
（云端已移除这些命令，故本地必须接住并跑出结果，云端只留 LLM 强相关）。

能力：
  - `plan()`：根据路由结果生成待本地执行的脚本清单；
  - `run()`：顺序批量执行本地脚本（含超时保护），逐条收集退出码/耗时/输出；
  - `run_all()`：把「判定 + 执行 + 汇总」一链路跑通，供 CLI/脚本直接调用。

本模块是**纯逻辑 + 子进程执行**，不依赖数据层，结果交由 sync 模块留痕。
"""
import os
import shlex
import subprocess
import time


class LocalWorker(object):
    """本地批量测试执行器。"""

    def __init__(self, root_dir=None, timeout=300, dry_run=False):
        self.root_dir = root_dir or os.getcwd()
        self.timeout = timeout      # 单脚本超时（秒）
        self.dry_run = dry_run      # True：只打印不真跑（CI 演练用）

    # ---------- 计划 ----------
    def plan(self, local_scripts):
        """把 local 脚本清单转成可执行命令清单（含路径解析）。"""
        plan = []
        for s in local_scripts:
            plan.append(self._resolve(s))
        return plan

    def _resolve(self, script):
        # 绝对路径直接返回；相对路径拼到 root_dir
        if os.path.isabs(script):
            return script
        return os.path.join(self.root_dir, script)

    # ---------- 执行 ----------
    def run_one(self, script):
        """执行单个脚本，返回 {script, exit_code, duration, output}。"""
        cmd = self._resolve(script)
        start = time.time()
        if self.dry_run:
            duration = time.time() - start
            return {"script": script, "exit_code": 0, "duration": round(duration, 3),
                    "output": "[dry-run] would run: %s" % script}
        try:
            proc = subprocess.run(
                ["bash", cmd],
                capture_output=True, text=True,
                timeout=self.timeout,
                cwd=self.root_dir,
            )
            duration = time.time() - start
            return {
                "script": script,
                "exit_code": proc.returncode,
                "duration": round(duration, 3),
                "output": (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:],
            }
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            return {"script": script, "exit_code": 124, "duration": round(duration, 3),
                    "output": "[timeout %ss]" % self.timeout}
        except Exception as e:  # noqa
            duration = time.time() - start
            return {"script": script, "exit_code": -1, "duration": round(duration, 3),
                    "output": "[error] %s" % e}

    def run(self, local_scripts):
        """批量执行，逐条记录，返回结果列表 + 汇总。"""
        results = [self.run_one(s) for s in local_scripts]
        ok = sum(1 for r in results if r["exit_code"] == 0)
        total_dur = round(sum(r["duration"] for r in results), 3)
        return {
            "results": results,
            "summary": {
                "total": len(results),
                "pass": ok,
                "fail": len(results) - ok,
                "total_duration": total_dur,
            },
        }

    # ---------- 一键链路 ----------
    def run_all(self, local_scripts):
        """判定已由外部完成，直接执行并返回 run() 结构。"""
        return self.run(local_scripts)


# 便捷单例
default_worker = LocalWorker()
