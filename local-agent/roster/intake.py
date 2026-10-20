# -*- coding: utf-8 -*-
"""
派单接入层（intake · 角色名册 → 派单路由）
==========================================
对端（管理-派单控制面 / 本地中控 / 网关）发来一条派单请求：

    {"target": "arch.developer",          # ID / 中文名 / @串，都认
     "task": "把登录模块的 token 刷新逻辑补上",
     "entity": "issue-42",                # 可选：关联实体
     "source": "piliangzijiedan-dong",    # 可选：谁派来的
     "detail": {...}}                     # 可选：上下文

本层**不另起一套派发**——把请求翻译成 dispatcher 认识的标准事件，走既有链路：
`normalize_event → rules → queue → guard → router.dispatch`。

三个必须做对的地方：

  ① **秘书入口规则不绕过**：本仓规则是「默认入口永远是秘书」，但**显式指定了目标
     角色的派单属于显式触发**（`[触发:角色]` 优先于默认入口，见 AGENTS.md 触发强制化）。
     所以：给了 target → 直接派给该角色；没给 target → 派给秘书由其路由。
     这是「沿原意图」，不是绕过护栏——护栏 `guard_entry` 管的是**对话入口**，不是派单。

  ② **认不出的目标不猜**：`resolve()` 失败即返回未派发 + 候选，让对端修；
     猜一个"最像的"角色等于把活派给错的人，比失败更糟。

  ③ **不可跑的角色直接拒派（不是派了再警告）**：登记了但本地没有实现类 = 派过去没人开工，
     返回 `ok=False` + `reason=role_not_implemented`，**不写 dispatch、不占 dedup 键、
     不返回 event_id**。`ok=True + warning` 是对端最容易误判的假绿——`ok` 只代表"活了"，
     不代表"能跑"。要派就给可跑的实现类，或先补实现再派。

留痕：每次接入都写一条 dispatch 记录（走 enqueue），对端可用 event_id 回查。
"""
import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from . import payload as _payload
from . import specs as _specs

__all__ = ["intake", "intake_batch", "ENTRY_ROLE_ID"]


ENTRY_ROLE_ID = "arch.secretary"


def _ensure_schema():
    try:
        from data import schema
        schema.init_schema()
    except Exception:  # noqa: BLE001 库不可用不阻断（下游会再报）
        pass


def intake(req, dispatch=True):
    """一条派单请求 → 走标准调度链路。返回结构化结果（含 event_id 供回查）。

    dispatch=False 时只解析不派发（对端可先拿这个做预演/dry-run）。
    """
    req = dict(req or {})
    target = req.get("target") or req.get("role") or req.get("role_id") or ""
    task = (req.get("task") or req.get("req") or "").strip()
    entity = req.get("entity") or ""
    source = req.get("source") or "roster.intake"

    if not task:
        return {"ok": False, "reason": "empty_task",
                "hint": "派单必须带 task（要做什么），否则下游无法开工"}

    # ① 目标解析：显式角色优先；没给 → 秘书主入口
    if target:
        r = _payload.resolve(target)
        if not r.get("ok"):
            return {"ok": False, "reason": "unknown_target", "target": target,
                    "suggestions": r.get("suggestions", []),
                    "hint": "用 catalog() 里的 role_id 派单；认不出不猜，避免派错人"}
    else:
        spec = _specs.get_spec(ENTRY_ROLE_ID)
        r = {"ok": True, "role_id": ENTRY_ROLE_ID, "name": spec["name"],
             "impl": spec["impl"], "source": "entry_default"}

    role_id, role_name = r["role_id"], r["name"]

    # ② 不可跑 → 拒派（执行-验证分离：能不能跑是 registry 说了算，不是 warning 说了算）
    if not r.get("impl", False):
        return {"ok": False, "reason": "role_not_implemented",
                "role_id": role_id, "role": role_name,
                "sources": [k for k in ("settings", "team", "relay")
                            if (_specs.get_spec(role_id) or {}).get(f"in_{k}")],
                "hint": (f"{role_name} 在事实源里登记了，但本地没有实现类"
                         f"（roles.ROLE_REGISTRY）——派过去只会留痕不会开工，故拒派。"
                         f"补实现或改派 catalog 里 impl=true 的角色。")}

    # ③ 翻译成标准事件（dispatcher 认得的那种）
    event = {
        "event_type": req.get("event_type") or "requirement",
        "source": source,
        "entity": entity or req.get("title") or task[:40],
        "gid": req.get("gid") or "",
        "detail": {
            "task": task,
            "role_id": role_id,
            "role": role_name,
            "from_contract": req.get("contract") or _payload.CONTRACT,
            "requester": req.get("requester") or "",
            **(req.get("detail") or {}),
        },
    }

    if not dispatch:
        return {"ok": True, "dry_run": True, "event": event,
                "role_id": role_id, "role": role_name, "impl": True}

    _ensure_schema()
    try:
        from dispatcher.engine import Dispatcher
        from dispatcher import rules as rules_mod
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "dispatcher_unavailable", "error": str(e),
                "role_id": role_id, "role": role_name}

    # ④ 定向规则：把「派给谁」说清楚，而不是让通用规则再猜一次
    rule = {
        "name": "roster_target_dispatch",
        "match": {"event_type": event["event_type"]},
        "target_role": role_name,
        "action": "dispatch",
        "gate": "auto",
        "dedup_key": "{entity}:roster:" + role_id,
        "priority": 95,
    }
    engine = Dispatcher(rule_engine=rules_mod.RuleEngine([rule]))
    result = engine.process_event(event)
    status = result.get("status")

    out = {
        # 只有真派出去才算 ok；queue 的 hold/queued 不是"已派"
        "ok": status == "dispatched",
        "status": status,
        "event_id": result.get("event_id"),
        "role_id": role_id,
        "role": role_name,
        "target_agent": result.get("target_agent", ""),
        "entity": event["entity"],
    }
    if not out["ok"]:
        out["reason"] = result.get("note") or status or "not_dispatched"
    return out


def intake_batch(reqs, dispatch=True):
    """批量派单（对端一次推一批）：逐条 intake，汇总成功/失败，不因单条失败中断。"""
    results = [intake(r, dispatch=dispatch) for r in (reqs or [])]
    return {
        "ok": all(r.get("ok") for r in results) if results else False,
        "total": len(results),
        "accepted": sum(1 for r in results if r.get("ok")),
        "rejected": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }
