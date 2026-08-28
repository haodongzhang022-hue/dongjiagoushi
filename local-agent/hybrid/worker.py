# -*- coding: utf-8 -*-
"""
本地执行器（LocalWorker）
=========================
在本地批量执行测试/脚本/管线，产出结果 JSON 供 sync 同步回云端留痕。

核心能力：
  - run_command      : 执行单条命令并捕获输出
  - run_test_suite   : 批量执行测试脚本
  - run_all_tests    : 跑全量 37 个测试脚本（本地化清单）
  - write_results    : 写出 .cnb-results/results.json
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RESULTS_DIR = Path(".cnb-results")
RESULTS_FILE = RESULTS_DIR / "results.json"
DEFAULT_TIMEOUT = 600  # 10 分钟


class LocalWorker:
    """本地批量执行器。"""

    def __init__(self, workspace=None, timeout=DEFAULT_TIMEOUT):
        self.workspace = Path(workspace or os.getcwd())
        self.timeout = timeout
        self.results = {
            "timestamp": "",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": 0,
            "tests": [],
        }

    def run_command(self, cmd, cwd=None):
        """执行单条命令，返回 (returncode, stdout, stderr)。"""
        cwd = cwd or self.workspace
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"TIMEOUT ({self.timeout}s)"

    def run_test_suite(self, scripts):
        """批量执行测试脚本，记录每个脚本的通过/失败状态。"""
        start = time.time()
        self.results["tests"] = []

        for script in scripts:
            script_path = self.workspace / script
            if not script_path.exists():
                self.results["tests"].append({
                    "name": script,
                    "status": "skipped",
                    "message": "file not found",
                    "duration": 0,
                })
                self.results["skipped"] += 1
                continue

            s_time = time.time()
            rc, stdout, stderr = self.run_command(f"bash {script}")
            duration = round(time.time() - s_time, 2)

            status = "passed" if rc == 0 else "failed"
            self.results["tests"].append({
                "name": script,
                "status": status,
                "message": stdout[-500:] if rc == 0 else (stderr[-500:] or stdout[-500:]),
                "duration": duration,
            })

            if rc == 0:
                self.results["passed"] += 1
            else:
                self.results["failed"] += 1

        self.results["total"] = len(self.results["tests"])
        self.results["duration"] = round(time.time() - start, 2)
        self.results["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return self.results

    def write_results(self):
        """将结果写入 .cnb-results/results.json。"""
        RESULTS_DIR.mkdir(exist_ok=True)
        RESULTS_FILE.write_text(
            json.dumps(self.results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(RESULTS_FILE)

    def run_all_tests(self):
        """跑全量本地化测试脚本。"""
        from .router import LOCAL_TEST_SCRIPTS
        return self.run_test_suite(LOCAL_TEST_SCRIPTS)


def run_tests_local(scripts=None):
    """便捷函数：创建 LocalWorker 并批量执行测试。"""
    worker = LocalWorker()
    if scripts is None:
        return worker.run_all_tests()
    return worker.run_test_suite(scripts)
