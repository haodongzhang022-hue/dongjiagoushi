# -*- coding: utf-8 -*-
"""模型选择逻辑（确定性，不靠 LLM 判断）。

选择优先级（从高到低）：
  1. 环境变量覆盖（NPC_MODEL_OVERRIDE）：人显式指定，最高优先级；
  2. prefer 里第一个「不在 unavailable 黑名单」的大参数模型；
  3. fallback = platform_default：不写 model，走平台默认模型（永远能通）。

「黑名单是缓存不是墓碑」：平台上线某个模型后，把它从 unavailable 删掉，
prefer 里同名候选立刻生效 —— 换模型只改数据，不改代码、不改流水线。
"""
import os
import re

from .spec import (
    ModelSpec,
    ModelPolicy,
    ModelSpecError,
    SOURCE_PREFER,
    SOURCE_OVERRIDE,
    SOURCE_FALLBACK,
)

# npc:go 拒绝模型 ID 时的报错特征（实测原文）
_MODEL_REJECT_PATTERNS = (
    re.compile(r'model "([^"]+)" is not in the optional models list', re.I),
    re.compile(r'模型 "([^"]+)" 不在当前组织可选模型列表', re.I),
)


def select_model(spec=None, env=None, config_path=None):
    """按策略选出一个模型。

    :param spec: ModelSpec；不传则从 config_path / 默认路径加载
    :param env:  环境变量映射；默认 os.environ
    :return: ModelPolicy
    """
    spec = spec or ModelSpec.load(config_path)
    env = os.environ if env is None else env

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
        )

    usable = spec.usable
    if usable:
        chosen = usable[0]
        skipped = [m for m in spec.prefer if m not in usable]
        reason = "大参数优先命中 %s" % chosen
        if skipped:
            reason += "（已跳过不可用：%s）" % "、".join(skipped)
        return ModelPolicy(
            model=chosen, source=SOURCE_PREFER, reason=reason, spec=spec
        )

    # 全部候选都不可用 → 兜底：不写 model，走平台默认
    return ModelPolicy(
        model=None,
        source=SOURCE_FALLBACK,
        reason="prefer 候选全部在不可用列表（%s），降级走平台默认模型"
        % "、".join(spec.prefer),
        spec=spec,
    )


def resolve(config_path=None, env=None):
    """给流水线用的解析入口：返回可直接消费的 dict。"""
    policy = select_model(config_path=config_path, env=env)
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
