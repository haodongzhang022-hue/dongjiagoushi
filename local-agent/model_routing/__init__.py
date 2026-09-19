# -*- coding: utf-8 -*-
"""模型路由模块（model-routing · Issue #147 · v0.1.0-init）

统一「主 + 备」模型策略，避免角色/配置散点写死：
  - 一选主通道：deepseek-v4.1-flash
  - 二选备用通道：glm-5.3-flash（主渠道不通自动降级）

对外显式接口：ModelRoutingAbility / route_call / resolve_models。
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
