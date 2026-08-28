# -*- coding: utf-8 -*-
"""
TestRegistry · 集中测试注册表
==============================
把仓库全部 CPU 密集测试脚本的「脚本路径 → 覆盖源码模块 + 依赖」关系集中到
registry.json，提供统一查询接口供增量选择器 / 缓存层 / 策略引擎消费。

核心能力：
  - `load()`               加载 registry.json 到内存（带缓存）
  - `all_tests()`          返回全部已注册测试
  - `get(test)`            按脚本路径查单个测试的元信息
  - `covers(test)`         返回该测试覆盖的源码模块列表
  - `dependencies(test)`   返回该测试的前置依赖测试
  - `find_by_source(path)` 反向：给定源码文件 → 返回受影响的测试清单
  - `impact_closure(test)` 传递闭包：给定测试 → 所有直接/间接依赖它的测试
  - `summary()`            注册表概览（数量/按 kind 分组）

本模块是纯逻辑，无外部依赖，不写库——查询结果由上层（缓存/选择器）消费。
"""
import json
import os
import threading

__version__ = "v2.0"

# 单例锁（并发查询安全）
_lock = threading.Lock()
_cache = None
_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")


def _load_raw():
    """加载 registry.json 原始内容（内部）。"""
    global _cache
    with _lock:
        if _cache is None:
            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        return _cache


def reload():
    """强制重新加载注册表（文件变更后调用）。"""
    global _cache
    with _lock:
        _cache = None
    return _load_raw()


def load():
    """返回注册表顶层 dict（含 version/tests 等字段）。"""
    return _load_raw()


def all_tests():
    """返回全部已注册测试脚本路径 list。"""
    return sorted(load()["tests"].keys())


def count():
    """返回已注册测试总数。"""
    return len(all_tests())


def get(test):
    """按脚本路径查单个测试的元信息 dict；未注册返回 None。"""
    return load()["tests"].get(test)


def get_name(test):
    """返回测试名（不含路径/扩展名）。"""
    info = get(test)
    return info["name"] if info else None


def covers(test):
    """返回该测试覆盖的源码模块路径 list。"""
    info = get(test)
    return list(info.get("covers", [])) if info else []


def dependencies(test):
    """返回该测试的前置依赖测试脚本路径 list（直接依赖）。"""
    info = get(test)
    return list(info.get("depends_on", [])) if info else []


def find_by_source(source_path):
    """反向查询：给定源码文件/模块路径 → 返回受影响的测试脚本路径 list。

    支持精确匹配和目录前缀匹配（如 "topology/" 匹配覆盖 topology/ 下所有文件的测试）。
    同时支持文件前缀匹配（如 "topology/router" 匹配 "topology/router.py"）。
    """
    tests = load()["tests"]
    hits = []
    sp = source_path.rstrip("/")  # 去尾斜杠方便比较
    for test_path, info in tests.items():
        for covered in info.get("covers", []):
            cv = covered.rstrip("/")
            # 精确匹配、covered 目录包含 source、或 source 目录包含 covered、或文件前缀匹配
            if (sp == cv or
                sp.startswith(cv + "/") or
                cv.startswith(sp + "/") or
                cv.startswith(sp)):
                hits.append(test_path)
                break
    return sorted(set(hits))


def find_many_by_source(source_paths):
    """批量反向查询：多个源码路径 → 去重后的受影响测试清单。"""
    result = set()
    for sp in source_paths:
        result.update(find_by_source(sp))
    return sorted(result)


def impact_closure(test):
    """传递闭包：给定测试 → 所有依赖它的测试（含间接依赖，防漏测）。

    例如 A depends_on B，则 B 变更后需跑 B 和 A。
    用 DFS 遍历所有依赖方向。
    """
    tests = load()["tests"]
    visited = set()

    def dfs(t):
        if t in visited:
            return
        visited.add(t)
        info = tests.get(t)
        if not info:
            return
        # 谁依赖 t ？ 即 scan 所有测试 whose depends_on 含 t
        for other, oinfo in tests.items():
            if t in oinfo.get("depends_on", []):
                dfs(other)

    dfs(test)
    # 返回依赖闭包（含自身）
    return sorted(visited)


def affected_tests(changed_files):
    """综合入口：给定变更文件清单 → 返回需要运行的测试清单。

    1. 对每个变更文件用 find_by_source 找直接覆盖的测试；
    2. 对找到的测试做 impact_closure（依赖传播防漏测）；
    3. 去重排序返回。
    """
    direct = find_many_by_source(changed_files)
    result = set()
    for t in direct:
        result.update(impact_closure(t))
    return sorted(result)


def summary():
    """注册表概览。"""
    data = load()
    tests = data["tests"]
    kinds = {}
    for info in tests.values():
        k = info.get("kind", "unknown")
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "version": data.get("version"),
        "total": len(tests),
        "by_kind": kinds,
        "generated_at": data.get("generated_at"),
    }


# 便捷单例
default_registry = {
    "all_tests": all_tests,
    "get": get,
    "covers": covers,
    "dependencies": dependencies,
    "find_by_source": find_by_source,
    "find_many_by_source": find_many_by_source,
    "impact_closure": impact_closure,
    "affected_tests": affected_tests,
    "summary": summary,
    "reload": reload,
    "count": count,
}
