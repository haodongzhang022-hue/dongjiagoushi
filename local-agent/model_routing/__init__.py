# -*- coding: utf-8 -*-
"""模型路由模块（model-routing · Issue #147 · v0.2.0-update）

统一配置文件管理模型（models.yml · 唯一事实源），避免角色/配置散点写死：
  - 不指定 → 走通用默认 default；
  - 指定角色 → roles[role] 字段级覆盖 default；
  - 主通道不通 → 自动降级备用通道。

对外显式接口：ModelRoutingAbility / route_call / resolve_models / spec。
"""
from . import spec
from .engine import route_call, resolve_models, trace_overview, record_trace, is_unavailable
from .ability import ModelRoutingAbility

__all__ = [
    "spec",
    "route_call",
    "resolve_models",
    "trace_overview",
    "record_trace",
    "is_unavailable",
    "ModelRoutingAbility",
]
