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
    """解析目标渠道顺序（主 → 二选 → 三选 …），并集中过模型别名映射。

    优先级：显式 policy > role 覆盖（roles[role]→default）> 通用默认。
    未指定角色（role=None）→ 走 default（「不指定就默认通用」）。
    Issue #182 复评：模型别名（alias）统一在此收口——每个模型名过 `_spec.resolve_alias`，
    未登记别名（版本后缀型）在此显式报红（不放行），不再散落在 openai_compat 里各自映射。
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
    # 集中过别名映射（未登记别名在此报红）
    out = []
    for m in order:
        out.append(_spec.resolve_alias(m))
    return out


def route_call(caller, system_prompt="", user_input="", policy=None, role=None, **kw):
    """按「主 → 备 → 三备 …」调用模型，主渠道不通自动逐档降级。

    caller: 可调用对象 (model, system_prompt, user_input, **kw) -> text
            测试/真实后端均可注入，核心降级逻辑不受传输影响。
    role:   角色名；未指定走通用默认（不指定就默认通用）。

    ★ 显性降级（用户 2026-10-20 PR #185）：
      降级**不是静默换模型**——每一跳都写 `degraded=1` + `fallback_from` + `next`，
      结果里带 `degraded/from_model/used_tier`，让调用方一眼看到「本轮不是主档回答的」。
      全链耗尽时同样如实报 `degraded=True`，不假装成功。
    """
    models = resolve_models(policy, role=role)
    attempts = []
    from_model = None  # 第一档（用户指定的那一档）原模型，用于显性标注降级来源
    for idx, model in enumerate(models):
        tier = _tier_role(idx)
        if idx == 0:
            from_model = model
        try:
            out = caller(model, system_prompt, user_input, **kw)
            degraded = idx > 0
            rec = record_trace({
                "event": "model.call.ok",
                "model": model,
                "role": tier,
                "attempt": idx + 1,
                "chain": models,
                "degraded": 1 if degraded else 0,
                "fallback_from": from_model if degraded else None,
            })
            if degraded:
                # 显性降级留痕：单独一条，供监控/调用方 grep，无需回看整条链
                record_trace({
                    "event": "model.call.degraded",
                    "model": model,
                    "role": tier,
                    "fallback_from": from_model,
                    "attempt": idx + 1,
                    "skipped": [a["model"] for a in attempts],
                })
            return {"ok": True, "model": model, "role": tier,
                    "output": out, "attempts": attempts, "trace": rec,
                    "chain": models,
                    "degraded": degraded,
                    "from_model": from_model if degraded else None,
                    "used_tier": tier}
        except Exception as e:  # noqa: BLE001
            unavailable = is_unavailable(e)
            nxt = models[idx + 1] if idx + 1 < len(models) else None
            attempts.append({"model": model, "role": tier, "error": str(e),
                             "unavailable": unavailable, "next": nxt})
            # 显性降级：失败这一跳当场留痕「降去哪」，不留到用户去猜
            record_trace({
                "event": "model.call.fail",
                "model": model,
                "role": tier,
                "unavailable": unavailable,
                "error": str(e),
                "degraded": 1 if nxt else 0,
                "fallback_from": model if nxt else None,
                "next": nxt,
            })
            # 当前档不通 → 继续降级到下一档；非「不通」型错误也继续尝试下一档（保可用）
            continue
    record_trace({"event": "model.call.exhausted",
                  "models": models, "attempts": attempts,
                  "fallback_from": from_model, "degraded": 1 if len(models) > 1 else 0})
    return {"ok": False, "model": None, "role": None, "output": None,
            "attempts": attempts, "reason": "all_channels_unavailable",
            "chain": models, "degraded": len(models) > 1, "from_model": from_model,
            "used_tier": None}


def last_degraded():
    """读留痕判断**最近一次**调用是否发生过降级（供 llm 层把降级标进结果）。

    为什么读留痕而不是让调用方自己判：降级发生在 route_call 内部，调用方只看得到
    最终文本；若调用方另记一份状态，就会出现「库说降级、实际没降」的两套口径。
    唯一事实源仍是 model_routing_trace.jsonl。
    """
    if not os.path.exists(_TRACE_FILE):
        return None
    try:
        last = None
        with open(_TRACE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
        if not last:
            return None
        ev = last.get("event")
        if ev in ("model.call.ok", "model.call.exhausted"):
            return {"degraded": bool(last.get("degraded")),
                    "model": last.get("model"),
                    "fallback_from": last.get("fallback_from"),
                    "chain": last.get("chain") or last.get("models"),
                    "ts": last.get("ts")}
    except Exception:  # noqa: BLE001
        return None
    return None


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
