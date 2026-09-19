# -*- coding: utf-8 -*-
"""ModelRoutingAbility · 模型路由能力（全员可挂载 · Issue #147）

统一配置文件管理（models.yml · 唯一事实源）：
  - 不指定角色 → 走通用默认（default）；
  - 指定角色 → 走该角色覆盖（roles[role]→default 字段级覆盖）。
任何角色直接调用，不各自声明模型。
"""
from model_routing.engine import route_call, resolve_models, trace_overview, record_trace
from model_routing import spec as _spec


class ModelRoutingAbility:
    def capability(self):
        return {
            "name": "model_routing",
            "config_file": _spec.config_path(),
            "default": _spec.default_policy(),
            "role_overrides": _spec.role_overrides(),
            "default_chain": list(_spec.default_chain()),
            "rule": "配置文件统一管理：不指定走 default；roles 可按角色单独覆盖；按链自动逐档降级（每次调用时实时读配置，改配置即长期生效）",
        }

    def config_file(self):
        """返回唯一配置文件路径（改模型只改这里）。"""
        return _spec.config_path()

    def models_for(self, policy=None, role=None):
        """解析某角色（或默认）的渠道顺序（主 → 备）。"""
        return resolve_models(policy, role=role)

    def role_policy(self, role=None):
        """解析某角色的完整策略（含 default 继承）。"""
        return _spec.role_policy(role)

    def default_chain(self):
        """通用默认渠道链（主 → 二选 → 三选 …）。"""
        return list(_spec.default_chain())

    def chain_for(self, role=None):
        """某角色的渠道链（不指定 → 通用默认）。"""
        return list(_spec.role_chain(role))

    def call(self, caller, system_prompt="", user_input="", policy=None, role=None, **kw):
        return route_call(caller, system_prompt, user_input, policy=policy, role=role, **kw)

    def overview(self):
        return trace_overview()

    def record(self, event):
        return record_trace(event)
