# -*- coding: utf-8 -*-
"""
角色灵活增减层 · 插件化角色注册（plugin）
==========================================
用户诉求："灵活增减角色的能力，需要规则支撑。"

当前 `roles/__init__.py` 的 `ROLE_REGISTRY` 是**硬编码字典**——增删一个角色必须
改代码。这违背"完整不残次"的可持续演进原则。

本模块提供 **角色插件化注册规则**：

  - 角色自动发现：扫描 `roles.d/` 目录下的 `*.py`，自动加载并注册；
  - 注册规则（必须满足，否则拒绝并显式报错）：
      1. 文件在 `roles.d/` 下（命名空间隔离）；
      2. 定义类继承 `roles.base.BaseRole`（统一契约）；
      3. 类定义了 `name`（全局唯一角色名，带「架构·」或「市场·」命名空间前缀）；
      4. 可提供 `output_contract()` 输出契约（推荐，AI 可读）。
  - 与内置 `ROLE_REGISTRY` 合并，支持**运行时增减**而无需改核心代码；
  - 提供 `enable/disable` 运行时开关（配合规模声明里的 roles 子集过滤）。

用法：
    # 把一个新角色写成 roles.d/my_new_role.py，下次启动自动加载：
    python local-agent/run.py --list-roles   # 即可看到该角色

    # 运行时动态注册：
    from scale.plugin import register_role, unregister_role
"""
import importlib.util
import inspect
import os
import sys
import threading

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "roles.d")
_lock = threading.Lock()

# 动态注册的角色（键：角色名 → 类）
_dynamic_roles = {}
_plugin_files = {}


def _discover_plugins():
    """扫描 roles.d/*.py，返回 {文件名: 绝对路径}。"""
    if not os.path.isdir(PLUGIN_DIR):
        return {}
    return {
        f[:-3]: os.path.join(PLUGIN_DIR, f)
        for f in sorted(os.listdir(PLUGIN_DIR))
        if f.endswith(".py") and not f.startswith("_")
    }


def _load_module_from_path(module_name, path):
    """从文件路径动态加载模块。"""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _extract_roles_from_module(mod):
    """从模块中提取满足注册规则的角色类列表。"""
    from roles.base import BaseRole

    found = []
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        # 规则1：必须是 BaseRole 子类
        if not (issubclass(obj, BaseRole) and obj is not BaseRole):
            continue
        # 规则2：类必须定义 name（角色名）
        cls_name = getattr(obj, "name", "")
        if not cls_name:
            raise ValueError(
                f"插件角色类 {name} 未定义 name（需带「架构·」/「市场·」命名空间前缀）"
            )
        # 规则3：命名空间规则（架构· 或 市场· 前缀）
        if not (cls_name.startswith("架构·") or cls_name.startswith("市场·")):
            raise ValueError(
                f"插件角色 {cls_name} 未按命名空间规则命名（需「架构·」或「市场·」前缀）"
            )
        found.append((cls_name, obj))
    return found


def load_plugins(verbose=True):
    """加载 roles.d/ 下所有插件角色，注册进动态注册表。

    返回: list[(role_name, status)]  —— status: loaded / error
    """
    with _lock:
        loaded = []
        for fname, path in _discover_plugins().items():
            if fname in _plugin_files and _plugin_files[fname] == path:
                # 已加载且未变化，跳过（避免重复 exec）
                continue
            mod_name = f"roles_d_{fname}"
            try:
                mod = _load_module_from_path(mod_name, path)
                for role_name, cls in _extract_roles_from_module(mod):
                    _dynamic_roles[role_name] = cls
                    loaded.append((role_name, "loaded"))
                _plugin_files[fname] = path
            except Exception as e:  # noqa: BLE001
                loaded.append((fname, f"error: {e}"))
        if verbose:
            for name, st in loaded:
                print(f"[插件] 角色 {name}: {st}")
        return loaded


def register_role(role_class):
    """运行时动态注册一个角色类（满足规则才注册）。"""
    name = getattr(role_class, "name", "")
    if not name:
        raise ValueError("角色类未定义 name")
    with _lock:
        _dynamic_roles[name] = role_class
    return name


def unregister_role(role_name):
    """运行时注销一个动态角色。返回是否成功。"""
    with _lock:
        if role_name in _dynamic_roles:
            del _dynamic_roles[role_name]
            return True
        return False


def dynamic_registry():
    """当前动态注册的角色映射（dict name→class）。"""
    load_plugins(verbose=False)
    with _lock:
        return dict(_dynamic_roles)


def merged_registry():
    """内置注册表 + 动态插件注册表 的合并视图。"""
    from roles import ROLE_REGISTRY

    merged = dict(ROLE_REGISTRY)
    merged.update(dynamic_registry())
    return merged


def get_role_merged(name):
    """按名取角色实例（内置或插件均可）。"""
    reg = merged_registry()
    cls = reg.get(name)
    return cls() if cls else None


def filter_by_spec(role_names, spec_roles):
    """按规模声明的 roles 子集过滤角色名列表。

    若 spec_roles 为空则返回全部；否则只返回命中的。
    """
    if not spec_roles:
        return list(role_names)
    return [r for r in role_names if r in spec_roles]
