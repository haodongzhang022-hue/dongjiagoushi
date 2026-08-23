# -*- coding: utf-8 -*-
"""模型后端抽象基类与注册表。"""


class LLMBackend:
    """统一的 LLM 调用接口。子类实现 call()。"""

    name = "base"

    def call(self, system_prompt, user_input):
        raise NotImplementedError

    def available(self):
        """该后端当前是否可用（如是否配了 key）。"""
        return False


class BackendRegistry:
    _backends = {}

    @classmethod
    def register(cls, backend_cls):
        cls._backends[backend_cls.name] = backend_cls
        return backend_cls

    @classmethod
    def get(cls, backend=None):
        if backend and backend in cls._backends:
            return cls._backends[backend]()
        # 自动选择：按注册顺序返回第一个 available 的
        for name, bcls in cls._backends.items():
            inst = bcls()
            if inst.available():
                return inst
        # 全部不可用 → 返回兜底（占位）
        from .cli_fallback import CliFallbackBackend

        return CliFallbackBackend()
