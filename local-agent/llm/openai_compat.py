# -*- coding: utf-8 -*-
"""OpenAI 兼容后端（默认）。未配 key 时不可用，交由兜底。"""
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
        self.model = os.environ.get("LOCAL_AGENT_MODEL", "gpt-4o-mini")

    def available(self):
        return bool(self.api_key)

    def call(self, system_prompt, user_input):
        if not self.available():
            raise RuntimeError("OpenAI 兼容后端未配置 key")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
            )
            return resp.choices[0].message.content
        except ImportError:
            raise RuntimeError(
                "缺少 openai 依赖。请 pip install openai，或使用 --backend cli_fallback 占位模式。"
            )
