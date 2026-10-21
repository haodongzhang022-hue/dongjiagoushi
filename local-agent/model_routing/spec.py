# -*- coding: utf-8 -*-
"""模型路由规范 · 唯一事实源（Issue #147 · module model-routing v0.3.0-update）

用户诉求（Issue #147 第三版 · Issue #182 复评收紧 · PR #184）：
  - 模型指定**收敛到一个配置文件**统一管理（`models.yml`）；
  - **角色按需指定（Issue #182 复评，不造假差异化）**：只有**真正需要不同链**的角色
    才写进 `roles`；其余角色走 `fallback_chain`（= default.chain 的 YAML 锚点引用，
    配置层禁止重复字面量）。不在配置里堆与 default 逐字相同的空壳链；
  - **角色别名归一**：`role_aliases` 让「架构·开发」与「开发」双向可查，避免云端传全称、配置写短名而匹配不上；
  - **模型版本别名（alias）实名登记**：`1017` 这类口语版本串只在人类确认平台真实 ID 后
    才登记；未登记一律在解析期显式报红（不放行），不留伪配置；
  - **改配置必须长期生效**（非单次有效）：配置在**每次解析时**加载，不缓存死值；
  - **多级降级链**：主通道 → 二选备用 → 三选备用（如 v4.1-flash → codebuddy → glm-5.3-flash）。

铁律：模型 ID / 渠道优先级只在 `models.yml` 声明一次。
  本文件是「读配置的代码层」——负责加载 + 解析 + 暴露稳定接口，
  自身不做任何模型 ID 硬编码（仅保留一份兜底常量防配置损坏时彻底不可用）。
其他层（.cnb.yml / llm 后端 / 文档 / 测试）都从这里读取，禁止各自取名。
"""
import os
import re

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
    """模型名别名归一（`deepseek-v4.1-flash-1017` → 平台真实 ID）。

    Issue #182 / PR #184 复评：别名表 `alias` 是**唯一**翻译处，右侧必须是平台
    可选列表里真实存在的 ID。未登记别名**显式报红**（不放行）——后端拿到坏模型名
    会静默 stage error（#177 事故），所以解析期就拦下，不沉默透传。

    判定：模型名若带版本后缀（形如 `-<数字>`）但不在 alias 表登记，视为「未登记别名」
    → 抛 RuntimeError（红灯），逼配置显式化；普通模型 ID（无版本后缀）原样返回。
    """
    if not model:
        return model
    table = _raw().get("alias") or {}
    if not isinstance(table, dict):
        table = {}
    if model in table:
        return str(table[model])
    # 版本后缀型串（如 deepseek-v4.1-flash-1017）未登记 → 显式报红，不放行
    if isinstance(model, str) and re.search(r"-\d{2,}$", model):
        raise RuntimeError(
            "未登记别名，解析期拦下（不放行）：%r —— 请在 models.yml 的 alias 下登记真实平台 ID" % model
        )
    return model


def alias_table():
    """版本别名表（`{口语版本串: 平台真实 ID}`），由配置唯一声明。"""
    table = _raw().get("alias") or {}
    return table if isinstance(table, dict) else {}


def alias_key_issues():
    """别名**键**体检：登记了左值却没人会用它 = 配置垃圾，且右值坏掉不会被发现。

    场景：`alias: {minimax-3.1-flash: <真实ID>}` —— 若 `minimax-3.1-flash` 既不在
    任何角色链里、也不是 default/fallback 的成员，这条登记就永远不会被 `resolve_alias`
    走到；右值写成错 ID 也没人能测出来（#177 事故的静默版）。
    这类条目要么是「登记了忘接线」（应写进角色链），要么是「名字打错」（应修键）。

    返回 [{key, value, reason, detail}]。
    """
    table = alias_table()
    if not table:
        return []
    used = set()
    for m in list(default_chain()) + list(fallback_chain()):
        used.add(m)
    for role in role_overrides():
        used.update(role_chain(role))
    bad = []
    for key in table:
        if key not in used:
            bad.append({
                "key": key, "value": table[key], "reason": "alias_unused",
                "detail": "alias 键 %r 未被任何角色链引用（登记了但接线不到，右值写坏也测不出来）"
                          % key,
            })
    return bad


