# -*- coding: utf-8 -*-
"""模型路由规范 · 唯一事实源（Issue #147 · module model-routing v0.1.0-init）

用户诉求（Issue #147）：
  - 一选（主通道）= deepseek v4.1 flash
  - 二选（备用通道）= glm-5.3-flash，主渠道不通时启用
  - 全角色统一走这套「主 + 备」策略，不做 per-role 写死散点

铁律：模型 ID / 渠道优先级只在这里声明一次。
其他层（.cnb.yml / llm 后端 / 文档 / 测试）都从这里读取，禁止各自取名。
"""

# 渠道优先级（顺序即降级顺序：主 → 备）
PRIMARY = "deepseek-v4.1-flash"
FALLBACK = "glm-5.3-flash"

# 渠道定义：priority 越小越优先；kind 标明渠道类型
CHANNELS = [
    {
        "priority": 1,
        "model": PRIMARY,
        "role": "primary",
        "desc": "一选主通道（用户指定：deepseek v4.1 flash）",
    },
    {
        "priority": 2,
        "model": FALLBACK,
        "role": "fallback",
        "desc": "二选备用通道（主渠道不通时启用，用户指定：glm 5.3 flash）",
    },
]

# 默认角色 → 渠道策略（全角色统一，避免散点写死）
DEFAULT_POLICY = {"primary": PRIMARY, "fallback": FALLBACK}

# 触发降级的信号（渠道不通判定）
UNAVAILABLE_SIGNALS = (
    "unavailable",
    "timeout",
    "connection_error",
    "rate_limit",
    "402",
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def channel_order():
    """返回按优先级排序的模型列表（主 → 备）。"""
    return [c["model"] for c in sorted(CHANNELS, key=lambda c: c["priority"])]
