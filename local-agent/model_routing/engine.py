# -*- coding: utf-8 -*-
"""模型路由引擎 · 多级降级链（Issue #147 · v0.3.0-update）

确定性逻辑（非 LLM 判断）：
  - 按 spec 的渠道链顺序取「主模型」调用；
  - 主渠道不通（不可用/超时/限流/5xx）→ 自动降级到下一档；
  - 逐档降级直到成功或链耗尽；
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


def _tier_role(idx):
    """第 idx 档的语义名（0=primary，1=fallback，2+=fallback2…）。"""
    if idx == 0:
        return "primary"
    if idx == 1:
        return "fallback"
    return f"fallback{idx}"


def resolve_models(policy=None, role=None):
    """解析目标渠道顺序（主 → 二选 → 三选 …）。

    优先级：显式 policy > role 覆盖（roles[role]→default）> 通用默认。
    未指定角色（role=None）→ 走 default（「不指定就默认通用」）。
    """
    if policy is None:
        policy = _spec.role_policy(role)
    order = []
    if isinstance(policy, dict) and policy.get("chain"):
        order = [m for m in policy["chain"] if m]
    if not order and isinstance(policy, dict):
        # 兼容旧 policy 写法（primary/fallback）
        for k in ("primary", "fallback"):
            if policy.get(k) and policy[k] not in order:
                order.append(policy[k])
    # 兜底：策略缺字段时退回 spec 规范顺序
    if not order:
        order = _spec.channel_order(role)
    return order


def route_call(caller, system_prompt="", user_input="", policy=None, role=None, **kw):
    """按「主 → 备 → 三备 …」调用模型，主渠道不通自动逐档降级。

    caller: 可调用对象 (model, system_prompt, user_input, **kw) -> text
            测试/真实后端均可注入，核心降级逻辑不受传输影响。
    role:   角色名；未指定走通用默认（不指定就默认通用）。
    """
    models = resolve_models(policy, role=role)
    attempts = []
    for idx, model in enumerate(models):
        tier = _tier_role(idx)
        try:
            out = caller(model, system_prompt, user_input, **kw)
            rec = record_trace({
                "event": "model.call.ok",
                "model": model,
                "role": tier,
                "attempt": idx + 1,
                "chain": models,
            })
            return {"ok": True, "model": model, "role": tier,
                    "output": out, "attempts": attempts, "trace": rec,
                    "chain": models}
        except Exception as e:  # noqa: BLE001
            unavailable = is_unavailable(e)
            attempts.append({"model": model, "role": tier, "error": str(e),
                             "unavailable": unavailable})
            record_trace({
                "event": "model.call.fail",
                "model": model,
                "role": tier,
                "unavailable": unavailable,
                "error": str(e),
            })
            # 当前档不通 → 继续降级到下一档；非「不通」型错误也继续尝试下一档（保可用）
            continue
    record_trace({"event": "model.call.exhausted",
                  "models": models, "attempts": attempts})
    return {"ok": False, "model": None, "role": None, "output": None,
            "attempts": attempts, "reason": "all_channels_unavailable",
            "chain": models}


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


def call_with_chain(caller_by_model, system_prompt="", user_input="",
                    policy=None, role=None):
    """按渠道链分派到「每档各自的 caller」——真实降级接线点。

    caller_by_model: dict{model_name: callable}，缺该档 caller 时视为不可用并降级。
    这是把「文件配置的模型链」接进「真实多后端」的最小闭环：
      链上第一档用它的后端调用；不通则换下一档的后端。
    """
    def _dispatch(model, sp, ui, **kw):
        fn = caller_by_model.get(model)
        if fn is None:
            raise RuntimeError(f"channel unavailable: no caller bound for {model}")
        return fn(sp, ui, **kw)
    return route_call(_dispatch, system_prompt=system_prompt,
                      user_input=user_input, policy=policy, role=role)
