# -*- coding: utf-8 -*-
"""模型路由规范 · 唯一事实源（Issue #147 · module model-routing v0.3.0-update）

用户诉求（Issue #147 第三版）：
  - 模型指定**收敛到一个配置文件**统一管理（`models.yml`）；
  - **不指定就默认通用**：未在 roles 中列出的角色继承 default；
  - **允许对某个角色单独指定**：roles 下按角色名覆盖（默认不启用定制）；
  - **改配置必须长期生效**（非单次有效）：配置在**每次解析时**加载，不缓存死值；
  - **多级降级链**：主通道 → 二选备用 → 三选备用（如 v4.1-flash → codebuddy → glm-5.3-flash）。

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
_FALLBACK_CHAIN = ("deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash")
_FALLBACK_SIGNALS = (
    "unavailable", "timeout", "connection_error", "rate_limit",
    "402", "403", "429", "500", "502", "503", "504",
)

_MISSING = object()


def _load_raw():
    """加载配置文件（YAML）；失败返回 None（走兜底）。

    ★ 每次调用都重新读取（不缓存）——保证「后来改配置也生效」，
      不是单次有效；改 models.yml 无需重启/重装。
    """
    path = config_path()
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


def _raw():
    return _load_raw() or {}


def config_path():
    """返回当前生效的配置文件路径（供文档/CLI 显示）。"""
    return os.environ.get(CONFIG_ENV) or CONFIG_FILE


def _chain_of(block):
    """从一段配置（default 或 role 覆盖）解析渠道链。

    支持两种写法：
      ① 新写法：`chain: [m1, m2, m3]`（优先）；
      ② 旧写法：`primary: m1` + `fallback: m2`（兼容，等价 chain=[m1, m2]）。
    返回按优先级排序、去重的元组；空块返回 ()。
    """
    if not isinstance(block, dict):
        return ()
    chain = block.get("chain", _MISSING)
    out = []
    if isinstance(chain, (list, tuple)):
        out = [str(x) for x in chain if x]
    if not out:
        # 旧写法兼容：primary + fallback
        p, f = block.get("primary"), block.get("fallback")
        out = [str(x) for x in (p, f) if x]
    # 去重保序
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return tuple(uniq)


def default_chain():
    """通用默认渠道链（不指定角色时用）。配置缺失 → 内置兜底链。"""
    c = _chain_of(_raw().get("default"))
    return c or _FALLBACK_CHAIN


def role_chain(role=None):
    """解析某角色的渠道链：roles[role] 覆盖 default（字段级）。

    - role 为空 / 未在 roles 中 → 继承 default（「不指定就默认通用」）；
    - roles[role].chain 存在 → 整链覆盖；
    - 只写 primary/fallback → 该子链覆盖后，用 default 链**补全尾部**（不缩短降级链）。
    """
    base = list(default_chain())
    if not role:
        return tuple(base)
    roles = _raw().get("roles") or {}
    ov = roles.get(role) or {}
    if not isinstance(ov, dict):
        return tuple(base)
    ov_chain = _chain_of(ov)
    if not ov_chain:
        return tuple(base)
    # 整链覆盖：ov 自带 chain（新写法）→ 直接用
    if isinstance(ov.get("chain"), (list, tuple)):
        return ov_chain
    # 旧写法（primary/fallback 子链）→ 覆盖头部，default 链补全剩余档位
    merged = list(ov_chain)
    for m in base:
        if m not in merged:
            merged.append(m)
    return tuple(merged)


def default_policy():
    """通用默认策略（不指定角色时用）——保留 primary/fallback 兼容字段。"""
    c = default_chain()
    return {"chain": list(c), "primary": c[0], "fallback": c[-1] if len(c) > 1 else c[0]}


def role_policy(role=None):
    """解析某角色的策略：roles[role] 覆盖 default 的对应字段。

    - role 为空 / 未在 roles 中 → 继承 default（「不指定就默认通用」）；
    - 返回 chain（完整链）+ primary（首档）+ fallback（末档），字段级覆盖兼容。
    """
    c = role_chain(role)
    return {"chain": list(c), "primary": c[0], "fallback": c[-1] if len(c) > 1 else c[0]}


def role_overrides():
    """返回所有显式指定的角色（供俯瞰：哪些角色被单独指定）。"""
    roles = _raw().get("roles") or {}
    return {k: v for k, v in roles.items() if isinstance(v, dict)}


def unavailable_signals():
    """渠道不通判定信号（触发降级）。"""
    sig = _raw().get("unavailable_signals")
    if isinstance(sig, (list, tuple)) and sig:
        return tuple(str(s) for s in sig)
    return _FALLBACK_SIGNALS


# ---- 向后兼容常量（从配置派生，非硬编码）----
_DEFAULT = default_policy()
PRIMARY = _DEFAULT["primary"]
FALLBACK = _DEFAULT["fallback"]


def channels(role=None):
    """按优先级返回渠道定义（主 → 二选 → 三选 …），可按角色覆盖。"""
    chain = role_chain(role)
    descs = {0: "一选主通道", 1: "二选备用通道（主渠道不通时启用）",
             2: "三选备用通道（前两档均不通时启用）"}
    out = []
    for idx, model in enumerate(chain):
        if idx == 0:
            ch_role = "primary"
        elif idx == 1:
            ch_role = "fallback"
        else:
            ch_role = f"fallback{idx}"
        out.append({"priority": idx + 1, "model": model, "role": ch_role,
                    "desc": descs.get(idx, f"{idx + 1}选备用通道")})
    return out


def channel_order(role=None):
    """返回按优先级排序的模型列表（主 → 备 → 三备）。"""
    return [c["model"] for c in channels(role)]


# 兼容旧接口：默认策略 + 渠道列表
DEFAULT_POLICY = dict(_DEFAULT)
CHANNELS = channels()
UNAVAILABLE_SIGNALS = unavailable_signals()