def npc_go_params():
    """平台 `npc:go` 可控参数（推理深度 / 上下文窗口 / 输出上限 / 轮次）。

    为什么不和 `model` 放一起：`model` 是 `default.chain[0]` 的**派生物**（唯一事实源在
    default.chain，配置里不重复字面量）；而这几项**不派生于渠道链**——显式指定自定义
    model 时平台会回落到内置默认（medium / 1m / 48k / 500），把期望值写死才防「以为设了
    其实没设」。配置缺失返回 {}（不臆造平台默认值）。
    """
    blk = _raw().get("npc_go")
    return dict(blk) if isinstance(blk, dict) else {}


def last_resort_model():
    """兜底档的**平台可执行单模型**（三档里的档3）。

    为什么单列：`npc:go` 只接受一个 model 字段，渠道链上某些档在平台侧跑不起来；
    这一条是「连备用话术都没得跑」时的最后一道可执行模型。
    配置缺失 → 取 chain 末档（不臆造模型名）。
    """
    m = _raw().get("last_resort_model")
    if isinstance(m, str) and m.strip():
        return resolve_alias(m.strip())
    c = default_chain()
    return c[-1] if c else _FALLBACK_CHAIN[-1]


def tier_view(role=None):
    """把某角色的渠道链解读成**三档语义**（用户 2026-10-20 PR #185 定调）。

      档1 `fast`        —— 指定：该角色**显式写进 roles** 的链首档（专属快档）；
      档2 `same`        —— 和其他角色一样：与 `fallback_chain` 重合的档位；
      档3 `last_resort` —— 现在的兜底：`last_resort_model` 单模型。

    判据是确定性的两条：① 是否 `specified`（显式写进 roles）；② 成员是否在
    `fallback_chain` 里。未列出的角色（specified=False）全部记 `same`——它的首个模型
    本来就叫默认，不冒充「指定」。快档角色链首若与默认链成员同名（如 glm-5.3-flash），
    仍记 `fast`：显式指定的首档语义就是「指定」，这是配置写法的约定。
    """
    chain = list(role_chain(role))
    fb = set(fallback_chain())
    last = last_resort_model()
    specified = is_role_specified(role)
    tiers = []
    for idx, model in enumerate(chain):
        if idx == 0 and specified:
            tier = "fast"
        elif model in fb:
            tier = "same"
        elif model == last:
            tier = "last_resort"
        else:
            tier = "extra"
        tiers.append({"tier": tier, "model": model, "priority": idx + 1})
    return {"role": role, "chain": chain, "tiers": tiers,
            "last_resort_model": last,
            "specified": is_role_specified(role)}


def is_fast_role(role):
    """该角色是否挂了「快档优先」的三档链（显式写进 roles 且档序与快档档序一致）。

    判据（Issue #199 拍板后收紧，确定性、不靠感觉）：
      ① 角色**显式**写进 `roles`（不是走 fallback 的未列出角色）；
      ② 其链**首档 = 快档第一优先**（`default_chain()[0]`，即 `deepseek-v4.1-flash`），
         且**末档 = `last_resort_model`**（`glm-5.3-flash`）。
    不再用「首档异于默认链首」——人类把第一优先定成了默认链首，那条判据会让
    快档角色恒为 False（自相矛盾）。现在的语义是「显式锚定快档档序」，而非「另排一套」。
    """
    if not is_role_specified(role):
        return False
    c = role_chain(role)
    d = default_chain()
    if not c or not d:
        return False
    return c[0] == d[0] and c[-1] == last_resort_model()


def default_chain():
    """通用默认渠道链（不指定角色时用）。配置缺失 → 内置兜底链。"""
    c = _chain_of(_raw().get("default"))
    return c or _FALLBACK_CHAIN


