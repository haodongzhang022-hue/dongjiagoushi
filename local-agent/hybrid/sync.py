# -*- coding: utf-8 -*-
"""
结果同步（ResultSyncer）
========================
将本地执行结果同步回云端留痕——commit + push .cnb-results/ 目录。

流程：
  1. 读取 .cnb-results/results.json
  2. git add .cnb-results/
  3. git commit（带结果摘要）
  4. git push（到当前分支）
"""

import json
import os
import subprocess
from pathlib import Path

RESULTS_DIR = Path(".cnb-results")
RESULTS_FILE = RESULTS_DIR / "results.json"


class ResultSyncer:
    """本地结果同步器。"""

    def __init__(self, workspace=None, branch=None):
        self.workspace = Path(workspace or os.getcwd())
        self.branch = branch

    def _git(self, *args):
        """执行 git 命令并返回输出。"""
        proc = subprocess.run(
            ["git", "-C", str(self.workspace)] + list(args),
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def sync(self, commit_msg=None):
        """同步本地结果到云端。返回 (success, message)。"""
        if not (self.workspace / RESULTS_FILE).exists():
            return False, f"结果文件不存在: {RESULTS_FILE}"

        # 读取结果摘要
        try:
            with open(self.workspace / RESULTS_FILE, encoding="utf-8") as f:
                results = json.load(f)
            summary = (
                f"[hybrid-sync] 本地测试 {results.get('passed', 0)}/"
                f"{results.get('total', 0)} 通过, "
                f"{results.get('failed', 0)} 失败, "
                f"{results.get('duration', 0)}s"
            )
        except (json.JSONDecodeError, OSError) as e:
            summary = f"[hybrid-sync] 结果读取失败: {e}"

        # git add
        rc, _, err = self._git("add", str(RESULTS_DIR))
        if rc != 0:
            return False, f"git add 失败: {err}"

        # 检查是否有变更
        rc, status, _ = self._git("status", "--porcelain", str(RESULTS_DIR))
        if not status:
            return True, "无变更，跳过 commit"

        # git commit
        commit_msg = commit_msg or summary
        rc, _, err = self._git("commit", "-m", commit_msg)
        if rc != 0:
            # 可能没有配置 user
            self._git("config", "user.name", "hybrid-sync-bot")
            self._git("config", "user.email", "hybrid-sync@cnb.cool")
            rc, _, err = self._git("commit", "-m", commit_msg)
            if rc != 0:
                return False, f"git commit 失败: {err}"

        # git push
        if self.branch:
            rc, _, err = self._git("push", "origin", f"HEAD:{self.branch}")
        else:
            rc, _, err = self._git("push")
        if rc != 0:
            return False, f"git push 失败: {err}"

        return True, summary


def sync_results(workspace=None, branch=None):
    """便捷函数：创建 ResultSyncer 并执行同步。"""
    return ResultSyncer(workspace=workspace, branch=branch).sync()
