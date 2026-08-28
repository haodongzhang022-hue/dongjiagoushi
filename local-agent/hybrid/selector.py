# -*- coding: utf-8 -*-
"""
IncrementalSelector · 增量测试选择器（Issue #65 · T2）
======================================================
`git diff` → 受影响测试选择器，含**依赖传播**：
  - 改公共模块（如 data/schema.py）→ 所有依赖它的测试全部纳入（防漏测）；
  - 只跑受影响的测试，不跑全量。

与 TestRegistry 的关系：
  - Registry 提供「测试脚本→覆盖源码模块」的静态映射；
  - Selector 消费 Registry，把 git diff 的变更文件映射为需运行的测试清单。

用法：
    from hybrid.selector import IncrementalSelector
    sel = IncrementalSelector()
    tests = sel.select(base="main", head="HEAD")   # 返回需运行的测试清单
"""
import os
import subprocess


class IncrementalSelector(object):
    """增量测试选择器：git diff → 受影响测试。"""

    def __init__(self, registry=None, repo_root=None):
        from hybrid.registry import TestRegistry, default_registry
        self.registry = registry or default_registry
        self.repo_root = repo_root or self._find_repo_root()

    @staticmethod
    def _find_repo_root():
        """从当前目录向上找 .git 目录（仓库根）。"""
        d = os.getcwd()
        while d != "/":
            if os.path.exists(os.path.join(d, ".git")):
                return d
            d = os.path.dirname(d)
        return os.getcwd()

    # ---------- git diff 解析 ----------
    def changed_files(self, base="main", head="HEAD"):
        """获取 base..head 之间的变更文件列表。

        返回 list[str]（相对仓库根的路径）。
        """
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...{head}"],
                capture_output=True, text=True, cwd=self.repo_root,
                timeout=30,
            )
            if proc.returncode != 0:
                # 回退：base..head 无公共祖先时用 base...head 的补集
                proc = subprocess.run(
                    ["git", "diff", "--name-only", base, head],
                    capture_output=True, text=True, cwd=self.repo_root,
                    timeout=30,
                )
            files = [f.strip() for f in proc.stdout.strip().split("\n") if f.strip()]
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def changed_staged(self):
        """获取已暂存（git diff --cached）的变更文件。"""
        try:
            proc = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True, cwd=self.repo_root,
                timeout=30,
            )
            files = [f.strip() for f in proc.stdout.strip().split("\n") if f.strip()]
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    # ---------- 选择逻辑 ----------
    def select(self, changed_files=None, base="main", head="HEAD", include_all_on_error=True):
        """根据变更文件选择需运行的测试脚本。

        参数：
          changed_files: 显式传入变更文件列表（若为 None 则走 git diff 解析）；
          base/head: git diff 的分支范围；
          include_all_on_error: diff 解析失败时是否回退全量（防漏测，保守安全）。

        返回：
          {"tests": [...], "changed_files": [...], "propagated": bool}
        """
        if changed_files is None:
            changed_files = self.changed_files(base=base, head=head)
            # 也包含已暂存文件
            staged = self.changed_staged()
            changed_files = list(set(changed_files) | set(staged))

        if not changed_files:
            return {"tests": [], "changed_files": [], "propagated": False}

        # 过滤掉非源码文件（如 .md 文档、.gitignore 等）
        source_files = [f for f in changed_files if self._is_source(f)]
        if not source_files:
            return {"tests": [], "changed_files": changed_files, "propagated": False}

        # 通过 registry 计算受影响测试
        tests = self.registry.affected(source_files)
        return {
            "tests": sorted(tests),
            "changed_files": sorted(source_files),
            "propagated": True,
        }

    # ---------- 内部工具 ----------
    @staticmethod
    def _is_source(filepath):
        """判断是否为源码文件（需要触发测试）。文档/配置/图片不算。"""
        # 排除文档、配置、图片、锁定文件
        ignore_exts = {".md", ".png", ".jpg", ".gif", ".svg", ".ico", ".lock"}
        if filepath.endswith(".cnb.yml") or filepath.startswith(".git/"):
            return False
        ext = os.path.splitext(filepath)[1].lower()
        if ext in ignore_exts:
            return False
        # 明确排除的路径
        if filepath in (".gitignore", "README.md", "AGENTS.md"):
            return False
        return True


# 便捷单例
default_selector = IncrementalSelector()
