# -*- coding: utf-8 -*-
"""
IncrementalSelector · 变更感知增量测试选择器
============================================
把「每次全量跑 43 个 CPU 密集测试」优化为「只跑受变更影响的测试」。

核心能力：
  - `changed_files(base, head)`  用 git diff 获取两个提交间的变更文件
  - `select(changed)`            给定变更文件 → 返回需运行的测试清单（含依赖传播）
  - `incremental(base, head)`    一键：git diff → 受影响测试（增量选择）

与 TestRegistry（T1）的关系：
  - 本模块消费 registry 数据（registry.json 或 registry.py 接口）；
  - 默认使用 `hybrid.registry`（T1 提供）；如未合并，自动读 registry.json 兜底。

本模块是纯逻辑 + git 子进程，无额外外部依赖。
"""
import json
import os
import subprocess


# registry.json 路径（与 T1 的 registry.py 同目录）
_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")


class IncrementalSelector(object):
    """变更感知增量测试选择器。"""

    def __init__(self, root_dir=None, registry=None):
        self.root_dir = root_dir or os.getcwd()
        self._registry = registry      # 可选注入（T1 的 registry 模块）
        self._reg_data = None          # 内置 registry.json 数据缓存

    # ---------- registry 数据访问 ----------
    def _load_registry_data(self):
        """加载 registry 数据。

        优先用外部注入的 registry 模块；否则尝试 import hybrid.registry；
        最后回退到直接读 registry.json。
        """
        if self._reg_data is not None:
            return self._reg_data
        # 尝试注入/import registry
        if self._registry is not None:
            tests = self._registry.all_tests()
            # 构造与 registry.json 相同结构
            self._reg_data = {"tests": {}}
            for t in tests:
                info = self._registry.get(t) or {}
                self._reg_data["tests"][t] = info
            return self._reg_data
        # 尝试 import hybrid.registry（T1 已合并时）
        try:
            from hybrid import registry as reg
            tests = reg.all_tests()
            self._reg_data = {"tests": {}}
            for t in tests:
                info = reg.get(t) or {}
                self._reg_data["tests"][t] = info
            return self._reg_data
        except (ImportError, AttributeError):
            pass
        # 回退：直接读 registry.json
        if os.path.exists(_REGISTRY_PATH):
            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                self._reg_data = json.load(f)
            return self._reg_data
        raise RuntimeError(
            "TestRegistry 数据不可用：registry.json 不存在且 hybrid.registry 无法导入"
        )

    @property
    def registry(self):
        return self._registry

    # ---------- git diff ----------
    def changed_files(self, base="HEAD~1", head="HEAD"):
        """获取 base 到 head 之间变更的文件清单。

        默认比较上一个提交到当前提交（单提交增量）。
        也支持 base='origin/main' 等任意 git 引用。
        返回值：变更文件路径 list（新增/修改/删除）。
        """
        cmd = ["git", "diff", "--name-only", base, head]
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=self.root_dir, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError("git diff failed: %s" % proc.stderr[-500:])
        files = [f for f in proc.stdout.strip().split("\n") if f.strip()]
        return files

    def changed_files_workdir(self):
        """获取工作区未提交的变更文件清单（git diff --name-only）。

        用于本地开发时的增量选择（尚未提交的变更）。
        """
        cmd = ["git", "diff", "--name-only"]
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=self.root_dir, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError("git diff failed: %s" % proc.stderr[-500:])
        files = [f for f in proc.stdout.strip().split("\n") if f.strip()]
        # 加上已暂存但未提交的（git diff --cached）
        proc2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True,
            cwd=self.root_dir, timeout=30,
        )
        if proc2.returncode == 0:
            for f in proc2.stdout.strip().split("\n"):
                if f.strip() and f not in files:
                    files.append(f.strip())
        return files

    # ---------- 选择逻辑 ----------
    def _find_by_source(self, source_path):
        """在 registry 数据中查找覆盖给定源码的测试。

        与 T1 registry v2.1 一致的路径归一化：`local-agent/` 前缀与裸路径
        **双向兼容**。无论 source_path / covers 是否带 `local-agent/` 前缀，
        都生成两个变体（带前缀 / 裸路径）参与匹配，保证：
          - `local-agent/collab/engine.py` 与 `collab/engine.py` 视为等价；
          - 注册表 covers 统一为 `local-agent/` 前缀时，裸路径变更也能命中。
        """
        data = self._load_registry_data()
        tests = data.get("tests", {})
        sp = source_path.rstrip("/")
        # 双向归一化：源路径同时生成「裸路径 / 带 local-agent/ 前缀」两个变体
        sp_variants = {sp}
        if sp.startswith("local-agent/"):
            sp_variants.add(sp[len("local-agent/"):])
        else:
            sp_variants.add("local-agent/" + sp)

        hits = []
        for test_path, info in tests.items():
            for covered in info.get("covers", []):
                cv = covered.rstrip("/")
                # covers 同样做双向归一化（防御：注册表内未统一前缀也兼容）
                cv_variants = {cv}
                if cv.startswith("local-agent/"):
                    cv_variants.add(cv[len("local-agent/"):])
                else:
                    cv_variants.add("local-agent/" + cv)
                matched = False
                for s in sp_variants:
                    for c in cv_variants:
                        if (s == c or
                            s.startswith(c + "/") or
                            c.startswith(s + "/") or
                            c.startswith(s)):
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    hits.append(test_path)
                    break
        return sorted(set(hits))

    def _impact_closure(self, test):
        """依赖传播闭包：给定测试 → 所有依赖它的测试（含间接）。"""
        data = self._load_registry_data()
        tests = data.get("tests", {})
        visited = set()

        def dfs(t):
            if t in visited:
                return
            visited.add(t)
            for other, oinfo in tests.items():
                if t in oinfo.get("depends_on", []):
                    dfs(other)

        dfs(test)
        return sorted(visited)

    def select(self, changed_files):
        """给定变更文件清单 → 返回需运行的测试脚本路径 list。

        内部用 registry 数据完成映射 + 依赖传播。
        """
        if not changed_files:
            return []
        # 过滤掉测试脚本自身（.sh 变更不触发测试）
        source_files = [f for f in changed_files if not f.endswith(".sh")]
        direct = set()
        for sf in source_files:
            direct.update(self._find_by_source(sf))
        result = set()
        for t in direct:
            result.update(self._impact_closure(t))
        return sorted(result)

    def suggest_tests(self, changed_files):
        """变更未命中 registry 覆盖时的**候选测试推断**（防"假绿"兜底）。

        `select()` 只认 registry 登记的 covers；一旦变更落在**未登记的模块**
        （新增模块、纯文档、新脚本）上，select() 返回空 → CI 以前直接回落"只跑
        核心冒烟"，等于该模块一个测试都没跑却显示通过（Issue #166 踩过：
        comment_stream 新增模块没登记 registry，CI 跳过了它的信号灯）。

        这里按**命名约定**反推候选：变更路径里的模块名（如
        `local-agent/comment_stream/reader.py` → `comment_stream`）去匹配
        `tests/test_<name>*.sh` / `local-agent/tests/test_<name>*.sh`。
        只返回**磁盘上真实存在**的脚本，推断不出就返回空（让调用方回落冒烟）。

        Args:
            changed_files: git 变更文件清单
        Returns:
            list: 候选测试脚本路径（仓库根相对），按路径排序
        """
        if not changed_files:
            return []
        root = self.root_dir
        test_dirs = [os.path.join("local-agent", "tests"), "tests"]
        available = {}
        for d in test_dirs:
            full = os.path.join(root, d)
            if not os.path.isdir(full):
                continue
            for fn in os.listdir(full):
                if fn.startswith("test_") and fn.endswith(".sh"):
                    available[os.path.join(d, fn)] = fn

        hits = set()
        for f in changed_files:
            parts = f.rstrip("/").split("/")
            # 变更文件所属模块名：取父目录名（新增模块的源码/文档都能命中）
            mods = set()
            if len(parts) >= 2:
                mods.add(parts[-2])
            if parts and parts[-1].endswith(".py"):
                mods.add(parts[-1][:-3])
            # docs/FOO.md / docs/adr/0007-foo.md 也按文件名推断
            stem = os.path.splitext(parts[-1])[0]
            if stem:
                mods.add(stem.replace("-", "_").split("_0")[0])
            for mod in mods:
                mod = mod.strip().lower()
                if len(mod) < 4:
                    continue
                for path, fn in available.items():
                    tname = fn[len("test_"):-len(".sh")].lower()
                    if tname == mod or tname.startswith(mod) or mod.startswith(tname):
                        hits.add(path)
        return sorted(hits)

    def incremental(self, base="HEAD~1", head="HEAD"):
        """一键增量选择：git diff → 受影响测试。"""
        files = self.changed_files(base, head)
        return self.select(files)

    def incremental_workdir(self):
        """一键增量选择：工作区变更 → 受影响测试。"""
        files = self.changed_files_workdir()
        return self.select(files)

    # ---------- 全量兜底 ----------
    def full_suite(self):
        """返回全部已注册测试（全量兜底）。"""
        data = self._load_registry_data()
        return sorted(data.get("tests", {}).keys())


# 便捷单例
default_selector = IncrementalSelector()