def fallback_chain():
    """继承兜底链（角色未显式指定时的去向，仍属 default 体系）。

    Issue #182 复评收紧：fallback_chain 在配置层通过 YAML 锚点 *default_chain
    **引用** default.chain，禁止重复字面量；改默认链只改一处即两链同步。
    配置缺失时退回 default_chain（保证结构一致）。
    """
    c = _chain_of(_raw().get("fallback_chain"))
    if c:
        return c
    return default_chain()


def role_aliases():
    """角色别名表（`{规范全名: [短名...]}`，由配置唯一声明，不写死代码）。"""
    aliases = _raw().get("role_aliases") or {}
    return aliases if isinstance(aliases, dict) else {}


def role_alias(role):
    """角色别名归一（`架构·开发` ↔ `开发` 双向可查）。

    云端 `@org/repo(架构·开发)` 传全称，配置若用短名调用也能对上。
    别名表由 `role_aliases` 唯一声明，不写死代码。
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
    canonical = role_alias(role)
    # 规范全名优先，其次原始名（短名也可能直接写在 roles 下）
    for name in (canonical, role):
        if not name:
            continue
        blk = roles.get(str(name))
        if isinstance(blk, dict):
            return blk
    return {}


def is_role_specified(role=None):
    """该角色是否**显式**在 roles 里指定过（防"以为配了其实没配"）。"""
    if not role:
        return False
    return bool(_chain_of(role_override(role)))


def role_at(role, idx=0):
    """取某角色渠道链的第 idx 档模型（0=主档）。越界返回末档，永不返回空。

    Issue #182 复评：返回值一律过 `resolve_alias` 映射；若含未登记别名则显式报红
    （不放行），不把坏模型名透传给后端。
    """
    c = role_chain(role)
    if not c:
        base = list(fallback_chain()) or list(_FALLBACK_CHAIN)
        m = base[idx] if idx < len(base) else base[-1]
        return resolve_alias(m)
    m = c[idx] if idx < len(c) else c[-1]
    return resolve_alias(m)


def role_chain(role=None):
    """解析某角色的渠道链（**仅真正差异化的角色显式列出**）。

    解析顺序（固定）：
      1. 角色别名（`role_aliases`，全称 ↔ 短名双向归一）；
      2. roles[角色] 整链 / 子链；
      3. **fallback_chain**（= default.chain 的引用，仍属 default 体系）；
      4. 内置兜底常量。
    「未列出的角色」走 fallback_chain——配置层不再堆与 default 逐字相同的空壳链
    （Issue #182 复评：23/25 条空壳声明已撤销）。

    - role 为空 → 走 default（「不指定就默认通用」只在 role 缺失时生效）；
    - roles[角色].chain 存在 → 整链覆盖；
    - 只写 primary/fallback → 该子链覆盖头部，fallback_chain 补全尾部（不缩短降级链）。
    """
    if not role:
        return tuple(default_chain())
    ov = role_override(role)
    if not isinstance(ov, dict) or not _chain_of(ov):
        return tuple(fallback_chain())
    ov_chain = _chain_of(ov)
    # 整链覆盖：ov 自带 chain（新写法）→ 直接用
    if isinstance(ov.get("chain"), (list, tuple)):
        return ov_chain
    # 旧写法（primary/fallback 子链）→ 覆盖头部，fallback_chain 补全剩余档位
    base = list(fallback_chain())
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

    读不到 settings 时返回空（不误报）。
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


_PREFIXES = ("架构·", "市场·")


def short_names(role):
    """某规范角色「应当」对应的全部短名写法（用于别名完整性审计）。

    来源两份合并：
      1. `role_aliases` 表里显式登记的短名；
      2. 去掉已知前缀（架构·/市场·）得到的自然短名（如 架构·开发 → 开发）。
    第 2 份保证：即使有人把 role_aliases 里对应条目**删掉**，审计仍能发现
    「规范名有、短名没接上」的断裂（Issue #182 复评：断点②换位置复发防护）。
    不含自身、不含已在 roles 里显式写出的同名（避免误报）。
    """
    role = str(role)
    out = []
    aliases = role_aliases()
    names = aliases.get(role)
    if names:
        out.extend(str(n) for n in (names if isinstance(names, (list, tuple)) else [names]))
    for pre in _PREFIXES:
        if role.startswith(pre) and len(role) > len(pre):
            out.append(role[len(pre):])
    # 去重、去自身、去空
    seen, uniq = set(), []
    for n in out:
        if n and n != role and n not in seen:
            seen.add(n); uniq.append(n)
    return uniq


def audit_roles():
    """体检（Issue #182 复评 · 全称 + 短名双体检）：

    返回所有**配置不健康**的角色条目，分三类，每条带原因：
      1. 空壳链：roles 里显式列出但 chain 与 fallback_chain 逐字相同（应撤销，改用 fallback）；
      2. 别名断裂：某规范角色的短名解析出的链 ≠ 该角色本身的链（别名没接上，短名会静默走 fallback）；
      3. 缺链：声明角色解析出的链为空（配置彻底坏掉）。
    注：未显式列出、自然走 fallback_chain 的角色**不算不健康**（那是预期行为，不是空壳）。
    """
    bad = []
    declared = declared_roles()
    fb = list(fallback_chain())
    # ① 空壳链
    for role, blk in (_raw().get("roles") or {}).items():
        if not isinstance(blk, dict):
            continue
        # 空壳判据(Issue #199 拍板后收紧)：链与 fallback 逐字相同 **且** 不承担快档锚定语义。
        # 快档角色即便档序与 default 同构，也显式承担「档1指定/档2一样/档3兜底」契约
        # (is_fast_role 可判定)，不算空壳 —— 否则人类把第一优先定为 default 链首后，
        # 快档角色会被误判为空壳而反复制造删-加抖动。
        if _chain_of(blk) == tuple(fb) and not is_fast_role(role):
            bad.append({"role": role, "reason": "shell_chain",
                        "detail": "roles 里显式列出但链与 fallback_chain 逐字相同且不锚定快档，属空壳，应删"})
    # ②③ 全称 + 短名双体检
    for role in declared:
        rc = list(role_chain(role))
        if not rc:
            bad.append({"role": role, "reason": "empty_chain",
                        "detail": "声明角色解析出空链"})
            continue
        # 别名断裂判据（Issue #199 拍板后收紧）：不能只比「短名链 ≠ 规范名链」——
        # 快档锚定角色的链与 fallback 同构后，短名缺失也会解析出同样的链，
        # 断了根本比不出来（静默盲区）。改为**直接查 role_aliases 声明**：
        # 显式写进 roles 的角色，其短名必须真在 role_aliases 里登记，缺即报红。
        _ra = (_raw().get("role_aliases") or {})
        _decl = _ra.get(role)
        if role in (_raw().get("roles") or {}) and not _decl:
            bad.append({"role": role, "reason": "alias_broken",
                        "detail": "roles 里显式列出但 role_aliases 未登记短名（短名会静默走 fallback）"})
            continue
        for short in short_names(role):
            sc = list(role_chain(short))
            if sc != rc:
                bad.append({"role": role, "reason": "alias_broken",
                            "detail": "短名 %r 解析链 %r ≠ 规范名链 %r（别名断裂，短名会静默走 fallback）"
                                      % (short, sc, rc)})
    # ④ 模型别名键体检（登记了但没人用 = 接线不到，右值坏掉也测不出来）
    for item in alias_key_issues():
        bad.append({"role": item["key"], "reason": item["reason"], "detail": item["detail"]})
    # ⑤ 快档链必须能「显性降级」：首档之外至少还要有 1 档与其他角色相同的模型
    #    （只挂单档 = 首档一挂就整条断，等于把静默失败写进配置）
    for role in role_overrides():
        view = tier_view(role)
        kinds = [t["tier"] for t in view["tiers"]]
        if "same" not in kinds:
            bad.append({"role": role, "reason": "no_degrade_target",
                        "detail": "链 %r 没有「与其他角色一样」的档位，主档不通就无处降级（显性降级缺位）"
                                  % (view["chain"],)})
    return bad


def audit_roles_flat():
    """audit_roles 的扁平角色名列表（兼容旧调用 / CLI）。"""
    return [b["role"] for b in audit_roles()]


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
