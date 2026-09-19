# -*- coding: utf-8 -*-
"""模型路由引擎 · 主通道 → 备用通道降级（Issue #147）

确定性逻辑（非 LLM 判断）：
  - 按 spec 的渠道优先级取「主模型」调用；
  - 主渠道不通（不可用/超时/限流/5xx）→ 自动降级到备用模型；
  - 全程留痕（每次路由决策写 model_routing_trace）。
"""
import os
import sys
import json
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL_AGENT = os.path.dirname(_HERE)
if _LOCAL_AGENT not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT)

from model_routing import spec as _spec  # noqa: E402

TRACE_DIR = os.path.join(_HERE, "_trace")
_TRACE_FILE = os.path.join(TRACE_DIR, "model_routing_trace.jsonl")


def _ensure_dir():
    os.makedirs(TRACE_DIR, exist_ok=True)


def record_trace(event):
    """写一条路由留痕（可回溯，供监控/审计读取）。"""
    _ensure_dir()
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    try:
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return payload


def is_unavailable(error):
    """判断一个错误是否属「渠道不通」（应触发降级）。"""
    if error is None:
        return False
    text = str(error).lower()
    return any(sig in text for sig in _spec.UNAVAILABLE_SIGNALS)


def resolve_models(policy=None):
    """解析某个角色/策略的目标渠道顺序（主 → 备）。"""
    policy = policy or _spec.DEFAULT_POLICY
    order = []
    if policy.get("primary"):
        order.append(policy["primary"])
    if policy.get("fallback") and policy["fallback"] not in order:
        order.append(policy["fallback"])
    # 兜底：策略缺字段时退回 spec 规范顺序
    if not order:
        order = _spec.channel_order()
    return order


def route_call(caller, system_prompt="", user_input="", policy=None, **kw):
    """按「主 → 备」调用模型，主渠道不通自动降级。

    caller: 可调用对象 (model, system_prompt, user_input, **kw) -> text
            测试/真实后端均可注入，核心降级逻辑不受传输影响。
    """
    models = resolve_models(policy)
    attempts = []
    for idx, model in enumerate(models):
        role = "primary" if idx == 0 else "fallback"
        try:
            out = caller(model, system_prompt, user_input, **kw)
            rec = record_trace({
                "event": "model.call.ok",
                "model": model,
                "role": role,
                "attempt": idx + 1,
            })
            return {"ok": True, "model": model, "role": role,
                    "output": out, "attempts": attempts, "trace": rec}
        except Exception as e:  # noqa: BLE001
            unavailable = is_unavailable(e)
            attempts.append({"model": model, "role": role, "error": str(e),
                             "unavailable": unavailable})
            record_trace({
                "event": "model.call.fail",
                "model": model,
                "role": role,
                "unavailable": unavailable,
                "error": str(e),
            })
            # 主渠道不通 → 继续降级；非「不通」型错误也继续尝试备用（保可用）
            continue
    record_trace({"event": "model.call.exhausted",
                  "models": models, "attempts": attempts})
    return {"ok": False, "model": None, "role": None, "output": None,
            "attempts": attempts, "reason": "all_channels_unavailable"}


def trace_overview():
    """读取留痕，统计各模型调用成功/失败次数（供监控俯瞰）。"""
    stats = {}
    if not os.path.exists(_TRACE_FILE):
        return stats
    try:
        with open(_TRACE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                model = ev.get("model") or "unknown"
                st = stats.setdefault(model, {"ok": 0, "fail": 0})
                if ev.get("event") == "model.call.ok":
                    st["ok"] += 1
                elif ev.get("event") == "model.call.fail":
                    st["fail"] += 1
    except Exception:  # noqa: BLE001
        pass
    return stats
