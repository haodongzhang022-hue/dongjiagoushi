# -*- coding: utf-8 -*-
"""模型选择策略的数据结构与校验（唯一事实源：.cnb/npc-models.yml）。

设计要点：
  - 策略是**数据**不是代码：模型 ID 全部在配置文件里，随平台更新只改数据；
  - 策略读入后立即**确定性校验**（不是 LLM 判断），非法配置直接失败，
    绝不允许"配置写错了就静默走个凑合值"；
  - 兜底只允许 `platform_default` 这一种语义（= npc:go 不写 model），
    因为它才是"永远能通"的那条路；把某个模型 ID 当兜底等于把坑搬回去。
"""
import os

DEFAULT_CONFIG_PATH = os.path.join(".cnb", "npc-models.yml")

# 兜底策略唯一合法值：不写 model，走平台默认模型
FALLBACK_PLATFORM_DEFAULT = "platform_default"

# 决策来源标记（写进日志/回执，方便复盘中查明为什么用了这个模型）
SOURCE_PREFER = "prefer"                # 命中 prefer 里的大参数模型
SOURCE_OVERRIDE = "override"            # 环境变量临时覆盖
SOURCE_FALLBACK = "fallback"            # 降级到平台默认


class ModelSpecError(ValueError):
    """配置非法。"""


class ModelSpec(object):
    """一条模型策略。"""

    def __init__(self, prefer, unavailable, fallback, override_env, history):
        self.prefer = prefer
        self.unavailable = unavailable
        self.fallback = fallback
        self.override_env = override_env
        self.history = history

    # ---------- 构造与校验 ----------
    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ModelSpecError("npc-models 配置必须是映射（dict）")

        prefer = data.get("prefer") or []
        if not isinstance(prefer, list) or not all(isinstance(x, str) for x in prefer):
            raise ModelSpecError("prefer 必须是字符串列表")
        prefer = [x.strip() for x in prefer if x and x.strip()]
        if not prefer:
            raise ModelSpecError("prefer 不能为空：至少给一个候选大参数模型")

        unavailable = data.get("unavailable") or []
        if not isinstance(unavailable, list):
            raise ModelSpecError("unavailable 必须是字符串列表")
        unavailable = [str(x).strip() for x in unavailable if str(x).strip()]

        # 显式写了 fallback 就必须是 platform_default；留空/不写才取默认。
        if "fallback" in data and data["fallback"] not in (None, ""):
            fallback = data["fallback"]
        elif "fallback" in data and data["fallback"] == "":
            raise ModelSpecError(
                "fallback 写了但为空：要么省略该字段（默认 platform_default），"
                "要么显式写 platform_default"
            )
        else:
            fallback = FALLBACK_PLATFORM_DEFAULT
        if fallback != FALLBACK_PLATFORM_DEFAULT:
            raise ModelSpecError(
                "fallback 只允许 %r（= 不写 model，走平台默认模型）；"
                "写成具体模型 ID 等于把漂移风险搬回来，实测过会静默失效"
                % FALLBACK_PLATFORM_DEFAULT
            )

        override_env = data.get("override_env") or "NPC_MODEL_OVERRIDE"
        if not isinstance(override_env, str):
            raise ModelSpecError("override_env 必须是字符串")

        history = data.get("history") or []
        if not isinstance(history, list):
            raise ModelSpecError("history 必须是字符串列表")

        return cls(prefer, unavailable, fallback, override_env, history)

    @classmethod
    def load(cls, path=None):
        """从 YAML 加载（缺文件即报错，不静默兜底）。"""
        path = path or DEFAULT_CONFIG_PATH
        if not os.path.exists(path):
            raise ModelSpecError("找不到模型配置：%s" % path)
        try:
            import yaml
        except ImportError:
            raise ModelSpecError("解析 npc-models.yml 需要 pyyaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    # ---------- 派生的查询 ----------
    @property
    def usable(self):
        """prefer 里「不在黑名单」的候选（保持原顺序）。"""
        blocked = set(self.unavailable)
        return [m for m in self.prefer if m not in blocked]

    def is_blocked(self, model):
        return model in set(self.unavailable)

    def to_dict(self):
        return {
            "prefer": list(self.prefer),
            "usable": self.usable,
            "unavailable": list(self.unavailable),
            "fallback": self.fallback,
            "override_env": self.override_env,
            "history": list(self.history),
        }


class ModelPolicy(object):
    """一次选择的决策结果。"""

    def __init__(self, model, source, reason, spec=None):
        self.model = model            # 选中的模型 ID；None = 走平台默认（不写 model）
        self.source = source          # prefer / override / fallback
        self.reason = reason          # 人可读的原因（写进回执与日志）
        self.spec = spec

    @property
    def use_platform_default(self):
        return self.model is None

    @property
    def npc_options(self):
        """给 npc:go 用的 options 片段。

        走平台默认时返回 {}（**不含 model 键**）——这一点是关键：
        只要写了 model: ''，npc:go 会报 `"model" must be a non-empty string`。
        """
        return {} if self.model is None else {"model": self.model}

    def to_dict(self):
        return {
            "model": self.model,
            "use_platform_default": self.use_platform_default,
            "source": self.source,
            "reason": self.reason,
        }

    def __repr__(self):
        return "<ModelPolicy model=%r source=%s>" % (self.model, self.source)
