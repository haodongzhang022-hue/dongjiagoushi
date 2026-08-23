# -*- coding: utf-8 -*-
"""
本地 Agent · 模型后端抽象
==========================
多后端统一接口：OpenAI 兼容 API（默认）+ CLI 兜底/占位。
未配置 key 时降级为「契约生成 + 占位执行」，不假执行推理，
保证流水线骨架可跑通、可测试（对应云端 "无 key 不伪造" 纪律）。
"""
from .base import LLMBackend, BackendRegistry
from .openai_compat import OpenAICompatBackend
from .cli_fallback import CliFallbackBackend

__all__ = [
    "LLMBackend",
    "BackendRegistry",
    "OpenAICompatBackend",
    "CliFallbackBackend",
]


def get_backend(backend=None):
    """返回一个后端实例。backend 未指定时按环境自动选择。"""
    return BackendRegistry.get(backend)
