# -*- coding: utf-8 -*-
"""模型路由规范 · 唯一事实源（Issue #147 · module model-routing v0.2.0-update）

用户诉求（Issue #147 第二版）：
  - 模型指定**收敛到一个配置文件**统一管理（`models.yml`）；
  - **不指定就默认通用**：未在 roles 中列出的角色继承 default；
  - **允许对某个角色单独指定**：roles 下按角色名覆盖；
  - 改模型只改一处（models.yml），无需跨文件检查/修改散点写死。

铁律：模型 ID / 渠道优先级只在 `models.yml` 声明一次。
  本文件是「读配置的代码层」——负责加载 + 解析 + 暴露稳定接口，
  自身不做任何模型 ID 硬编码（仅保留一份兜底常量防配置损坏时彻底不可用）。
其他层（.cnb.yml / llm 后端 / 文档 / 测试）都从这里读取，禁止各自取名。
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_HERE, "models.yml")
CONFIG_ENV = "MODEL_ROUTING_CONFIG"  # 可指向自定义配置文件（部署多环境用）

# 兜底常量（仅当配置文件缺失/损坏时启用，保证系统仍可用不崩）
_FALLBACK_DEFAULT = {"primary": "deepseek-v4.1-flash", "fallback": "glm-5.3-flash"}
_FALLBACK_SIGNALS = (
    "unavailable", "timeout", "connection_error", "rate_limit",
    "402", "403", "429", "500", "502", "503", "504",
)


def _load_raw():
    """加载配置文件（YAML）；失败返回 None（走兜底）。"""
    path = os.environ.get(CONFIG_ENV) or CONFIG_FILE
    if not os.path.exists(path):
        return None
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


_RAW = _load_raw() or {}


def config_path():
    """返回当前生效的配置文件路径（供文档/CLI 显示）。"""
    return os.environ.get(CONFIG_ENV) or CONFIG_FILE


def default_policy():
    """通用默认策略（不指定角色时用）。"""
    d = _RAW.get("default") or {}
    return {
        "primary": d.get("primary") or _FALLBACK_DEFAULT["primary"],
        "fallback": d.get("fallback") or _FALLBACK_DEFAULT["fallback"],
    }


def role_policy(role=None):
    """解析某角色的策略：roles[role] 覆盖 default 的对应字段。

    - role 为空 / 未在 roles 中 → 继承 default（「不指定就默认通用」）；
    - roles[role] 只写 primary → fallback 仍继承 default（字段级覆盖）。
    """
    base = default_policy()
    if not role:
        return base
    roles = _RAW.get("roles") or {}
    ov = roles.get(role) or {}
    if not isinstance(ov, dict):
        ov = {}
    return {
        "primary": ov.get("primary") or base["primary"],
        "fallback": ov.get("fallback") or base["fallback"],
    }


def role_overrides():
    """返回所有显式指定的角色（供俯瞰：哪些角色被单独指定）。"""
    roles = _RAW.get("roles") or {}
    return {k: v for k, v in roles.items() if isinstance(v, dict)}


def unavailable_signals():
    """渠道不通判定信号（触发降级）。"""
    sig = _RAW.get("unavailable_signals")
    if isinstance(sig, (list, tuple)) and sig:
        return tuple(str(s) for s in sig)
    return _FALLBACK_SIGNALS


# ---- 向后兼容常量（从配置派生，非硬编码）----
_DEFAULT = default_policy()
PRIMARY = _DEFAULT["primary"]
FALLBACK = _DEFAULT["fallback"]


def channels(role=None):
    """按优先级返回渠道定义（主 → 备），可按角色覆盖。"""
    p = role_policy(role)
    return [
        {"priority": 1, "model": p["primary"], "role": "primary",
         "desc": "一选主通道"},
        {"priority": 2, "model": p["fallback"], "role": "fallback",
         "desc": "二选备用通道（主渠道不通时启用）"},
    ]


def channel_order(role=None):
    """返回按优先级排序的模型列表（主 → 备）。"""
    return [c["model"] for c in channels(role)]


# 兼容旧接口：默认策略 + 渠道列表
DEFAULT_POLICY = dict(_DEFAULT)
CHANNELS = channels()
UNAVAILABLE_SIGNALS = unavailable_signals()
