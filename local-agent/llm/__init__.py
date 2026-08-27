# -*- coding: utf-8 -*-
"""
本地 Agent · 模型后端抽象
==========================
多后端统一接口：OpenAI 兼容 API（默认）+ CLI 兜底/占位。
未配置 key 时降级为「契约生成 + 占位执行」，不假执行推理，
保证流水线骨架可跑通、可测试（对应云端 "无 key 不伪造" 纪律）。

缓存能力（Issue #41 全链路缓存优化）：
  - cache.py：context caching 参数透传 + 缓存命中监控（按 agent × 层归因）。
"""
from .base import LLMBackend, BackendRegistry
from .openai_compat import OpenAICompatBackend
from .cli_fallback import CliFallbackBackend
from . import cache

__all__ = [
    "LLMBackend",
    "BackendRegistry",
    "OpenAICompatBackend",
    "CliFallbackBackend",
    "cache",
]


def get_backend(backend=None):
    """返回一个后端实例。backend 未指定时按环境自动选择。"""
    return BackendRegistry.get(backend)
