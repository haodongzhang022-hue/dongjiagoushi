# -*- coding: utf-8 -*-
"""模型路由规范 · 唯一事实源（Issue #147 · module model-routing v0.3.0-update）

用户诉求（Issue #147 第三版 · Issue #182 收紧）：
  - 模型指定**收敛到一个配置文件**统一管理（`models.yml`）；
  - **角色逐个指定（Issue #182 收紧）**：`.cnb/settings.yml` 里声明的每个角色
    在 `roles` 下都必须显式写出自己的链；未写明的角色**不再悄悄继承 default**，
    而是走 `fallback_chain` 且在 `role_policy()` 里标 `specified=False`（可审计）；
  - **角色别名归一**：`role_aliases` 让「架构·开发」与「开发」指向同一条配置，
    避免云端传全称、配置写短名而匹配不上；
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


def resolve_alias(model):
    """模型名别名归一（`deepseek-v4.1-flash-1017` → `deepseek-v4.1-flash`）。

    Issue #182：用户口中的版本串（如 1017）与平台精确 ID 常不一致。
    别名表 `alias` 是**唯一**的翻译处——右侧必须是平台可选列表里真实存在的 ID，
    否则写错一个字符就是 `is not in the optional models list` → 整个 stage error，
    评论 @ 角色整条唤醒链路静默失效（#177 事故）。所以这里只做映射，不臆造。
    """
    if not model:
        return model
    table = _raw().get("alias") or {}
    if not isinstance(table, dict):
        return model
    return str(table.get(model, model))


def default_chain():
    """通用默认渠道链（不指定角色时用）。配置缺失 → 内置兜底链。"""
    c = _chain_of(_raw().get("default"))
    return c or _FALLBACK_CHAIN


def fallback_chain():
    """继承兜底链（角色未显式指定时的去向，仍属 default 体系）。

    设计意图（Issue #182）：`default.chain` 主档可能随全局调整，
    但未在 `roles` 里逐个写明的角色，应走一条**明确声明过的兜底链**，
    不再悄悄等同 default——否则"以为配了角色、其实全在走默认"无法被发现。
    未配置时退回 default_chain。
    """
    c = _chain_of(_raw().get("fallback_chain"))
    return c or default_chain()


def role_aliases():
    """角色别名表（`{规范名: [写法A, 写法B]}`，由配置唯一声明，不写死代码）。"""
    aliases = _raw().get("role_aliases") or {}
    return aliases if isinstance(aliases, dict) else {}


def role_candidates(role):
    """该角色在配置里的候选名（规范名 + 全部写法，**含自身**）。

    Issue #182 真实断点：别名表把「架构·开发」规一到短名 `开发`，
    但 `roles` 里写的是全称 —— 单靠"归一后只查一个名"会两头对不上。
    所以查配置时同时接受两种写法：自身优先，其次规范名。
    """
    if not role:
        return []
    alias = role_alias(role)          # 归一后的规范短名
    out = [str(role)]
    if alias and str(alias) not in out:
        out.append(str(alias))
    # 规范名 → 它的其它写法也一并认（配置可能写在任一写法下）
    names = role_aliases().get(str(alias))
    if isinstance(names, (list, tuple)):
        for n in names:
            if str(n) not in out:
                out.append(str(n))
    return out


def role_alias(role):
    """角色别名归一（`架构·开发` → 配置里声明的短名，如 `开发`）。

    解决「同一个角色两种写法」——云端 `@org/repo(架构·开发)` 传全称，
    配置里若写短名就匹配不上。别名表由 `role_aliases` 唯一声明，不写死代码。
    """
    if not role:
        return role
    for canonical, names in role_aliases().items():
        names = names if isinstance(names, (list, tuple)) else [names]
        if role == canonical or role in [str(n) for n in names]:
            return str(canonical)
    return role


def role_override(role):
    """取该角色的覆盖块（兼容全称/短名两种写法），未配置返回 {}。"""
    roles = _raw().get("roles") or {}
    for name in role_candidates(role):
        blk = roles.get(name)
        if isinstance(blk, dict):
            return blk
    return {}


def is_role_specified(role=None):
    """该角色是否**显式**在 roles 里指定过（防"以为配了其实没配"）。"""
    if not role:
        return False
    return bool(_chain_of(role_override(role)))


def role_at(role, idx=0):
    """取某角色渠道链的第 idx 档模型（0=主档）。越界返回末档，永不返回空。"""
    c = role_chain(role)
    if not c:
        return _FALLBACK_CHAIN[0]
    return c[idx] if idx < len(c) else c[-1]


def role_chain(role=None):
    """解析某角色的渠道链（**角色逐个指定 · 不再静默继承默认**）。

    解析顺序（固定）：
      1. 角色别名（`role_aliases`，含「架构·开发」→ `开发` 这类前缀归一）；
      2. roles[角色] 整链 / 子链；
      3. **default.fallback_chain**（继承兜底链，仍属 default 体系）；
      4. 内置兜底常量。
    「未列出的角色」不再悄悄继承 default，而是继承 `fallback_chain`——
    配置漂移会暴露成显式未指定（`is_role_specified()` 可查），而不是伪装成"已指定"。

    - role 为空 → 直接走 default（「不指定就默认通用」只在 role 缺失时生效）；
    - roles[角色].chain 存在 → 整链覆盖；
    - 只写 primary/fallback → 该子链覆盖后，用 fallback_chain **补全尾部**（不缩短降级链）。
    """
    base = list(fallback_chain())
    if not role:
        return tuple(default_chain())
    ov = role_override(role)
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


def settings_path():
    """`.cnb/settings.yml` 路径（角色声明的事实源）。"""
    root = os.path.dirname(os.path.dirname(_HERE))  # local-agent/.. = 仓库根
    return os.path.join(root, ".cnb", "settings.yml")


def declared_roles():
    """`.cnb/settings.yml` 里声明的全部 NPC 角色名（`npc.roles[].name`）。

    Issue #182：「角色逐个指定模型」要能机器体检——声明的角色一个都不能漏配，
    否则又回到「以为是默认、其实没人管」。读不到 settings 时返回空（不误报）。
    """
    path = settings_path()
    if not os.path.exists(path):
        return []
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return []
    roles = (((data.get("npc") or {}).get("roles")) or [])
    return [str(r.get("name")) for r in roles if isinstance(r, dict) and r.get("name")]


def audit_roles():
    """体检：settings.yml 声明但 `roles` 未显式指定模型链的角色列表。"""
    return [r for r in declared_roles() if not is_role_specified(r)]


def default_policy():
    """通用默认策略（不指定角色时用）——保留 primary/fallback 兼容字段。"""
    c = default_chain()
    return {"chain": list(c), "primary": c[0], "fallback": c[-1] if len(c) > 1 else c[0]}


def role_policy(role=None):
    """解析某角色的策略：roles[角色] 覆盖，缺省走继承兜底链。

    - role 为空 → default（「不指定就默认通用」）；
    - 角色未显式指定 → 继承 `fallback_chain` 且在结果里标 `specified=False`；
    - 返回 chain（完整链）+ primary（首档）+ fallback（末档）+ specified。
    """
    c = role_chain(role)
    return {
        "chain": list(c),
        "primary": c[0],
        "fallback": c[-1] if len(c) > 1 else c[0],
        "specified": is_role_specified(role),
    }


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
