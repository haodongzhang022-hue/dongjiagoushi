# -*- coding: utf-8 -*-
"""ModelRoutingAbility · 模型路由能力（全员可挂载 · Issue #147）

统一策略：一选 deepseek-v4.1-flash → 二选 glm-5.3-flash（主渠道不通降级）。
任何角色直接调用，不各自声明模型。
"""
from model_routing.engine import route_call, resolve_models, trace_overview, record_trace
from model_routing import spec as _spec


class ModelRoutingAbility:
    def capability(self):
        return {
            "name": "model_routing",
            "primary": _spec.PRIMARY,
            "fallback": _spec.FALLBACK,
            "rule": "一选主通道 deepseek-v4.1-flash；主渠道不通自动降级 glm-5.3-flash",
        }

    def models_for(self, policy=None):
        return resolve_models(policy)

    def call(self, caller, system_prompt="", user_input="", policy=None, **kw):
        return route_call(caller, system_prompt, user_input, policy=policy, **kw)

    def overview(self):
        return trace_overview()

    def record(self, event):
        return record_trace(event)
