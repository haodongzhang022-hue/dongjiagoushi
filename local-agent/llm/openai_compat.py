# -*- coding: utf-8 -*-
"""OpenAI 兼容后端（默认）。未配 key 时不可用，交由兜底。

支持 context caching（prompt prefix caching）参数透传 + 缓存命中监控：
  - 启用时向 `chat.completions.create()` 透传 `extra_headers: {"ep_ctxcache":"1"}`，
    命中相同前缀 tokens 时按增量计费（deepseek context caching 机制）。
  - 每次调用按「共享前缀字符」估算节省量并记录到缓存命中监控（llm.cache）。

模型来源（Issue #147 v0.3.0-update · 统一配置 + 按角色解析）：
  - 每次 call() 都按 `role=` 从唯一配置（models.yml）解析渠道链，取**主档**模型；
  - 主档不通时**自动逐档降级**（主 → 二选 → 三选 …），改配置即长期生效；
  - role 缺省（未传）→ 走通用默认（「不指定就默认通用」）。
"""
import os

from .base import LLMBackend, BackendRegistry


def _resolve_backends(role=None):
    """解析「模型名 → 真实调用器」映射（多后端降级接线点）。

    返回 (caller_by_model, default_model)：
      - 每个模型名都绑定到**同一真实传输**（OpenAI 兼容 HTTP），仅 model 字段不同；
        因此降级 = 换 model 字段重发，无需另一套协议；
      - `codebuddy` / `glm` 等备用通道同样走 OpenAI 兼容端点（网关侧路由到对应模型）。
    这样把「配置文件的模型链」真实接进「多后端降级」。
    """
    from model_routing import spec as _spec
    chain = _spec.channel_order(role)
    default_model = chain[0] if chain else _spec.PRIMARY
    return chain, default_model


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

    def _call_model(self, model, system_prompt, user_input, **kw):
        """用指定 model 发起一次真实调用（供渠道链降级复用）。"""
        from llm import cache as _cache
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        kwargs = {}
        # context caching 参数透传（命中共享前缀 → 增量计费）
        headers = _cache.build_cache_headers()
        if headers:
            kwargs.update(headers)
        prefix_chars = len(system_prompt or "")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            **kwargs,
        )
        if prefix_chars > 0:
            _cache.record_cache_event(
                agent=self.name, layer="llm", cache_hit=1,
                prefix_chars=prefix_chars,
                saved_tokens=max(1, prefix_chars // 3),
            )
        return resp.choices[0].message.content

    def call(self, system_prompt, user_input, role=None, **kw):
        if not self.available():
            raise RuntimeError("OpenAI 兼容后端未配置 key")
        # 显式环境变量指定单模型时尊重之（不启用渠道链）
        env_model = os.environ.get("LOCAL_AGENT_MODEL")
        if env_model:
            try:
                return self._call_model(env_model, system_prompt, user_input, **kw)
            except ImportError:
                raise RuntimeError(
                    "缺少 openai 依赖。请 pip install openai，或使用 --backend cli_fallback 占位模式。"
                )
        try:
            from model_routing import call_with_chain
        except Exception:  # noqa: BLE001
            # 无 model_routing 时退回单模型（保可用，不崩）
            return self._call_model(self.model, system_prompt, user_input, **kw)
        chain, _default_model = _resolve_backends(role)
        callers = {m: (lambda sp, ui, **k: self._call_model(m, sp, ui, **k)) for m in chain}
        res = call_with_chain(callers, system_prompt=system_prompt,
                              user_input=user_input, role=role)
        if res["ok"]:
            return res["output"]
        # 全链不通 → 显式失败（不静默、不假装成功）
        raise RuntimeError(
            "all model channels unavailable (chain=%s): %s"
            % (res.get("chain"), res.get("attempts"))
        )
