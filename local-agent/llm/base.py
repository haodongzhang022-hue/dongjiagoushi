# -*- coding: utf-8 -*-
"""模型后端抽象基类与注册表。"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 llm.cache）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class LLMBackend:
    """统一的 LLM 调用接口。子类实现 call()。

    generate() 为 call() 的语义别名（兼容 benchmark.py 等调用点）。
    cache-aware 能力经 llm.cache 模块提供（context caching 透传 + 命中监控）。
    """

    name = "base"

    def call(self, system_prompt, user_input, **kw):
        raise NotImplementedError

    def available(self):
        """该后端当前是否可用（如是否配了 key）。"""
        return False

    # ------------------------------------------------------------
    # 语义别名：generate() 兼容（修复 benchmark 等调用点断裂 bug）
    # ------------------------------------------------------------
    def generate(self, user_input, system_prompt="", **kw):
        """generate() = call() 别名。system_prompt 缺省用后端默认。

        原断裂 bug：benchmark.py 调用 `llm.generate(...)` 而后端只有 `call()`。
        现在 generate() 是 call() 的直通别名，配合 llm.cache 缓存感知调用，
        即完成「context caching 透传 + 缓存命中监控」的默认接入。
        """
        return self.call(system_prompt, user_input, **kw)


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
