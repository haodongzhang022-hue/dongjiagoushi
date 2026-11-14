# -*- coding: utf-8 -*-
"""模型选择逻辑（确定性，不靠 LLM 判断）。

选择优先级（从高到低）：
  1. 环境变量覆盖（NPC_MODEL_OVERRIDE）：人显式指定，最高优先级；
  2. **角色闸门**：触发的 NPC 角色在 `big_model_roles` 里（= 架构师）→
     prefer 里第一个「不在 unavailable 黑名单」的大参数模型；
  3. 其余角色 → `default_model`（统一默认档，如 deepseek-v4.1-flash）；
     该项留空或落在黑名单里 → 直接走第 4 档；
  4. fallback = platform_default：不写 model，走平台默认模型（永远能通）。

为什么要有第 2/3 档的分层：大参数模型贵且慢，**只有真正需要深判断的架构师角色**
值得；其他角色（秘书/开发/进度推手…）用快档小模型更合适。分层判据是平台注入的
`CNB_NPC_NAME`（角色全称），不是人肉约定、不是各处自己写 model。

「黑名单是缓存不是墓碑」：平台上线某个模型后，把它从 unavailable 删掉，
prefer / default_model 里同名候选立刻生效 —— 换模型只改数据，不改代码、不改流水线。
"""
import os
import re

from .spec import (
    ModelSpec,
    ModelPolicy,
    ModelSpecError,
    SOURCE_PREFER,
    SOURCE_OVERRIDE,
    SOURCE_ROLE_DEFAULT,
    SOURCE_FALLBACK,
)

# 平台注入的 NPC 角色名环境变量（@角色 触发时由平台写入）
ROLE_ENV_KEY = "CNB_NPC_NAME"

# 角色命名空间前缀：配置里写「总师」与「架构·总师」视为同一个角色，
# 避免 settings.yml 改名时信号灯和真实触发对不上（确定性归一，不猜）。
_ROLE_PREFIXES = ("架构·", "市场·")


def _norm_role(role):
    """角色名归一到短名（去掉「架构·」「市场·」前缀）。"""
    role = (role or "").strip()
    for p in _ROLE_PREFIXES:
        if role.startswith(p):
            return role[len(p):]
    return role

# npc:go 拒绝模型 ID 时的报错特征（实测原文）
_MODEL_REJECT_PATTERNS = (
    re.compile(r'model "([^"]+)" is not in the optional models list', re.I),
    re.compile(r'模型 "([^"]+)" 不在当前组织可选模型列表', re.I),
)


def select_model(spec=None, env=None, config_path=None, role=None):
    """按策略选出一个模型。

    :param spec: ModelSpec；不传则从 config_path / 默认路径加载
    :param env:  环境变量映射；默认 os.environ
    :param role: 触发本次 NPC 的角色名；不传则读 env 的 CNB_NPC_NAME
    :return: ModelPolicy
    """
    spec = spec or ModelSpec.load(config_path)
    env = os.environ if env is None else env
    role = (role if role is not None else (env.get(ROLE_ENV_KEY) or "")).strip()

    override_key = spec.override_env or "NPC_MODEL_OVERRIDE"
    override = (env.get(override_key) or "").strip()
    if override:
        warn = ""
        if spec.is_blocked(override):
            warn = "（注意：该 ID 在 unavailable 黑名单里，实测可能不可用；人显式指定优先）"
        return ModelPolicy(
            model=override,
            source=SOURCE_OVERRIDE,
            reason="环境变量 %s=%s 显式覆盖%s" % (override_key, override, warn),
            spec=spec,
            role=role,
        )

    # ---- 角色闸门：只有名单里的角色吃大参数模型 ----
    wants_big = any(_norm_role(role) == _norm_role(r) for r in spec.big_model_roles)
    if wants_big:
        usable = spec.usable
        if usable:
            chosen = usable[0]
            skipped = [m for m in spec.prefer if m not in usable]
            reason = "架构师角色「%s」→ 大参数优先命中 %s" % (role, chosen)
            if skipped:
                reason += "（已跳过不可用：%s）" % "、".join(skipped)
            return ModelPolicy(
                model=chosen, source=SOURCE_PREFER, reason=reason, spec=spec,
                role=role,
            )
        # 大参数全不可用 → 掉到平台默认（不退而求其次用小模型写死）
        return ModelPolicy(
            model=None,
            source=SOURCE_FALLBACK,
            reason="架构师角色「%s」的大参数候选全部不可用（%s），降级走平台默认模型"
            % (role, "、".join(spec.prefer)),
            spec=spec,
            role=role,
        )

    # ---- 其余角色：统一默认档（快档小模型），不参与大参数偏好 ----
    dm = spec.default_model
    if dm and not spec.is_blocked(dm):
        reason = "非架构师角色「%s」→ 默认档 %s" % (role or "（未识别角色）", dm)
        return ModelPolicy(
            model=dm, source=SOURCE_ROLE_DEFAULT, reason=reason, spec=spec, role=role
        )

    # 默认档没配 / 被拉黑 → 兜底：不写 model，走平台默认
    why = "未配置 default_model" if not dm else "default_model=%s 在不可用列表（%s）" % (
        dm, "、".join(spec.prefer))
    return ModelPolicy(
        model=None,
        source=SOURCE_FALLBACK,
        reason="角色「%s」走兜底：%s，降级走平台默认模型"
        % (role or "（未识别角色）", why),
        spec=spec,
        role=role,
    )


def resolve(config_path=None, env=None, role=None):
    """给流水线用的解析入口：返回可直接消费的 dict。"""
    policy = select_model(config_path=config_path, env=env, role=role)
    out = policy.to_dict()
    out["npc_options"] = policy.npc_options
    return out


def learn_from_error(text, spec=None):
    """从 npc:go 的失败日志里认出「被拒的模型 ID」。

    用于兜底触发时的**闭环学习**：流水线把日志喂进来，拿到一个待加入
    unavailable 的 ID 与一句人可读建议——不自动改仓库（那要人决定），
    但把"该改哪一行、为什么"直接摆出来，避免同一个坑踩第二次。
    """
    spec = spec or ModelSpec.load()
    text = text or ""
    for pat in _MODEL_REJECT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        model = m.group(1).strip()
        if spec.is_blocked(model):
            hint = "%s 已在 unavailable 黑名单里，无需重复添加；检查 prefer 是否还有别的候选" % model
        else:
            hint = "把 %r 加进 .cnb/npc-models.yml 的 unavailable，并把下一个大参数模型放到 prefer 最前" % model
        return {"model": model, "known": spec.is_blocked(model), "hint": hint}
    return None
