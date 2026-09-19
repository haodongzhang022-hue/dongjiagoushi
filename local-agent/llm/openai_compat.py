# -*- coding: utf-8 -*-
"""OpenAI 兼容后端（默认）。未配 key 时不可用，交由兜底。

支持 context caching（prompt prefix caching）参数透传 + 缓存命中监控：
  - 启用时向 `chat.completions.create()` 透传 `extra_headers: {"ep_ctxcache":"1"}`，
    命中相同前缀 tokens 时按增量计费（deepseek context caching 机制）。
  - 每次调用按「共享前缀字符」估算节省量并记录到缓存命中监控（llm.cache）。
"""
import os

from .base import LLMBackend, BackendRegistry


@BackendRegistry.register
class OpenAICompatBackend(LLMBackend):
    name = "openai_compat"

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get(
            "LOCAL_AGENT_API_KEY"
        )
        self.base_url = os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        # 默认模型走唯一事实源（Issue #147：一选 deepseek-v4.1-flash）
        try:
            from model_routing.spec import PRIMARY as _DEFAULT_MODEL
        except Exception:  # noqa: BLE001
            _DEFAULT_MODEL = "deepseek-v4.1-flash"
        self.model = os.environ.get("LOCAL_AGENT_MODEL", _DEFAULT_MODEL)

    def available(self):
        return bool(self.api_key)

    def call(self, system_prompt, user_input, **kw):
        if not self.available():
            raise RuntimeError("OpenAI 兼容后端未配置 key")
        try:
            from llm import cache as _cache
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            kwargs = {}
            # context caching 参数透传（命中共享前缀 → 增量计费）
            headers = _cache.build_cache_headers()
            if headers:
                kwargs.update(headers)
            # 估算共享前缀（system_prompt 作为稳定前缀）节省量
            prefix_chars = len(system_prompt or "")
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                **kwargs,
            )
            # 记录缓存命中事件（前缀 > 0 且启用缓存视为命中复用；无凭据估算）
            if prefix_chars > 0:
                _cache.record_cache_event(
                    agent=self.name, layer="llm", cache_hit=1,
                    prefix_chars=prefix_chars,
                    saved_tokens=max(1, prefix_chars // 3),
                )
            return resp.choices[0].message.content
        except ImportError:
            raise RuntimeError(
                "缺少 openai 依赖。请 pip install openai，或使用 --backend cli_fallback 占位模式。"
            )
