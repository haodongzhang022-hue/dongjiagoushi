# -*- coding: utf-8 -*-
"""
TestRegistry · 测试注册表（Issue #65 · T1）
=============================================
集中声明 32 个本地测试脚本 → 覆盖源码模块 + 依赖关系。

解决「COVERS 头散落在各测试脚本」的架构问题：
  - 元数据从 32 个分散注释中收敛到**集中 JSON**（数据驱动）；
  - 支持程序化查询：按源码文件 → 找到需要跑的测试脚本；
  - 支持依赖传播：公共模块变更 → 所有依赖它的测试全部纳入。

设计原则：
  - **数据驱动**：`test_registry.json` 为唯一事实来源，本模块提供查询接口；
  - **无外部硬依赖**：纯逻辑 + json 读取，可独立测试；
  - **解耦**：不 import data/collab 等运行时模块，只做映射查询。

用法：
    from hybrid.registry import TestRegistry, default_registry
    reg = TestRegistry()
    reg.tests_for_file("local-agent/hybrid/router.py")   # → [测试脚本名...]
    reg.tests_for_module("hybrid")                        # → 覆盖 hybrid 模块的测试
    reg.affected("local-agent/data/schema.py")           # → 含依赖传播的测试清单
"""
import json
import os

# 注册表数据文件位置（相对本文件）
_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_registry.json")


class TestRegistry(object):
    """测试注册表：集中声明测试脚本→源码模块映射。"""

    def __init__(self, data_file=None):
        self.data_file = data_file or _DATA_FILE
        self._registry = self._load()

    # ---------- 数据加载 ----------
    def _load(self):
        """从 JSON 文件加载注册表。文件不存在则返回空注册表。"""
        if not os.path.exists(self.data_file):
            return {"version": "1.0", "scripts": {}}
        with open(self.data_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # ---------- 查询接口 ----------

    @property
    def scripts(self):
        """返回 {测试脚本名: {covers:[...], depends_on:[...]}}。"""
        return self._registry.get("scripts", {})

    def all_script_names(self):
        """全部测试脚本名列表。"""
        return sorted(self.scripts.keys())

    def covers_of(self, script_name):
        """返回某测试脚本覆盖的源码模块/文件列表。"""
        meta = self.scripts.get(script_name, {})
        return meta.get("covers", [])

    def depends_on(self, script_name):
        """返回某测试脚本的依赖源码列表（依赖传播用）。"""
        meta = self.scripts.get(script_name, {})
        return meta.get("depends_on", [])

    def tests_for_file(self, filepath):
        """按源码文件路径 → 找到需要跑的测试脚本列表。

        匹配规则（前缀匹配）：
          - 精确匹配：文件路径完整包含在 covers 中；
          - 目录匹配：文件路径的父目录在 covers 中（如 covers="local-agent/hybrid" 匹配
            "local-agent/hybrid/router.py"）；
          - 模块匹配：文件属于某模块目录（如 covers="hybrid" 匹配 "local-agent/hybrid/..."）。
        """
        filepath = self._normalize(filepath)
        result = []
        for name, meta in self.scripts.items():
            covers = meta.get("covers", [])
            if self._match(filepath, covers):
                result.append(name)
        return sorted(result)

    def tests_for_module(self, module_name):
        """按模块名（如 "hybrid"、"data"、"collab"）→ 找到覆盖该模块的测试。"""
        module_name = self._normalize(module_name)
        result = []
        for name, meta in self.scripts.items():
            covers = meta.get("covers", [])
            for c in covers:
                c = self._normalize(c)
                if module_name in c or c in module_name:
                    result.append(name)
                    break
        return sorted(result)

    def affected(self, filepaths):
        """按变更文件列表 → 返回需运行的测试清单（含依赖传播）。

        依赖传播规则：
          1. 直接匹配：变更文件在测试脚本的 covers 中 → 该测试纳入；
          2. 依赖传播：变更文件是公共基础设施（如 data/schema.py），
             所有 depends_on 包含该文件的测试也纳入（防漏测）；
          3. 去重：同一测试不重复出现。
        """
        if isinstance(filepaths, str):
            filepaths = [filepaths]
        normalized_files = [self._normalize(f) for f in filepaths]

        # 直接匹配
        direct = set()
        for f in normalized_files:
            for t in self.tests_for_file(f):
                direct.add(t)

        # 依赖传播：找到所有 depends_on 包含变更文件的测试
        propagated = set()
        for f in normalized_files:
            for name, meta in self.scripts.items():
                deps = meta.get("depends_on", [])
                normalized_deps = [self._normalize(d) for d in deps]
                if any(self._match(f, [d]) for d in normalized_deps):
                    propagated.add(name)

        return sorted(direct | propagated)

    def summary(self):
        """注册表摘要：脚本总数 + 覆盖模块数。"""
        scripts = self.scripts
        all_covers = set()
        for meta in scripts.values():
            all_covers.update(meta.get("covers", []))
        return {
            "total_scripts": len(scripts),
            "total_covers": len(all_covers),
            "covers": sorted(all_covers),
        }

    # ---------- 内部工具 ----------
    @staticmethod
    def _normalize(path):
        """规范化路径：去前导 './'，去尾部 '/'。"""
        p = path.strip().lstrip("./")
        return p.rstrip("/")

    def _match(self, filepath, covers):
        """判断 filepath 是否命中 covers 中任一规则。

        命中规则：
          - covers 项与 filepath 相同（精确匹配文件）；
          - covers 项是 filepath 的父目录（目录前缀匹配）；
          - covers 项是模块名，filepath 包含该模块路径（模块匹配）。
        """
        fp = self._normalize(filepath)
        for c in covers:
            c = self._normalize(c)
            if c == fp:
                return True
            # 目录前缀：covers="local-agent/hybrid" 匹配 "local-agent/hybrid/router.py"
            if fp.startswith(c + "/"):
                return True
            # 模块名：covers="hybrid" 匹配 "local-agent/hybrid/router.py"
            if c in fp.split("/"):
                return True
        return False


# 便捷单例
default_registry = TestRegistry()
